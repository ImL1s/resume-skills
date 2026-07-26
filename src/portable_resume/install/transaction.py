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
from .catalog import BUNDLE_VERSION, HOST_PROFILES, MANIFEST_SCHEMA
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


@dataclass(slots=True)
class InstallCheckpoint:
    root: str
    snapshot_dir: str
    paths: dict[str, dict[str, Any]]


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


def _supports_descriptor_relative_commit() -> bool:
    return os.name != "nt" and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")


def _open_directory_from_slash(path: str, *, allow_leaf_symlink: bool = False) -> int:
    """Open a directory by walking each component from ``/`` with ``O_NOFOLLOW``.

    Never pathname-open a multi-component resolved path in one shot: a writable
    ancestor swapped for a symlink after ``realpath`` would otherwise be followed
    through intermediate components.
    """
    import stat as stat_mod

    abs_path = os.path.abspath(os.path.expanduser(path))
    parts = [part for part in abs_path.split(os.sep) if part]
    if not parts:
        raise DiagnosticError("E_INSTALL_CONFLICT")

    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        current_fd = os.open("/", flags)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error

    opened: list[int] = [current_fd]
    prefix = "/"
    try:
        for index, part in enumerate(parts):
            is_leaf = index == len(parts) - 1
            parent_fd = current_fd
            try:
                st = os.lstat(part, dir_fd=parent_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error

            if stat_mod.S_ISLNK(st.st_mode):
                if is_leaf and allow_leaf_symlink:
                    try:
                        target = os.readlink(part, dir_fd=parent_fd)
                    except OSError as error:
                        raise DiagnosticError("E_INSTALL_CONFLICT") from error
                    for fd in opened:
                        os.close(fd)
                    opened.clear()
                    if not os.path.isabs(target):
                        target = os.path.normpath(os.path.join(prefix, target))
                    return _open_directory_from_slash(target, allow_leaf_symlink=False)
                if is_leaf:
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                try:
                    target = os.readlink(part, dir_fd=parent_fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                if not os.path.isabs(target):
                    target = os.path.normpath(os.path.join(prefix, target))
                try:
                    if os.path.commonpath((target, prefix)) != prefix:
                        raise DiagnosticError("E_INSTALL_CONFLICT")
                except ValueError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                remaining = parts[index + 1 :]
                combined = os.path.join(target, *remaining) if remaining else target
                for fd in opened:
                    os.close(fd)
                opened.clear()
                return _open_directory_from_slash(combined, allow_leaf_symlink=allow_leaf_symlink)

            try:
                next_fd = os.open(part, flags, dir_fd=parent_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            opened.append(next_fd)
            current_fd = next_fd
            prefix = os.path.join(prefix, part)

        for fd in opened[:-1]:
            os.close(fd)
        opened.clear()
        return current_fd
    except DiagnosticError:
        for fd in opened:
            os.close(fd)
        raise
    except OSError as error:
        for fd in opened:
            os.close(fd)
        raise DiagnosticError("E_INSTALL_CONFLICT") from error


def _open_skill_root_descriptor(root: str) -> int:
    """Open the skill root for descriptor-relative commits.

    The skill-root path itself may be a symlink (common dotfiles layouts such as
    ``~/.claude/skills`` → a shared directory). Each ancestor component is
    pinned from ``/`` with ``O_NOFOLLOW``; only the final component may be a
    symlink, resolved once via ``readlink`` and reopened component-wise.
    Intermediate payload parents still use no-follow opens under this root fd.
    """
    if not _supports_descriptor_relative_commit():
        raise DiagnosticError("E_INSTALL_CONFLICT")
    return _open_directory_from_slash(root, allow_leaf_symlink=True)


def _open_directory_under_root(root_fd: int, rel_dir: str) -> int:
    """Open an existing directory under root_fd without following symlinks.

    Intermediate directory descriptors are closed on both success and failure so
    multi-component paths do not leak fds across payload commits.
    """
    parts = [part for part in rel_dir.split(os.sep) if part and part != "."]
    if not parts:
        return root_fd
    current_fd = root_fd
    opened: list[int] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if current_fd is not root_fd:
                opened.append(current_fd)
            current_fd = next_fd
        for fd in opened:
            os.close(fd)
        opened.clear()
        return current_fd
    except Exception:
        for fd in opened:
            os.close(fd)
        if current_fd is not root_fd:
            os.close(current_fd)
        raise


def _mkdir_directory_under_root(root_fd: int, rel_dir: str) -> None:
    """Create rel_dir under root_fd when missing; never follow symlinks."""
    parts = [part for part in rel_dir.split(os.sep) if part and part != "."]
    if not parts:
        return
    current_fd = root_fd
    opened: list[int] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current_fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                try:
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if current_fd is not root_fd:
                opened.append(current_fd)
            current_fd = next_fd
    finally:
        for fd in opened:
            os.close(fd)
        if current_fd is not root_fd:
            os.close(current_fd)


def _commit_payload_file(*, root: str, root_fd: int | None, rel: str, staged_src: str) -> None:
    """Atomically commit one staged payload under root with TOCTOU-resistant checks."""
    safe = _safe_rel_path(rel)
    basename = os.path.basename(safe)
    parent_rel = os.path.dirname(safe)
    if not basename:
        raise DiagnosticError("E_INSTALL_CONFLICT")

    _dest_under_root(root, safe)

    if _supports_descriptor_relative_commit():
        if root_fd is None:
            raise DiagnosticError("E_INSTALL_CONFLICT")
        _mkdir_directory_under_root(root_fd, parent_rel)
        parent_fd = _open_directory_under_root(root_fd, parent_rel)
        try:
            os.replace(staged_src, basename, dst_dir_fd=parent_fd)
        finally:
            if parent_fd is not root_fd:
                os.close(parent_fd)
        return

    # Platforms without dir_fd / O_NOFOLLOW replace: fail closed instead of a
    # residual pathname TOCTOU window (Windows is not a V1 release gate).
    raise DiagnosticError("E_INSTALL_CONFLICT")


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
        backup_root: str | None = None
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
            if backups:
                backup_parent = _dest_under_root(root, f"{SUPPORT_DIR}/{BACKUP_DIR}")
                if os.path.lexists(backup_parent) and (
                    os.path.islink(backup_parent) or not os.path.isdir(backup_parent)
                ):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                os.makedirs(backup_parent, mode=0o755, exist_ok=True)
                backup_root = tempfile.mkdtemp(
                    prefix=time.strftime("%Y%m%dT%H%M%SZ-", time.gmtime()),
                    dir=backup_parent,
                )
                journal["backup_root"] = backup_root
            for rel, data in plan.files.items():
                safe = _safe_rel_path(rel)
                dest = Path(stage_dir) / safe
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                mode = 0o755 if rel.endswith("run_reader.py") else 0o644
                dest.chmod(mode)
                journal["paths"][safe] = {
                    "state": "staged",
                    "sha256": sha256_bytes(data),
                    "existed": False,
                }
            # Snapshot every existing destination before the first replacement.
            # Owned files need the same rollback protection as foreign conflicts.
            rollback_root = os.path.join(stage_dir, ".rollback")
            for rel in sorted(plan.files):
                safe = _safe_rel_path(rel)
                src = _dest_under_root(root, safe)
                if not os.path.lexists(src):
                    continue
                if os.path.islink(src) or not os.path.isfile(src):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                target = os.path.join(rollback_root, safe)
                _copy_regular_nofollow(src, target)
                journal["paths"][safe]["existed"] = True
                journal["paths"][safe]["rollback_backup"] = target
                journal["paths"][safe]["original_sha256"] = sha256_file(target)
            # backup non-owned conflicts / forced replaces
            for rel in backups:
                safe = _safe_rel_path(rel)
                src = _dest_under_root(root, safe)
                if os.path.islink(src):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                if os.path.isfile(src):
                    target = os.path.join(backup_root, safe)
                    _copy_regular_nofollow(src, target)
                    journal["paths"][safe]["backup"] = target
            journal["state"] = "committing"
            _write_journal(root, journal)
            # commit files
            root_fd: int | None = None
            if _supports_descriptor_relative_commit():
                root_fd = _open_skill_root_descriptor(root)
            try:
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
                    if kind == "retain":
                        journal["paths"][safe]["state"] = "retained"
                        _write_journal(root, journal)
                        continue
                    src = os.path.join(stage_dir, safe)
                    _commit_payload_file(root=root, root_fd=root_fd, rel=safe, staged_src=src)
                    journal["paths"][safe]["state"] = "committed"
                    _write_journal(root, journal)
            finally:
                if root_fd is not None:
                    os.close(root_fd)
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
            if backups:
                result["backup_root"] = backup_root
            return result
        except Exception:
            _attempt_rollback(root, journal)
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


def _copy_regular_nofollow(src: str, target: str) -> None:
    """Copy one regular file without following the source or target."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    target_created = False
    try:
        infd = os.open(src, flags)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    try:
        import stat as stat_mod

        source_stat = os.fstat(infd)
        if not stat_mod.S_ISREG(source_stat.st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        outfd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            stat_mod.S_IMODE(source_stat.st_mode),
        )
        target_created = True
        try:
            while True:
                chunk = os.read(infd, 1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(outfd, view)
                    view = view[written:]
            os.fchmod(outfd, stat_mod.S_IMODE(source_stat.st_mode))
        finally:
            os.close(outfd)
    except Exception:
        if target_created:
            try:
                os.remove(target)
            except OSError:
                pass
        raise
    finally:
        os.close(infd)


def capture_install_checkpoint(plan: ActionPlan) -> InstallCheckpoint:
    """Capture every file an install plan may mutate for cross-root compensation."""
    snapshot_dir = tempfile.mkdtemp(prefix="portable-resume-checkpoint-")
    paths: dict[str, dict[str, Any]] = {}
    existing = load_manifest(plan.root)
    candidates = set(plan.files)
    if existing is not None:
        candidates.update(existing.files)
    candidates.add(f"{SUPPORT_DIR}/{MANIFEST_NAME}")
    candidates.add(f"{SUPPORT_DIR}/{LOCK_NAME}")
    try:
        for rel in sorted(candidates):
            safe = _safe_rel_path(rel)
            dest = _dest_under_root(plan.root, safe)
            meta: dict[str, Any] = {"existed": False, "allowed_sha256": []}
            if safe in plan.files:
                meta["allowed_sha256"].append(sha256_bytes(plan.files[safe]))
            if safe == f"{SUPPORT_DIR}/{MANIFEST_NAME}":
                meta["allowed_sha256"].append(sha256_bytes(plan.manifest.dumps().encode("utf-8")))
            if safe == f"{SUPPORT_DIR}/{LOCK_NAME}":
                meta["transaction_lock"] = True
            if os.path.lexists(dest):
                if os.path.islink(dest) or not os.path.isfile(dest):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                snapshot = os.path.join(snapshot_dir, safe)
                _copy_regular_nofollow(dest, snapshot)
                meta.update(
                    {
                        "existed": True,
                        "snapshot": snapshot,
                        "sha256": sha256_file(snapshot),
                    }
                )
            paths[safe] = meta
        return InstallCheckpoint(root=plan.root, snapshot_dir=snapshot_dir, paths=paths)
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise


def restore_install_checkpoint(
    checkpoint: InstallCheckpoint,
    *,
    backup_root: str | None = None,
) -> None:
    """Restore a completed root install to its captured byte-for-byte file state."""
    removed: list[str] = []
    for rel, meta in checkpoint.paths.items():
        dest = _dest_under_root(checkpoint.root, rel)
        if meta.get("existed"):
            snapshot = meta.get("snapshot")
            if not isinstance(snapshot, str) or not os.path.isfile(snapshot) or os.path.islink(snapshot):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            if sha256_file(snapshot) != meta.get("sha256"):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            _restore_regular_nofollow(snapshot, dest)
            continue
        if not os.path.lexists(dest):
            continue
        if os.path.islink(dest) or not os.path.isfile(dest):
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        allowed = set(meta.get("allowed_sha256") or ())
        if sha256_file(dest) not in allowed:
            if not meta.get("transaction_lock"):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            lock_bytes = Path(dest).read_bytes()
            if not (
                lock_bytes.startswith(b"pid=")
                and lock_bytes.endswith(b"\n")
                and lock_bytes[4:-1].isdigit()
            ):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
        os.remove(dest)
        removed.append(rel)
    if backup_root:
        if not _path_within_support(checkpoint.root, backup_root):
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        if os.path.islink(backup_root):
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        _safe_rmtree_under_support(checkpoint.root, backup_root)
    _cleanup_empty_dirs(checkpoint.root, removed_paths=removed)


def discard_install_checkpoint(checkpoint: InstallCheckpoint) -> None:
    shutil.rmtree(checkpoint.snapshot_dir, ignore_errors=True)


def _restore_regular_nofollow(snapshot: str, dest: str) -> None:
    """Atomically restore one checkpoint file without following destination symlinks."""
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".portable-resume-restore-", dir=parent)
    os.close(fd)
    os.remove(temporary)
    try:
        _copy_regular_nofollow(snapshot, temporary)
        os.replace(temporary, dest)
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def _path_within_support(root: str, path: str) -> bool:
    support = os.path.realpath(os.path.join(root, SUPPORT_DIR))
    candidate = os.path.realpath(path)
    try:
        return os.path.commonpath((candidate, support)) == support and candidate != support
    except ValueError:
        return False


def _open_parent_and_target_under_fd(base_fd: int, rel: str) -> tuple[int, int, str]:
    """Open parent dir and target directory under base_fd without following symlinks."""
    parts = [part for part in rel.split(os.sep) if part and part != "."]
    if not parts:
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if len(parts) == 1:
        target_name = parts[0]
        try:
            target_fd = os.open(target_name, flags, dir_fd=base_fd)
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        return base_fd, target_fd, target_name
    current_fd = base_fd
    opened: list[int] = []
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            if current_fd is not base_fd:
                opened.append(current_fd)
            current_fd = next_fd
        parent_fd = current_fd
        target_name = parts[-1]
        try:
            target_fd = os.open(target_name, flags, dir_fd=parent_fd)
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        for fd in opened:
            os.close(fd)
        opened.clear()
        return parent_fd, target_fd, target_name
    except Exception:
        for fd in opened:
            os.close(fd)
        if current_fd is not base_fd:
            os.close(current_fd)
        raise


def _rmtree_nofollow_dirfd(dir_fd: int) -> None:
    """Delete directory contents at dir_fd without following symlinks."""
    import stat as stat_mod

    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    for name in os.listdir(dir_fd):
        try:
            st = os.lstat(name, dir_fd=dir_fd)
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        if stat_mod.S_ISDIR(st.st_mode) and not stat_mod.S_ISLNK(st.st_mode):
            sub_fd = os.open(name, flags, dir_fd=dir_fd)
            try:
                _rmtree_nofollow_dirfd(sub_fd)
            finally:
                os.close(sub_fd)
            try:
                os.rmdir(name, dir_fd=dir_fd)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        else:
            try:
                os.unlink(name, dir_fd=dir_fd)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error


def _safe_rmtree_under_support(root: str, path: str) -> None:
    """Remove a support subtree using pinned dirfds (TOCTOU-resistant)."""
    import stat as stat_mod

    if not isinstance(path, str):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    if not _supports_descriptor_relative_commit():
        raise DiagnosticError("E_RECOVERY_REQUIRED")

    try:
        st = os.lstat(path)
    except OSError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    if stat_mod.S_ISLNK(st.st_mode):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    if not stat_mod.S_ISDIR(st.st_mode):
        raise DiagnosticError("E_RECOVERY_REQUIRED")

    support_base = os.path.abspath(os.path.join(root, SUPPORT_DIR))
    candidate = os.path.abspath(path)
    try:
        if os.path.commonpath((candidate, support_base)) != support_base or candidate == support_base:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
    except ValueError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error

    rel = os.path.relpath(candidate, support_base)
    if rel == "." or rel.startswith(".."):
        raise DiagnosticError("E_RECOVERY_REQUIRED")

    try:
        root_fd = _open_skill_root_descriptor(root)
    except DiagnosticError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    support_fd: int | None = None
    parent_fd: int | None = None
    target_fd: int | None = None
    try:
        try:
            support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
        except DiagnosticError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        parent_fd, target_fd, target_name = _open_parent_and_target_under_fd(support_fd, rel)
        st = os.fstat(target_fd)
        if not stat_mod.S_ISDIR(st.st_mode):
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        _rmtree_nofollow_dirfd(target_fd)
        os.close(target_fd)
        target_fd = None
        os.rmdir(target_name, dir_fd=parent_fd)
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    finally:
        if target_fd is not None:
            os.close(target_fd)
        if parent_fd is not None and parent_fd not in (root_fd, support_fd):
            os.close(parent_fd)
        if support_fd is not None and support_fd != root_fd:
            os.close(support_fd)
        os.close(root_fd)


def _try_safe_rmtree_under_support(root: str, path: str) -> None:
    """Best-effort support cleanup; swallow containment failures."""
    try:
        _safe_rmtree_under_support(root, path)
    except (DiagnosticError, OSError):
        pass


def _rollback_paths(root: str, journal: dict[str, Any]) -> tuple[int, bool]:
    restored = 0
    complete = True
    for rel, meta in journal.get("paths", {}).items():
        try:
            safe = _safe_rel_path(str(rel))
            dest = _dest_under_root(root, safe)
        except DiagnosticError:
            continue
        rollback_backup = meta.get("rollback_backup") or meta.get("backup")
        if rollback_backup:
            if not _path_within_support(root, rollback_backup):
                complete = False
                continue
            if os.path.isfile(rollback_backup) and not os.path.islink(rollback_backup):
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    os.replace(rollback_backup, dest)
                    restored += 1
                    continue
                except OSError:
                    complete = False
                    continue
            # A prior rollback attempt may already have consumed the snapshot.
            try:
                original_sha = meta.get("original_sha256")
                if original_sha and os.path.isfile(dest) and not os.path.islink(dest):
                    if sha256_file(dest) == original_sha:
                        continue
            except OSError:
                pass
            complete = False
            continue
        if not meta.get("existed"):
            try:
                if not os.path.lexists(dest):
                    continue
                if os.path.islink(dest) or not os.path.isfile(dest):
                    complete = False
                    continue
                if sha256_file(dest) != meta.get("sha256"):
                    complete = False
                    continue
                os.remove(dest)
                restored += 1
            except OSError:
                complete = False
    return restored, complete


def _attempt_rollback(root: str, journal: dict[str, Any]) -> None:
    journal["state"] = "rollback"
    try:
        _write_journal(root, journal)
    except OSError:
        pass
    _restored, complete = _rollback_paths(root, journal)
    if complete:
        stage_dir = journal.get("stage_dir")
        if stage_dir:
            _try_safe_rmtree_under_support(root, stage_dir)
        backup_root = journal.get("backup_root")
        if backup_root:
            _try_safe_rmtree_under_support(root, backup_root)
        try:
            os.remove(journal_path(root))
        except OSError:
            pass


def recover_root(root: str) -> dict[str, Any]:
    path = journal_path(root)
    if not os.path.isfile(path):
        return {"ok": True, "recovered": False}
    with RootLock(root):
        journal = json.loads(Path(path).read_text(encoding="utf-8"))
        if journal.get("state") == "complete":
            stage_dir = journal.get("stage_dir")
            if stage_dir:
                if _path_within_support(root, stage_dir):
                    _try_safe_rmtree_under_support(root, stage_dir)
                else:
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
            os.remove(path)
            return {"ok": True, "recovered": True, "action": "cleared_complete_journal"}
        # incomplete: restore only transaction snapshots; keep journal on drift.
        restored, complete = _rollback_paths(root, journal)
        if not complete:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        stage_dir = journal.get("stage_dir")
        if stage_dir and os.path.isdir(stage_dir):
            if _path_within_support(root, stage_dir):
                _try_safe_rmtree_under_support(root, stage_dir)
        backup_root = journal.get("backup_root")
        if backup_root and _path_within_support(root, backup_root) and not os.path.islink(backup_root):
            _try_safe_rmtree_under_support(root, backup_root)
        os.remove(path)
        return {"ok": True, "recovered": True, "action": "restored_from_journal", "restored_paths": restored}


def verify_root(root: str, *, claim: str | None = None) -> dict[str, Any]:
    require_no_pending_journal(root)
    manifest = load_manifest(root)
    if manifest is None:
        raise DiagnosticError("E_VERIFY_MISMATCH")
    if manifest.schema_version != MANIFEST_SCHEMA or manifest.bundle_version != BUNDLE_VERSION:
        raise DiagnosticError("E_VERIFY_MISMATCH")
    if claim is not None and claim not in manifest.claims:
        raise DiagnosticError("E_VERIFY_MISMATCH")
    mismatches: list[str] = []
    for claim_id, meta in manifest.claims.items():
        if claim is not None and claim_id != claim:
            continue
        host = meta.get("host")
        if host not in HOST_PROFILES or meta.get("bundle_version") != BUNDLE_VERSION:
            raise DiagnosticError("E_VERIFY_MISMATCH")
        expected_files = materialize_plan(host)
        expected_identity = package_identity(expected_files)
        if manifest.package_identity != expected_identity:
            raise DiagnosticError("E_VERIFY_MISMATCH")
        claimed_paths = {rel for rel, entry in manifest.files.items() if claim_id in entry.claims}
        if claimed_paths != set(expected_files):
            raise DiagnosticError("E_VERIFY_MISMATCH")
        for rel, expected_bytes in sorted(expected_files.items()):
            entry = manifest.files[rel]
            expected_sha = sha256_bytes(expected_bytes)
            if entry.sha256 != expected_sha:
                mismatches.append(rel)
                continue
            try:
                path = _dest_under_root(root, rel)
                if os.path.islink(path) or not os.path.isfile(path):
                    mismatches.append(rel)
                    continue
                if sha256_file(path) != expected_sha:
                    mismatches.append(rel)
            except (DiagnosticError, OSError):
                mismatches.append(rel)
    if mismatches:
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
    from ..registry import matrix_dimensions

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
        "expected": matrix_dimensions()["cells"],
        "packaging_cells_supported": sum(1 for cell in cells if cell["packaging_supported"]),
        "live_cells_supported": 0,
        "cells": cells,
    }
