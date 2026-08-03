"""Root lock, durable journal, stage/commit/rollback, verify, uninstall."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat as stat_mod
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
import contextlib
import threading

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
# Machine-local control plane under support (#33 Option A). Shareable payload
# stays at SUPPORT_DIR/runtime and SUPPORT_DIR/resources; mutable state lives
# under SUPPORT_DIR/STATE_SUBDIR and is gitignored for project installs.
STATE_SUBDIR = ".state"
MANIFEST_NAME = "manifest.json"
LOCK_NAME = "install.lock"
JOURNAL_NAME = "journal.json"
BACKUP_DIR = "backups"
STAGE_PREFIX = "portable-resume-stage-"
_BACKUP_NAME_PREFIX_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-")
# Deterministic shareable ignore policy for project-committed payload trees.
GITIGNORE_NAME = ".gitignore"
GITIGNORE_BYTES = (
    b"# portable-resume: machine-local control state only (#33)\n"
    b"# Keep runtime/ and resources/ shareable; never commit locks/journals.\n"
    b".state/\n"
)
# Names under SUPPORT_DIR that journals must never be allowed to delete.
_PROTECTED_SUPPORT_NAMES = frozenset(
    {
        "runtime",
        "resources",
        STATE_SUBDIR,
        GITIGNORE_NAME,
        # Legacy v1 control basenames (pre-#33) until migration completes.
        BACKUP_DIR,
        MANIFEST_NAME,
        LOCK_NAME,
        JOURNAL_NAME,
    }
)
# Control basenames live under SUPPORT_DIR/STATE_SUBDIR after #33.
_CONTROL_BASENAMES = frozenset({LOCK_NAME, JOURNAL_NAME, MANIFEST_NAME})


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
    # Selected source Skills for this install (#151); None means all enabled.
    sources: tuple[str, ...] | None = None

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
            "sources": list(self.sources) if self.sources is not None else None,
        }


@dataclass(slots=True)
class InstallCheckpoint:
    root: str
    snapshot_dir: str
    paths: dict[str, dict[str, Any]]


_test_harness_state = threading.local()


def _is_windows_install_allowed_for_tests() -> bool:
    """Return True iff the test harness context is currently active on this thread."""
    return getattr(_test_harness_state, "allow_windows_install", False)


@contextlib.contextmanager
def _allow_windows_install_for_tests() -> Iterator[None]:
    """Strict test-only context manager enabling Windows installer transaction execution.

    MUST be imported and used ONLY within test suites (e.g.
    ``tests/integration/test_windows_install_adversarial.py``). Restores default
    fail-closed state unconditionally upon exit via try...finally.
    """
    previous = _is_windows_install_allowed_for_tests()
    _test_harness_state.allow_windows_install = True
    try:
        yield
    finally:
        _test_harness_state.allow_windows_install = previous


def require_mutating_install_platform() -> None:
    """Fail closed before Windows (or other non-POSIX) mutating installer ops.

    Policy B for issue #29: exclusive root locking and reparse-safe control-store
    semantics are verified on POSIX only. Mutating install/uninstall/recover must
    not pretend to lock on ``os.name == "nt"``. Dry-run planning, matrix/hosts,
    verify (read-only), package builds, and the reader remain available where
    individually safe.
    """

    if os.name == "nt" and not _is_windows_install_allowed_for_tests():
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")


def control_state_dir(root: str) -> str:
    """Absolute path to machine-local control state (``…/.portable-resume/.state``)."""

    return os.path.join(root, SUPPORT_DIR, STATE_SUBDIR)


def support_dir(root: str) -> str:
    return os.path.join(root, SUPPORT_DIR)


class RootLock:
    def __init__(self, root: str, *, wait_seconds: float = 5.0) -> None:
        self.root = root
        self.support = support_dir(root)
        self.state = control_state_dir(root)
        self.path = os.path.join(self.state, LOCK_NAME)
        self._fd: int | None = None
        self.wait_seconds = wait_seconds
        # Windows: hold backend.acquire_exclusive_lock context across RootLock life.
        self._win_lock_cm: Any | None = None

    def __enter__(self) -> "RootLock":
        # Windows Phase 3 (#125): exclusive lock via platform_fs Win32 primitive.
        # Product install/uninstall/recover still call require_mutating_install_platform()
        # before RootLock — do not treat lock success as product enablement.
        #
        # Require *real* Windows (sys.platform), not merely os.name=="nt" mocks on
        # POSIX hosts, so fail-closed tests never create support dirs via a spoofed
        # Windows backend selection.
        if os.name == "nt" and sys.platform.startswith("win"):
            return self._enter_windows()
        if os.name == "nt":
            raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")
        return self._enter_posix()

    def _enter_windows(self) -> "RootLock":
        from ..platform_fs import get_filesystem_backend

        backend = get_filesystem_backend()
        caps = backend.capabilities
        if not caps.exclusive_locking or not caps.handle_locking:
            raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")
        try:
            st = os.lstat(self.root)
            if stat_mod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400):
                raise DiagnosticError("E_UNSAFE_PATH")
        except OSError as error:
            if isinstance(error, DiagnosticError):
                raise
        _ensure_control_state_directory(self.root)
        deadline = time.monotonic() + self.wait_seconds
        last_error: BaseException | None = None
        while True:
            try:
                cm = backend.acquire_exclusive_lock(self.path)
                fd = cm.__enter__()
                self._win_lock_cm = cm
                self._fd = fd
                _write_root_lock_pid(fd)
                return self
            except DiagnosticError as error:
                last_error = error
                if error.code == "E_INSTALL_BUSY" and time.monotonic() < deadline:
                    time.sleep(0.05)
                    continue
                raise
            except OSError as error:
                last_error = error
                if time.monotonic() >= deadline:
                    raise DiagnosticError("E_INSTALL_BUSY") from error
                time.sleep(0.05)
        if last_error is not None:
            raise DiagnosticError("E_INSTALL_BUSY") from last_error
        raise DiagnosticError("E_INSTALL_BUSY")

    def _enter_posix(self) -> "RootLock":
        # Never open/create support paths on platforms without exclusive locking.
        require_mutating_install_platform()
        _ensure_control_state_directory(self.root)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            fd: int | None = None
            try:
                import fcntl

                # #33 P1: if a v1 lock still exists, flock it *before* migration so
                # a concurrent pre-#33 installer cannot publish under the old path
                # while we rename control files out from under it.
                legacy_lock = _legacy_lock_path(self.root)
                new_lock = self.path
                if os.path.lexists(legacy_lock) and not os.path.lexists(new_lock):
                    fd = _open_legacy_support_control_file(
                        self.root,
                        LOCK_NAME,
                        flags=os.O_RDWR,
                        mode=0o644,
                    )
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Rename keeps the flock on the same inode (POSIX).
                    _migrate_v1_control_state(self.root)
                else:
                    fd = _open_support_control_file(
                        self.root,
                        LOCK_NAME,
                        flags=os.O_RDWR | os.O_CREAT,
                        mode=0o644,
                    )
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Drain any stranded legacy artifacts (partial prior migrate).
                    _migrate_v1_control_state(self.root)
                _write_root_lock_pid(fd)
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
        if self._win_lock_cm is not None:
            try:
                self._win_lock_cm.__exit__(exc_type, exc, tb)
            finally:
                self._win_lock_cm = None
                self._fd = None
            return
        if self._fd is not None:
            try:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


def _write_root_lock_pid(fd: int) -> None:
    """Best-effort pid payload on the locked fd (POSIX + Windows CRT fd)."""

    try:
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
    except OSError:
        # Lock is still held; pid write is advisory.
        pass


def journal_path(root: str) -> str:
    """Preferred (#33) journal path; may not exist until migration/write."""

    return os.path.join(control_state_dir(root), JOURNAL_NAME)


def manifest_path(root: str) -> str:
    """Preferred (#33) manifest path for writes; readers use resolve helpers."""

    return os.path.join(control_state_dir(root), MANIFEST_NAME)


def _legacy_manifest_path(root: str) -> str:
    return os.path.join(root, SUPPORT_DIR, MANIFEST_NAME)


def _legacy_journal_path(root: str) -> str:
    return os.path.join(root, SUPPORT_DIR, JOURNAL_NAME)


def _legacy_lock_path(root: str) -> str:
    return os.path.join(root, SUPPORT_DIR, LOCK_NAME)


def resolve_manifest_path(root: str) -> str | None:
    """Return the on-disk manifest path (new or legacy), or None if absent."""

    new = manifest_path(root)
    if os.path.lexists(new):
        return new
    legacy = _legacy_manifest_path(root)
    if os.path.lexists(legacy):
        return legacy
    return None


def load_manifest(root: str) -> Manifest | None:
    path = resolve_manifest_path(root)
    if path is None:
        return None
    # Prefer #33 state path open; fall back to legacy basename under support.
    try:
        if path == manifest_path(root):
            raw = _read_support_control_file(root, MANIFEST_NAME)
        else:
            raw = _read_legacy_support_control_file(root, MANIFEST_NAME)
    except DiagnosticError as error:
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
    for path in (journal_path(root), _legacy_journal_path(root)):
        if not os.path.lexists(path):
            continue
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
    sources: tuple[str, ...] | None = None,
) -> ActionPlan:
    """Build an advisory install plan from the current root state.

    The returned plan is **not** mutation authority. ``execute_install`` rebuilds
    an equivalent plan under ``RootLock`` from the exact locked ownership
    manifest so stale preflight claims cannot be committed (#35).
    """

    if host not in HOST_PROFILES:
        raise DiagnosticError.invalid()
    files = materialize_plan(host, sources=sources)
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
        sources=sources,
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


