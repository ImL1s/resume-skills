"""Root lock, durable journal, stage/commit/rollback, verify, uninstall."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat as stat_mod
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..diagnostics import DiagnosticError
from .catalog import BUNDLE_VERSION, HOST_PROFILES, MANIFEST_SCHEMA
from .control_schema import ControlSchemaError, parse_journal_document
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
STAGE_PREFIX = "portable-resume-stage-"
_BACKUP_NAME_PREFIX_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-")
# Names under SUPPORT_DIR that journals must never be allowed to delete.
_PROTECTED_SUPPORT_NAMES = frozenset(
    {
        "runtime",
        "resources",
        BACKUP_DIR,
        MANIFEST_NAME,
        LOCK_NAME,
        JOURNAL_NAME,
    }
)


# Content identity for the previous ownership manifest (not generation alone).
_MANIFEST_ABSENT = "absent"


def manifest_content_digest(manifest: Manifest | None) -> str:
    """Return a stable identity for the previous manifest, or ``absent`` if none."""

    if manifest is None:
        return _MANIFEST_ABSENT
    return sha256_bytes(manifest.dumps().encode("utf-8"))


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
    # Preflight token: exact previous ownership identity observed while planning.
    # Execute recomputes under lock and never commits these fields as authority.
    base_generation: int | None = None
    base_manifest_digest: str = _MANIFEST_ABSENT

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
            "base_generation": self.base_generation,
            "base_manifest_digest": self.base_manifest_digest,
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
        _ensure_support_directory(self.root)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            fd: int | None = None
            try:
                fd = _open_support_control_file(
                    self.root,
                    LOCK_NAME,
                    flags=os.O_RDWR | os.O_CREAT,
                    mode=0o644,
                )
                if os.name == "nt":
                    self._fd = fd
                    return self
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.ftruncate(fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                payload = f"pid={os.getpid()}\n".encode("ascii")
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                try:
                    os.fsync(fd)
                except OSError:
                    pass
                self._fd = fd
                return self
            except BlockingIOError as error:
                if fd is not None:
                    os.close(fd)
                if time.monotonic() >= deadline:
                    raise DiagnosticError("E_INSTALL_BUSY") from error
                time.sleep(0.05)
            except DiagnosticError:
                if fd is not None:
                    os.close(fd)
                raise
            except OSError as error:
                if fd is not None:
                    os.close(fd)
                # Symlink / wrong type surfaces as ELOOP or similar — fail closed as conflict.
                if getattr(error, "errno", None) in {
                    getattr(os, "ELOOP", object()),
                    getattr(os, "EISDIR", object()),
                }:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
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
    if not os.path.lexists(path):
        return None
    try:
        raw = _read_support_control_file(root, MANIFEST_NAME)
    except DiagnosticError as error:
        # Missing is None; corrupt/symlink/type issues are verify failures.
        if not os.path.lexists(path):
            return None
        raise DiagnosticError("E_VERIFY_MISMATCH") from error
    try:
        return Manifest.loads(raw.decode("utf-8"))
    except ValueError as error:
        raise DiagnosticError("E_VERIFY_MISMATCH") from error
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DiagnosticError("E_VERIFY_MISMATCH") from error


def require_no_pending_journal(root: str) -> None:
    path = journal_path(root)
    if not os.path.lexists(path):
        return
    if os.path.islink(path) or not os.path.isfile(path):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
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
    """Build an advisory install plan from the current root state.

    The returned plan is **not** mutation authority. ``execute_install`` rebuilds
    an equivalent plan under ``RootLock`` from the exact locked ownership
    manifest so stale preflight claims cannot be committed (#35).
    """

    if host not in HOST_PROFILES:
        raise DiagnosticError.invalid()
    files = materialize_plan(host)
    identity = package_identity(files)
    claim = claim_key(host=host, scope=scope, root=root)
    existing = load_manifest(root)
    base_generation = None if existing is None else existing.generation
    base_digest = manifest_content_digest(existing)
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
        kind = _classify_dest(
            root=root,
            rel=rel,
            data=data,
            existing=existing,
            claim=claim,
            force_with_backup=force_with_backup,
        )
        if kind == "create":
            creates.append(rel)
        elif kind == "retain":
            retains.append(rel)
        elif kind == "replace":
            replaces.append(rel)
        elif kind == "backup":
            replaces.append(rel)
            backups.append(rel)
        else:
            raise DiagnosticError("E_INVARIANT")
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
        base_generation=base_generation,
        base_manifest_digest=base_digest,
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


_CONTROL_BASENAMES = frozenset({LOCK_NAME, JOURNAL_NAME, MANIFEST_NAME})


def _ensure_install_root_exists(root: str) -> None:
    """Create the skill-root directory if missing (legacy makedirs support-path behavior)."""
    if os.path.lexists(root):
        if not os.path.isdir(root):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        return
    try:
        os.makedirs(root, mode=0o755, exist_ok=True)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    if not os.path.isdir(root) or (os.path.islink(root) and not os.path.isdir(root)):
        raise DiagnosticError("E_INSTALL_CONFLICT")


def _ensure_support_directory(root: str) -> None:
    """Create or open ``.portable-resume`` under root without following a symlink support dir."""
    _ensure_install_root_exists(root)
    if _supports_descriptor_relative_commit():
        root_fd = _open_skill_root_descriptor(root)
        try:
            try:
                st = os.lstat(SUPPORT_DIR, dir_fd=root_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(SUPPORT_DIR, 0o755, dir_fd=root_fd)
                except FileExistsError:
                    pass
                try:
                    st = os.lstat(SUPPORT_DIR, dir_fd=root_fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISDIR(st.st_mode):
                raise DiagnosticError("E_INSTALL_CONFLICT")
            flags = (
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                support_fd = os.open(SUPPORT_DIR, flags, dir_fd=root_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            os.close(support_fd)
            return
        finally:
            os.close(root_fd)

    support = os.path.join(root, SUPPORT_DIR)
    if os.path.lexists(support):
        try:
            st = os.lstat(support)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISDIR(st.st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        return
    try:
        os.mkdir(support, 0o755)
    except FileExistsError:
        pass
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    try:
        st = os.lstat(support)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISDIR(st.st_mode):
        raise DiagnosticError("E_INSTALL_CONFLICT")


def _open_support_control_file(
    root: str,
    name: str,
    *,
    flags: int,
    mode: int = 0o644,
) -> int:
    """Open a control-plane basename under support with no-follow regular-file checks."""
    if name not in _CONTROL_BASENAMES:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    _ensure_support_directory(root)
    if _supports_descriptor_relative_commit():
        root_fd = _open_skill_root_descriptor(root)
        support_fd: int | None = None
        try:
            support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
            try:
                existing = os.lstat(name, dir_fd=support_fd)
            except FileNotFoundError:
                existing = None
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if existing is not None and (
                stat_mod.S_ISLNK(existing.st_mode) or not stat_mod.S_ISREG(existing.st_mode)
            ):
                raise DiagnosticError("E_INSTALL_CONFLICT")
            open_flags = flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(name, open_flags, mode, dir_fd=support_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            try:
                st = os.fstat(fd)
            except OSError as error:
                os.close(fd)
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if not stat_mod.S_ISREG(st.st_mode):
                os.close(fd)
                raise DiagnosticError("E_INSTALL_CONFLICT")
            return fd
        finally:
            if support_fd is not None:
                os.close(support_fd)
            os.close(root_fd)

    path = os.path.join(root, SUPPORT_DIR, name)
    if os.path.lexists(path):
        try:
            st = os.lstat(path)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
    try:
        fd = os.open(path, flags | getattr(os, "O_CLOEXEC", 0), mode)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    try:
        st = os.fstat(fd)
    except OSError as error:
        os.close(fd)
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    if not stat_mod.S_ISREG(st.st_mode):
        os.close(fd)
        raise DiagnosticError("E_INSTALL_CONFLICT")
    return fd


def _read_support_control_file(root: str, name: str) -> bytes:
    fd = _open_support_control_file(root, name, flags=os.O_RDONLY)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _atomic_write_support_file(root: str, name: str, data: bytes) -> None:
    """Atomically replace a control document under the pinned support directory."""
    if name not in {JOURNAL_NAME, MANIFEST_NAME}:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    if not isinstance(data, (bytes, bytearray)):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    payload = bytes(data)
    _ensure_support_directory(root)

    if _supports_descriptor_relative_commit():
        root_fd = _open_skill_root_descriptor(root)
        support_fd: int | None = None
        tmp_name: str | None = None
        try:
            support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
            tmp_name = f".{name}.tmp-{secrets.token_hex(8)}"
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                fd = os.open(tmp_name, flags, 0o644, dir_fd=support_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                try:
                    os.fsync(fd)
                except OSError:
                    pass
            finally:
                os.close(fd)
            try:
                existing = os.lstat(name, dir_fd=support_fd)
            except FileNotFoundError:
                existing = None
            except OSError as error:
                try:
                    os.unlink(tmp_name, dir_fd=support_fd)
                except OSError:
                    pass
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if existing is not None and (
                stat_mod.S_ISLNK(existing.st_mode) or not stat_mod.S_ISREG(existing.st_mode)
            ):
                try:
                    os.unlink(tmp_name, dir_fd=support_fd)
                except OSError:
                    pass
                raise DiagnosticError("E_INSTALL_CONFLICT")
            try:
                os.replace(tmp_name, name, src_dir_fd=support_fd, dst_dir_fd=support_fd)
            except OSError as error:
                try:
                    os.unlink(tmp_name, dir_fd=support_fd)
                except OSError:
                    pass
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            tmp_name = None
            try:
                os.fsync(support_fd)
            except OSError:
                pass
            return
        finally:
            if tmp_name is not None and support_fd is not None:
                try:
                    os.unlink(tmp_name, dir_fd=support_fd)
                except OSError:
                    pass
            if support_fd is not None:
                os.close(support_fd)
            os.close(root_fd)

    support = os.path.join(root, SUPPORT_DIR)
    path = os.path.join(support, name)
    if os.path.lexists(path) and (os.path.islink(path) or not os.path.isfile(path)):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    tmp_path = os.path.join(support, f".{name}.tmp-{secrets.token_hex(8)}")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(tmp_path, flags, 0o644)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            try:
                os.fsync(fd)
            except OSError:
                pass
        finally:
            os.close(fd)
        os.replace(tmp_path, path)
    except OSError as error:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise DiagnosticError("E_INSTALL_CONFLICT") from error


def _open_directory_from_slash(path: str, *, allow_leaf_symlink: bool = False) -> int:
    """Open a directory by walking each component from ``/`` with ``O_NOFOLLOW``.

    Never pathname-open a multi-component resolved path in one shot: a writable
    ancestor swapped for a symlink after ``realpath`` would otherwise be followed
    through intermediate components.

    When a symlink is encountered, the replacement directory is opened *before*
    releasing any previously pinned ancestor descriptors, so there is no gap
    where the original path can be retargeted and then re-accepted.
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
        index = 0
        while index < len(parts):
            part = parts[index]
            is_leaf = index == len(parts) - 1
            parent_fd = current_fd
            try:
                st = os.lstat(part, dir_fd=parent_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error

            if stat_mod.S_ISLNK(st.st_mode):
                if is_leaf and not allow_leaf_symlink:
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                try:
                    target = os.readlink(part, dir_fd=parent_fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error

                # Open the replacement while ancestors remain pinned (no close-then-
                # reopen gap). Then continue the component walk so a later leaf
                # symlink (skill-root) still gets allow_leaf_symlink handling.
                if not os.path.isabs(target):
                    rel_parts = [p for p in target.replace("\\", "/").split("/") if p and p != "."]
                    probe_fd = parent_fd
                    probe_opened: list[int] = []
                    try:
                        for rel_part in rel_parts:
                            if rel_part == os.pardir:
                                raise DiagnosticError("E_INSTALL_CONFLICT")
                            try:
                                next_probe = os.open(rel_part, flags, dir_fd=probe_fd)
                            except OSError as error:
                                raise DiagnosticError("E_INSTALL_CONFLICT") from error
                            if probe_fd is not parent_fd:
                                probe_opened.append(probe_fd)
                            probe_fd = next_probe
                        replacement_fd = probe_fd
                        for fd in probe_opened:
                            os.close(fd)
                        probe_opened.clear()
                    except Exception:
                        for fd in probe_opened:
                            os.close(fd)
                        if probe_fd is not parent_fd:
                            os.close(probe_fd)
                        raise
                    new_prefix = os.path.abspath(os.path.join(prefix, target))
                else:
                    if not is_leaf:
                        try:
                            if os.path.commonpath((os.path.abspath(target), prefix)) != prefix:
                                raise DiagnosticError("E_INSTALL_CONFLICT")
                        except ValueError as error:
                            raise DiagnosticError("E_INSTALL_CONFLICT") from error
                    replacement_fd = _open_directory_from_slash(
                        target,
                        allow_leaf_symlink=False,
                    )
                    new_prefix = os.path.abspath(target)

                for fd in opened:
                    os.close(fd)
                opened = [replacement_fd]
                current_fd = replacement_fd
                prefix = new_prefix
                if is_leaf:
                    opened.clear()
                    return replacement_fd
                index += 1
                continue

            try:
                next_fd = os.open(part, flags, dir_fd=parent_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            opened.append(next_fd)
            current_fd = next_fd
            prefix = os.path.join(prefix, part)
            index += 1

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


def _validate_staged_regular_file(
    *,
    parent_fd: int,
    basename: str,
    expected_sha256: str | None = None,
) -> None:
    """Reject symlink/dir/fifo staged entries before commit replace."""
    import hashlib
    import stat as stat_mod

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(basename, flags, dir_fd=parent_fd)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    try:
        if not stat_mod.S_ISREG(os.fstat(fd).st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        if expected_sha256 is not None:
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            if digest.hexdigest() != expected_sha256:
                raise DiagnosticError("E_INSTALL_CONFLICT")
    finally:
        os.close(fd)


def _open_parent_under_root_fd(
    root_fd: int,
    rel: str,
    *,
    create: bool = False,
) -> tuple[int, str, bool]:
    """Return ``(parent_fd, basename, owns_parent_fd)`` for ``rel`` under ``root_fd``."""
    safe = _safe_rel_path(rel)
    basename = os.path.basename(safe)
    parent_rel = os.path.dirname(safe)
    if not basename or basename in {os.pardir, "."}:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    if create:
        _mkdir_directory_under_root(root_fd, parent_rel)
    if parent_rel in ("", "."):
        return root_fd, basename, False
    parent_fd = _open_directory_under_root(root_fd, parent_rel)
    return parent_fd, basename, True


def _sha256_regular_under_root_fd(root_fd: int, rel: str) -> str:
    parent_fd, basename, owns_parent = _open_parent_under_root_fd(root_fd, rel, create=False)
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(basename, flags, dir_fd=parent_fd)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        try:
            st = os.fstat(fd)
            if not stat_mod.S_ISREG(st.st_mode):
                raise DiagnosticError("E_INSTALL_CONFLICT")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest()
        finally:
            os.close(fd)
    finally:
        if owns_parent:
            os.close(parent_fd)


def _sha256_open_fd(fd: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _is_hex_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _mkdir_unique_under_fd(parent_fd: int, prefix: str) -> str:
    """Create a unique subdirectory under parent_fd; return the basename."""
    for _ in range(32):
        name = f"{prefix}{secrets.token_hex(6)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            return name
        except FileExistsError:
            continue
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
    raise DiagnosticError("E_INSTALL_CONFLICT")


def _materialize_bytes_under_fd(base_fd: int, rel: str, data: bytes, *, mode: int) -> None:
    """Write ``rel`` under base_fd with mkdir-nofollow + O_EXCL regular create."""
    safe = _safe_rel_path(rel)
    parent_rel = os.path.dirname(safe)
    basename = os.path.basename(safe)
    if not basename:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    _mkdir_directory_under_root(base_fd, parent_rel)
    parent_fd, leaf, owns_parent = _open_parent_under_root_fd(base_fd, safe, create=False)
    # When parent_rel is empty, parent is base_fd; still open via helper for consistency.
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            fd = os.open(leaf, flags, mode, dir_fd=parent_fd)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    finally:
        if owns_parent:
            os.close(parent_fd)


def _unlink_regular_under_root_fd(
    root_fd: int,
    rel: str,
    *,
    expected_sha256: str | None = None,
) -> bool:
    """Unlink a regular payload file under a pinned root. Return False if absent or digest mismatch.

    When ``expected_sha256`` is set, rename the leaf to a quarantine name under the same
    parent fd first so the hashed inode is the one that will be deleted (leaf-swap safe).
    """
    if expected_sha256 is not None and not _is_hex_sha256(expected_sha256):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    parent_fd, basename, owns_parent = _open_parent_under_root_fd(root_fd, rel, create=False)
    try:
        try:
            st = os.lstat(basename, dir_fd=parent_fd)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        if expected_sha256 is None:
            try:
                os.unlink(basename, dir_fd=parent_fd)
            except FileNotFoundError:
                return False
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            return True

        quarantine = f".portable-resume-unlink-{secrets.token_hex(8)}"
        try:
            os.rename(basename, quarantine, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        restored = False
        try:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(quarantine, flags, dir_fd=parent_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            try:
                st = os.fstat(fd)
                if not stat_mod.S_ISREG(st.st_mode):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                digest = _sha256_open_fd(fd)
            finally:
                os.close(fd)
            if digest != expected_sha256:
                try:
                    os.rename(quarantine, basename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    restored = True
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                return False
            try:
                os.unlink(quarantine, dir_fd=parent_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            return True
        except Exception:
            if not restored:
                try:
                    os.rename(quarantine, basename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                except OSError:
                    pass
            raise
    finally:
        if owns_parent:
            os.close(parent_fd)


def _replace_under_root_from_support_path(
    *,
    root: str,
    root_fd: int,
    rel: str,
    support_src: str,
    expected_sha256: str | None = None,
) -> None:
    """Atomically replace payload ``rel`` from an authorized path under ``.portable-resume``."""
    if not _path_within_support(root, support_src):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    if expected_sha256 is not None and not _is_hex_sha256(expected_sha256):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    support_base = os.path.abspath(os.path.join(root, SUPPORT_DIR))
    src_abs = os.path.abspath(support_src)
    src_rel = os.path.relpath(src_abs, support_base)
    if src_rel.startswith("..") or os.path.isabs(src_rel):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    src_parts = [part for part in src_rel.split(os.sep) if part and part != "."]
    if not src_parts or any(part in {os.pardir, "."} for part in src_parts):
        raise DiagnosticError("E_RECOVERY_REQUIRED")

    support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
    src_parent_fd: int | None = None
    dst_parent_fd: int | None = None
    owns_dst_parent = False
    try:
        # Open source parent under support without following symlinks.
        if len(src_parts) == 1:
            src_parent_fd = support_fd
            src_basename = src_parts[0]
        else:
            src_parent_rel = "/".join(src_parts[:-1])
            src_parent_fd = _open_directory_under_root(support_fd, src_parent_rel)
            src_basename = src_parts[-1]
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            src_fd = os.open(src_basename, flags, dir_fd=src_parent_fd)
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        try:
            st = os.fstat(src_fd)
            if not stat_mod.S_ISREG(st.st_mode):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            if expected_sha256 is not None:
                if _sha256_open_fd(src_fd) != expected_sha256:
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
        finally:
            os.close(src_fd)

        dst_parent_fd, dst_basename, owns_dst_parent = _open_parent_under_root_fd(
            root_fd, rel, create=True
        )
        try:
            os.replace(
                src_basename,
                dst_basename,
                src_dir_fd=src_parent_fd,
                dst_dir_fd=dst_parent_fd,
            )
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    finally:
        if owns_dst_parent and dst_parent_fd is not None:
            os.close(dst_parent_fd)
        if src_parent_fd is not None and src_parent_fd is not support_fd:
            os.close(src_parent_fd)
        os.close(support_fd)


def _commit_payload_file(
    *,
    root: str,
    root_fd: int | None,
    rel: str,
    staged_src: str,
    stage_dir: str | None = None,
    expected_sha256: str | None = None,
) -> None:
    """Atomically commit one staged payload under root with TOCTOU-resistant checks."""
    safe = _safe_rel_path(rel)
    basename = os.path.basename(safe)
    parent_rel = os.path.dirname(safe)
    if not basename:
        raise DiagnosticError("E_INSTALL_CONFLICT")

    _dest_under_root(root, safe)

    if not _supports_descriptor_relative_commit():
        # Platforms without dir_fd / O_NOFOLLOW replace: fail closed (Windows not a V1 gate).
        raise DiagnosticError("E_INSTALL_CONFLICT")
    if root_fd is None or not stage_dir:
        raise DiagnosticError("E_INSTALL_CONFLICT")

    # Stage identity must match the journal-owned stage tree before any replace.
    authorized_stage = _authorize_support_cleanup(root, stage_dir, role="stage")
    if authorized_stage is None:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    stage_name = os.path.basename(authorized_stage)
    staged_abs = os.path.abspath(staged_src)
    try:
        staged_rel = os.path.relpath(staged_abs, authorized_stage)
    except ValueError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    if staged_rel.startswith("..") or os.path.isabs(staged_rel):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    src_basename = os.path.basename(staged_rel)
    src_parent_rel = os.path.dirname(staged_rel)

    _mkdir_directory_under_root(root_fd, parent_rel)
    support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
    stage_fd: int | None = None
    src_parent_fd: int | None = None
    dst_parent_fd: int | None = None
    try:
        stage_fd = _open_directory_under_root(support_fd, stage_name)
        if src_parent_rel in ("", "."):
            src_parent_fd = stage_fd
        else:
            src_parent_fd = _open_directory_under_root(stage_fd, src_parent_rel)
        dst_parent_fd = _open_directory_under_root(root_fd, parent_rel)
        _validate_staged_regular_file(
            parent_fd=src_parent_fd,
            basename=src_basename,
            expected_sha256=expected_sha256,
        )
        os.replace(
            src_basename,
            basename,
            src_dir_fd=src_parent_fd,
            dst_dir_fd=dst_parent_fd,
        )
    finally:
        if dst_parent_fd is not None and dst_parent_fd is not root_fd:
            os.close(dst_parent_fd)
        if (
            src_parent_fd is not None
            and src_parent_fd not in (stage_fd, support_fd, root_fd)
        ):
            os.close(src_parent_fd)
        if stage_fd is not None and stage_fd not in (support_fd, root_fd):
            os.close(stage_fd)
        if support_fd is not root_fd:
            os.close(support_fd)


def _classify_dest(
    *,
    root: str,
    rel: str,
    data: bytes,
    existing: Manifest | None,
    claim: str,
    force_with_backup: bool,
) -> str:
    """Return create|retain|replace|backup under current disk state.

    Ownership is claim/manifest-aware: a path listed in the ownership manifest
    (this claim or shared multi-claim payload) may be replaced. Foreign paths
    require an explicit force-with-backup policy for the current classification.
    """

    dest = _dest_under_root(root, rel)
    if not os.path.lexists(dest):
        return "create"
    if os.path.islink(dest) or not os.path.isfile(dest):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    current = sha256_file(dest)
    expected = sha256_bytes(data)
    if current == expected:
        return "retain"
    if existing is not None and rel in existing.files:
        entry = existing.files[rel]
        # Claim owns the path, or the path is already in the shared owned set
        # (multi-claim coordinated upgrade). Foreign unknowns are not here.
        if claim in entry.claims or entry.claims:
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
        # Preflight token is advisory for payload bytes, but ownership identity
        # must still match: if the locked manifest digest diverged, fail busy so
        # multi-root compensation restores the captured checkpoint rather than
        # committing a newer concurrent generation then rolling it back (#35).
        existing_pre = load_manifest(root)
        current_digest = manifest_content_digest(existing_pre)
        if current_digest != plan.base_manifest_digest:
            raise DiagnosticError("E_INSTALL_BUSY")
        changed_since_preflight = False

        # Honor preflight force classification when the Python API calls
        # execute_install(plan) without repeating force_with_backup=True.
        effective_force = force_with_backup or bool(plan.backups)
        locked = plan_install(
            host=plan.host,
            scope=plan.scope,
            root=plan.root,
            dry_run=False,
            force_with_backup=effective_force,
        )
        # Request identity must match; payload/manifest always come from locked rebuild.
        if (
            locked.host != plan.host
            or locked.scope != plan.scope
            or locked.claim != plan.claim
            or os.path.realpath(locked.root) != os.path.realpath(plan.root)
        ):
            raise DiagnosticError("E_INSTALL_BUSY")
        # Digest must still match after replan observation (same locked read path).
        if locked.base_manifest_digest != plan.base_manifest_digest:
            raise DiagnosticError("E_INSTALL_BUSY")
        plan = locked
        existing = existing_pre
        # Re-evaluate ownership under the lock for the rebuilt plan only.
        planned_backups = set(plan.backups)
        backups: list[str] = []
        for rel, data in plan.files.items():
            kind = _classify_dest(
                root=root,
                rel=rel,
                data=data,
                existing=existing,
                claim=plan.claim,
                force_with_backup=effective_force or rel in planned_backups,
            )
            if kind == "backup":
                backups.append(rel)
        _ensure_support_directory(root)
        if not _supports_descriptor_relative_commit():
            raise DiagnosticError("E_INSTALL_CONFLICT")
        pin_root_fd = _open_skill_root_descriptor(root)
        support_fd: int | None = None
        stage_fd: int | None = None
        stage_dir = ""
        backup_root: str | None = None
        try:
            support_fd = _open_directory_under_root(pin_root_fd, SUPPORT_DIR)
            stage_name = _mkdir_unique_under_fd(support_fd, STAGE_PREFIX)
            stage_dir = os.path.join(os.path.abspath(root), SUPPORT_DIR, stage_name)
            stage_fd = os.open(
                stage_name,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=support_fd,
            )
            journal = {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "staging",
                "generation": plan.generation,
                "claim": plan.claim,
                "stage_dir": stage_dir,
                "backup_root": backup_root,
                "paths": {},
            }
            if backups:
                try:
                    os.mkdir(BACKUP_DIR, 0o755, dir_fd=support_fd)
                except FileExistsError:
                    pass
                # Re-open backups under support without following a symlink leaf.
                try:
                    backup_parent_fd = os.open(
                        BACKUP_DIR,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=support_fd,
                    )
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                try:
                    backup_name = _mkdir_unique_under_fd(
                        backup_parent_fd,
                        time.strftime("%Y%m%dT%H%M%SZ-", time.gmtime()),
                    )
                finally:
                    os.close(backup_parent_fd)
                backup_root = os.path.join(os.path.abspath(root), SUPPORT_DIR, BACKUP_DIR, backup_name)
                journal["backup_root"] = backup_root
            for rel, data in plan.files.items():
                safe = _safe_rel_path(rel)
                mode = 0o755 if rel.endswith("run_reader.py") else 0o644
                _materialize_bytes_under_fd(stage_fd, safe, data, mode=mode)
                journal["paths"][safe] = {
                    "state": "staged",
                    "sha256": sha256_bytes(data),
                    "existed": False,
                }
            # Snapshot every existing destination before the first replacement.
            # Owned files need the same rollback protection as foreign conflicts.
            for rel in sorted(plan.files):
                safe = _safe_rel_path(rel)
                try:
                    src_parent_fd, src_base, owns_src_parent = _open_parent_under_root_fd(
                        pin_root_fd, safe, create=False
                    )
                except DiagnosticError:
                    # Parent path missing → create target; no snapshot.
                    continue
                try:
                    try:
                        st = os.lstat(src_base, dir_fd=src_parent_fd)
                    except FileNotFoundError:
                        continue
                    except OSError as error:
                        raise DiagnosticError("E_INSTALL_CONFLICT") from error
                    if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
                        raise DiagnosticError("E_INSTALL_CONFLICT")
                    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
                    try:
                        src_fd = os.open(src_base, flags, dir_fd=src_parent_fd)
                    except OSError as error:
                        raise DiagnosticError("E_INSTALL_CONFLICT") from error
                    try:
                        st = os.fstat(src_fd)
                        if not stat_mod.S_ISREG(st.st_mode):
                            raise DiagnosticError("E_INSTALL_CONFLICT")
                        snap_mode = stat_mod.S_IMODE(st.st_mode)
                        chunks: list[bytes] = []
                        while True:
                            chunk = os.read(src_fd, 1024 * 1024)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        body = b"".join(chunks)
                    finally:
                        os.close(src_fd)
                finally:
                    if owns_src_parent:
                        os.close(src_parent_fd)
                payload_digest = sha256_bytes(body)
                rollback_rel = f".rollback/{safe}"
                _materialize_bytes_under_fd(stage_fd, rollback_rel, body, mode=snap_mode)
                target = os.path.join(stage_dir, ".rollback", safe)
                journal["paths"][safe]["existed"] = True
                journal["paths"][safe]["rollback_backup"] = target
                journal["paths"][safe]["original_sha256"] = payload_digest
            # backup non-owned conflicts / forced replaces
            for rel in backups:
                safe = _safe_rel_path(rel)
                if backup_root is None:
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                try:
                    body_digest = _sha256_regular_under_root_fd(pin_root_fd, safe)
                except DiagnosticError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                src_parent_fd, src_base, owns_src_parent = _open_parent_under_root_fd(
                    pin_root_fd, safe, create=False
                )
                try:
                    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
                    src_fd = os.open(src_base, flags, dir_fd=src_parent_fd)
                    try:
                        chunks = []
                        while True:
                            chunk = os.read(src_fd, 1024 * 1024)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        body = b"".join(chunks)
                    finally:
                        os.close(src_fd)
                finally:
                    if owns_src_parent:
                        os.close(src_parent_fd)
                if sha256_bytes(body) != body_digest:
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                # Write under backup dir via support_fd/backups/<name>/...
                backup_name = os.path.basename(backup_root)
                backups_fd = os.open(
                    BACKUP_DIR,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=support_fd,
                )
                try:
                    one_backup_fd = os.open(
                        backup_name,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=backups_fd,
                    )
                    try:
                        _materialize_bytes_under_fd(one_backup_fd, safe, body, mode=0o644)
                    finally:
                        os.close(one_backup_fd)
                finally:
                    os.close(backups_fd)
                journal["paths"][safe]["backup"] = os.path.join(backup_root, safe)
            journal["state"] = "committing"
            _write_journal(root, journal)
            # commit files
            root_fd: int | None = pin_root_fd
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
                        force_with_backup=effective_force or safe in planned_backups or safe in backups,
                    )
                    if kind == "backup" and safe not in backups and not effective_force and safe not in planned_backups:
                        raise DiagnosticError("E_INSTALL_CONFLICT")
                    if kind == "retain":
                        journal["paths"][safe]["state"] = "retained"
                        _write_journal(root, journal)
                        continue
                    src = os.path.join(stage_dir, safe)
                    _commit_payload_file(
                        root=root,
                        root_fd=root_fd,
                        rel=safe,
                        staged_src=src,
                        stage_dir=stage_dir,
                        expected_sha256=sha256_bytes(plan.files[rel]),
                    )
                    journal["paths"][safe]["state"] = "committed"
                    _write_journal(root, journal)
            finally:
                # pin_root_fd is closed in outer finally; do not close here.
                root_fd = None
            # Remove owned orphans (in old manifest, not in new plan, sole claim released).
            # Journal orphan targets *before* delete so crash recovery can reason about them.
            orphan_removed: list[str] = []
            orphan_pending: list[tuple[str, str]] = []  # rel, sha256
            if existing is not None:
                for rel, entry in list(existing.files.items()):
                    if rel in plan.files:
                        continue
                    # After rebuild, plan.manifest already dropped empty-claim orphans.
                    if rel in plan.manifest.files:
                        continue
                    try:
                        digest = _sha256_regular_under_root_fd(pin_root_fd, rel)
                    except DiagnosticError:
                        continue
                    if digest == entry.sha256:
                        orphan_pending.append((rel, entry.sha256))
            if orphan_pending:
                journal["orphans"] = {
                    rel: {"sha256": digest, "state": "pending"}
                    for rel, digest in orphan_pending
                }
                journal["state"] = "orphaning"
                _write_journal(root, journal)
                for rel, digest in orphan_pending:
                    try:
                        removed = _unlink_regular_under_root_fd(
                            pin_root_fd,
                            rel,
                            expected_sha256=digest,
                        )
                        if removed:
                            orphan_removed.append(rel)
                            journal["orphans"][rel]["state"] = "removed"
                        else:
                            journal["orphans"][rel]["state"] = "skipped"
                        _write_journal(root, journal)
                    except DiagnosticError:
                        journal["orphans"][rel]["state"] = "skipped"
                        _write_journal(root, journal)
            # Durable intent before replacing the ownership manifest: on-disk journal
            # records the target generation so recover can recognize a published
            # generation even if the later ``complete`` journal write fails.
            journal["state"] = "publishing_manifest"
            journal["target_generation"] = plan.generation
            _write_journal(root, journal)
            _atomic_write_support_file(
                root,
                MANIFEST_NAME,
                plan.manifest.dumps().encode("utf-8"),
            )
            journal["state"] = "complete"
            try:
                _write_journal(root, journal)
            except DiagnosticError:
                # Manifest is already the ownership source of truth. Prefer dropping a
                # stale incomplete journal so recover cannot rollback under gen N.
                try:
                    _unlink_support_control_file(root, JOURNAL_NAME)
                except DiagnosticError:
                    pass
            # After the new manifest is published, never payload-rollback on cleanup
            # failure: leave a complete journal (or generation-matched stale journal)
            # for recover_root instead.
            try:
                _delete_authorized_support_subtree(root, stage_dir, role="stage")
            except DiagnosticError:
                pass
            try:
                if os.path.lexists(journal_path(root)):
                    _unlink_support_control_file(root, JOURNAL_NAME)
            except DiagnosticError:
                pass
            result = {
                "ok": True,
                "dry_run": False,
                "plan": plan.to_dict(),
                "generation": plan.generation,
                "changed_since_preflight": changed_since_preflight,
                "previous_manifest_digest": plan.base_manifest_digest,
            }
            if orphan_removed:
                result["orphan_removed"] = orphan_removed
            if backups:
                result["backup_root"] = backup_root
            return result
        except Exception:
            if "journal" in locals() and isinstance(journal, dict):
                if not _install_generation_is_published(root, journal):
                    _attempt_rollback(root, journal)
            raise
        finally:
            if stage_fd is not None:
                os.close(stage_fd)
            if support_fd is not None:
                os.close(support_fd)
            os.close(pin_root_fd)


def _write_journal(root: str, journal: dict[str, Any]) -> None:
    payload = json.dumps(journal, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    # Self-check closed journal schema before durable write (#28).
    try:
        parse_journal_document(payload)
    except ControlSchemaError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    _atomic_write_support_file(root, JOURNAL_NAME, payload.encode("utf-8"))


def _unlink_support_control_file(root: str, name: str) -> None:
    """Unlink a control basename under support without following a symlink leaf."""
    if name not in _CONTROL_BASENAMES:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    if not _supports_descriptor_relative_commit():
        path = os.path.join(root, SUPPORT_DIR, name)
        if not os.path.lexists(path):
            return
        if os.path.islink(path) or not os.path.isfile(path):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        os.unlink(path)
        return
    root_fd = _open_skill_root_descriptor(root)
    support_fd: int | None = None
    try:
        try:
            support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
        except DiagnosticError:
            return
        try:
            st = os.lstat(name, dir_fd=support_fd)
        except FileNotFoundError:
            return
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        try:
            os.unlink(name, dir_fd=support_fd)
        except FileNotFoundError:
            return
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
    finally:
        if support_fd is not None:
            os.close(support_fd)
        os.close(root_fd)


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
        _delete_authorized_support_subtree(checkpoint.root, backup_root, role="backup")
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


def _authorize_support_cleanup(root: str, path: str, *, role: str) -> str | None:
    """Authorize journal-driven deletion of stage/backup trees only.

    ``role`` is ``\"stage\"`` (direct child ``portable-resume-stage-*`` under
    ``.portable-resume``) or ``\"backup\"`` (direct child under
    ``.portable-resume/backups``). Protected control-plane names such as
    ``runtime``, ``resources``, and ``backups`` itself are never authorized.

    Returns the absolute path to delete, or ``None`` when the authorized path is
    already absent (idempotent cleanup).
    """
    import stat as stat_mod

    if role not in {"stage", "backup"}:
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    if not isinstance(path, str) or not path:
        raise DiagnosticError("E_RECOVERY_REQUIRED")

    support_path = os.path.join(root, SUPPORT_DIR)
    try:
        support_stat = os.lstat(support_path)
    except OSError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    if stat_mod.S_ISLNK(support_stat.st_mode) or not stat_mod.S_ISDIR(support_stat.st_mode):
        raise DiagnosticError("E_RECOVERY_REQUIRED")

    support_base = os.path.abspath(support_path)
    candidate = os.path.abspath(path)
    try:
        if os.path.commonpath((candidate, support_base)) != support_base or candidate == support_base:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
    except ValueError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error

    rel = os.path.relpath(candidate, support_base)
    parts = [part for part in rel.split(os.sep) if part and part != "."]
    if any(part in {os.pardir, "."} for part in parts):
        raise DiagnosticError("E_RECOVERY_REQUIRED")

    if role == "stage":
        if len(parts) != 1:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        name = parts[0]
        if name in _PROTECTED_SUPPORT_NAMES or not name.startswith(STAGE_PREFIX):
            raise DiagnosticError("E_RECOVERY_REQUIRED")
    else:
        if len(parts) != 2 or parts[0] != BACKUP_DIR:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        backup_name = parts[1]
        if (
            not backup_name
            or backup_name in {os.pardir, "."}
            or backup_name in _PROTECTED_SUPPORT_NAMES
            or not _BACKUP_NAME_PREFIX_RE.match(backup_name)
        ):
            raise DiagnosticError("E_RECOVERY_REQUIRED")

    if not os.path.lexists(path):
        return None

    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    if stat_mod.S_ISLNK(path_stat.st_mode) or not stat_mod.S_ISDIR(path_stat.st_mode):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    return candidate


def _delete_authorized_support_subtree(root: str, path: str, *, role: str) -> None:
    """Authorize then delete a stage/backup tree; failures stay fail-closed."""
    authorized = _authorize_support_cleanup(root, path, role=role)
    if authorized is None:
        return
    _safe_rmtree_under_support(root, authorized)


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
    if not _supports_descriptor_relative_commit():
        # Payload restore/delete mutations require dirfd containment (Windows residual #29).
        return 0, False
    try:
        root_fd = _open_skill_root_descriptor(root)
    except DiagnosticError:
        return 0, False
    try:
        for rel, meta in journal.get("paths", {}).items():
            try:
                safe = _safe_rel_path(str(rel))
            except DiagnosticError:
                # Ignore unusable journal path keys (e.g. ``../escape``) so recovery is not
                # stuck forever on entries that can never be applied under the root.
                continue
            rollback_backup = meta.get("rollback_backup") or meta.get("backup")
            if rollback_backup:
                if not isinstance(rollback_backup, str) or not _path_within_support(root, rollback_backup):
                    complete = False
                    continue
                original_sha = meta.get("original_sha256")
                if not _is_hex_sha256(original_sha):
                    complete = False
                    continue
                if os.path.isfile(rollback_backup) and not os.path.islink(rollback_backup):
                    try:
                        _replace_under_root_from_support_path(
                            root=root,
                            root_fd=root_fd,
                            rel=safe,
                            support_src=rollback_backup,
                            expected_sha256=str(original_sha),
                        )
                        restored += 1
                        continue
                    except DiagnosticError:
                        complete = False
                        continue
                # A prior rollback attempt may already have consumed the snapshot.
                try:
                    if _sha256_regular_under_root_fd(root_fd, safe) == original_sha:
                        continue
                except DiagnosticError:
                    pass
                complete = False
                continue
            if not meta.get("existed"):
                try:
                    expected = meta.get("sha256")
                    if not _is_hex_sha256(expected):
                        complete = False
                        continue
                    removed = _unlink_regular_under_root_fd(
                        root_fd,
                        safe,
                        expected_sha256=str(expected),
                    )
                    if removed:
                        restored += 1
                    else:
                        # File missing already counts as restored for create-rollback.
                        try:
                            _sha256_regular_under_root_fd(root_fd, safe)
                            complete = False
                        except DiagnosticError:
                            continue
                except DiagnosticError:
                    complete = False
    finally:
        os.close(root_fd)
    return restored, complete


def _install_generation_is_published(root: str, journal: dict[str, Any]) -> bool:
    """Return True when the on-disk ownership manifest matches this journal generation.

    Used after the ownership manifest has been atomically replaced: a subsequent
    failure to write ``state=complete`` must not let recover_root roll payload
    back under the already-published generation.
    """
    if journal.get("state") == "complete":
        return True
    target = journal.get("target_generation", journal.get("generation"))
    if not isinstance(target, int):
        return False
    try:
        manifest = load_manifest(root)
    except DiagnosticError:
        return False
    if manifest is None:
        return False
    return manifest.generation == target


def _clear_published_install_journal(root: str, journal: dict[str, Any]) -> dict[str, Any]:
    """Clear stage/journal for a published generation without payload rollback."""
    stage_dir = journal.get("stage_dir")
    if stage_dir:
        # Explicit recover must fail closed: do not clear the journal if
        # authorized cleanup cannot complete.
        _delete_authorized_support_subtree(root, stage_dir, role="stage")
    # Force-with-backup trees are retained after a successful install for
    # the caller; complete-journal recovery must not destroy them.
    _unlink_support_control_file(root, JOURNAL_NAME)
    action = (
        "cleared_complete_journal"
        if journal.get("state") == "complete"
        else "cleared_published_generation_journal"
    )
    return {"ok": True, "recovered": True, "action": action}


def _attempt_rollback(root: str, journal: dict[str, Any]) -> None:
    if _install_generation_is_published(root, journal):
        # Manifest already published; do not undo payload under a new generation.
        return
    journal["state"] = "rollback"
    try:
        _write_journal(root, journal)
    except (OSError, DiagnosticError):
        pass
    _restored, complete = _rollback_paths(root, journal)
    if complete:
        stage_dir = journal.get("stage_dir")
        if stage_dir:
            try:
                _delete_authorized_support_subtree(root, stage_dir, role="stage")
            except DiagnosticError:
                pass
        backup_root = journal.get("backup_root")
        if backup_root:
            try:
                _delete_authorized_support_subtree(root, backup_root, role="backup")
            except DiagnosticError:
                pass
        try:
            _unlink_support_control_file(root, JOURNAL_NAME)
        except DiagnosticError:
            # Do not ambient-delete control paths after a containment failure.
            pass


def recover_root(root: str) -> dict[str, Any]:
    path = journal_path(root)
    if not os.path.lexists(path):
        return {"ok": True, "recovered": False}
    if os.path.islink(path) or not os.path.isfile(path):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    with RootLock(root):
        try:
            raw = _read_support_control_file(root, JOURNAL_NAME)
            journal = parse_journal_document(raw)
        except (DiagnosticError, OSError, ControlSchemaError, TypeError, ValueError, UnicodeDecodeError) as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        if _install_generation_is_published(root, journal):
            return _clear_published_install_journal(root, journal)
        # incomplete and not yet published: restore only transaction snapshots.
        restored, complete = _rollback_paths(root, journal)
        if not complete:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        stage_dir = journal.get("stage_dir")
        if stage_dir:
            _delete_authorized_support_subtree(root, stage_dir, role="stage")
        backup_root = journal.get("backup_root")
        if backup_root:
            _delete_authorized_support_subtree(root, backup_root, role="backup")
        _unlink_support_control_file(root, JOURNAL_NAME)
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
    root_fd: int | None = None
    if _supports_descriptor_relative_commit():
        try:
            root_fd = _open_skill_root_descriptor(root)
        except DiagnosticError as error:
            raise DiagnosticError("E_VERIFY_MISMATCH") from error
    try:
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
                    if root_fd is not None:
                        if _sha256_regular_under_root_fd(root_fd, rel) != expected_sha:
                            mismatches.append(rel)
                    else:
                        path = _dest_under_root(root, rel)
                        if os.path.islink(path) or not os.path.isfile(path):
                            mismatches.append(rel)
                            continue
                        if sha256_file(path) != expected_sha:
                            mismatches.append(rel)
                except (DiagnosticError, OSError):
                    mismatches.append(rel)
    finally:
        if root_fd is not None:
            os.close(root_fd)
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
        if not _supports_descriptor_relative_commit():
            raise DiagnosticError("E_INSTALL_CONFLICT")
        removed: list[str] = []
        retained_drift: list[str] = []
        # remove claim refs
        del manifest.claims[claim]
        root_fd = _open_skill_root_descriptor(root)
        try:
            for path, entry in list(manifest.files.items()):
                if claim in entry.claims:
                    entry.claims = [c for c in entry.claims if c != claim]
                if entry.claims:
                    continue
                try:
                    _safe_rel_path(path)
                except DiagnosticError:
                    # Malicious/escaped manifest entry: drop from manifest, never delete outside root.
                    del manifest.files[path]
                    continue
                try:
                    matches = _sha256_regular_under_root_fd(root_fd, path) == entry.sha256
                except DiagnosticError:
                    matches = False
                if matches:
                    try:
                        if _unlink_regular_under_root_fd(
                            root_fd,
                            path,
                            expected_sha256=entry.sha256,
                        ):
                            removed.append(path)
                        else:
                            retained_drift.append(path)
                    except DiagnosticError as error:
                        raise DiagnosticError("E_INSTALL_CONFLICT") from error
                else:
                    # Parent-swap / missing / drift: never ambient-delete.
                    # Missing parents/files count as already removed. Existing non-regular
                    # leaf is a conflict. Unopenable parents (symlink swap / missing) drop
                    # the manifest entry without deleting outside.
                    try:
                        parent_fd, basename, owns_parent = _open_parent_under_root_fd(
                            root_fd, path, create=False
                        )
                    except DiagnosticError:
                        del manifest.files[path]
                        continue
                    try:
                        try:
                            st = os.lstat(basename, dir_fd=parent_fd)
                        except FileNotFoundError:
                            del manifest.files[path]
                            continue
                        if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
                            raise DiagnosticError("E_INSTALL_CONFLICT")
                        retained_drift.append(path)
                    finally:
                        if owns_parent:
                            os.close(parent_fd)
                del manifest.files[path]
        finally:
            os.close(root_fd)
        manifest.generation += 1
        if manifest.claims:
            _atomic_write_support_file(
                root,
                MANIFEST_NAME,
                manifest.dumps().encode("utf-8"),
            )
        else:
            # remove support metadata when no claims remain; keep drifted files
            try:
                _unlink_support_control_file(root, MANIFEST_NAME)
            except DiagnosticError:
                # Never ambient-fallback delete after control-store failure.
                pass
            # best-effort cleanup of empty owned skill dirs / support tree only
            try:
                _cleanup_empty_dirs(root, removed_paths=removed)
            except DiagnosticError:
                pass
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
