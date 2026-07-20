"""No-follow stable file reads and source-isolated SQLite-family snapshots."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from typing import Callable, Iterator
from urllib.parse import quote

from .bounds import DEFAULT_BOUNDS, Bounds, ReadBudget
from .diagnostics import DiagnosticError
from .paths import canonical_root, require_regular_no_symlinks

AttemptHook = Callable[[str, int, str], None]


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    content_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class StableRead:
    data: bytes
    fingerprint: FileFingerprint
    attempts: int


@dataclass(slots=True)
class SQLiteSnapshot:
    """Private copied SQLite family; call ``connect`` rather than opening source."""

    directory: str
    database: str
    source_name: str
    attempts: int
    family: tuple[str, ...]
    _temporary: tempfile.TemporaryDirectory[str]

    @property
    def uri(self) -> str:
        # quote keeps the URI path deterministic and prevents query injection from names.
        encoded = quote(os.path.abspath(self.database), safe="/")
        return f"file:{encoded}?mode=ro&cache=private"

    def connect(self) -> sqlite3.Connection:
        if not os.path.commonpath((os.path.realpath(self.database), os.path.realpath(self.directory))) == os.path.realpath(self.directory):
            raise DiagnosticError("E_INVARIANT")
        connection = sqlite3.connect(self.uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        value = connection.execute("PRAGMA query_only").fetchone()
        if value != (1,):
            connection.close()
            raise DiagnosticError("E_INVARIANT")
        return connection

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> "SQLiteSnapshot":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _fingerprint(stat_result: os.stat_result, content_sha256: str | None = None) -> FileFingerprint:
    return FileFingerprint(
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_mode,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        content_sha256,
    )


def _open_directory_beneath(directory: str, root: str) -> int:
    relative = os.path.relpath(os.path.abspath(directory), root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
        raise DiagnosticError.unsafe_path()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        current_fd = os.open(root, flags)
    except OSError as error:
        raise DiagnosticError.unsafe_path() from error
    try:
        for part in (entry for entry in relative.split(os.sep) if entry not in ("", ".")):
            if part == os.pardir:
                raise DiagnosticError.unsafe_path()
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _directory_fingerprint(
    directory: str, *, limit: int, root: str | None = None
) -> tuple[tuple[str, FileFingerprint], ...]:
    descriptor: int | None = None
    try:
        if root is not None:
            descriptor = _open_directory_beneath(directory, root)
            names = sorted(os.listdir(descriptor))
        else:
            names = sorted(os.listdir(directory))
        if len(names) > limit:
            raise DiagnosticError.limit_exceeded()
        output: list[tuple[str, FileFingerprint]] = []
        for name in names:
            if "/" in name or "\x00" in name:
                raise DiagnosticError.unsafe_path()
            if descriptor is None:
                current = os.lstat(os.path.join(directory, name))
            else:
                current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            output.append((name, _fingerprint(current)))
        return tuple(output)
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError.source_busy() from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _open_no_follow(path: str, root: str) -> int:
    """Open a regular file by walking every component descriptor-relative."""

    safe, _ = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    parent_fd = _open_directory_beneath(parent, root)
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(basename, flags, dir_fd=parent_fd)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error
    finally:
        os.close(parent_fd)
    current = os.fstat(descriptor)
    if not stat.S_ISREG(current.st_mode):
        os.close(descriptor)
        raise DiagnosticError.unsafe_path()
    return descriptor


def stable_read_bytes(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    max_bytes: int = DEFAULT_BOUNDS.record_bytes,
    attempts: int = DEFAULT_BOUNDS.snapshot_attempts,
    membership_limit: int = DEFAULT_BOUNDS.scanned_records,
    budget: ReadBudget | None = None,
    hook: AttemptHook | None = None,
) -> StableRead:
    """Read stable bytes without following symlinks; retry a changing source."""

    if max_bytes < 0 or max_bytes > DEFAULT_BOUNDS.sqlite_snapshot_bytes or not 1 <= attempts <= DEFAULT_BOUNDS.snapshot_attempts:
        raise DiagnosticError.invalid()
    safe, base = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    for attempt in range(1, attempts + 1):
        before_membership = _directory_fingerprint(parent, limit=membership_limit, root=base)
        descriptor = _open_no_follow(safe, base)
        try:
            before_stat = os.fstat(descriptor)
            before = _fingerprint(before_stat)
            if before.size > max_bytes:
                raise DiagnosticError.limit_exceeded()
            if hook:
                hook("before-read", attempt, safe)
            data = _read_bounded_descriptor(descriptor, max_bytes)
            if len(data) > max_bytes:
                raise DiagnosticError.limit_exceeded()
            content_hash = hashlib.sha256(data).hexdigest()
            observed = _fingerprint(before_stat, content_hash)
            if hook:
                hook("after-read", attempt, safe)
            os.lseek(descriptor, 0, os.SEEK_SET)
            verified_data = _read_bounded_descriptor(descriptor, max_bytes)
            verified = _fingerprint(os.fstat(descriptor), hashlib.sha256(verified_data).hexdigest())
            if hook:
                hook("after-verify-read", attempt, safe)
            # Observe parent membership before the terminal content hash.  A
            # same-stat mutation performed during that observation is then
            # detected by the terminal descriptor read below.
            middle_membership = _directory_fingerprint(parent, limit=membership_limit, root=base)
            os.lseek(descriptor, 0, os.SEEK_SET)
            final_data = _read_bounded_descriptor(descriptor, max_bytes)
            final = _fingerprint(os.fstat(descriptor), hashlib.sha256(final_data).hexdigest())
        finally:
            os.close(descriptor)
        after_membership = _directory_fingerprint(parent, limit=membership_limit, root=base)
        if (
            observed == verified == final
            and before_membership == middle_membership == after_membership
            and len(data) == before.size
            and data == verified_data == final_data
        ):
            if budget is not None:
                budget.consume_records()
                budget.consume_bytes(len(data))
            return StableRead(data=data, fingerprint=observed, attempts=attempt)
    family = (os.path.basename(safe),)
    raise DiagnosticError.source_busy(attempts=attempts, family=family)


def _read_bounded_descriptor(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > maximum:
        raise DiagnosticError.limit_exceeded()
    return data


def _family_paths(database: str) -> dict[str, str]:
    return {
        "main": database,
        "wal": database + "-wal",
        "shm": database + "-shm",
        "journal": database + "-journal",
    }


def _family_state(database: str, root: str, *, bounds: Bounds) -> tuple[
    tuple[tuple[str, FileFingerprint], ...], tuple[tuple[str, FileFingerprint | None], ...]
]:
    parent = os.path.dirname(database)
    membership = _directory_fingerprint(parent, limit=bounds.scanned_records, root=root)
    values: list[tuple[str, FileFingerprint | None]] = []
    for label, path in _family_paths(database).items():
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            values.append((label, None))
            continue
        except OSError as error:
            raise DiagnosticError.source_busy(family=(os.path.basename(path),)) from error
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise DiagnosticError.unsafe_path()
        require_regular_no_symlinks(path, root)
        observation = stable_read_bytes(
            path,
            root=root,
            max_bytes=bounds.sqlite_snapshot_bytes,
            attempts=1,
            membership_limit=bounds.scanned_records,
        )
        values.append((label, observation.fingerprint))
    return membership, tuple(values)


def _family_names(database: str) -> tuple[str, ...]:
    return tuple(os.path.basename(path) for path in _family_paths(database).values())


def snapshot_sqlite_family(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    bounds: Bounds = DEFAULT_BOUNDS,
    attempts: int | None = None,
    hook: AttemptHook | None = None,
    provider: str | None = None,
) -> SQLiteSnapshot:
    """Copy a coherent SQLite main/WAL family and monitor, but never copy, SHM."""

    maximum_attempts = attempts if attempts is not None else bounds.snapshot_attempts
    if not 1 <= maximum_attempts <= bounds.snapshot_attempts:
        raise DiagnosticError.invalid()
    safe, base = require_regular_no_symlinks(database, root)
    family_names = _family_names(safe)
    for attempt in range(1, maximum_attempts + 1):
        before = _family_state(safe, base, bounds=bounds)
        state = dict(before[1])
        if state["journal"] is not None:
            raise DiagnosticError(
                "E_SQLITE_HOT_JOURNAL",
                provider=provider,
                attempts=attempt,
                family=(os.path.basename(safe + "-journal"),),
            )
        if hook:
            hook("before-copy", attempt, safe)
        temporary = tempfile.TemporaryDirectory(prefix="portable-resume-sqlite-")
        os.chmod(temporary.name, 0o700)
        try:
            total = 0
            for label in ("main", "wal"):
                source = _family_paths(safe)[label]
                if state[label] is None:
                    continue
                remaining = bounds.sqlite_snapshot_bytes - total
                if remaining < 0:
                    raise DiagnosticError.limit_exceeded()
                read = stable_read_bytes(
                    source,
                    root=base,
                    # WAL may exceed a single transcript bound; use the SQLite family cap.
                    max_bytes=min(bounds.sqlite_snapshot_bytes, remaining),
                    attempts=1,
                    membership_limit=bounds.scanned_records,
                )
                if read.fingerprint != state[label]:
                    raise DiagnosticError.source_busy(
                        attempts=attempt,
                        family=(os.path.basename(source),),
                        provider=provider,
                    )
                total += len(read.data)
                if total > bounds.sqlite_snapshot_bytes:
                    raise DiagnosticError.limit_exceeded()
                destination = os.path.join(temporary.name, os.path.basename(source))
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    view = memoryview(read.data)
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if hook:
                hook("after-copy", attempt, safe)
            after = _family_state(safe, base, bounds=bounds)
            if hook:
                hook("after-verify", attempt, safe)
            final = _family_state(safe, base, bounds=bounds)
            if before == after == final:
                private_database = os.path.join(temporary.name, os.path.basename(safe))
                return SQLiteSnapshot(
                    directory=temporary.name,
                    database=private_database,
                    source_name=os.path.basename(safe),
                    attempts=attempt,
                    family=tuple(
                        os.path.basename(_family_paths(safe)[name])
                        for name, fingerprint in before[1]
                        if fingerprint is not None
                    ),
                    _temporary=temporary,
                )
        except DiagnosticError as error:
            temporary.cleanup()
            if error.code not in {"E_SOURCE_BUSY"}:
                raise
        except BaseException:
            temporary.cleanup()
            raise
        else:
            temporary.cleanup()
    raise DiagnosticError.source_busy(attempts=maximum_attempts, family=family_names, provider=provider)


@contextlib.contextmanager
def private_sqlite_connection(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    bounds: Bounds = DEFAULT_BOUNDS,
    attempts: int | None = None,
    hook: AttemptHook | None = None,
    provider: str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield query-only SQLite connected exclusively to a private stable copy."""

    snapshot = snapshot_sqlite_family(
        database,
        root=root,
        bounds=bounds,
        attempts=attempts,
        hook=hook,
        provider=provider,
    )
    try:
        connection = snapshot.connect()
        try:
            yield connection
        finally:
            connection.close()
    finally:
        snapshot.close()


@contextlib.contextmanager
def query_only_live_sqlite(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    provider: str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Read-only connection to the live DB without a private multi-hundred-MB copy.

    Used when the main DB exceeds ``sqlite_snapshot_bytes`` (e.g. OpenCode homes
    >1GiB). Still refuses rollback ``-journal`` hot files and enables
    ``query_only``. Concurrent WAL writers may cause ``E_SOURCE_BUSY``-class
    failures; callers treat those as degraded, not silent success.
    """
    from urllib.parse import quote

    safe, _base = require_regular_no_symlinks(database, root)
    if os.path.exists(f"{safe}-journal") or os.path.lexists(f"{safe}-journal"):
        raise DiagnosticError("E_SQLITE_HOT_JOURNAL", provider=provider)
    uri = f"file:{quote(safe)}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        value = connection.execute("PRAGMA query_only").fetchone()
        if value is None or value[0] != 1:
            raise DiagnosticError("E_INVARIANT", provider=provider)
        yield connection
    finally:
        connection.close()


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Test/audit helper; it never participates in source discovery."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