def _mkdir_nofollow_child(parent_fd: int, name: str, *, mode: int = 0o755) -> None:
    """Create *name* under *parent_fd* if missing; reject symlink/non-dir."""

    try:
        st = os.lstat(name, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, mode, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            st = os.lstat(name, dir_fd=parent_fd)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    if stat_mod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(st.st_mode):
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
            if stat_mod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(st.st_mode):
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

    support = support_dir(root)
    if os.path.lexists(support):
        try:
            st = os.lstat(support)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(st.st_mode):
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
    if stat_mod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(st.st_mode):
        raise DiagnosticError("E_INSTALL_CONFLICT")


def _ensure_control_state_directory(root: str) -> None:
    """Ensure shareable support dir and private ``.state`` control dir exist (#33)."""

    _ensure_support_directory(root)
    if _supports_descriptor_relative_commit():
        root_fd = _open_skill_root_descriptor(root)
        support_fd: int | None = None
        try:
            support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
            _mkdir_nofollow_child(support_fd, STATE_SUBDIR, mode=0o700)
            return
        finally:
            if support_fd is not None:
                os.close(support_fd)
            os.close(root_fd)

    state = control_state_dir(root)
    if os.path.lexists(state):
        try:
            st = os.lstat(state)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(st.st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        return
    try:
        os.mkdir(state, 0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    try:
        st = os.lstat(state)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    if stat_mod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(st.st_mode):
        raise DiagnosticError("E_INSTALL_CONFLICT")


def _migrate_v1_control_state(root: str) -> dict[str, Any]:
    """Move pre-#33 control files from ``.portable-resume/`` into ``.state/``.

    Idempotent and resumable: when the new manifest already exists, still drain
    any remaining legacy journal/lock/backups/stage trees (partial migrate).
    Refuses when both legacy and new manifests exist (ambiguous).
    Does not move payload ``runtime/`` or ``resources/``.
    Rewrites absolute journal recovery paths that pointed at moved trees.
    """

    _ensure_control_state_directory(root)
    support = support_dir(root)
    state = control_state_dir(root)
    new_manifest = os.path.join(state, MANIFEST_NAME)
    legacy_manifest = os.path.join(support, MANIFEST_NAME)
    if os.path.lexists(new_manifest) and os.path.lexists(legacy_manifest):
        raise DiagnosticError("E_INSTALL_CONFLICT")

    moved: list[str] = []

    # Prefer descriptor-relative renames so a post-open support/.state symlink
    # swap cannot redirect migration outside the skill root (#33 Codex P1).
    use_dirfd = _supports_descriptor_relative_commit()
    root_fd: int | None = None
    support_fd: int | None = None
    state_fd: int | None = None
    try:
        if use_dirfd:
            root_fd = _open_skill_root_descriptor(root)
            support_fd, state_fd = _open_control_parent_fd(root_fd)

        def _rename_child(name: str, *, require_dir: bool = False) -> bool:
            """Rename support/*name* → state/*name*. Return True if moved."""

            if use_dirfd and support_fd is not None and state_fd is not None:
                try:
                    st = os.lstat(name, dir_fd=support_fd)
                except FileNotFoundError:
                    return False
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                if stat_mod.S_ISLNK(st.st_mode):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                if require_dir and not stat_mod.S_ISDIR(st.st_mode):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                if not require_dir and not stat_mod.S_ISREG(st.st_mode) and not stat_mod.S_ISDIR(
                    st.st_mode
                ):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                try:
                    dst_st = os.lstat(name, dir_fd=state_fd)
                except FileNotFoundError:
                    dst_st = None
                if dst_st is not None:
                    # Same inode (hardlink sentinel for lock) is already migrated.
                    if st.st_ino == dst_st.st_ino and st.st_dev == dst_st.st_dev:
                        return False
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                try:
                    os.rename(name, name, src_dir_fd=support_fd, dst_dir_fd=state_fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                return True

            src = os.path.join(support, name)
            dst = os.path.join(state, name)
            if not os.path.lexists(src):
                return False
            if os.path.lexists(dst):
                try:
                    if os.path.samefile(src, dst):
                        return False
                except OSError:
                    pass
                raise DiagnosticError("E_INSTALL_CONFLICT")
            try:
                st = os.lstat(src)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if stat_mod.S_ISLNK(st.st_mode):
                raise DiagnosticError("E_INSTALL_CONFLICT")
            if require_dir and not stat_mod.S_ISDIR(st.st_mode):
                raise DiagnosticError("E_INSTALL_CONFLICT")
            try:
                os.rename(src, dst)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            return True

        # Regular control files (order: lock last so flock holders keep the inode).
        for name in (MANIFEST_NAME, JOURNAL_NAME, LOCK_NAME):
            if _rename_child(name, require_dir=False):
                moved.append(name)
                if name == LOCK_NAME:
                    # Keep legacy lock pathname occupied with a hardlink to the
                    # flocked inode so a concurrent pre-#33 installer cannot
                    # create a second lock under the old path (#33 Codex P1).
                    _link_lock_sentinel(support=support, state=state)

        if _rename_child(BACKUP_DIR, require_dir=True):
            moved.append(BACKUP_DIR)

        # Stage trees that lived as direct children of support.
        try:
            names = os.listdir(support)
        except OSError:
            names = []
        for name in names:
            if not name.startswith(STAGE_PREFIX):
                continue
            if _rename_child(name, require_dir=True):
                moved.append(name)
    finally:
        if state_fd is not None:
            os.close(state_fd)
        if support_fd is not None:
            os.close(support_fd)
        if root_fd is not None:
            os.close(root_fd)

    # Always attempt journal path rewrite: a prior crash may have moved trees
    # already while leaving absolute legacy paths in the journal body.
    _rewrite_journal_paths_after_migration(root, support=support, state=state)

    return {
        "migrated": bool(moved),
        "layout": "state-v1",
        "moved": sorted(moved),
    }


def _link_lock_sentinel(*, support: str, state: str) -> None:
    """Hardlink ``state/install.lock`` back to ``support/install.lock`` when possible."""

    src = os.path.join(state, LOCK_NAME)
    dst = os.path.join(support, LOCK_NAME)
    if not os.path.lexists(src) or os.path.lexists(dst):
        return
    try:
        os.link(src, dst)
    except OSError:
        # Best-effort on platforms/filesystems without hardlinks.
        return


def _rewrite_journal_paths_after_migration(
    root: str,
    *,
    support: str,
    state: str,
) -> None:
    """Rewrite absolute journal recovery paths after v1→.state tree moves (#33)."""

    journal_file = os.path.join(state, JOURNAL_NAME)
    if not os.path.lexists(journal_file):
        return
    try:
        raw = _read_support_control_file(root, JOURNAL_NAME)
        journal = parse_journal_document(raw)
    except (DiagnosticError, OSError, ControlSchemaError, TypeError, ValueError, UnicodeDecodeError):
        # Leave unreadable journal for recover_root to fail closed.
        return

    support_real = os.path.realpath(support)
    state_real = os.path.realpath(state)
    changed = False

    def _remap(path: object) -> object:
        nonlocal changed
        if not isinstance(path, str) or not path:
            return path
        # Try abspath (symlink spelling) and realpath (resolved) so journals that
        # recorded either form still remap after migration (#33 Codex P1).
        candidates: list[str] = []
        try:
            candidates.append(os.path.abspath(path))
        except OSError:
            pass
        try:
            candidates.append(os.path.realpath(path))
        except OSError:
            pass
        for abs_path in candidates:
            try:
                if os.path.commonpath((abs_path, support_real)) != support_real:
                    continue
                rel = os.path.relpath(abs_path, support_real)
            except (OSError, ValueError):
                continue
            if rel in {".", ""} or rel.startswith(".."):
                continue
            # Do not rewrite payload paths (runtime/resources).
            top = rel.split(os.sep, 1)[0]
            if top in {"runtime", "resources", STATE_SUBDIR, GITIGNORE_NAME}:
                continue
            remapped = os.path.join(state_real, rel)
            if remapped != path:
                changed = True
            return remapped
        return path

    if "stage_dir" in journal:
        journal["stage_dir"] = _remap(journal.get("stage_dir"))
    if "backup_root" in journal:
        journal["backup_root"] = _remap(journal.get("backup_root"))
    paths = journal.get("paths")
    if isinstance(paths, dict):
        for rel, meta in list(paths.items()):
            if not isinstance(meta, dict):
                continue
            if "rollback_backup" in meta:
                meta["rollback_backup"] = _remap(meta.get("rollback_backup"))
            paths[rel] = meta
        journal["paths"] = paths

    if not changed:
        return
    try:
        _write_journal(root, journal)
    except DiagnosticError:
        # Best-effort rewrite; recover remains fail-closed if paths stay stale.
        return


def _open_control_parent_fd(root_fd: int) -> tuple[int, int]:
    """Return ``(support_fd, state_fd)``; caller closes both."""

    support_fd = _open_directory_under_root(root_fd, SUPPORT_DIR)
    try:
        _mkdir_nofollow_child(support_fd, STATE_SUBDIR, mode=0o700)
        flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        state_fd = os.open(STATE_SUBDIR, flags, dir_fd=support_fd)
    except OSError as error:
        os.close(support_fd)
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    return support_fd, state_fd


def _open_support_control_file(
    root: str,
    name: str,
    *,
    flags: int,
    mode: int = 0o644,
) -> int:
    """Open a control-plane basename under ``.portable-resume/.state`` (#33)."""
    if name not in _CONTROL_BASENAMES:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    _ensure_control_state_directory(root)
    if _supports_descriptor_relative_commit():
        root_fd = _open_skill_root_descriptor(root)
        support_fd: int | None = None
        state_fd: int | None = None
        try:
            support_fd, state_fd = _open_control_parent_fd(root_fd)
            try:
                existing = os.lstat(name, dir_fd=state_fd)
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
                fd = os.open(name, open_flags, mode, dir_fd=state_fd)
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
            if state_fd is not None:
                os.close(state_fd)
            if support_fd is not None:
                os.close(support_fd)
            os.close(root_fd)

    path = os.path.join(control_state_dir(root), name)
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


def _open_legacy_support_control_file(
    root: str,
    name: str,
    *,
    flags: int,
    mode: int = 0o644,
) -> int:
    """Open a v1 control basename directly under ``.portable-resume/`` (read migration)."""

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


def _read_legacy_support_control_file(root: str, name: str) -> bytes:
    fd = _open_legacy_support_control_file(root, name, flags=os.O_RDONLY)
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
    """Atomically replace a control document under ``.portable-resume/.state`` (#33)."""
    if name not in {JOURNAL_NAME, MANIFEST_NAME}:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    if not isinstance(data, (bytes, bytearray)):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    payload = bytes(data)
    _ensure_control_state_directory(root)

    if _supports_descriptor_relative_commit():
        root_fd = _open_skill_root_descriptor(root)
        support_fd: int | None = None
        state_fd: int | None = None
        tmp_name: str | None = None
        try:
            support_fd, state_fd = _open_control_parent_fd(root_fd)
            tmp_name = f".{name}.tmp-{secrets.token_hex(8)}"
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                fd = os.open(tmp_name, flags, 0o644, dir_fd=state_fd)
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
                existing = os.lstat(name, dir_fd=state_fd)
            except FileNotFoundError:
                existing = None
            except OSError as error:
                try:
                    os.unlink(tmp_name, dir_fd=state_fd)
                except OSError:
                    pass
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            if existing is not None and (
                stat_mod.S_ISLNK(existing.st_mode) or not stat_mod.S_ISREG(existing.st_mode)
            ):
                try:
                    os.unlink(tmp_name, dir_fd=state_fd)
                except OSError:
                    pass
                raise DiagnosticError("E_INSTALL_CONFLICT")
            try:
                os.replace(tmp_name, name, src_dir_fd=state_fd, dst_dir_fd=state_fd)
            except OSError as error:
                try:
                    os.unlink(tmp_name, dir_fd=state_fd)
                except OSError:
                    pass
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            tmp_name = None
            try:
                os.fsync(state_fd)
            except OSError:
                pass
            return
        finally:
            if tmp_name is not None and state_fd is not None:
                try:
                    os.unlink(tmp_name, dir_fd=state_fd)
                except OSError:
                    pass
            if state_fd is not None:
                os.close(state_fd)
            if support_fd is not None:
                os.close(support_fd)
            os.close(root_fd)

    state = control_state_dir(root)
    path = os.path.join(state, name)
    if os.path.lexists(path) and (os.path.islink(path) or not os.path.isfile(path)):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    tmp_path = os.path.join(state, f".{name}.tmp-{secrets.token_hex(8)}")
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


def _materialize_bytes_under_fd(
    base_fd: int,
    rel: str,
    data: bytes,
    *,
    mode: int,
    fsync: bool = False,
) -> None:
    """Write ``rel`` under base_fd with mkdir-nofollow + O_EXCL regular create.

    When ``fsync`` is True, durable-flush the new regular file before return
    (required before a journal may authorize deletes that depend on the snapshot).
    """
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
            if fsync:
                try:
                    os.fsync(fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
        finally:
            os.close(fd)
        if fsync:
            try:
                os.fsync(parent_fd)
            except OSError:
                # Directory fsync is best-effort on platforms that reject it.
                pass
    finally:
        if owns_parent:
            os.close(parent_fd)


def _fsync_path_ancestors(root_fd: int, rel: str) -> None:
    """Fsync ``root_fd`` and every directory component of ``rel`` under it.

    Required after recovery may have recreated intermediate payload parents so
    directory entries are durable before stage/journal evidence is discarded.
    """
    safe = _safe_rel_path(rel)
    parts = [part for part in safe.split(os.sep) if part and part != "."]
    # Leaf basename is a file; only directory components need fsync here.
    dir_parts = parts[:-1] if parts else []
    try:
        os.fsync(root_fd)
    except OSError as error:
        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    if not dir_parts:
        return
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = root_fd
    opened: list[int] = []
    try:
        for part in dir_parts:
            try:
                next_fd = os.open(part, flags, dir_fd=current)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            opened.append(next_fd)
            try:
                os.fsync(next_fd)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            current = next_fd
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _fsync_tree_dirfd(dir_fd: int) -> None:
    """Durable-flush every regular file and directory under ``dir_fd`` (depth-first).

    Fail closed on traversal/open/fsync errors so callers never publish a journal
    that depends on unsynced rollback material.
    """
    try:
        names = os.listdir(dir_fd)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    flags_dir = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    flags_file = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    for name in names:
        try:
            st = os.lstat(name, dir_fd=dir_fd)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISDIR(st.st_mode):
            try:
                child = os.open(name, flags_dir, dir_fd=dir_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            try:
                _fsync_tree_dirfd(child)
                try:
                    os.fsync(child)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
            finally:
                os.close(child)
        elif stat_mod.S_ISREG(st.st_mode):
            try:
                fd = os.open(name, flags_file, dir_fd=dir_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            try:
                try:
                    os.fsync(fd)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
            finally:
                os.close(fd)
    try:
        os.fsync(dir_fd)
    except OSError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error


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
                # Only restore quarantine when basename is still free. If a
                # concurrent writer created a new leaf under the original name,
                # leave both entries (do not clobber the new leaf).
                try:
                    os.lstat(basename, dir_fd=parent_fd)
                except FileNotFoundError:
                    try:
                        os.rename(
                            quarantine,
                            basename,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                        )
                        restored = True
                    except OSError as error:
                        raise DiagnosticError("E_INSTALL_CONFLICT") from error
                else:
                    # Basename occupied: keep quarantine under its unique name so
                    # concurrent bytes are not destroyed (caller fails closed).
                    pass
                return False
            try:
                os.unlink(quarantine, dir_fd=parent_fd)
            except OSError as error:
                raise DiagnosticError("E_INSTALL_CONFLICT") from error
            return True
        except Exception:
            if not restored:
                try:
                    os.lstat(basename, dir_fd=parent_fd)
                except FileNotFoundError:
                    try:
                        os.rename(
                            quarantine,
                            basename,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                        )
                    except OSError:
                        pass
                # If basename is occupied, leave quarantine name in place.
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
    if_absent: bool = False,
) -> bool:
    """Place payload ``rel`` from an authorized path under ``.portable-resume``.

    Returns True when a payload leaf was written/replaced.

    * ``if_absent=False`` (install recovery): ``os.replace`` snapshot → dest.
    * ``if_absent=True`` (uninstall recovery): exclusive-create the destination
      from snapshot bytes; return False when a live leaf already exists so
      concurrent edits / unreadable leaves are never overwritten.
    """
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
        if len(src_parts) == 1:
            src_parent_fd = support_fd
            src_basename = src_parts[0]
        else:
            src_parent_rel = "/".join(src_parts[:-1])
            src_parent_fd = _open_directory_under_root(support_fd, src_parent_rel)
            src_basename = src_parts[-1]

        read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            src_fd = os.open(src_basename, read_flags, dir_fd=src_parent_fd)
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        try:
            st = os.fstat(src_fd)
            if not stat_mod.S_ISREG(st.st_mode):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            snap_mode = stat_mod.S_IMODE(st.st_mode) or 0o644
            if if_absent:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(src_fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                body = b"".join(chunks)
                if expected_sha256 is not None and sha256_bytes(body) != expected_sha256:
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
            elif expected_sha256 is not None:
                if _sha256_open_fd(src_fd) != expected_sha256:
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
        finally:
            os.close(src_fd)

        dst_parent_fd, dst_basename, owns_dst_parent = _open_parent_under_root_fd(
            root_fd, rel, create=True
        )
        if if_absent:
            # Write a complete temp leaf, fsync, then link into place. link fails with
            # EEXIST when the destination already exists, so partial writes never become
            # the durable destination name (retry keeps the intact stage snapshot).
            tmp_name = f".portable-resume-restore-{secrets.token_hex(8)}"
            excl = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                out_fd = os.open(tmp_name, excl, snap_mode, dir_fd=dst_parent_fd)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            try:
                view = memoryview(body)
                while view:
                    written = os.write(out_fd, view)
                    view = view[written:]
                try:
                    os.fchmod(out_fd, snap_mode)
                except OSError:
                    pass
                try:
                    os.fsync(out_fd)
                except OSError as error:
                    raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            finally:
                os.close(out_fd)
            try:
                os.link(
                    tmp_name,
                    dst_basename,
                    src_dir_fd=dst_parent_fd,
                    dst_dir_fd=dst_parent_fd,
                )
            except FileExistsError:
                try:
                    os.unlink(tmp_name, dir_fd=dst_parent_fd)
                except OSError:
                    pass
                # Prior attempt may have linked but crashed before parent fsync.
                # Persist the existing destination dirent (and recreated parents)
                # before callers discard stage evidence on "already present".
                try:
                    os.fsync(dst_parent_fd)
                except OSError as error:
                    raise DiagnosticError("E_RECOVERY_REQUIRED") from error
                _fsync_path_ancestors(root_fd, rel)
                return False
            except OSError as error:
                try:
                    os.unlink(tmp_name, dir_fd=dst_parent_fd)
                except OSError:
                    pass
                if getattr(error, "errno", None) == getattr(os, "EEXIST", object()):
                    try:
                        os.fsync(dst_parent_fd)
                    except OSError as fsync_error:
                        raise DiagnosticError("E_RECOVERY_REQUIRED") from fsync_error
                    _fsync_path_ancestors(root_fd, rel)
                    return False
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            try:
                os.unlink(tmp_name, dir_fd=dst_parent_fd)
            except OSError:
                pass
            # Persist the destination directory entry and any recreated parents
            # before callers may discard the stage snapshot.
            try:
                os.fsync(dst_parent_fd)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            _fsync_path_ancestors(root_fd, rel)
            return True

        try:
            os.replace(
                src_basename,
                dst_basename,
                src_dir_fd=src_parent_fd,
                dst_dir_fd=dst_parent_fd,
            )
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        try:
            os.fsync(dst_parent_fd)
        except OSError:
            pass
        try:
            _fsync_path_ancestors(root_fd, rel)
        except DiagnosticError:
            pass
        return True
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
    state_fd: int | None = None
    stage_fd: int | None = None
    src_parent_fd: int | None = None
    dst_parent_fd: int | None = None
    try:
        # Stage trees live under .portable-resume/.state/ after #33.
        # Legacy single-component stage under support is still authorized for recovery.
        stage_parent_rel = os.path.dirname(
            os.path.relpath(authorized_stage, os.path.join(os.path.abspath(root), SUPPORT_DIR))
        )
        if stage_parent_rel in ("", "."):
            stage_fd = _open_directory_under_root(support_fd, stage_name)
        else:
            state_fd = _open_directory_under_root(support_fd, STATE_SUBDIR)
            stage_fd = _open_directory_under_root(state_fd, stage_name)
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
            and src_parent_fd not in (stage_fd, state_fd, support_fd, root_fd)
        ):
            os.close(src_parent_fd)
        if stage_fd is not None and stage_fd not in (state_fd, support_fd, root_fd):
            os.close(stage_fd)
        if state_fd is not None and state_fd not in (support_fd, root_fd):
            os.close(state_fd)
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


def execute_install(
    plan: ActionPlan,
    *,
    force_with_backup: bool = False,
    lock: RootLock | None = None,
) -> dict[str, Any]:
    """Install one claim into ``plan.root``.

    When ``lock`` is provided (multi-root orchestration, #23), the caller must
    already hold that exclusive ``RootLock`` for ``plan.root``; this path will
    not re-acquire (locks are not re-entrant).
    """
    root = plan.root
    if plan.dry_run:
        before = _tree_snapshot(root)
        # observational only
        after = _tree_snapshot(root)
        if before != after:
            raise DiagnosticError("E_INVARIANT")
        return {"ok": True, "dry_run": True, "plan": plan.to_dict()}

    require_mutating_install_platform()
    if lock is not None:
        _require_held_root_lock(lock, root)
        return _execute_install_under_lock(plan, force_with_backup=force_with_backup)
    with RootLock(root):
        return _execute_install_under_lock(plan, force_with_backup=force_with_backup)


def _require_held_root_lock(lock: RootLock, root: str) -> None:
    if lock._fd is None:
        raise DiagnosticError("E_INSTALL_BUSY")
    if os.path.realpath(lock.root) != os.path.realpath(root):
        raise DiagnosticError("E_INSTALL_CONFLICT")


def _execute_install_under_lock(
    plan: ActionPlan,
    *,
    force_with_backup: bool = False,
) -> dict[str, Any]:
    """Mutating install body. Caller must hold ``RootLock`` for ``plan.root``."""
    root = plan.root
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
        sources=plan.sources,
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
    _ensure_control_state_directory(root)
    if not _supports_descriptor_relative_commit():
        if os.name == "nt" and _is_windows_install_allowed_for_tests():
            return _execute_install_under_lock_windows(
                plan=plan,
                existing=existing,
                backups=backups,
                planned_backups=planned_backups,
                effective_force=effective_force,
                changed_since_preflight=changed_since_preflight,
            )
        raise DiagnosticError("E_INSTALL_CONFLICT")
    pin_root_fd = _open_skill_root_descriptor(root)
    support_fd: int | None = None
    state_fd: int | None = None
    stage_fd: int | None = None
    stage_dir = ""
    backup_root: str | None = None
    try:
        support_fd, state_fd = _open_control_parent_fd(pin_root_fd)
        stage_name = _mkdir_unique_under_fd(state_fd, STAGE_PREFIX)
        stage_dir = os.path.join(control_state_dir(root), stage_name)
        stage_fd = os.open(
            stage_name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=state_fd,
        )
        journal = {
            "schema_version": "portable-resume/install-journal-v1",
            "state": "staging",
            "generation": plan.generation,
            "claim": plan.claim,
            "stage_dir": stage_dir,
            "backup_root": backup_root,
            "operation": "install",
            "paths": {},
        }
        if backups:
            try:
                os.mkdir(BACKUP_DIR, 0o755, dir_fd=state_fd)
            except FileExistsError:
                pass
            # Re-open backups under state without following a symlink leaf.
            try:
                backup_parent_fd = os.open(
                    BACKUP_DIR,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=state_fd,
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
            backup_root = os.path.join(control_state_dir(root), BACKUP_DIR, backup_name)
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
            # Write under backup dir via state_fd/backups/<name>/...
            backup_name = os.path.basename(backup_root)
            backups_fd = os.open(
                BACKUP_DIR,
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=state_fd,
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
        if state_fd is not None:
            os.close(state_fd)
        if support_fd is not None:
            os.close(support_fd)
        os.close(pin_root_fd)



def _execute_install_under_lock_windows(
    plan: ActionPlan,
    existing: Manifest | None,
    backups: list[str],
    planned_backups: set[str],
    effective_force: bool,
    changed_since_preflight: bool,
) -> dict[str, Any]:
    from ..platform_fs import get_filesystem_backend
    backend = get_filesystem_backend()
    root = plan.root

    stage_name = f"{STAGE_PREFIX}{secrets.token_hex(8)}"
    stage_dir = os.path.join(control_state_dir(root), stage_name)
    backend.mkdirs_beneath(stage_dir, root=root)

    backup_root: str | None = None
    if backups:
        backup_name = time.strftime("%Y%m%dT%H%M%SZ-", time.gmtime()) + secrets.token_hex(4)
        backup_root = os.path.join(control_state_dir(root), BACKUP_DIR, backup_name)
        backend.mkdirs_beneath(backup_root, root=root)

    journal: dict[str, Any] = {
        "schema_version": "portable-resume/install-journal-v1",
        "state": "staging",
        "generation": plan.generation,
        "claim": plan.claim,
        "stage_dir": stage_dir,
        "backup_root": backup_root,
        "operation": "install",
        "paths": {},
    }

    try:
        for rel, data in plan.files.items():
            safe = _safe_rel_path(rel)
            staged_path = os.path.join(stage_dir, safe)
            backend.mkdirs_beneath(os.path.dirname(staged_path), root=root)
            with open(staged_path, "wb") as f:
                f.write(data)
            journal["paths"][safe] = {
                "state": "staged",
                "sha256": sha256_bytes(data),
                "existed": False,
            }

        for rel in sorted(plan.files):
            safe = _safe_rel_path(rel)
            dest = _dest_under_root(root, safe)
            if os.path.lexists(dest):
                try:
                    st = os.lstat(dest)
                except OSError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                with open(dest, "rb") as f:
                    body = f.read()
                payload_digest = sha256_bytes(body)
                rollback_path = os.path.join(stage_dir, ".rollback", safe)
                backend.mkdirs_beneath(os.path.dirname(rollback_path), root=root)
                with open(rollback_path, "wb") as f:
                    f.write(body)
                journal["paths"][safe]["existed"] = True
                journal["paths"][safe]["rollback_backup"] = rollback_path
                journal["paths"][safe]["original_sha256"] = payload_digest

        for rel in backups:
            safe = _safe_rel_path(rel)
            if backup_root is None:
                raise DiagnosticError("E_INSTALL_CONFLICT")
            dest = _dest_under_root(root, safe)
            with open(dest, "rb") as f:
                body = f.read()
            backup_path = os.path.join(backup_root, safe)
            backend.mkdirs_beneath(os.path.dirname(backup_path), root=root)
            with open(backup_path, "wb") as f:
                f.write(body)
            journal["paths"][safe]["backup"] = backup_path

        journal["state"] = "committing"
        _write_journal(root, journal)

        for rel in sorted(plan.files):
            safe = _safe_rel_path(rel)
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
            dst = _dest_under_root(root, safe)
            backend.mkdirs_beneath(os.path.dirname(dst), root=root)
            backend.replace_beneath(src, dst, root=root)
            journal["paths"][safe]["state"] = "committed"
            _write_journal(root, journal)

        orphan_removed: list[str] = []
        orphan_pending: list[tuple[str, str]] = []
        if existing is not None:
            for rel, entry in list(existing.files.items()):
                if rel in plan.files or rel in plan.manifest.files:
                    continue
                dest = _dest_under_root(root, rel)
                if os.path.lexists(dest):
                    try:
                        with open(dest, "rb") as f:
                            digest = sha256_bytes(f.read())
                    except OSError:
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
                dest = _dest_under_root(root, rel)
                try:
                    backend.unlink_beneath(dest, root=root)
                    orphan_removed.append(rel)
                    journal["orphans"][rel]["state"] = "removed"
                except DiagnosticError:
                    journal["orphans"][rel]["state"] = "skipped"
                _write_journal(root, journal)

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
            try:
                _unlink_support_control_file(root, JOURNAL_NAME)
            except DiagnosticError:
                pass

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


def _uninstall_claim_windows(
    *,
    root: str,
    claim: str,
    manifest: Manifest,
) -> dict[str, Any]:
    from ..platform_fs import get_filesystem_backend
    backend = get_filesystem_backend()

    removable: list[tuple[str, str]] = []
    drop_from_manifest: list[str] = []

    for path, entry in list(manifest.files.items()):
        if claim not in entry.claims:
            continue
        remaining = [c for c in entry.claims if c != claim]
        if remaining:
            entry.claims = remaining
            continue
        try:
            _safe_rel_path(path)
        except DiagnosticError:
            drop_from_manifest.append(path)
            continue
        dest = _dest_under_root(root, path)
        matches = False
        if os.path.lexists(dest):
            try:
                with open(dest, "rb") as f:
                    matches = sha256_bytes(f.read()) == entry.sha256
            except OSError:
                matches = False
        if matches:
            removable.append((path, entry.sha256))
            drop_from_manifest.append(path)
        else:
            drop_from_manifest.append(path)

    for path in drop_from_manifest:
        manifest.files.pop(path, None)

    removed_files: list[str] = []
    for path, sha256 in removable:
        dest = _dest_under_root(root, path)
        try:
            backend.unlink_beneath(dest, root=root)
            removed_files.append(path)
        except DiagnosticError:
            pass

    manifest.claims.pop(claim, None)
    manifest.generation += 1

    if manifest.files:
        _atomic_write_support_file(root, MANIFEST_NAME, manifest.dumps().encode("utf-8"))
    else:
        _unlink_support_control_file(root, MANIFEST_NAME)

    return {
        "ok": True,
        "removed_files": removed_files,
        "claim": claim,
        "generation": manifest.generation,
    }


def _rollback_paths_windows(root: str, journal: dict[str, Any]) -> tuple[int, bool]:
    from ..platform_fs import get_filesystem_backend
    backend = get_filesystem_backend()
    restored = 0
    complete = True
    operation = journal.get("operation") or "install"

    for rel, meta in journal.get("paths", {}).items():
        try:
            safe = _safe_rel_path(str(rel))
        except DiagnosticError:
            continue
        if isinstance(meta, dict) and meta.get("state") in {"retained", "skipped"}:
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
                dest = _dest_under_root(root, safe)
                if operation == "uninstall" and os.path.lexists(dest):
                    continue
                try:
                    backend.mkdirs_beneath(os.path.dirname(dest), root=root)
                    backend.replace_beneath(rollback_backup, dest, root=root)
                    restored += 1
                    continue
                except DiagnosticError:
                    complete = False
                    continue
            dest = _dest_under_root(root, safe)
            if os.path.lexists(dest):
                try:
                    with open(dest, "rb") as f:
                        if sha256_bytes(f.read()) == original_sha:
                            restored += 1
                            continue
                except OSError:
                    pass
            complete = False
        else:
            dest = _dest_under_root(root, safe)
            if os.path.lexists(dest):
                staged_sha = meta.get("sha256")
                if isinstance(staged_sha, str):
                    try:
                        with open(dest, "rb") as f:
                            if sha256_bytes(f.read()) != staged_sha:
                                complete = False
                                continue
                    except OSError:
                        complete = False
                        continue
                try:
                    backend.unlink_beneath(dest, root=root)
                    restored += 1
                except DiagnosticError:
                    complete = False

    return restored, complete


def _restore_checkpoint_files_windows(
    checkpoint: InstallCheckpoint,
    *,
    backup_root: str | None = None,
) -> None:
    from ..platform_fs import get_filesystem_backend
    backend = get_filesystem_backend()
    root = checkpoint.root
    for rel, meta in checkpoint.paths.items():
        if meta.get("transaction_lock"):
            continue
        dest = _dest_under_root(root, rel)
        if meta.get("existed"):
            snapshot = meta.get("snapshot")
            if isinstance(snapshot, str) and os.path.isfile(snapshot) and not os.path.islink(snapshot):
                backend.mkdirs_beneath(os.path.dirname(dest), root=root)
                backend.replace_beneath(snapshot, dest, root=root)
        else:
            if os.path.lexists(dest):
                backend.unlink_beneath(dest, root=root)
    if backup_root:
        _delete_authorized_support_subtree(root, backup_root, role="backup")


def _write_journal(root: str, journal: dict[str, Any]) -> None:
    payload = json.dumps(journal, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    # Self-check closed journal schema before durable write (#28).
    try:
        parse_journal_document(payload)
    except ControlSchemaError as error:
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    _atomic_write_support_file(root, JOURNAL_NAME, payload.encode("utf-8"))


def _unlink_support_control_file(root: str, name: str) -> None:
    """Unlink a control basename under ``.portable-resume/.state`` (#33)."""
    if name not in _CONTROL_BASENAMES:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    if not _supports_descriptor_relative_commit():
        path = os.path.join(control_state_dir(root), name)
        if not os.path.lexists(path):
            # Legacy v1 location during migration window.
            legacy = os.path.join(root, SUPPORT_DIR, name)
            if not os.path.lexists(legacy):
                return
            if os.path.islink(legacy) or not os.path.isfile(legacy):
                raise DiagnosticError("E_INSTALL_CONFLICT")
            os.unlink(legacy)
            return
        if os.path.islink(path) or not os.path.isfile(path):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        os.unlink(path)
        return
    root_fd = _open_skill_root_descriptor(root)
    support_fd: int | None = None
    state_fd: int | None = None
    try:
        try:
            support_fd, state_fd = _open_control_parent_fd(root_fd)
        except DiagnosticError:
            return
        try:
            st = os.lstat(name, dir_fd=state_fd)
        except FileNotFoundError:
            return
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
        if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
            raise DiagnosticError("E_INSTALL_CONFLICT")
        try:
            os.unlink(name, dir_fd=state_fd)
        except FileNotFoundError:
            return
        except OSError as error:
            raise DiagnosticError("E_INSTALL_CONFLICT") from error
    finally:
        if state_fd is not None:
            os.close(state_fd)
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
    """Capture every file an install plan may mutate for cross-root compensation.

    Call only while the corresponding root lock is held (#23).
    """
    snapshot_dir = tempfile.mkdtemp(prefix="portable-resume-checkpoint-")
    paths: dict[str, dict[str, Any]] = {}
    existing = load_manifest(plan.root)
    candidates = set(plan.files)
    if existing is not None:
        candidates.update(existing.files)
    candidates.add(f"{SUPPORT_DIR}/{STATE_SUBDIR}/{MANIFEST_NAME}")
    candidates.add(f"{SUPPORT_DIR}/{STATE_SUBDIR}/{LOCK_NAME}")
    # Legacy v1 control paths (pre-#33) still snapshotted during migration windows.
    candidates.add(f"{SUPPORT_DIR}/{MANIFEST_NAME}")
    candidates.add(f"{SUPPORT_DIR}/{LOCK_NAME}")
    try:
        for rel in sorted(candidates):
            safe = _safe_rel_path(rel)
            dest = _dest_under_root(plan.root, safe)
            meta: dict[str, Any] = {"existed": False, "allowed_sha256": []}
            if safe in plan.files:
                meta["allowed_sha256"].append(sha256_bytes(plan.files[safe]))
            if safe in {
                f"{SUPPORT_DIR}/{STATE_SUBDIR}/{MANIFEST_NAME}",
                f"{SUPPORT_DIR}/{MANIFEST_NAME}",
            }:
                meta["allowed_sha256"].append(sha256_bytes(plan.manifest.dumps().encode("utf-8")))
            if safe in {
                f"{SUPPORT_DIR}/{STATE_SUBDIR}/{LOCK_NAME}",
                f"{SUPPORT_DIR}/{LOCK_NAME}",
            }:
                # Never snapshot the live exclusive lock we hold: compensation
                # always removes installer lock metadata rather than restoring a
                # pid file from mid-transaction (#23 multi-root holds locks
                # before checkpoint).
                meta["transaction_lock"] = True
                meta["existed"] = False
                paths[safe] = meta
                continue
            if os.path.lexists(dest):
                if os.path.islink(dest) or not os.path.isfile(dest):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                snapshot = os.path.join(snapshot_dir, safe)
                _copy_regular_nofollow(dest, snapshot)
                digest = sha256_file(snapshot)
                meta.update(
                    {
                        "existed": True,
                        "snapshot": snapshot,
                        "sha256": digest,
                    }
                )
                # Live pre-state is also an allowed post-transaction identity for
                # compensation drift checks (already at checkpoint).
                if digest not in meta["allowed_sha256"]:
                    meta["allowed_sha256"].append(digest)
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
    """Restore a completed root install to its captured byte-for-byte file state.

    Never overwrites a live regular file whose digest is outside the transaction's
    allowed set (pre-checkpoint snapshot or planned post-install bytes). Unknown
    concurrent mutation returns ``E_RECOVERY_REQUIRED`` (#23).
    """
    if os.name == "nt" and _is_windows_install_allowed_for_tests():
        return _restore_checkpoint_files_windows(checkpoint, backup_root=backup_root)
    removed: list[str] = []
    root = checkpoint.root
    root_fd: int | None = None
    if _supports_descriptor_relative_commit():
        try:
            root_fd = _open_skill_root_descriptor(root)
        except DiagnosticError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
    try:
        for rel, meta in checkpoint.paths.items():
            # Exclusive install.lock is owned by the holding RootLock for the whole
            # multi-root txn; never unlink it while compensation runs under locks.
            if meta.get("transaction_lock"):
                continue
            dest = _dest_under_root(root, rel)
            allowed = set(meta.get("allowed_sha256") or ())
            snap_sha = meta.get("sha256")
            if isinstance(snap_sha, str):
                allowed.add(snap_sha)
            if meta.get("existed"):
                snapshot = meta.get("snapshot")
                if not isinstance(snapshot, str) or not os.path.isfile(snapshot) or os.path.islink(snapshot):
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
                if sha256_file(snapshot) != meta.get("sha256"):
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
                _restore_regular_nofollow(
                    snapshot,
                    dest,
                    allowed_live_sha256=allowed if allowed else None,
                )
                continue
            # Path was absent at checkpoint: remove only if live digest is a
            # transaction-created payload (quarantine unlink when dirfd works).
            if root_fd is not None:
                # Probe with lstat first so symlink/non-regular/unopenable parents
                # fail closed; only a confirmed missing leaf is a no-op success.
                try:
                    parent_fd, basename, owns_parent = _open_parent_under_root_fd(
                        root_fd, rel, create=False
                    )
                except DiagnosticError as error:
                    raise DiagnosticError("E_RECOVERY_REQUIRED") from error
                try:
                    try:
                        st = os.lstat(basename, dir_fd=parent_fd)
                    except FileNotFoundError:
                        continue
                    except OSError as error:
                        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
                    if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
                        raise DiagnosticError("E_RECOVERY_REQUIRED")
                finally:
                    if owns_parent:
                        os.close(parent_fd)
                try:
                    live = _sha256_regular_under_root_fd(root_fd, rel)
                except DiagnosticError as error:
                    raise DiagnosticError("E_RECOVERY_REQUIRED") from error
                if live not in allowed:
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
                if _unlink_regular_under_root_fd(root_fd, rel, expected_sha256=live):
                    removed.append(rel)
                    continue
                # False: missing after check, digest raced under quarantine, or
                # leaf became non-regular. Only a truly absent leaf is success.
                try:
                    parent_fd, basename, owns_parent = _open_parent_under_root_fd(
                        root_fd, rel, create=False
                    )
                except DiagnosticError as error:
                    raise DiagnosticError("E_RECOVERY_REQUIRED") from error
                try:
                    try:
                        os.lstat(basename, dir_fd=parent_fd)
                    except FileNotFoundError:
                        continue
                    except OSError as error:
                        raise DiagnosticError("E_RECOVERY_REQUIRED") from error
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
                finally:
                    if owns_parent:
                        os.close(parent_fd)
            if not os.path.lexists(dest):
                continue
            if os.path.islink(dest) or not os.path.isfile(dest):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            if sha256_file(dest) not in allowed:
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            os.remove(dest)
            removed.append(rel)
    finally:
        if root_fd is not None:
            os.close(root_fd)
    if backup_root:
        _delete_authorized_support_subtree(root, backup_root, role="backup")
    _cleanup_empty_dirs(root, removed_paths=removed)


def install_multi_targets(
    targets: list[tuple[str, str]],
    *,
    scope: str,
    dry_run: bool = False,
    force_with_backup: bool = False,
    sources: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Install multiple ``(host, root)`` targets as one same-process multi-root txn (#23).

    Acquires exclusive locks on unique physical roots in canonical order, then
    replans, checkpoints, mutates, and compensates **while all locks remain held**.

    Durability boundary: in-memory ``/tmp`` checkpoints do not survive process
    crash; per-root journals remain independently recoverable via ``recover_root``.
    This is same-process compensation, not durable cross-root atomicity.
    """
    if not targets:
        return []
    if dry_run:
        results: list[dict[str, Any]] = []
        for host, root in targets:
            plan = plan_install(
                host=host,
                scope=scope,
                root=root,
                dry_run=True,
                force_with_backup=force_with_backup,
                sources=sources,
            )
            results.append(execute_install(plan, force_with_backup=force_with_backup))
        return results

    require_mutating_install_platform()

    # Unlocked preflight: catch deterministic conflicts (foreign files, plans)
    # before creating support/lock trees on every target root.
    for host, root in targets:
        plan_install(
            host=host,
            scope=scope,
            root=root,
            dry_run=False,
            force_with_backup=force_with_backup,
            sources=sources,
        )

    # Canonical unique physical roots (dedupe shared destinations).
    physical_to_roots: dict[str, str] = {}
    for _host, root in targets:
        key = os.path.realpath(root)
        physical_to_roots.setdefault(key, root)
    ordered_keys = sorted(physical_to_roots.keys())

    held: list[tuple[str, RootLock]] = []
    checkpoints: list[InstallCheckpoint] = []
    completed: list[tuple[str, InstallCheckpoint, dict[str, Any]]] = []
    results: list[dict[str, Any]] = []
    try:
        for key in ordered_keys:
            lock = RootLock(physical_to_roots[key])
            lock.__enter__()
            held.append((key, lock))

        lock_by_key = {key: lock for key, lock in held}

        # Journals + replan only after every lock is held.
        for key, lock in held:
            require_no_pending_journal(lock.root)

        plans: list[ActionPlan] = []
        for host, root in targets:
            plan = plan_install(
                host=host,
                scope=scope,
                root=root,
                dry_run=False,
                force_with_backup=force_with_backup,
                sources=sources,
            )
            plans.append(plan)

        # Shared-root package identity recheck under locks.
        groups: dict[str, list[str]] = {}
        for plan in plans:
            groups.setdefault(os.path.realpath(plan.root), []).append(plan.host)
        for hosts in groups.values():
            if len(hosts) < 2:
                continue
            identities = {
                package_identity(materialize_plan(host, sources=sources)) for host in hosts
            }
            if len(identities) > 1:
                raise DiagnosticError("E_INSTALL_CONFLICT", family=tuple(sorted(hosts)))

        for plan in plans:
            key = os.path.realpath(plan.root)
            lock = lock_by_key[key]
            # Replan + checkpoint immediately before each execute so shared
            # physical roots capture the generation that this step will undo
            # (not the common pre-transaction generation).
            live_plan = plan_install(
                host=plan.host,
                scope=scope,
                root=plan.root,
                dry_run=False,
                force_with_backup=force_with_backup,
                sources=sources,
            )
            checkpoint = capture_install_checkpoint(live_plan)
            checkpoints.append(checkpoint)
            result = execute_install(
                live_plan,
                force_with_backup=force_with_backup,
                lock=lock,
            )
            results.append(result)
            completed.append((plan.host, checkpoint, result))
        return results
    except Exception:
        compensation_failures: list[str] = []
        for host, checkpoint, result in reversed(completed):
            try:
                restore_install_checkpoint(
                    checkpoint,
                    backup_root=result.get("backup_root"),
                )
            except Exception:
                compensation_failures.append(host)
        if compensation_failures:
            raise DiagnosticError(
                "E_RECOVERY_REQUIRED",
                family=tuple(sorted(compensation_failures)),
            )
        raise
    finally:
        for checkpoint in checkpoints:
            try:
                discard_install_checkpoint(checkpoint)
            except Exception:
                pass
        for _key, lock in reversed(held):
            try:
                lock.__exit__(None, None, None)
            except Exception:
                pass


def discard_install_checkpoint(checkpoint: InstallCheckpoint) -> None:
    shutil.rmtree(checkpoint.snapshot_dir, ignore_errors=True)


def _restore_regular_nofollow(
    snapshot: str,
    dest: str,
    *,
    allowed_live_sha256: set[str] | None = None,
) -> None:
    """Atomically restore one checkpoint file without following destination symlinks.

    When ``allowed_live_sha256`` is set and ``dest`` exists, re-hash the live
    regular inode under ``O_NOFOLLOW`` and refuse replace unless that digest is
    still in the allowed transaction set (binds check to the replaced leaf).
    """
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    if allowed_live_sha256 is not None and os.path.lexists(dest):
        if os.path.islink(dest) or not os.path.isfile(dest):
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            live_fd = os.open(dest, flags)
        except OSError as error:
            raise DiagnosticError("E_RECOVERY_REQUIRED") from error
        try:
            st = os.fstat(live_fd)
            if not stat_mod.S_ISREG(st.st_mode):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            live = _sha256_open_fd(live_fd)
            if live not in allowed_live_sha256:
                raise DiagnosticError("E_RECOVERY_REQUIRED")
        finally:
            os.close(live_fd)
    fd, temporary = tempfile.mkstemp(prefix=".portable-resume-restore-", dir=parent)
    os.close(fd)
    os.remove(temporary)
    try:
        _copy_regular_nofollow(snapshot, temporary)
        # Re-check immediately before replace when a live leaf was present.
        if allowed_live_sha256 is not None and os.path.lexists(dest):
            if os.path.islink(dest) or not os.path.isfile(dest):
                raise DiagnosticError("E_RECOVERY_REQUIRED")
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                live_fd = os.open(dest, flags)
            except OSError as error:
                raise DiagnosticError("E_RECOVERY_REQUIRED") from error
            try:
                st = os.fstat(live_fd)
                if not stat_mod.S_ISREG(st.st_mode):
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
                live = _sha256_open_fd(live_fd)
                if live not in allowed_live_sha256:
                    raise DiagnosticError("E_RECOVERY_REQUIRED")
            finally:
                os.close(live_fd)
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

    ``role`` is ``\"stage\"`` (``portable-resume-stage-*`` under
    ``.portable-resume/.state`` or legacy under ``.portable-resume``) or
    ``\"backup\"`` under ``.portable-resume/.state/backups`` (or legacy
    ``.portable-resume/backups``). Protected payload names such as ``runtime``
    and ``resources`` are never authorized.

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
    if stat_mod.S_ISLNK(support_stat.st_mode) or bool(getattr(support_stat, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(support_stat.st_mode):
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
        # #33: .state/<stage>  |  legacy: <stage>
        if len(parts) == 2 and parts[0] == STATE_SUBDIR:
            name = parts[1]
        elif len(parts) == 1:
            name = parts[0]
        else:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
        if name in _PROTECTED_SUPPORT_NAMES or not name.startswith(STAGE_PREFIX):
            raise DiagnosticError("E_RECOVERY_REQUIRED")
    else:
        # #33: .state/backups/<name>  |  legacy: backups/<name>
        if len(parts) == 3 and parts[0] == STATE_SUBDIR and parts[1] == BACKUP_DIR:
            backup_name = parts[2]
        elif len(parts) == 2 and parts[0] == BACKUP_DIR:
            backup_name = parts[1]
        else:
            raise DiagnosticError("E_RECOVERY_REQUIRED")
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
    if stat_mod.S_ISLNK(path_stat.st_mode) or bool(getattr(path_stat, "st_file_attributes", 0) & 0x400) or not stat_mod.S_ISDIR(path_stat.st_mode):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    return candidate


def _delete_authorized_support_subtree(root: str, path: str, *, role: str) -> None:
    """Authorize then delete a stage/backup tree; failures stay fail-closed."""
    authorized = _authorize_support_cleanup(root, path, role=role)
    if authorized is None:
        return
    if os.name == "nt" and _is_windows_install_allowed_for_tests():
        if os.path.exists(authorized):
            shutil.rmtree(authorized, ignore_errors=True)
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
        if os.name == "nt" and _is_windows_install_allowed_for_tests():
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
            return
        _safe_rmtree_under_support(root, path)
    except (DiagnosticError, OSError):
        pass


def _rollback_paths(root: str, journal: dict[str, Any]) -> tuple[int, bool]:
    restored = 0
    complete = True
    if not _supports_descriptor_relative_commit():
        if os.name == "nt" and _is_windows_install_allowed_for_tests():
            return _rollback_paths_windows(root, journal)
        # Payload restore/delete mutations require dirfd containment (Windows residual #29).
        return 0, False
    operation = journal.get("operation") or "install"
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
            # Retained/skipped paths must not be rewritten from stage snapshots
            # (post-snapshot drift / shared-claim policy).
            if isinstance(meta, dict) and meta.get("state") in {"retained", "skipped"}:
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
                        # Uninstall: exclusive-create only (never overwrite a live leaf,
                        # including unreadable mode-000 / concurrent edits). Install:
                        # replace is intentional to restore pre-commit originals.
                        wrote = _replace_under_root_from_support_path(
                            root=root,
                            root_fd=root_fd,
                            rel=safe,
                            support_src=rollback_backup,
                            expected_sha256=str(original_sha),
                            if_absent=(operation == "uninstall"),
                        )
                        if wrote:
                            restored += 1
                        # if_absent and live leaf present → preserved; still complete.
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

    Uninstall journals (``operation=uninstall``) publish either a new generation
    without the target claim, or removal of the ownership manifest when no claims
    remain. Incomplete staging/committing must never be treated as published solely
    because the manifest is missing (manual tamper residual).
    """
    if journal.get("state") == "complete":
        return True
    target = journal.get("target_generation", journal.get("generation"))
    if not isinstance(target, int):
        return False
    operation = journal.get("operation") or "install"
    try:
        manifest = load_manifest(root)
    except DiagnosticError:
        return False
    if operation == "uninstall":
        claim = journal.get("claim")
        if not isinstance(claim, str) or not claim:
            return False
        if manifest is None:
            # Last-claim uninstall removes the ownership manifest only after
            # entering publishing_manifest (or completing path removals).
            if journal.get("state") == "publishing_manifest":
                return True
            paths = journal.get("paths") or {}
            if not isinstance(paths, dict) or not paths:
                return False
            return all(
                isinstance(meta, dict) and meta.get("state") in {"removed", "retained", "skipped"}
                for meta in paths.values()
            )
        return manifest.generation == target and claim not in manifest.claims
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
    legacy_path = _legacy_journal_path(root)
    if not os.path.lexists(path) and not os.path.lexists(legacy_path):
        return {"ok": True, "recovered": False}
    active = path if os.path.lexists(path) else legacy_path
    if os.path.islink(active) or not os.path.isfile(active):
        raise DiagnosticError("E_RECOVERY_REQUIRED")
    require_mutating_install_platform()
    with RootLock(root):
        try:
            # Migration may have moved the journal into .state/ under the lock.
            if os.path.lexists(journal_path(root)):
                raw = _read_support_control_file(root, JOURNAL_NAME)
            else:
                raw = _read_legacy_support_control_file(root, JOURNAL_NAME)
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
    """Observe one coherent ownership generation.

    On POSIX, when an ownership support tree already exists, take the exclusive
    root lock so a cooperating install/uninstall/recover cannot interleave
    mid-hash. Do not create support/lock paths for roots that were never
    installed (stay observationally pure). Windows residual (#29): observational
    verify without exclusive locking (mutating install already fails closed).
    """
    # Lock when either #33 state or legacy v1 support ownership exists.
    has_control = os.path.isdir(control_state_dir(root)) or (
        os.path.isdir(os.path.join(root, SUPPORT_DIR))
        and (
            os.path.lexists(_legacy_manifest_path(root))
            or os.path.lexists(manifest_path(root))
            or os.path.lexists(_legacy_lock_path(root))
        )
    )
    if os.name != "nt" and has_control:
        with RootLock(root):
            return _verify_root_locked(root, claim=claim)
    return _verify_root_locked(root, claim=claim)


def _verify_root_locked(root: str, *, claim: str | None = None) -> dict[str, Any]:
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
        expected_by_host: dict[str, tuple[dict[str, bytes], str]] = {}
        for claim_id, meta in manifest.claims.items():
            if claim is not None and claim_id != claim:
                continue
            host = meta.get("host")
            if host not in HOST_PROFILES or meta.get("bundle_version") != BUNDLE_VERSION:
                raise DiagnosticError("E_VERIFY_MISMATCH")
            if host not in expected_by_host:
                files = materialize_plan(host)
                expected_by_host[host] = (files, package_identity(files))
            expected_files, expected_identity = expected_by_host[host]
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
        "control_state_dir": control_state_dir(root),
        "control_layout": "state-v1",
    }


def _read_regular_bytes_under_root_fd(root_fd: int, rel: str) -> tuple[bytes, int]:
    """Return ``(body, mode)`` for a regular no-follow payload file under root_fd."""
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
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks), stat_mod.S_IMODE(st.st_mode)
        finally:
            os.close(fd)
    finally:
        if owns_parent:
            os.close(parent_fd)


def uninstall_claim(*, host: str, scope: str, root: str, dry_run: bool = False) -> dict[str, Any]:
    """Remove one ownership claim under a durable recoverable journal (#22).

    Removable sole-claim files are snapshotted into an installer stage tree before
    unlink; crash recovery restores the previous payload + manifest generation
    when the target generation is not yet published.
    """
    claim = claim_key(host=host, scope=scope, root=root)
    if dry_run:
        manifest = load_manifest(root)
        if manifest is None or claim not in manifest.claims:
            return {"ok": True, "dry_run": True, "removed_files": [], "claim": claim}
        removable = [p for p, e in manifest.files.items() if e.claims == [claim]]
        return {"ok": True, "dry_run": True, "removed_files": removable, "claim": claim}

    require_mutating_install_platform()
    with RootLock(root):
        require_no_pending_journal(root)
        manifest = load_manifest(root)
        if manifest is None or claim not in manifest.claims:
            return {"ok": True, "removed_files": [], "claim": claim}
        if not _supports_descriptor_relative_commit():
            if os.name == "nt" and _is_windows_install_allowed_for_tests():
                return _uninstall_claim_windows(root=root, claim=claim, manifest=manifest)
            raise DiagnosticError("E_INSTALL_CONFLICT")

        base_generation = manifest.generation
        target_generation = base_generation + 1
        # Classify under the pinned root before any durable mutation.
        root_fd = _open_skill_root_descriptor(root)
        removable: list[tuple[str, str]] = []  # (rel, expected_sha256)
        retained_drift: list[str] = []
        drop_from_manifest: list[str] = []
        try:
            for path, entry in list(manifest.files.items()):
                if claim not in entry.claims:
                    continue
                remaining = [c for c in entry.claims if c != claim]
                if remaining:
                    entry.claims = remaining
                    continue
                try:
                    _safe_rel_path(path)
                except DiagnosticError:
                    # Malicious/escaped manifest entry: drop from manifest, never delete outside root.
                    drop_from_manifest.append(path)
                    continue
                try:
                    matches = _sha256_regular_under_root_fd(root_fd, path) == entry.sha256
                except DiagnosticError:
                    matches = False
                if matches:
                    removable.append((path, entry.sha256))
                    drop_from_manifest.append(path)
                    continue
                # Parent-swap / missing / drift: never ambient-delete.
                try:
                    parent_fd, basename, owns_parent = _open_parent_under_root_fd(
                        root_fd, path, create=False
                    )
                except DiagnosticError:
                    drop_from_manifest.append(path)
                    continue
                try:
                    try:
                        st = os.lstat(basename, dir_fd=parent_fd)
                    except FileNotFoundError:
                        drop_from_manifest.append(path)
                        continue
                    if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
                        raise DiagnosticError("E_INSTALL_CONFLICT")
                    retained_drift.append(path)
                    drop_from_manifest.append(path)
                finally:
                    if owns_parent:
                        os.close(parent_fd)
        finally:
            os.close(root_fd)

        del manifest.claims[claim]
        for path in drop_from_manifest:
            manifest.files.pop(path, None)
        manifest.generation = target_generation

        # No payload/manifest mutation required (claim gone from memory only after
        # shared-file claim-ref updates + empty removable set still needs publish).
        # Always journal when we will rewrite the ownership generation.
        pin_root_fd: int | None = None
        support_fd: int | None = None
        state_fd: int | None = None
        stage_fd: int | None = None
        journal: dict[str, Any] | None = None
        stage_dir = ""
        removed: list[str] = []
        try:
            pin_root_fd = _open_skill_root_descriptor(root)
            support_fd, state_fd = _open_control_parent_fd(pin_root_fd)
            stage_name = _mkdir_unique_under_fd(state_fd, STAGE_PREFIX)
            stage_dir = os.path.join(control_state_dir(root), stage_name)
            stage_fd = os.open(
                stage_name,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=state_fd,
            )
            journal = {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "staging",
                "generation": base_generation,
                "target_generation": target_generation,
                "claim": claim,
                "stage_dir": stage_dir,
                "backup_root": None,
                "operation": "uninstall",
                "paths": {},
            }
            # Snapshot every removable owned file before the first unlink.
            # Durable-flush each snapshot (and parents) so a crash after the journal
            # write cannot lose rollback material while deletions are authorized.
            for rel, expected_sha in removable:
                body, mode = _read_regular_bytes_under_root_fd(pin_root_fd, rel)
                if sha256_bytes(body) != expected_sha:
                    # Digest raced after classification: treat as retained drift.
                    retained_drift.append(rel)
                    continue
                rollback_rel = f".rollback/{rel}"
                _materialize_bytes_under_fd(
                    stage_fd,
                    rollback_rel,
                    body,
                    mode=mode,
                    fsync=True,
                )
                journal["paths"][rel] = {
                    "state": "pending",
                    "existed": True,
                    "rollback_backup": os.path.join(stage_dir, ".rollback", rel),
                    "original_sha256": expected_sha,
                    "sha256": expected_sha,
                }
            # Fsync the full stage tree (nested .rollback/... dirs + files) so
            # directory entries for intermediate path components are durable
            # before the journal authorizes payload unlinks.
            _fsync_tree_dirfd(stage_fd)
            _write_journal(root, journal)

            journal["state"] = "committing"
            _write_journal(root, journal)
            for rel, meta in list(journal["paths"].items()):
                expected_sha = meta.get("original_sha256") or meta.get("sha256")
                if not _is_hex_sha256(expected_sha):
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                try:
                    unlinked = _unlink_regular_under_root_fd(
                        pin_root_fd,
                        rel,
                        expected_sha256=str(expected_sha),
                    )
                except DiagnosticError as error:
                    raise DiagnosticError("E_INSTALL_CONFLICT") from error
                if unlinked:
                    removed.append(rel)
                    meta["state"] = "removed"
                else:
                    # False means missing *or* post-snapshot digest drift.
                    # Never treat live drifted content as removed: rollback must
                    # not overwrite concurrent user edits with the stage snapshot.
                    try:
                        _sha256_regular_under_root_fd(pin_root_fd, rel)
                    except DiagnosticError:
                        # Leaf/parent gone after snapshot — already removed.
                        removed.append(rel)
                        meta["state"] = "removed"
                    else:
                        meta["state"] = "retained"
                        meta.pop("rollback_backup", None)
                        meta.pop("original_sha256", None)
                        retained_drift.append(rel)
                journal["paths"][rel] = meta
                _write_journal(root, journal)

            journal["state"] = "publishing_manifest"
            journal["target_generation"] = target_generation
            _write_journal(root, journal)
            if manifest.claims:
                _atomic_write_support_file(
                    root,
                    MANIFEST_NAME,
                    manifest.dumps().encode("utf-8"),
                )
            else:
                try:
                    _unlink_support_control_file(root, MANIFEST_NAME)
                except DiagnosticError:
                    # Never ambient-fallback delete after control-store failure.
                    raise

            journal["state"] = "complete"
            try:
                _write_journal(root, journal)
            except DiagnosticError:
                # Manifest/absence is already ownership truth; prefer dropping a
                # stale incomplete journal so recover cannot re-install payload.
                try:
                    _unlink_support_control_file(root, JOURNAL_NAME)
                except DiagnosticError:
                    pass
            try:
                _delete_authorized_support_subtree(root, stage_dir, role="stage")
            except DiagnosticError:
                pass
            try:
                if os.path.lexists(journal_path(root)):
                    _unlink_support_control_file(root, JOURNAL_NAME)
            except DiagnosticError:
                pass
            if not manifest.claims:
                try:
                    _cleanup_empty_dirs(root, removed_paths=removed)
                except DiagnosticError:
                    pass
            return {
                "ok": True,
                "claim": claim,
                "removed_files": removed,
                "retained_drift": retained_drift,
                "generation": target_generation,
            }
        except Exception:
            if journal is not None and not _install_generation_is_published(root, journal):
                _attempt_rollback(root, journal)
            raise
        finally:
            if stage_fd is not None:
                os.close(stage_fd)
            if state_fd is not None:
                os.close(state_fd)
            if support_fd is not None:
                os.close(support_fd)
            if pin_root_fd is not None:
                os.close(pin_root_fd)


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
