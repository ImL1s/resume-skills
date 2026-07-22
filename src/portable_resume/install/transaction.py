"""Root lock, durable journal, stage/commit/rollback, verify, uninstall."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..diagnostics import DiagnosticError
from .catalog import BUNDLE_VERSION, HOST_PROFILES
from .manifest import (
    OWNER_MARKER,
    Manifest,
    build_manifest,
    claim_key,
    empty_manifest,
    sha256_bytes,
    sha256_file,
    validate_rel_path,
)
from .render import frontmatter_keys, materialize_plan, package_identity, render_skill_markdown

SUPPORT_DIR = ".portable-resume"
MANIFEST_NAME = "manifest.json"
LOCK_NAME = "install.lock"
JOURNAL_NAME = "journal.json"
BACKUP_DIR = "backups"


@dataclass(slots=True)
class ActionPlan:
    root: str
    claim: str
    host: str
    scope: str
    generation: int
    package_identity: str
    files: dict[str, bytes]
    manifest: Manifest
    creates: list[str]
    replaces: list[str]
    backups: list[str]
    retains: list[str]
    dry_run: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "claim": self.claim,
            "host": self.host,
            "scope": self.scope,
            "generation": self.generation,
            "package_identity": self.package_identity,
            "creates": self.creates,
            "replaces": self.replaces,
            "backups": self.backups,
            "retains": self.retains,
            "dry_run": self.dry_run,
            "file_count": len(self.files),
        }


class RootLock:
    def __init__(self, root: str, *, wait_seconds: float = 5.0) -> None:
        self.root = root
        self.support = os.path.join(root, SUPPORT_DIR)
        self.path = os.path.join(self.support, LOCK_NAME)
        self._fd: int | None = None
        self.wait_seconds = wait_seconds

    def __enter__(self) -> "RootLock":
        os.makedirs(self.support, mode=0o755, exist_ok=True)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                if os.name == "nt":
                    self._fd = fd
                    return self
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
                return self
            except BlockingIOError as error:
                os.close(fd)
                if time.monotonic() >= deadline:
                    raise DiagnosticError("E_INSTALL_BUSY") from error
                time.sleep(0.05)
            except OSError as error:
                os.close(fd)
                raise DiagnosticError("E_INSTALL_BUSY") from error

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            try:
                if os.name != "nt":
                    import fcntl

                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


def journal_path(root: str) -> str:
    return os.path.join(root, SUPPORT_DIR, JOURNAL_NAME)


def manifest_path(root: str) -> str:
    return os.path.join(root, SUPPORT_DIR, MANIFEST_NAME)


def load_manifest(root: str) -> Manifest | None:
    path = manifest_path(root)
    if not os.path.isfile(path):
        return None
    try:
        return Manifest.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as error:
        raise DiagnosticError("E_VERIFY_MISMATCH") from error
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise DiagnosticError("E_VERIFY_MISMATCH") from error


def require_no_pending_journal(root: str) -> None:
    path = journal_path(root)
    if os.path.isfile(path):
        raise DiagnosticError("E_RECOVERY_REQUIRED")


def _tree_snapshot(root: str) -> dict[str, tuple[int, float]]:
    """path -> (size, mtime) for dry-run purity checks."""
    result: dict[str, tuple[int, float]] = {}
    if not os.path.exists(root):
        return result
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            result[path] = (st.st_size, st.st_mtime_ns if hasattr(st, "st_mtime_ns") else st.st_mtime)
    return result


def plan_install(
    *,
    host: str,
    scope: str,
    root: str,
    dry_run: bool = False,
    force_with_backup: bool = False,
) -> ActionPlan:
    if host not in HOST_PROFILES:
        raise DiagnosticError.invalid()
    files = materialize_plan(host)
    identity = package_identity(files)
    claim = claim_key(host=host, scope=scope, root=root)
    existing = load_manifest(root)
    if existing is not None and existing.bundle_version != BUNDLE_VERSION and existing.claims:
        # Single version per root: allow update only when all claims move together.
        if any(c != claim for c in existing.claims):
            raise DiagnosticError("E_INSTALL_CONFLICT")
    generation = 1 if existing is None else existing.generation + 1
    try:
        manifest = build_manifest(
            files=files,
            claim=claim,
            host=host,
            scope=scope,
            root=root,
            package_identity=identity,
            generation=generation,
            existing=existing,
        )
    except ValueError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error

    creates: list[str] = []
    replaces: list[str] = []
    backups: list[str] = []
    retains: list[str] = []
    for rel, data in sorted(files.items()):
        # Containment matches execute path (reject escapes before planning).
        dest = _dest_under_root(root, rel)
        if not os.path.lexists(dest):
            creates.append(rel)
            continue
        if os.path.islink(dest) or not os.path.isfile(dest):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        current = sha256_file(dest)
        expected = sha256_bytes(data)
        if current == expected:
            retains.append(rel)
            continue
        owned = existing is not None and rel in existing.files and claim in existing.files[rel].claims
        owned_shared = existing is not None and rel in existing.files
        if owned or owned_shared:
            replaces.append(rel)
            continue
        # non-owned conflict
        if not force_with_backup:
            raise DiagnosticError("E_INSTALL_CONFLICT")
        replaces.append(rel)
        backups.append(rel)
    return ActionPlan(
        root=root,
        claim=claim,
        host=host,
        scope=scope,
        generation=generation,
        package_identity=identity,
        files=files,
        manifest=manifest,
        creates=creates,
        replaces=replaces,
        backups=backups,
        retains=retains,
        dry_run=dry_run,
    )


def _safe_rel_path(rel: str) -> str:
    """Reject absolute paths and parent escapes in relative install paths."""
    try:
        return validate_rel_path(rel)
    except ValueError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error


def _dest_under_root(root: str, rel: str) -> str:
    safe = _safe_rel_path(rel)
    # Join under root without resolving intermediate symlinks that escape via realpath of join alone.
    dest = os.path.realpath(os.path.join(root, safe))
    root_real = os.path.realpath(root)
    try:
        if os.path.commonpath((dest, root_real)) != root_real:
            raise DiagnosticError("E_INSTALL_CONFLICT")
    except ValueError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    return dest


def _classify_dest(
    *,
    root: str,
    rel: str,
    data: bytes,
    existing: Manifest | None,
    claim: str,
    force_with_backup: bool,
) -> str:
    """Return create|retain|replace|backup under current disk state."""
    dest = _dest_under_root(root, rel)
    if not os.path.lexists(dest):
        return "create"
    if os.path.islink(dest) or not os.path.isfile(dest):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    current = sha256_file(dest)
    expected = sha256_bytes(data)
    if current == expected:
        return "retain"
    owned = existing is not None and rel in existing.files
    if owned:
        return "replace"
    if force_with_backup:
        return "backup"
    raise DiagnosticError("E_INSTALL_CONFLICT")


def execute_install(plan: ActionPlan, *, force_with_backup: bool = False) -> dict[str, Any]:
    root = plan.root
    if plan.dry_run:
        before = _tree_snapshot(root)
        # observational only
        after = _tree_snapshot(root)
        if before != after:
            raise DiagnosticError("E_INVARIANT")
        return {"ok": True, "dry_run": True, "plan": plan.to_dict()}

    with RootLock(root):
        require_no_pending_journal(root)
        # re-read generation under lock
        existing = load_manifest(root)
        if existing is not None and existing.generation != plan.generation - 1 and existing.generation != 0:
            # allow exact expected previous generation
            if existing.generation + 1 != plan.generation:
                raise DiagnosticError("E_INSTALL_BUSY")
        # Re-evaluate ownership under the lock (close plan/execute TOCTOU window).
        # force is per-path: only paths that were planned as backups (or global flag).
        planned_backups = set(plan.backups)
        backups: list[str] = []
        for rel, data in plan.files.items():
            kind = _classify_dest(
                root=root,
                rel=rel,
                data=data,
                existing=existing,
                claim=plan.claim,
                force_with_backup=force_with_backup or rel in planned_backups,
            )
            if kind == "backup":
                backups.append(rel)
        stage_dir = tempfile.mkdtemp(prefix="portable-resume-stage-", dir=os.path.join(root, SUPPORT_DIR))
        backup_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        backup_root = os.path.join(root, SUPPORT_DIR, BACKUP_DIR, backup_id)
        journal = {
            "schema_version": "portable-resume/install-journal-v1",
            "state": "staging",
            "generation": plan.generation,
            "claim": plan.claim,
            "stage_dir": stage_dir,
            "backup_root": backup_root,
            "paths": {},
        }
        try:
            for rel, data in plan.files.items():
                safe = _safe_rel_path(rel)
                dest = Path(stage_dir) / safe
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                mode = 0o755 if rel.endswith("run_reader.py") else 0o644
                dest.chmod(mode)
                journal["paths"][safe] = {"state": "staged", "sha256": sha256_bytes(data)}
            # backup non-owned conflicts / forced replaces
            for rel in backups:
                safe = _safe_rel_path(rel)
                src = _dest_under_root(root, safe)
                if os.path.islink(src):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                if os.path.isfile(src):
                    target = os.path.join(backup_root, safe)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    # copy without following a late-swapped symlink
                    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
                    try:
                        infd = os.open(src, flags)
                    except OSError as error:
                        raise DiagnosticError("E_INSTALL_CONFLICT") from error
                    try:
                        with os.fdopen(infd, "rb") as src_fh, open(target, "wb") as dst_fh:
                            shutil.copyfileobj(src_fh, dst_fh)
                    except Exception:
                        try:
                            os.remove(target)
                        except OSError:
                            pass
                        raise
                    journal["paths"][safe]["backup"] = target
            journal["state"] = "committing"
            _write_journal(root, journal)
            # commit files
            for rel in sorted(plan.files):
                safe = _safe_rel_path(rel)
                # re-check each path immediately before replace
                kind = _classify_dest(
                    root=root,
                    rel=safe,
                    data=plan.files[rel],
                    existing=existing,
                    claim=plan.claim,
                    force_with_backup=force_with_backup or safe in planned_backups or safe in backups,
                )
                if kind == "backup" and safe not in backups and not force_with_backup and safe not in planned_backups:
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                src = os.path.join(stage_dir, safe)
                dest = _dest_under_root(root, safe)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.replace(src, dest)
                journal["paths"][safe]["state"] = "committed"
                _write_journal(root, journal)
            # Remove owned orphans (in old manifest, not in new plan, sole claim released).
            # Journal orphan targets *before* delete so crash recovery can reason about them.
            orphan_removed: list[str] = []
            orphan_pending: list[tuple[str, str, str]] = []  # rel, abs_path, sha256
            if existing is not None:
                for rel, entry in list(existing.files.items()):
                    if rel in plan.files:
                        continue
                    # After rebuild, plan.manifest already dropped empty-claim orphans.
                    if rel in plan.manifest.files:
                        continue
                    try:
                        abs_path = _dest_under_root(root, rel)
                    except DiagnosticError:
                        continue
                    if os.path.islink(abs_path) or not os.path.isfile(abs_path):
                        continue
                    try:
                        if sha256_file(abs_path) == entry.sha256:
                            orphan_pending.append((rel, abs_path, entry.sha256))
                    except OSError:
                        continue
            if orphan_pending:
                journal["orphans"] = {
                    rel: {"path": abs_path, "sha256": digest, "state": "pending"}
                    for rel, abs_path, digest in orphan_pending
                }
                journal["state"] = "orphaning"
                _write_journal(root, journal)
                for rel, abs_path, digest in orphan_pending:
                    try:
                        if sha256_file(abs_path) == digest:
                            os.remove(abs_path)
                            orphan_removed.append(rel)
                            journal["orphans"][rel]["state"] = "removed"
                            _write_journal(root, journal)
                    except OSError:
                        journal["orphans"][rel]["state"] = "skipped"
                        _write_journal(root, journal)
            # write manifest last
            Path(manifest_path(root)).write_text(plan.manifest.dumps(), encoding="utf-8")
            journal["state"] = "complete"
            _write_journal(root, journal)
            # cleanup stage and completed journal
            shutil.rmtree(stage_dir, ignore_errors=True)
            try:
                os.remove(journal_path(root))
            except OSError:
                pass
            result = {"ok": True, "dry_run": False, "plan": plan.to_dict(), "generation": plan.generation}
            if orphan_removed:
                result["orphan_removed"] = orphan_removed
            return result
        except Exception:
            _attempt_rollback(root, journal, plan)
            raise


def _write_journal(root: str, journal: dict[str, Any]) -> None:
    path = journal_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    payload = json.dumps(journal, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    # best-effort directory fsync for durability on crash
    try:
        dir_fd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _attempt_rollback(root: str, journal: dict[str, Any], plan: ActionPlan) -> None:
    journal["state"] = "rollback"
    try:
        _write_journal(root, journal)
    except OSError:
        return
    for rel, meta in journal.get("paths", {}).items():
        try:
            safe = _safe_rel_path(str(rel))
        except DiagnosticError:
            continue
        backup = meta.get("backup")
        dest = _dest_under_root(root, safe)
        if backup and os.path.isfile(backup):
            # only restore backups that themselves stay under root support dir
            backup_real = os.path.realpath(backup)
            support = os.path.realpath(os.path.join(root, SUPPORT_DIR))
            if not backup_real.startswith(support + os.sep):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(backup, dest)
        elif meta.get("state") == "committed" and rel in plan.creates:
            try:
                os.remove(dest)
            except OSError:
                pass
    stage_dir = journal.get("stage_dir")
    if stage_dir:
        shutil.rmtree(stage_dir, ignore_errors=True)


def recover_root(root: str) -> dict[str, Any]:
    path = journal_path(root)
    if not os.path.isfile(path):
        return {"ok": True, "recovered": False}
    with RootLock(root):
        journal = json.loads(Path(path).read_text(encoding="utf-8"))
        if journal.get("state") == "complete":
            stage_dir = journal.get("stage_dir")
            if stage_dir:
                shutil.rmtree(stage_dir, ignore_errors=True)
            os.remove(path)
            return {"ok": True, "recovered": True, "action": "cleared_complete_journal"}
        # incomplete: restore only sandboxed backups; keep journal if unrecoverable drift remains
        restored = 0
        for rel, meta in journal.get("paths", {}).items():
            try:
                safe = _safe_rel_path(str(rel))
            except DiagnosticError:
                continue
            backup = meta.get("backup")
            if backup and os.path.isfile(backup):
                backup_real = os.path.realpath(backup)
                support = os.path.realpath(os.path.join(root, SUPPORT_DIR))
                if not backup_real.startswith(support + os.sep):
                    continue
                dest = _dest_under_root(root, safe)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(backup, dest)
                restored += 1
        stage_dir = journal.get("stage_dir")
        if stage_dir and os.path.isdir(stage_dir):
            # stage must stay under support dir
            stage_real = os.path.realpath(stage_dir)
            support = os.path.realpath(os.path.join(root, SUPPORT_DIR))
            if stage_real.startswith(support + os.sep):
                shutil.rmtree(stage_dir, ignore_errors=True)
        os.remove(path)
        return {"ok": True, "recovered": True, "action": "restored_from_journal", "restored_paths": restored}


def verify_root(root: str, *, claim: str | None = None) -> dict[str, Any]:
    require_no_pending_journal(root)
    manifest = load_manifest(root)
    if manifest is None:
        raise DiagnosticError("E_VERIFY_MISMATCH")
    if claim is not None and claim not in manifest.claims:
        raise DiagnosticError("E_VERIFY_MISMATCH")
    mismatches: list[str] = []
    for rel, entry in sorted(manifest.files.items()):
        if claim is not None and claim not in entry.claims:
            continue
        try:
            path = _dest_under_root(root, rel)
        except DiagnosticError:
            mismatches.append(rel)
            continue
        if os.path.islink(path) or not os.path.isfile(path):
            mismatches.append(rel)
            continue
        try:
            if sha256_file(path) != entry.sha256:
                mismatches.append(rel)
                continue
        except OSError:
            mismatches.append(rel)
            continue
        if rel.endswith("SKILL.md"):
            text = Path(path).read_text(encoding="utf-8")
            keys = frontmatter_keys(text)
            if keys != ["name", "description"]:
                mismatches.append(rel)
    if mismatches:
        raise DiagnosticError("E_VERIFY_MISMATCH")
    from ..diagnostics import SOURCE_KEYS

    for claim_id, meta in manifest.claims.items():
        if claim is not None and claim_id != claim:
            continue
        for source in sorted(SOURCE_KEYS):
            skill = f"resume-{source}/SKILL.md"
            if skill not in manifest.files or claim_id not in manifest.files[skill].claims:
                raise DiagnosticError("E_VERIFY_MISMATCH")
            expected = render_skill_markdown(host=meta["host"], source=source)
            actual = Path(_dest_under_root(root, skill)).read_text(encoding="utf-8")
            if actual != expected:
                raise DiagnosticError("E_VERIFY_MISMATCH")
    return {
        "ok": True,
        "generation": manifest.generation,
        "claims": sorted(manifest.claims),
        "files": len(manifest.files),
        "owner": OWNER_MARKER,
    }


def uninstall_claim(*, host: str, scope: str, root: str, dry_run: bool = False) -> dict[str, Any]:
    claim = claim_key(host=host, scope=scope, root=root)
    if dry_run:
        manifest = load_manifest(root)
        if manifest is None or claim not in manifest.claims:
            return {"ok": True, "dry_run": True, "removed_files": [], "claim": claim}
        removable = [p for p, e in manifest.files.items() if e.claims == [claim]]
        return {"ok": True, "dry_run": True, "removed_files": removable, "claim": claim}

    with RootLock(root):
        require_no_pending_journal(root)
        manifest = load_manifest(root)
        if manifest is None or claim not in manifest.claims:
            return {"ok": True, "removed_files": [], "claim": claim}
        removed: list[str] = []
        retained_drift: list[str] = []
        # remove claim refs
        del manifest.claims[claim]
        for path, entry in list(manifest.files.items()):
            if claim in entry.claims:
                entry.claims = [c for c in entry.claims if c != claim]
            if entry.claims:
                continue
            try:
                abs_path = _dest_under_root(root, path)
            except DiagnosticError:
                # Malicious/escaped manifest entry: drop from manifest, never delete outside root.
                del manifest.files[path]
                continue
            if os.path.isfile(abs_path) and not os.path.islink(abs_path):
                try:
                    matches = sha256_file(abs_path) == entry.sha256
                except OSError:
                    matches = False
                if matches:
                    os.remove(abs_path)
                    removed.append(path)
                else:
                    retained_drift.append(path)
            del manifest.files[path]
        manifest.generation += 1
        if manifest.claims:
            Path(manifest_path(root)).write_text(manifest.dumps(), encoding="utf-8")
        else:
            # remove support metadata when no claims remain; keep drifted files
            try:
                os.remove(manifest_path(root))
            except OSError:
                pass
            # best-effort cleanup of empty owned skill dirs / support tree only
            _cleanup_empty_dirs(root, removed_paths=removed)
        return {
            "ok": True,
            "claim": claim,
            "removed_files": removed,
            "retained_drift": retained_drift,
            "generation": manifest.generation,
        }


def _cleanup_empty_dirs(root: str, *, removed_paths: list[str] | None = None) -> None:
    """Remove empty ancestors of owned removals and empty .portable-resume / resume-* trees.

    Never walks the entire skill root deleting arbitrary foreign empty skill dirs.
    """
    root_real = os.path.realpath(root)
    candidates: set[str] = set()
    for rel in removed_paths or ():
        try:
            abs_path = _dest_under_root(root, rel)
        except DiagnosticError:
            continue
        parent = os.path.dirname(abs_path)
        while parent.startswith(root_real) and parent != root_real:
            candidates.add(parent)
            parent = os.path.dirname(parent)
    # Always consider support dir cleanup after last claim.
    support = os.path.join(root_real, SUPPORT_DIR)
    if os.path.isdir(support):
        for dirpath, _dirnames, _filenames in os.walk(support, topdown=False):
            candidates.add(dirpath)
    for path in sorted(candidates, key=lambda p: p.count(os.sep), reverse=True):
        if path == root_real:
            continue
        try:
            if not os.path.isdir(path) or os.path.islink(path):
                continue
            if os.listdir(path):
                continue
            # Candidates are only ancestors of owned removals + .portable-resume walk.
            rel = os.path.relpath(path, root_real)
            top = rel.split(os.sep, 1)[0]
            if top == SUPPORT_DIR or top.startswith("resume-") or os.sep in rel:
                os.rmdir(path)
        except OSError:
            pass


def matrix_report() -> dict[str, Any]:
    from .catalog import matrix_cells
    from ..diagnostics import SOURCE_KEYS

    cells = []
    for host, source in matrix_cells():
        text = render_skill_markdown(host=host, source=source)
        keys = frontmatter_keys(text)
        packaging_ok = keys == ["name", "description"] and f"resume-{source}" in text
        cells.append(
            {
                "host": host,
                "source": source,
                "skill": f"resume-{source}",
                "profile": HOST_PROFILES[host].profile_id,
                "frontmatter_keys": keys,
                # packaging/filesystem matrix only — not live installed-host activation
                "packaging_supported": packaging_ok,
                "live_supported": False,
                "live_evidence": "not-run",
                "supported": packaging_ok,  # backward-compatible alias for packaging_supported
            }
        )
    return {
        "ok": all(cell["packaging_supported"] for cell in cells),
        "cell_count": len(cells),
        "expected": len(HOST_PROFILES) * len(SOURCE_KEYS),
        "packaging_cells_supported": sum(1 for cell in cells if cell["packaging_supported"]),
        "live_cells_supported": 0,
        "cells": cells,
    }
