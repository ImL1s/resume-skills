"""Fallback unsupported filesystem backend that fails closed for all operations."""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Iterator

from ..bounds import DEFAULT_BOUNDS
from ..diagnostics import DiagnosticError
from ..snapshot import AttemptHook, ReadBudget, SQLiteSnapshot, StableRead
from .api import FilesystemBackend, FilesystemCapabilities, FilesystemIdentity, FilesystemObjectIdentity


class UnsupportedFilesystemBackend(FilesystemBackend):
    """Fail-closed filesystem backend for unsupported operating systems."""

    def __init__(self) -> None:
        self._identity = FilesystemIdentity(
            os_name=os.name,
            sys_platform=sys.platform,
            is_posix=False,
            is_windows=False,
            backend_name="UnsupportedFilesystemBackend",
        )
        self._capabilities = FilesystemCapabilities(
            descriptor_relative=False,
            nofollow_reads=False,
            relative_mutations=False,
            sqlite_snapshots=False,
            atomic_output=False,
            exclusive_locking=False,
            reparse_points=False,
            handle_locking=False,
        )

    @property
    def identity(self) -> FilesystemIdentity:
        return self._identity

    @property
    def capabilities(self) -> FilesystemCapabilities:
        return self._capabilities

    def inspect_object_identity(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> FilesystemObjectIdentity:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

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
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def mkdirs_beneath(
        self,
        directory: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> str:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def unlink_beneath(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def replace_beneath(
        self,
        source_path: str | os.PathLike[str],
        target_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def sqlite_family_snapshot(
        self,
        database_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
        max_bytes: int = DEFAULT_BOUNDS.sqlite_snapshot_bytes,
    ) -> SQLiteSnapshot:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def atomic_replace_output(
        self,
        path: str,
        data: bytes | bytearray | memoryview,
        *,
        clobber: bool = False,
    ) -> str:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    @contextlib.contextmanager
    def acquire_exclusive_lock(
        self,
        lock_path: str | os.PathLike[str],
    ) -> Iterator[int]:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")
        yield 0  # type: ignore[unreachable]
