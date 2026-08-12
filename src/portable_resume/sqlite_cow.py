"""Darwin/APFS private SQLite snapshots for active WAL families.

The source family is handled only through no-follow descriptors.  SQLite is
opened only after an atomic APFS clone of the pinned main descriptor has been
materialized through the last checksum-validated WAL commit.  The connection
uses the exact private vnode, not its replaceable scratch pathname.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import secrets
import sqlite3
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Iterator
from urllib.parse import quote

from .bounds import DEFAULT_BOUNDS, Bounds, validate_bounds
from .diagnostics import DiagnosticError
from .paths import canonicalize_cwd, is_within, require_regular_no_symlinks
from .platform_fs.darwin_apfs import (
    DarwinCloneUnavailable,
    clone_file_from_fd,
    is_apfs_fd,
    unlink_volume_inode,
    volume_inode_path,
)
from .sqlite_wal import (
    WalHeader,
    WalPrefix,
    materialize_wal_prefix,
    validate_wal_header,
    validate_wal_prefix,
)

AttemptHook = Callable[[str, int, str], None]

_MAIN_NAME = "snapshot.sqlite"
_WAL_NAME = _MAIN_NAME + "-wal"
_SHM_NAME = _MAIN_NAME + "-shm"
_JOURNAL_NAME = _MAIN_NAME + "-journal"
_KNOWN_PRIVATE_MEMBERS = frozenset({_MAIN_NAME, _WAL_NAME, _SHM_NAME, _JOURNAL_NAME})
_SQLITE_COW_RESERVE_BYTES = 64 * 1024 * 1024
_SCRATCH_NAME_ATTEMPTS = 8
# Keep the cleanup primitive tied to the actual interpreter host.  Tests may
# emulate the Darwin capability gate by patching ``sys.platform``; that must
# not make a Linux process call Darwin-only ``unlinkat(AT_UNIQUE)`` symbols and
# mask the intended E_SQLITE_LIVE_WAL diagnostic.
_RUNTIME_IS_DARWIN = sys.platform == "darwin"

_CAPABILITY_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        errno.EXDEV,
        errno.EROFS,
        errno.EINVAL,
        errno.EACCES,
        errno.EPERM,
    )
    if value is not None
)
_LIMIT_ERRNOS = frozenset(
    value
    for value in (errno.ENOSPC, getattr(errno, "EDQUOT", None), errno.EFBIG)
    if value is not None
)
_RETRY_ERRNOS = frozenset(
    value for value in (errno.EINTR, errno.EAGAIN, errno.EBUSY, errno.EIO) if value is not None
)
_UNSAFE_ERRNOS = frozenset(
    value for value in (errno.ELOOP, errno.ENOTDIR, errno.ENOENT) if value is not None
)


def _identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)


def _full_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (*_identity(value), value.st_size, value.st_mtime_ns)


def _close_quietly(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _scratch_directory_empty(descriptor: int) -> bool:
    """Check scratch emptiness without materializing attacker-added entries."""

    try:
        with os.scandir(descriptor) as entries:
            return next(entries, None) is None
    except OSError as error:
        raise DiagnosticError("E_INVARIANT") from error


@dataclass(slots=True)
class _Deadline:
    expires_ns: int
    provider: str | None
    family: tuple[str, ...]
    attempt: int = 0

    @classmethod
    def from_bounds(
        cls,
        bounds: Bounds,
        *,
        provider: str | None,
        family: tuple[str, ...],
    ) -> "_Deadline":
        return cls(
            expires_ns=time.monotonic_ns() + bounds.sqlite_snapshot_deadline_ms * 1_000_000,
            provider=provider,
            family=family,
        )

    def expired(self) -> bool:
        return time.monotonic_ns() > self.expires_ns

    def check(self) -> None:
        if self.expired():
            raise DiagnosticError.source_busy(
                attempts=self.attempt or 0,
                family=self.family,
                provider=self.provider,
            )


@dataclass(slots=True)
class _PinnedFamily:
    safe: str
    root: str
    parent: str
    basename: str
    parent_fd: int
    parent_stat: os.stat_result
    main_fd: int
    main_stat: os.stat_result
    wal_fd: int
    wal_stat: os.stat_result
    shm_fd: int | None
    shm_stat: os.stat_result | None
    header: WalHeader

    @property
    def family_names(self) -> tuple[str, ...]:
        names = [self.basename, self.basename + "-wal"]
        if self.shm_fd is not None:
            names.append(self.basename + "-shm")
        return tuple(names)

    def close(self) -> None:
        for descriptor in (self.shm_fd, self.wal_fd, self.main_fd, self.parent_fd):
            _close_quietly(descriptor)
        self.shm_fd = None
        self.wal_fd = -1
        self.main_fd = -1
        self.parent_fd = -1


@dataclass(slots=True)
class _PrivateScratch:
    parent: str
    name: str
    path: str
    parent_fd: int
    directory_fd: int
    directory_identity: tuple[int, int, int]
    main_fd: int | None = None
    wal_fd: int | None = None
    closed: bool = False

    def verify_entry(self) -> None:
        if self.closed:
            raise DiagnosticError("E_INVARIANT")
        try:
            entry = os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False)
            opened = os.fstat(self.directory_fd)
        except OSError as error:
            raise DiagnosticError("E_INVARIANT") from error
        if not stat.S_ISDIR(entry.st_mode):
            raise DiagnosticError("E_INVARIANT")
        if _identity(entry) != self.directory_identity or _identity(opened) != self.directory_identity:
            raise DiagnosticError("E_INVARIANT")

    def cleanup(self) -> None:
        if self.closed:
            return
        failure: BaseException | None = None
        entry_mismatch = False
        try:
            try:
                self.verify_entry()
            except DiagnosticError:
                entry_mismatch = True
            for attribute in ("wal_fd", "main_fd"):
                descriptor = getattr(self, attribute)
                if descriptor is None or descriptor < 0:
                    continue
                try:
                    if _RUNTIME_IS_DARWIN:
                        unlink_volume_inode(descriptor)
                    else:
                        # Non-Darwin execution reaches this only in mocked unit
                        # tests; the production backend rejects it before clone.
                        expected = _identity(os.fstat(descriptor))
                        removed = False
                        for name in _KNOWN_PRIVATE_MEMBERS:
                            try:
                                current = os.stat(
                                    name,
                                    dir_fd=self.directory_fd,
                                    follow_symlinks=False,
                                )
                            except FileNotFoundError:
                                continue
                            if _identity(current) == expected:
                                os.unlink(name, dir_fd=self.directory_fd)
                                removed = True
                                break
                        if not removed:
                            raise DiagnosticError("E_INVARIANT")
                except FileNotFoundError as error:
                    if failure is None:
                        failure = DiagnosticError("E_INVARIANT")
                        failure.__cause__ = error
                except (DarwinCloneUnavailable, OSError) as error:
                    if failure is None:
                        failure = DiagnosticError("E_INVARIANT")
                        failure.__cause__ = error
                finally:
                    _close_quietly(descriptor)
                    setattr(self, attribute, None)
            try:
                if not _scratch_directory_empty(self.directory_fd):
                    raise DiagnosticError("E_INVARIANT")
                if failure is None and _RUNTIME_IS_DARWIN:
                    unlink_volume_inode(self.directory_fd, directory=True)
                    try:
                        os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        entry_mismatch = True
                elif failure is None:
                    self.verify_entry()
                    os.rmdir(self.name, dir_fd=self.parent_fd)
            except (DarwinCloneUnavailable, OSError) as error:
                if failure is None:
                    failure = DiagnosticError("E_INVARIANT")
                    failure.__cause__ = error
        except BaseException as error:
            failure = error
        finally:
            _close_quietly(self.directory_fd)
            self.directory_fd = -1
        _close_quietly(self.parent_fd)
        self.parent_fd = -1
        self.closed = True
        if entry_mismatch and failure is None:
            failure = DiagnosticError("E_INVARIANT")
        if failure is not None:
            if isinstance(failure, DiagnosticError) and failure.code == "E_INVARIANT":
                raise failure
            raise DiagnosticError("E_INVARIANT") from failure


@dataclass(slots=True)
class CowSQLiteSnapshot:
    """Accepted materialized private database backed by pinned scratch vnodes."""

    directory: str
    database: str
    source_name: str
    attempts: int
    family: tuple[str, ...]
    wal_prefix: WalPrefix
    _scratch: _PrivateScratch
    _deadline: _Deadline
    _provider: str | None
    _hook: AttemptHook | None

    @property
    def uri(self) -> str:
        descriptor = self._scratch.main_fd
        if descriptor is None or descriptor < 0:
            raise DiagnosticError("E_INVARIANT", provider=self._provider)
        try:
            encoded = quote(volume_inode_path(descriptor), safe="/")
        except DarwinCloneUnavailable as error:
            raise DiagnosticError("E_INVARIANT", provider=self._provider) from error
        return f"file:{encoded}?mode=ro&immutable=1&cache=private"

    def _call_hook(self, stage: str) -> None:
        if self._hook is not None:
            self._hook(stage, self.attempts, self.source_name)

    def connect(self) -> sqlite3.Connection:
        self._deadline.check()
        self._scratch.verify_entry()
        self._call_hook("before-private-connect")
        self._scratch.verify_entry()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.uri, uri=True)
            self._call_hook("after-private-connect")
            self._scratch.verify_entry()
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA query_only").fetchone() != (1,):
                raise DiagnosticError("E_INVARIANT", provider=self._provider)

            def progress() -> int:
                return 1 if self._deadline.expired() else 0

            connection.set_progress_handler(progress, 1_000)
            self._deadline.check()
            self._call_hook("before-private-integrity")
            integrity = connection.execute("PRAGMA integrity_check(1)").fetchone()
            self._deadline.check()
            if integrity != ("ok",):
                raise DiagnosticError.source_busy(
                    attempts=self.attempts,
                    family=self.family,
                    provider=self._provider,
                )
            return connection
        except DiagnosticError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as error:
            if connection is not None:
                connection.close()
            raise DiagnosticError.source_busy(
                attempts=self.attempts,
                family=self.family,
                provider=self._provider,
            ) from error

    def close(self) -> None:
        self._scratch.cleanup()

    def __enter__(self) -> "CowSQLiteSnapshot":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _absolute_directory_fd(directory: str) -> int:
    """Open a canonical absolute directory by a no-follow component walk."""

    canonical = canonicalize_cwd(directory)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.path.sep, flags)
    try:
        for part in (item for item in canonical.split(os.path.sep) if item):
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        _close_quietly(descriptor)
        raise


def _stat_entry(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise DiagnosticError.source_busy(family=(name,)) from error


def _open_regular_entry(parent_fd: int, name: str) -> tuple[int, os.stat_result]:
    entry = _stat_entry(parent_fd, name)
    if entry is None:
        raise DiagnosticError.source_busy(family=(name,))
    if not stat.S_ISREG(entry.st_mode):
        raise DiagnosticError.unsafe_path()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise DiagnosticError.unsafe_path() from error
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or _full_identity(opened) != _full_identity(entry):
        os.close(descriptor)
        raise DiagnosticError.source_busy(family=(name,))
    return descriptor, opened


def _classify_journal(parent_fd: int, basename: str, *, provider: str | None) -> None:
    name = basename + "-journal"
    current = _stat_entry(parent_fd, name)
    if current is None:
        return
    if not stat.S_ISREG(current.st_mode):
        raise DiagnosticError.unsafe_path()
    raise DiagnosticError(
        "E_SQLITE_HOT_JOURNAL",
        provider=provider,
        attempts=0,
        family=(name,),
    )


def _pin_family(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    provider: str | None,
    deadline: _Deadline,
) -> _PinnedFamily:
    # Import lazily so snapshot.py can expose this module without an import cycle.
    from .snapshot import _open_directory_beneath

    safe, base = require_regular_no_symlinks(database, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    parent_fd = _open_directory_beneath(parent, base)
    main_fd: int | None = None
    wal_fd: int | None = None
    shm_fd: int | None = None
    try:
        parent_stat = os.fstat(parent_fd)
        # Unsafe members take precedence over the capability diagnostic.
        for suffix in ("-journal", "-wal", "-shm"):
            current = _stat_entry(parent_fd, basename + suffix)
            if current is not None and not stat.S_ISREG(current.st_mode):
                raise DiagnosticError.unsafe_path()
        _classify_journal(parent_fd, basename, provider=provider)
        main_fd, main_stat = _open_regular_entry(parent_fd, basename)
        wal_name = basename + "-wal"
        wal_entry = _stat_entry(parent_fd, wal_name)
        if wal_entry is None:
            raise DiagnosticError(
                "E_SQLITE_LIVE_WAL",
                provider=provider,
                attempts=0,
                family=(),
            )
        wal_fd, wal_stat = _open_regular_entry(parent_fd, wal_name)
        shm_stat: os.stat_result | None = None
        if _stat_entry(parent_fd, basename + "-shm") is not None:
            shm_fd, shm_stat = _open_regular_entry(parent_fd, basename + "-shm")
        deadline.check()
        header = validate_wal_header(wal_fd, deadline_check=deadline.check)
        return _PinnedFamily(
            safe=safe,
            root=base,
            parent=parent,
            basename=basename,
            parent_fd=parent_fd,
            parent_stat=parent_stat,
            main_fd=main_fd,
            main_stat=main_stat,
            wal_fd=wal_fd,
            wal_stat=wal_stat,
            shm_fd=shm_fd,
            shm_stat=shm_stat,
            header=header,
        )
    except BaseException:
        _close_quietly(shm_fd)
        _close_quietly(wal_fd)
        _close_quietly(main_fd)
        _close_quietly(parent_fd)
        raise


def _scratch_candidates(source_root: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for value in (tempfile.gettempdir(), os.path.dirname(source_root)):
        candidate = canonicalize_cwd(value)
        if candidate in candidates or is_within(candidate, source_root):
            continue
        candidates.append(candidate)
    return tuple(candidates)


def _create_scratch_in(parent: str, *, source_device: int, deadline: _Deadline) -> _PrivateScratch:
    parent_fd = _absolute_directory_fd(parent)
    try:
        parent_stat = os.fstat(parent_fd)
        if parent_stat.st_dev != source_device or not is_apfs_fd(parent_fd):
            raise DarwinCloneUnavailable("scratch is not same-volume APFS")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        for _ in range(_SCRATCH_NAME_ATTEMPTS):
            deadline.check()
            name = "portable-resume-cow-" + secrets.token_hex(16)
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            except OSError:
                raise
            directory_fd: int | None = None
            try:
                directory_fd = os.open(name, flags, dir_fd=parent_fd)
                os.fchmod(directory_fd, 0o700)
                entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                opened = os.fstat(directory_fd)
                if not stat.S_ISDIR(entry.st_mode) or _identity(entry) != _identity(opened):
                    raise DiagnosticError("E_INVARIANT")
                return _PrivateScratch(
                    parent=parent,
                    name=name,
                    path=os.path.join(parent, name),
                    parent_fd=parent_fd,
                    directory_fd=directory_fd,
                    directory_identity=_identity(opened),
                )
            except BaseException:
                _close_quietly(directory_fd)
                try:
                    os.rmdir(name, dir_fd=parent_fd)
                except OSError:
                    pass
                raise
        raise DiagnosticError("E_INVARIANT")
    except BaseException:
        _close_quietly(parent_fd)
        raise


def _require_space(
    scratch: _PrivateScratch,
    *,
    main_size: int,
    wal_size: int,
) -> None:
    try:
        values = os.fstatvfs(scratch.directory_fd)
        fragment = values.f_frsize or values.f_bsize
        available = values.f_bavail * fragment
    except OSError as error:
        raise DiagnosticError.limit_exceeded() from error
    required = main_size + wal_size + _SQLITE_COW_RESERVE_BYTES
    if available < required:
        raise DiagnosticError.limit_exceeded()


def _map_clone_error(error: BaseException, *, provider: str | None, family: tuple[str, ...]) -> DiagnosticError:
    if isinstance(error, DarwinCloneUnavailable):
        return DiagnosticError(
            "E_SQLITE_LIVE_WAL", provider=provider, attempts=0, family=family[1:]
        )
    number = error.errno if isinstance(error, OSError) else None
    if number in _LIMIT_ERRNOS:
        return DiagnosticError.limit_exceeded()
    if number in _RETRY_ERRNOS:
        return DiagnosticError.source_busy(family=family, provider=provider)
    if number in _UNSAFE_ERRNOS:
        return DiagnosticError.unsafe_path()
    return DiagnosticError(
        "E_SQLITE_LIVE_WAL", provider=provider, attempts=0, family=family[1:]
    )


def _clone_main(
    family: _PinnedFamily,
    *,
    bounds: Bounds,
    deadline: _Deadline,
) -> _PrivateScratch:
    if sys.platform != "darwin" or not is_apfs_fd(family.main_fd):
        raise DiagnosticError(
            "E_SQLITE_LIVE_WAL",
            provider=deadline.provider,
            attempts=0,
            family=family.family_names[1:],
        )
    last_error: DiagnosticError | None = None
    for parent in _scratch_candidates(family.root):
        scratch: _PrivateScratch | None = None
        try:
            scratch = _create_scratch_in(
                parent,
                source_device=family.main_stat.st_dev,
                deadline=deadline,
            )
            initial_wal_size = os.fstat(family.wal_fd).st_size
            _require_space(
                scratch,
                main_size=family.main_stat.st_size,
                wal_size=initial_wal_size,
            )
            clone_file_from_fd(
                family.main_fd,
                scratch.directory_fd,
                _MAIN_NAME,
                deadline_check=deadline.check,
            )
            cloned = os.open(
                _MAIN_NAME,
                os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=scratch.directory_fd,
            )
            try:
                cloned_stat = os.fstat(cloned)
                if (
                    not stat.S_ISREG(cloned_stat.st_mode)
                    or cloned_stat.st_dev != family.main_stat.st_dev
                    or cloned_stat.st_size > bounds.sqlite_cow_logical_bytes
                ):
                    raise DiagnosticError.limit_exceeded()
                os.fchmod(cloned, 0o600)
                _require_space(
                    scratch,
                    main_size=cloned_stat.st_size,
                    wal_size=initial_wal_size,
                )
                scratch.main_fd = cloned
                cloned = -1
            finally:
                _close_quietly(cloned)
            return scratch
        except DiagnosticError as error:
            if scratch is not None:
                scratch.cleanup()
            if error.code == "E_SQLITE_LIVE_WAL":
                last_error = error
                continue
            raise
        except (DarwinCloneUnavailable, OSError) as error:
            if scratch is not None:
                scratch.cleanup()
            mapped = _map_clone_error(error, provider=deadline.provider, family=family.family_names)
            if mapped.code == "E_SQLITE_LIVE_WAL":
                last_error = mapped
                continue
            raise mapped from error
    if last_error is not None:
        raise last_error
    raise DiagnosticError(
        "E_SQLITE_LIVE_WAL",
        provider=deadline.provider,
        attempts=0,
        family=family.family_names[1:],
    )


def _copy_prefix(
    family: _PinnedFamily,
    scratch: _PrivateScratch,
    prefix: WalPrefix,
    *,
    deadline: _Deadline,
) -> str:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        destination = os.open(_WAL_NAME, flags, 0o600, dir_fd=scratch.directory_fd)
    except OSError as error:
        raise DiagnosticError("E_INVARIANT") from error
    digest = hashlib.sha256()
    scratch.wal_fd = destination
    offset = 0
    while offset < prefix.length:
        deadline.check()
        try:
            block = os.pread(family.wal_fd, min(64 * 1024, prefix.length - offset), offset)
        except OSError as error:
            raise DiagnosticError.source_busy(
                family=family.family_names, provider=deadline.provider
            ) from error
        if not block:
            raise DiagnosticError.source_busy(
                family=family.family_names, provider=deadline.provider
            )
        digest.update(block)
        view = memoryview(block)
        while view:
            written = os.write(destination, view)
            if written <= 0:
                raise DiagnosticError("E_INVARIANT")
            view = view[written:]
        offset += len(block)
    os.fsync(destination)
    os.fchmod(destination, 0o600)
    return digest.hexdigest()


def _same_entry(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    *,
    allow_content_change: bool,
) -> bool:
    current = _stat_entry(parent_fd, name)
    if current is None:
        return False
    if allow_content_change:
        return _identity(current) == _identity(expected)
    return _full_identity(current) == _full_identity(expected)


def _verify_source_acceptance(
    family: _PinnedFamily,
    *,
    prefix: WalPrefix,
    captured_wal_stat: os.stat_result,
    deadline: _Deadline,
) -> None:
    from .snapshot import _open_directory_beneath

    deadline.check()
    if not _same_entry(
        family.parent_fd, family.basename, family.main_stat, allow_content_change=True
    ):
        raise DiagnosticError.source_busy(family=family.family_names, provider=deadline.provider)
    if not _same_entry(
        family.parent_fd, family.basename + "-wal", family.wal_stat, allow_content_change=True
    ):
        raise DiagnosticError.source_busy(family=family.family_names, provider=deadline.provider)
    if family.shm_stat is not None and not _same_entry(
        family.parent_fd, family.basename + "-shm", family.shm_stat, allow_content_change=True
    ):
        raise DiagnosticError.source_busy(family=family.family_names, provider=deadline.provider)
    _classify_journal(family.parent_fd, family.basename, provider=deadline.provider)
    current_wal = os.fstat(family.wal_fd)
    if _identity(current_wal) != _identity(family.wal_stat) or current_wal.st_size < prefix.length:
        raise DiagnosticError.source_busy(family=family.family_names, provider=deadline.provider)
    # Appending beyond the accepted prefix is legal.  A same-length rewrite is
    # not: it is indistinguishable from truncate/regrow by length alone, while
    # normal WAL readers never rewrite an established generation in place.
    if (
        current_wal.st_size == captured_wal_stat.st_size
        and current_wal.st_ctime_ns != captured_wal_stat.st_ctime_ns
    ):
        raise DiagnosticError.source_busy(family=family.family_names, provider=deadline.provider)
    if validate_wal_header(family.wal_fd, deadline_check=deadline.check).raw != family.header.raw:
        raise DiagnosticError.source_busy(family=family.family_names, provider=deadline.provider)
    verified = validate_wal_prefix(
        family.wal_fd,
        source_size=prefix.length,
        max_bytes=prefix.length,
        max_frames=prefix.frame_count,
        deadline_check=deadline.check,
    )
    if verified != prefix:
        raise DiagnosticError.source_busy(family=family.family_names, provider=deadline.provider)
    verification_fd = _open_directory_beneath(family.parent, family.root)
    try:
        if _identity(os.fstat(verification_fd)) != _identity(family.parent_stat):
            raise DiagnosticError.source_busy(
                family=family.family_names, provider=deadline.provider
            )
    finally:
        os.close(verification_fd)


def _snapshot_attempt(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    bounds: Bounds,
    attempt: int,
    deadline: _Deadline,
    hook: AttemptHook | None,
    provider: str | None,
) -> CowSQLiteSnapshot:
    deadline.attempt = attempt
    family = _pin_family(database, root=root, provider=provider, deadline=deadline)
    scratch: _PrivateScratch | None = None
    try:
        if family.main_stat.st_size > bounds.sqlite_cow_logical_bytes:
            raise DiagnosticError.limit_exceeded()
        if hook is not None:
            hook("after-family-pin", attempt, family.safe)
        deadline.check()
        scratch = _clone_main(family, bounds=bounds, deadline=deadline)
        if hook is not None:
            hook("after-clone", attempt, family.safe)
        if validate_wal_header(family.wal_fd, deadline_check=deadline.check).raw != family.header.raw:
            raise DiagnosticError.source_busy(
                attempts=attempt, family=family.family_names, provider=provider
            )
        captured_wal_stat = os.fstat(family.wal_fd)
        wal_size = captured_wal_stat.st_size
        prefix = validate_wal_prefix(
            family.wal_fd,
            source_size=wal_size,
            max_bytes=bounds.sqlite_wal_bytes,
            max_frames=bounds.sqlite_wal_frames,
            deadline_check=deadline.check,
        )
        if hook is not None:
            hook("after-wal-prefix", attempt, family.safe)
        copied_digest = _copy_prefix(family, scratch, prefix, deadline=deadline)
        if copied_digest != prefix.sha256:
            raise DiagnosticError.source_busy(
                attempts=attempt, family=family.family_names, provider=provider
            )
        if hook is not None:
            hook("after-wal-copy", attempt, family.safe)
        _verify_source_acceptance(
            family,
            prefix=prefix,
            captured_wal_stat=captured_wal_stat,
            deadline=deadline,
        )
        if hook is not None:
            hook("before-accept", attempt, family.safe)
        _verify_source_acceptance(
            family,
            prefix=prefix,
            captured_wal_stat=captured_wal_stat,
            deadline=deadline,
        )
        scratch.verify_entry()
        if scratch.main_fd is None or scratch.wal_fd is None:
            raise DiagnosticError("E_INVARIANT", provider=provider)
        materialize_wal_prefix(
            scratch.main_fd,
            scratch.wal_fd,
            prefix,
            max_logical_bytes=bounds.sqlite_cow_logical_bytes,
            deadline_check=deadline.check,
        )
        try:
            private_database = volume_inode_path(scratch.main_fd)
        except DarwinCloneUnavailable as error:
            raise DiagnosticError("E_INVARIANT", provider=provider) from error
        return CowSQLiteSnapshot(
            directory=scratch.path,
            database=private_database,
            source_name=family.basename,
            attempts=attempt,
            family=family.family_names,
            wal_prefix=prefix,
            _scratch=scratch,
            _deadline=deadline,
            _provider=provider,
            _hook=hook,
        )
    except BaseException:
        if scratch is not None:
            scratch.cleanup()
        raise
    finally:
        family.close()


@contextlib.contextmanager
def private_sqlite_connection_live_wal_cow_impl(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    bounds: Bounds = DEFAULT_BOUNDS,
    attempts: int | None = None,
    hook: AttemptHook | None = None,
    provider: str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a query-only connection to a coherent private live-WAL snapshot."""

    validate_bounds(bounds)
    maximum_attempts = bounds.snapshot_attempts if attempts is None else attempts
    if type(maximum_attempts) is not int or not 1 <= maximum_attempts <= bounds.snapshot_attempts:
        raise DiagnosticError.invalid()
    basename = os.path.basename(os.fspath(database))
    family_names = (basename, basename + "-wal", basename + "-shm")
    deadline = _Deadline.from_bounds(bounds, provider=provider, family=family_names)
    last_busy: DiagnosticError | None = None
    snapshot: CowSQLiteSnapshot | None = None
    connection: sqlite3.Connection | None = None
    for attempt in range(1, maximum_attempts + 1):
        deadline.check()
        try:
            snapshot = _snapshot_attempt(
                database,
                root=root,
                bounds=bounds,
                attempt=attempt,
                deadline=deadline,
                hook=hook,
                provider=provider,
            )
            connection = snapshot.connect()
        except DiagnosticError as error:
            if connection is not None:
                connection.close()
                connection = None
            if snapshot is not None:
                snapshot.close()
                snapshot = None
            if error.code != "E_SOURCE_BUSY":
                raise
            last_busy = error
            continue
        break
    if snapshot is None or connection is None:
        raise DiagnosticError.source_busy(
            attempts=maximum_attempts,
            family=last_busy.family if last_busy and last_busy.family else family_names,
            provider=provider,
        )
    try:
        try:
            yield connection
            deadline.check()
        except sqlite3.OperationalError as error:
            if deadline.expired():
                raise DiagnosticError.source_busy(
                    attempts=snapshot.attempts,
                    family=snapshot.family,
                    provider=provider,
                ) from error
            raise
    finally:
        connection.close()
        snapshot.close()
