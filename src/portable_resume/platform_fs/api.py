"""Typed capability contract, platform identity, and abstract backend interface."""

from __future__ import annotations

import abc
import contextlib
import os
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from ..bounds import DEFAULT_BOUNDS

if TYPE_CHECKING:
    from ..bounds import ReadBudget
    from ..snapshot import AttemptHook, SQLiteSnapshot, StableRead


@dataclass(frozen=True, slots=True)
class FilesystemCapabilities:
    """Immutable, closed description of platform filesystem capabilities."""

    descriptor_relative: bool
    nofollow_reads: bool
    relative_mutations: bool
    sqlite_snapshots: bool
    atomic_output: bool
    exclusive_locking: bool
    reparse_points: bool
    handle_locking: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "descriptor_relative": self.descriptor_relative,
            "nofollow_reads": self.nofollow_reads,
            "relative_mutations": self.relative_mutations,
            "sqlite_snapshots": self.sqlite_snapshots,
            "atomic_output": self.atomic_output,
            "exclusive_locking": self.exclusive_locking,
            "reparse_points": self.reparse_points,
            "handle_locking": self.handle_locking,
        }


@dataclass(frozen=True, slots=True)
class FilesystemIdentity:
    """Platform-neutral filesystem identity."""

    os_name: str
    sys_platform: str
    is_posix: bool
    is_windows: bool
    backend_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "os_name": self.os_name,
            "sys_platform": self.sys_platform,
            "is_posix": self.is_posix,
            "is_windows": self.is_windows,
            "backend_name": self.backend_name,
        }


class FilesystemBackend(abc.ABC):
    """Abstract cross-platform safe filesystem backend interface."""

    @property
    @abc.abstractmethod
    def identity(self) -> FilesystemIdentity:
        """Return the platform identity for this backend."""

    @property
    @abc.abstractmethod
    def capabilities(self) -> FilesystemCapabilities:
        """Return the immutable capability flags for this backend."""

    @abc.abstractmethod
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
        """Read stable bytes without following symlinks beneath a safe root."""

    @abc.abstractmethod
    def mkdirs_beneath(
        self,
        directory: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> str:
        """Create directory and parents under root with safe permissions."""

    @abc.abstractmethod
    def unlink_beneath(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        """Safely unlink a regular file or leaf link beneath root without following symlinks."""

    @abc.abstractmethod
    def replace_beneath(
        self,
        source_path: str | os.PathLike[str],
        target_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        """Safely replace target_path with source_path under root."""

    @abc.abstractmethod
    def sqlite_family_snapshot(
        self,
        database_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
        max_bytes: int = DEFAULT_BOUNDS.sqlite_snapshot_bytes,
    ) -> SQLiteSnapshot:
        """Create a private isolated snapshot of a SQLite database and journal family."""

    @abc.abstractmethod
    def atomic_replace_output(
        self,
        path: str,
        data: bytes | bytearray | memoryview,
        *,
        clobber: bool = False,
    ) -> str:
        """Write payload to an exclusive temp file and os.replace onto target path."""

    @abc.abstractmethod
    def acquire_exclusive_lock(
        self,
        lock_path: str | os.PathLike[str],
    ) -> contextlib.AbstractContextManager[int]:
        """Acquire non-blocking exclusive file lock context manager returning open fd."""
