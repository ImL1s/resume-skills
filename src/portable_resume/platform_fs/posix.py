"""POSIX safe-filesystem backend implementation."""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Iterator

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..output_write import write_output_bytes
from ..paths import canonical_root, require_within
from ..snapshot import (
    AttemptHook,
    SQLiteSnapshot,
    StableRead,
    _open_directory_beneath,
    snapshot_sqlite_family,
    stable_read_bytes,
)
from .api import FilesystemBackend, FilesystemCapabilities, FilesystemIdentity


class PosixFilesystemBackend(FilesystemBackend):
    """Descriptor-relative POSIX safe-filesystem backend."""

    def __init__(self) -> None:
        self._identity = FilesystemIdentity(
            os_name=os.name,
            sys_platform=sys.platform,
            is_posix=True,
            is_windows=False,
            backend_name="PosixFilesystemBackend",
        )
        self._capabilities = FilesystemCapabilities(
            descriptor_relative=True,
            nofollow_reads=True,
            relative_mutations=False,
            sqlite_snapshots=True,
            atomic_output=True,
            exclusive_locking=True,
            reparse_points=False,
            handle_locking=False,
        )

    @property
    def identity(self) -> FilesystemIdentity:
        return self._identity

    @property
    def capabilities(self) -> FilesystemCapabilities:
        return self._capabilities

    def read_regular_stable(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
        max_bytes: int = DEFAULT_BOUNDS.record_bytes,
        attempts: int = DEFAULT_BOUNDS.snapshot_attempts,
        membership_limit: int = DEFAULT_BOUNDS.scanned_records,
        budget: ReadBudget | None = None,
        hook: AttemptHook | None = None,
    ) -> StableRead:
        return stable_read_bytes(
            path,
            root=root,
            max_bytes=max_bytes,
            attempts=attempts,
            membership_limit=membership_limit,
            budget=budget,
            hook=hook,
        )

    def mkdirs_beneath(
        self,
        directory: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> str:
        canonical_dir = require_within(directory, root)
        os.makedirs(canonical_dir, mode=0o700, exist_ok=True)
        return canonical_dir

    def unlink_beneath(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        canonical_path = require_within(path, root)
        base_canon = canonical_root(root)
        if canonical_path == base_canon:
            raise DiagnosticError.unsafe_path()

        parent = os.path.dirname(canonical_path)
        basename = os.path.basename(canonical_path)
        try:
            parent_fd = _open_directory_beneath(parent, base_canon)
        except Exception as error:
            raise DiagnosticError.unsafe_path() from error

        try:
            os.unlink(basename, dir_fd=parent_fd)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error
        finally:
            os.close(parent_fd)

    def replace_beneath(
        self,
        source_path: str | os.PathLike[str],
        target_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        src_canon = require_within(source_path, root)
        dst_canon = require_within(target_path, root)
        base_canon = canonical_root(root)
        if src_canon == base_canon or dst_canon == base_canon:
            raise DiagnosticError.unsafe_path()

        src_parent = os.path.dirname(src_canon)
        dst_parent = os.path.dirname(dst_canon)
        src_base = os.path.basename(src_canon)
        dst_base = os.path.basename(dst_canon)

        try:
            src_fd = _open_directory_beneath(src_parent, base_canon)
        except Exception as error:
            raise DiagnosticError.unsafe_path() from error

        try:
            dst_fd = _open_directory_beneath(dst_parent, base_canon)
        except Exception as error:
            os.close(src_fd)
            raise DiagnosticError.unsafe_path() from error

        try:
            os.replace(src_base, dst_base, src_dir_fd=src_fd, dst_dir_fd=dst_fd)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error
        finally:
            os.close(src_fd)
            os.close(dst_fd)

    def sqlite_family_snapshot(
        self,
        database_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
        max_bytes: int = DEFAULT_BOUNDS.sqlite_snapshot_bytes,
    ) -> SQLiteSnapshot:
        bounds = (
            DEFAULT_BOUNDS
            if max_bytes == DEFAULT_BOUNDS.sqlite_snapshot_bytes
            else DEFAULT_BOUNDS.with_overrides(sqlite_snapshot_bytes=max_bytes)
        )
        return snapshot_sqlite_family(database_path, root=root, bounds=bounds)

    def atomic_replace_output(
        self,
        path: str,
        data: bytes | bytearray | memoryview,
        *,
        clobber: bool = False,
    ) -> str:
        return write_output_bytes(path, data, clobber=clobber)

    @contextlib.contextmanager
    def acquire_exclusive_lock(
        self,
        lock_path: str | os.PathLike[str],
    ) -> Iterator[int]:
        target = os.fspath(lock_path)
        parent = os.path.dirname(os.path.abspath(target))
        if parent and not os.path.exists(parent):
            os.makedirs(parent, mode=0o700, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(target, flags, 0o600)
        except OSError as error:
            raise DiagnosticError("E_INSTALL_BUSY") from error
        try:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, IOError, ImportError) as error:
                raise DiagnosticError("E_INSTALL_BUSY") from error
            yield fd
        finally:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            except (OSError, ImportError):
                pass
            os.close(fd)
