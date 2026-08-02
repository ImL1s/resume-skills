"""Windows safe-filesystem backend scaffold implementation."""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import sys
import tempfile
from typing import Iterator

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..output_write import write_output_bytes
from ..paths import require_within
from ..snapshot import AttemptHook, FileFingerprint, SQLiteSnapshot, StableRead
from .api import FilesystemBackend, FilesystemCapabilities, FilesystemIdentity


class WindowsFilesystemBackend(FilesystemBackend):
    """Reparse-point and handle-aware Windows backend scaffold."""

    def __init__(self) -> None:
        self._identity = FilesystemIdentity(
            os_name=os.name,
            sys_platform=sys.platform,
            is_posix=False,
            is_windows=True,
            backend_name="WindowsFilesystemBackend",
        )
        self._capabilities = FilesystemCapabilities(
            descriptor_relative=False,
            nofollow_reads=False,
            relative_mutations=False,
            sqlite_snapshots=True,
            atomic_output=True,
            exclusive_locking=False,
            reparse_points=True,
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
        if (
            max_bytes < 0
            or max_bytes > DEFAULT_BOUNDS.sqlite_snapshot_bytes
            or not 1 <= attempts <= DEFAULT_BOUNDS.snapshot_attempts
        ):
            raise DiagnosticError.invalid()

        canonical_path = require_within(path, root)
        _ = membership_limit
        _ = budget

        for attempt in range(1, attempts + 1):
            if hook is not None:
                hook(str(canonical_path), attempt, "read")
            try:
                st1 = os.lstat(canonical_path)
                if stat.S_ISLNK(st1.st_mode) or not stat.S_ISREG(st1.st_mode):
                    raise DiagnosticError.unsafe_path()
                if st1.st_size > max_bytes:
                    raise DiagnosticError.limit_exceeded()

                with open(canonical_path, "rb") as fp:
                    data = fp.read(max_bytes + 1)

                st2 = os.lstat(canonical_path)
                if len(data) > max_bytes:
                    raise DiagnosticError.limit_exceeded()

                if (st1.st_size, st1.st_mtime_ns) == (st2.st_size, st2.st_mtime_ns):
                    if budget is not None:
                        budget.consume_bytes(len(data))
                    fingerprint = FileFingerprint(
                        device=st1.st_dev,
                        inode=st1.st_ino,
                        mode=st1.st_mode,
                        size=st1.st_size,
                        mtime_ns=st1.st_mtime_ns,
                    )
                    return StableRead(data=data, fingerprint=fingerprint, attempts=attempt)
            except DiagnosticError:
                raise
            except (OSError, IOError) as error:
                raise DiagnosticError.unsafe_path() from error

        raise DiagnosticError.source_busy(attempts=attempts)

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
        if max_bytes < 0 or max_bytes > DEFAULT_BOUNDS.sqlite_snapshot_bytes:
            raise DiagnosticError.invalid()
        canonical_db = require_within(database_path, root)
        try:
            st = os.lstat(canonical_db)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise DiagnosticError.unsafe_path()
            if st.st_size > max_bytes:
                raise DiagnosticError.limit_exceeded()
        except DiagnosticError:
            raise
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

        temp_dir = tempfile.TemporaryDirectory(prefix="portable-resume-sqlite-")
        try:
            base_name = os.path.basename(canonical_db)
            target_db = os.path.join(temp_dir.name, base_name)

            shutil.copy2(canonical_db, target_db)
            copied_family: list[str] = [base_name]

            for ext in ("-wal", "-journal"):
                sidecar = canonical_db + ext
                if os.path.isfile(sidecar) and not os.path.islink(sidecar):
                    shutil.copy2(sidecar, target_db + ext)
                    copied_family.append(base_name + ext)

            return SQLiteSnapshot(
                directory=temp_dir.name,
                database=target_db,
                source_name="windows_sqlite_snapshot",
                attempts=1,
                family=tuple(copied_family),
                _temporary=temp_dir,
            )
        except Exception:
            temp_dir.cleanup()
            raise

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
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")
