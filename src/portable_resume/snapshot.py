"""No-follow stable file reads and source-isolated SQLite-family snapshots."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import stat
import struct
import tempfile
from dataclasses import dataclass
from typing import BinaryIO, Callable, Iterator
from urllib.parse import quote

from .bounds import DEFAULT_BOUNDS, Bounds, ReadBudget
from .diagnostics import DiagnosticError
from .paths import is_within, require_regular_no_symlinks

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


@dataclass(frozen=True, slots=True)
class ScannedLine:
    ordinal: int
    text: str
    byte_offset: int
    terminated: bool
    utf8_valid: bool = True
    crlf: bool = False


@dataclass(frozen=True, slots=True)
class StableWindows:
    """Repeatedly verified metadata windows from one no-follow descriptor."""

    head: bytes
    tail: bytes
    tail_offset: int
    fingerprint: FileFingerprint
    window_sha256: str
    attempts: int


@dataclass(slots=True)
class FileSnapshot:
    """Private stable copy of one regular source file."""

    directory: str
    path: str
    source_name: str
    fingerprint: FileFingerprint
    attempts: int
    _temporary: tempfile.TemporaryDirectory[str]

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> "FileSnapshot":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


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
        # Windows absolute paths need forward slashes and a leading slash so
        # sqlite3 URI mode resolves ``file:///C:/...`` correctly (#206).
        abs_path = os.path.abspath(self.database)
        if os.name == "nt":
            abs_path = abs_path.replace("\\", "/")
            if len(abs_path) >= 2 and abs_path[1] == ":" and not abs_path.startswith("/"):
                abs_path = "/" + abs_path
            encoded = quote(abs_path, safe="/:")
        else:
            encoded = quote(abs_path, safe="/")
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


def _dirfd_io_supported() -> bool:
    """True when descriptor-relative open/stat are available (POSIX)."""

    return (
        os.name != "nt"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "open")
    )


def _open_directory_beneath(directory: str, root: str) -> int:
    relative = os.path.relpath(os.path.abspath(directory), root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
        raise DiagnosticError.unsafe_path()
    if not _dirfd_io_supported():
        # Pathname open after containment: Windows has no dir_fd walk.
        path = os.path.abspath(directory)
        if not is_within(path, root):
            raise DiagnosticError.unsafe_path()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            return os.open(path, flags)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error
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
    """Fingerprint parent directory membership (discovery / SQLite family only).

    Exact file reads must not use this for stability: a large sibling count must
    not make a single safe target unreadable (#16). Prefer
    ``_target_entry_fingerprint`` for descriptor-relative exact reads.
    """

    descriptor: int | None = None
    try:
        if root is not None and _dirfd_io_supported():
            descriptor = _open_directory_beneath(directory, root)
            target: str | int = descriptor
        else:
            # Windows / no-dir_fd: scandir by path after lexical containment.
            if root is not None:
                abs_dir = os.path.abspath(directory)
                if not is_within(abs_dir, root):
                    raise DiagnosticError.unsafe_path()
                target = abs_dir
            else:
                target = directory
        output: list[tuple[str, FileFingerprint]] = []
        with os.scandir(target) as entries:
            for entry in entries:
                if len(output) >= limit:
                    raise DiagnosticError.limit_exceeded()
                name = entry.name
                if "/" in name or "\x00" in name:
                    raise DiagnosticError.unsafe_path()
                current = entry.stat(follow_symlinks=False)
                output.append((name, _fingerprint(current)))
        output.sort(key=lambda item: item[0])
        return tuple(output)
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError.source_busy() from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _target_entry_fingerprint(
    parent: str,
    basename: str,
    *,
    root: str,
) -> FileFingerprint:
    """Identity of one basename under ``parent`` via dir_fd, ignoring siblings.

    Detects target rename/replace (device/inode/type/size/mtime drift) without
    enumerating unrelated parent directory entries (#16). On platforms without
    dir_fd, uses lstat after ``require_regular_no_symlinks``.
    """

    if not basename or basename in {".", ".."} or "/" in basename or "\x00" in basename:
        raise DiagnosticError.unsafe_path()
    if not _dirfd_io_supported():
        candidate = os.path.join(parent, basename)
        safe, _ = require_regular_no_symlinks(candidate, root)
        try:
            current = os.lstat(safe)
        except OSError as error:
            raise DiagnosticError.source_busy() from error
        if not stat.S_ISREG(current.st_mode):
            raise DiagnosticError.unsafe_path()
        return _fingerprint(current)
    parent_fd = _open_directory_beneath(parent, root)
    try:
        try:
            current = os.stat(basename, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise DiagnosticError.source_busy() from error
        if not stat.S_ISREG(current.st_mode):
            raise DiagnosticError.unsafe_path()
        return _fingerprint(current)
    finally:
        os.close(parent_fd)


def _entry_identity_matches(entry: FileFingerprint, open_stat: os.stat_result) -> bool:
    """True when basename entry identity matches an open descriptor's fstat."""

    opened = _fingerprint(open_stat)
    return (
        entry.device == opened.device
        and entry.inode == opened.inode
        and entry.mode == opened.mode
        and entry.size == opened.size
        and entry.mtime_ns == opened.mtime_ns
    )


def _open_no_follow(path: str, root: str) -> int:
    """Open a regular file by walking every component descriptor-relative.

    On Windows (no dir_fd / O_NOFOLLOW), open the path after
    ``require_regular_no_symlinks`` rejects symlink components.
    """

    safe, _ = require_regular_no_symlinks(path, root)
    if not _dirfd_io_supported():
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(safe, flags)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode):
            os.close(descriptor)
            raise DiagnosticError.unsafe_path()
        return descriptor
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


def _stable_read_bytes_impl(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    max_bytes: int = DEFAULT_BOUNDS.record_bytes,
    attempts: int = DEFAULT_BOUNDS.snapshot_attempts,
    membership_limit: int = DEFAULT_BOUNDS.scanned_records,
    budget: ReadBudget | None = None,
    hook: AttemptHook | None = None,
) -> StableRead:
    """POSIX/descriptor-relative stable read implementation (used by platform_fs.posix)."""

    if max_bytes < 0 or max_bytes > DEFAULT_BOUNDS.sqlite_snapshot_bytes or not 1 <= attempts <= DEFAULT_BOUNDS.snapshot_attempts:
        raise DiagnosticError.invalid()
    safe, base = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    # membership_limit retained for API compatibility; exact reads no longer
    # enumerate parent siblings (issue #16). Discovery still uses scanned_records.
    _ = membership_limit
    for attempt in range(1, attempts + 1):
        before_entry = _target_entry_fingerprint(parent, basename, root=base)
        descriptor = _open_no_follow(safe, base)
        try:
            before_stat = os.fstat(descriptor)
            if not _entry_identity_matches(before_entry, before_stat):
                continue
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
            verified_hash, verified_size = _hash_descriptor(
                descriptor,
                maximum=max_bytes,
            )
            verified = _fingerprint(os.fstat(descriptor), verified_hash)
            if hook:
                hook("after-verify-read", attempt, safe)
            # Re-pin basename through parent between verify hashes so rename/
            # replace races fail closed without scanning sibling entries.
            middle_entry = _target_entry_fingerprint(parent, basename, root=base)
            final_hash, final_size = _hash_descriptor(
                descriptor,
                maximum=max_bytes,
            )
            final_stat = os.fstat(descriptor)
            final = _fingerprint(final_stat, final_hash)
        finally:
            os.close(descriptor)
        after_entry = _target_entry_fingerprint(parent, basename, root=base)
        if (
            observed == verified == final
            and before_entry == middle_entry == after_entry
            and _entry_identity_matches(before_entry, before_stat)
            and _entry_identity_matches(after_entry, final_stat)
            and len(data) == verified_size == final_size == before.size
        ):
            if budget is not None:
                # Bytes only: adapters charge consume_records() per logical row/line.
                budget.consume_bytes(len(data))
            return StableRead(data=data, fingerprint=observed, attempts=attempt)
    family = (os.path.basename(safe),)
    raise DiagnosticError.source_busy(attempts=attempts, family=family)


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
    """Read stable bytes via the platform filesystem backend (#205).

    Call sites keep this public name; POSIX and Windows implementations live
    behind ``get_filesystem_backend().read_regular_stable``.
    """

    from .platform_fs import get_filesystem_backend

    return get_filesystem_backend().read_regular_stable(
        path,
        root=root,
        max_bytes=max_bytes,
        attempts=attempts,
        membership_limit=membership_limit,
        budget=budget,
        hook=hook,
    )


# Length-prefixed spool records for verified-attempt line replay (#10).
# Layout per line: >I (ordinal) >Q (byte_offset) >B (flags) >I (text_len) + utf-8
_SPOOL_HEADER = struct.Struct(">IQBI")
_SPOOL_FLAG_TERMINATED = 0x01
_SPOOL_FLAG_UTF8_VALID = 0x02
# Spill to disk above this so multi-MiB transcripts are not one big list[ScannedLine].
_SPOOL_RAM_CAP = 256 * 1024


def _spool_write_line(spool: BinaryIO, line: ScannedLine) -> None:
    text_b = line.text.encode("utf-8")
    flags = 0
    if line.terminated:
        flags |= _SPOOL_FLAG_TERMINATED
    if line.utf8_valid:
        flags |= _SPOOL_FLAG_UTF8_VALID
    spool.write(
        _SPOOL_HEADER.pack(line.ordinal, line.byte_offset, flags, len(text_b))
    )
    spool.write(text_b)


def _spool_iter_lines(spool: BinaryIO) -> Iterator[ScannedLine]:
    header_size = _SPOOL_HEADER.size
    while True:
        header = spool.read(header_size)
        if not header:
            return
        if len(header) != header_size:
            raise DiagnosticError("E_INVARIANT")
        ordinal, byte_offset, flags, text_len = _SPOOL_HEADER.unpack(header)
        text_b = spool.read(text_len)
        if len(text_b) != text_len:
            raise DiagnosticError("E_INVARIANT")
        try:
            text = text_b.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DiagnosticError("E_INVARIANT") from error
        yield ScannedLine(
            ordinal=ordinal,
            text=text,
            byte_offset=byte_offset,
            terminated=bool(flags & _SPOOL_FLAG_TERMINATED),
            utf8_valid=bool(flags & _SPOOL_FLAG_UTF8_VALID),
        )


def _collect_scanned_lines(
    descriptor: int,
    *,
    max_line_bytes: int,
    budget: ReadBudget | None,
    charge_transcript: bool,
    spool: BinaryIO | None = None,
) -> tuple[list[ScannedLine] | None, int, int, str]:
    """Stream lines from an open descriptor.

    Newline-terminated records set ``terminated=True``. A final buffer without a
    trailing newline is emitted with ``terminated=False`` when within bounds.

    When ``spool`` is provided, lines are written there (collect-free path for
    ``stable_scan_lines``) and the returned list is ``None``. Otherwise lines are
    collected into a list (unit-test / compatibility path).
    """

    buffer = bytearray()
    absolute_offset = 0
    collected: list[ScannedLine] | None = None if spool is not None else []
    line_ordinal = 0
    pending_bytes = 0
    pending_records = 0
    chunk_size = 64 * 1024
    digest = hashlib.sha256()

    def check_byte_budget(amount: int) -> None:
        if budget is None:
            return
        maximum = min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes)
        if budget.bytes_read + pending_bytes + amount > maximum:
            raise DiagnosticError.limit_exceeded()

    def check_record_budget() -> None:
        if budget is None:
            return
        if charge_transcript:
            maximum = min(
                budget.limits.transcript_records,
                DEFAULT_BOUNDS.transcript_records,
            )
            current = budget.transcript_records_read
        else:
            maximum = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
            current = budget.records
        if current + pending_records + 1 > maximum:
            raise DiagnosticError.limit_exceeded()

    def reject_oversize_unterminated_line() -> None:
        effective_len = len(buffer)
        if effective_len and buffer[-1] == 0x0d:
            effective_len -= 1
        if effective_len > max_line_bytes:
            raise DiagnosticError.limit_exceeded()

    def emit(line: ScannedLine) -> None:
        nonlocal line_ordinal
        if spool is not None:
            _spool_write_line(spool, line)
        else:
            assert collected is not None
            collected.append(line)
        line_ordinal += 1

    def drain_complete_lines() -> None:
        nonlocal absolute_offset, pending_records
        while True:
            newline_index = buffer.find(b"\n")
            if newline_index < 0:
                reject_oversize_unterminated_line()
                return
            line_bytes = bytes(buffer[: newline_index + 1])
            del buffer[: newline_index + 1]
            # Exclude LF and optional CR from the content-length budget so CRLF
            # and LF records with the same decoded text share the same ceiling.
            payload = line_bytes[:-1]
            if payload.endswith(b"\r"):
                payload = payload[:-1]
            if len(payload) > max_line_bytes:
                raise DiagnosticError.limit_exceeded()
            check_record_budget()
            pending_records += 1
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise DiagnosticError("E_CORRUPT_RECORD") from error
            emit(
                ScannedLine(
                    ordinal=line_ordinal,
                    text=text,
                    byte_offset=absolute_offset,
                    terminated=True,
                )
            )
            absolute_offset += len(line_bytes)

    while True:
        chunk = os.read(descriptor, chunk_size)
        if not chunk:
            break
        check_byte_budget(len(chunk))
        pending_bytes += len(chunk)
        digest.update(chunk)
        buffer.extend(chunk)
        drain_complete_lines()

    reject_oversize_unterminated_line()
    # JSONL often omits a trailing newline; treat remaining buffer as a final
    # line. An incomplete terminal UTF-8 sequence is live-writer tail state,
    # not interior corruption. Preserve the line boundary and let adapters
    # downgrade the unterminated record to W_PARTIAL_TAIL.
    if buffer:
        check_record_budget()
        pending_records += 1
        utf8_valid = True
        try:
            text = bytes(buffer).decode("utf-8").removesuffix("\r")
        except UnicodeDecodeError as error:
            if error.reason != "unexpected end of data" or error.end != len(buffer):
                raise DiagnosticError("E_CORRUPT_RECORD") from error
            text = bytes(buffer).decode("utf-8", errors="replace").removesuffix("\r")
            utf8_valid = False
        emit(
            ScannedLine(
                ordinal=line_ordinal,
                text=text,
                byte_offset=absolute_offset,
                terminated=False,
                utf8_valid=utf8_valid,
            )
        )
    return collected, pending_bytes, pending_records, digest.hexdigest()


def stable_scan_lines(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    budget: ReadBudget | None = None,
    max_line_bytes: int | None = None,
    charge_transcript: bool = False,
    hook: AttemptHook | None = None,
) -> Iterator[ScannedLine]:
    """Yield UTF-8 lines under no-follow / containment / budget rules.

    Uses the same root containment and symlink rejection as stable_read_bytes.
    Reads stream in chunks. A final unterminated buffer (common JSONL without a
    trailing newline) is emitted as one last line when within max_line_bytes.
    Caller-lowered ``Bounds`` for record_bytes, snapshot_attempts, and
    scanned_records membership are honored and clamped to DEFAULT_BOUNDS.

    Attempt-local lines are spooled (RAM up to ``_SPOOL_RAM_CAP``, then disk)
    and only replayed after the attempt fully verifies — never mid-attempt, and
    without retaining a full ``list[ScannedLine]`` (#10 collect-free residual).
    """

    # Always bound memory: a missing caller budget still uses DEFAULT_BOUNDS.
    effective_budget = budget if budget is not None else ReadBudget()
    budget_line_cap = min(
        effective_budget.limits.record_bytes,
        DEFAULT_BOUNDS.record_bytes,
    )
    if max_line_bytes is None:
        line_limit = budget_line_cap
    else:
        if max_line_bytes < 0:
            raise DiagnosticError.invalid()
        line_limit = min(max_line_bytes, budget_line_cap)
    max_file_bytes = min(
        DEFAULT_BOUNDS.source_read_bytes,
        effective_budget.limits.source_read_bytes,
    )
    safe, base = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    attempts = min(
        effective_budget.limits.snapshot_attempts,
        DEFAULT_BOUNDS.snapshot_attempts,
    )
    if attempts < 1:
        raise DiagnosticError.invalid()
    for attempt in range(1, attempts + 1):
        before_entry = _target_entry_fingerprint(parent, basename, root=base)
        descriptor = _open_no_follow(safe, base)
        spool: tempfile.SpooledTemporaryFile | None = None
        verified_spool: tempfile.SpooledTemporaryFile | None = None
        pending_bytes = 0
        pending_records = 0
        try:
            before_stat = os.fstat(descriptor)
            if not _entry_identity_matches(before_entry, before_stat):
                continue
            if before_stat.st_size > max_file_bytes:
                raise DiagnosticError.limit_exceeded()
            if hook:
                hook("before-read", attempt, safe)
            spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_RAM_CAP, mode="w+b")
            _list, pending_bytes, pending_records, content_hash = _collect_scanned_lines(
                descriptor,
                max_line_bytes=line_limit,
                budget=effective_budget,
                charge_transcript=charge_transcript,
                spool=spool,
            )
            observed = _fingerprint(before_stat, content_hash)
            if hook:
                hook("after-read", attempt, safe)
            verified_hash, verified_size = _hash_descriptor(
                descriptor,
                maximum=max_file_bytes,
            )
            verified = _fingerprint(os.fstat(descriptor), verified_hash)
            if hook:
                hook("after-verify-read", attempt, safe)
            middle_entry = _target_entry_fingerprint(parent, basename, root=base)
            final_hash, final_size = _hash_descriptor(
                descriptor,
                maximum=max_file_bytes,
            )
            final_stat = os.fstat(descriptor)
            final = _fingerprint(final_stat, final_hash)
            after_entry = _target_entry_fingerprint(parent, basename, root=base)
            if not (
                observed == verified == final
                and before_entry == middle_entry == after_entry
                and _entry_identity_matches(before_entry, before_stat)
                and _entry_identity_matches(after_entry, final_stat)
                and pending_bytes == verified_size == final_size == before_stat.st_size
            ):
                continue
            # Hand off spool for post-close replay so the source fd is never
            # held open while yielding to callers.
            verified_spool = spool
            spool = None
        finally:
            os.close(descriptor)
            if spool is not None:
                spool.close()
        if verified_spool is not None:
            effective_budget.consume_bytes(pending_bytes)
            if charge_transcript:
                effective_budget.consume_transcript_records(pending_records)
            else:
                effective_budget.consume_records(pending_records)
            try:
                verified_spool.seek(0)
                yield from _spool_iter_lines(verified_spool)
            finally:
                verified_spool.close()
            return
    family = (os.path.basename(safe),)
    raise DiagnosticError.source_busy(attempts=attempts, family=family)


def _spool_window_bytes(
    descriptor: int,
    spool: BinaryIO,
    *,
    maximum: int,
) -> tuple[str, int]:
    """Copy ``[current_pos, EOF)`` raw bytes into a spool, hashing as we go.

    The tail scanner uses this instead of the per-line spool so a bounded
    window cannot be amplified by per-record headers (#258 re-review P1).
    """

    digest = hashlib.sha256()
    total = 0
    while True:
        block = os.read(descriptor, 64 * 1024)
        if not block:
            break
        total += len(block)
        if total > maximum:
            raise DiagnosticError.limit_exceeded()
        digest.update(block)
        spool.write(block)
    return digest.hexdigest(), total


def _count_window_lines(
    spool: BinaryIO,
    *,
    max_line_bytes: int,
    discard_first: bool,
) -> int:
    """Count lines in a raw window spool without building ScannedLine objects.

    Applies the incremental ``record_bytes`` limit and the optional
    first-partial-line discard, but defers UTF-8 validation to the decode pass
    (which only visits the admitted suffix). Used to locate the trim boundary
    without materializing the whole window (codex re-review P1-3).
    """

    spool.seek(0)
    buffer = bytearray()
    first = True
    total = 0
    while True:
        chunk = spool.read(64 * 1024)
        if not chunk:
            break
        buffer.extend(chunk)
        while True:
            newline_index = buffer.find(b"\n")
            if newline_index < 0:
                # Unterminated line: fail early if it already exceeds the limit.
                effective = len(buffer) - (1 if buffer[-1:] == b"\r" else 0)
                if effective > max_line_bytes:
                    raise DiagnosticError.limit_exceeded()
                break
            line_bytes = bytes(buffer[: newline_index + 1])
            del buffer[: newline_index + 1]
            payload = line_bytes[:-1]
            if payload.endswith(b"\r"):
                payload = payload[:-1]
            if len(payload) > max_line_bytes:
                raise DiagnosticError.limit_exceeded()
            if first and discard_first:
                first = False
                continue
            first = False
            # Match stable_scan_lines: record_bytes limits decoded content, not
            # the LF or optional CRLF terminator. This still validates skipped
            # complete records before suffix admission.
            total += 1
    if buffer:
        if not (first and discard_first):
            total += 1
    return total


def _parse_window_lines(
    spool: BinaryIO,
    *,
    max_line_bytes: int,
    discard_first: bool,
    skip: int = 0,
) -> Iterator[ScannedLine]:
    """Split a raw window spool into ScannedLine records (replay pass).

    Applies ``record_bytes`` per line (``E_LIMIT_EXCEEDED``), UTF-8 validation
    (``E_CORRUPT_RECORD``), CRLF detection (``crlf`` flag), and the optional
    first-partial-line discard. Byte offsets are relative to the window start.

    ``skip`` drops the first N complete lines without decoding them, locating
    the admitted suffix without a second full decode pass (re-review P1-3).
    """

    spool.seek(0)
    buffer = bytearray()
    absolute_offset = 0
    ordinal = 0
    first = True
    remaining_skip = skip
    while True:
        chunk = spool.read(64 * 1024)
        if not chunk:
            break
        buffer.extend(chunk)
        while True:
            newline_index = buffer.find(b"\n")
            if newline_index < 0:
                # Unterminated line: fail early if it already exceeds the limit
                # (a trailing CR does not count toward the content ceiling).
                effective = len(buffer) - (1 if buffer[-1:] == b"\r" else 0)
                if effective > max_line_bytes:
                    raise DiagnosticError.limit_exceeded()
                break
            line_bytes = bytes(buffer[: newline_index + 1])
            del buffer[: newline_index + 1]
            payload = line_bytes[:-1]
            crlf = payload.endswith(b"\r")
            if crlf:
                payload = payload[:-1]
            if len(payload) > max_line_bytes:
                raise DiagnosticError.limit_exceeded()
            if first and discard_first:
                first = False
                absolute_offset += len(line_bytes)
                continue
            first = False
            if remaining_skip > 0:
                remaining_skip -= 1
                absolute_offset += len(line_bytes)
                continue
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise DiagnosticError("E_CORRUPT_RECORD") from error
            yield ScannedLine(
                ordinal=ordinal,
                text=text,
                byte_offset=absolute_offset,
                terminated=True,
                crlf=crlf,
            )
            ordinal += 1
            absolute_offset += len(line_bytes)
    if buffer:
        if first and discard_first or remaining_skip > 0:
            return
        payload = bytes(buffer)
        bare_cr = payload.endswith(b"\r")
        if bare_cr:
            payload = payload[:-1]
        if len(payload) > max_line_bytes:
            raise DiagnosticError.limit_exceeded()
        utf8_valid = True
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            if error.reason != "unexpected end of data" or error.end != len(buffer):
                raise DiagnosticError("E_CORRUPT_RECORD") from error
            text = payload.decode("utf-8", errors="replace")
            utf8_valid = False
        yield ScannedLine(
            ordinal=ordinal,
            text=text,
            byte_offset=absolute_offset,
            # Bare trailing CR terminates (readline parity) but is not a CRLF
            # pair: the mirror's reconstructed LF accounts for that CR.
            terminated=bare_cr,
            utf8_valid=utf8_valid,
            crlf=False,
        )


def stable_scan_tail_lines(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    budget: ReadBudget | None = None,
    max_line_bytes: int | None = None,
    charge_transcript: bool = False,
    stable_head_bytes: int = 0,
    on_stable_head: Callable[[bytes, bool], None] | None = None,
    hook: AttemptHook | None = None,
) -> Iterator[ScannedLine]:
    """Yield UTF-8 lines from a stable end-anchored window (#258).

    Same no-follow / containment / attempt-verification rules as
    ``stable_scan_lines``, but when the file exceeds the remaining
    ``source_read_bytes`` budget the scanner admits only the final
    ``remaining`` bytes (``tail_start = st_size - remaining``) instead of
    hard-failing. The first line is discarded when the window begins
    mid-record. After verification the admitted line count is trimmed to the
    remaining ``transcript_records`` (or ``scanned_records`` when
    ``charge_transcript`` is false), charging only the admitted records and
    the unique window bytes. The whole file is never hashed or buffered.

    ``stable_head_bytes`` optionally verifies a bounded head sample in the
    same descriptor generation and supplies it to ``on_stable_head`` before
    suffix trimming. Overlap with the tail is charged only once.
    """

    effective_budget = budget if budget is not None else ReadBudget()
    budget_line_cap = min(
        effective_budget.limits.record_bytes,
        DEFAULT_BOUNDS.record_bytes,
    )
    if max_line_bytes is None:
        line_limit = budget_line_cap
    else:
        if max_line_bytes < 0:
            raise DiagnosticError.invalid()
        line_limit = min(max_line_bytes, budget_line_cap)
    if stable_head_bytes < 0 or stable_head_bytes > 4 * 1024 * 1024:
        raise DiagnosticError.invalid()
    max_file_bytes = min(
        DEFAULT_BOUNDS.source_read_bytes,
        effective_budget.limits.source_read_bytes,
    )
    safe, base = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    attempts = min(
        effective_budget.limits.snapshot_attempts,
        DEFAULT_BOUNDS.snapshot_attempts,
    )
    if attempts < 1:
        raise DiagnosticError.invalid()
    for attempt in range(1, attempts + 1):
        before_entry = _target_entry_fingerprint(parent, basename, root=base)
        descriptor = _open_no_follow(safe, base)
        spool: tempfile.SpooledTemporaryFile | None = None
        verified_spool: tempfile.SpooledTemporaryFile | None = None
        pending_bytes = 0
        tail_start = 0
        starts_mid_line = False
        stable_head: bytes | None = None
        try:
            before_stat = os.fstat(descriptor)
            if not _entry_identity_matches(before_entry, before_stat):
                continue
            remaining = max(0, max_file_bytes - effective_budget.bytes_read)
            head_size = min(before_stat.st_size, stable_head_bytes)
            if before_stat.st_size <= remaining:
                tail_start = 0
            else:
                tail_capacity = max(0, remaining - head_size)
                tail_start = max(head_size, before_stat.st_size - tail_capacity)
            starts_mid_line = False
            boundary_probe: bytes | None = None
            if tail_start > 0:
                os.lseek(descriptor, tail_start - 1, os.SEEK_SET)
                boundary_probe = os.read(descriptor, 1)
                starts_mid_line = boundary_probe != b"\n"
            if hook:
                hook("before-read", attempt, safe)
            os.lseek(descriptor, 0, os.SEEK_SET)
            first_head = _read_exact_descriptor(
                descriptor,
                min(before_stat.st_size, stable_head_bytes),
            )
            os.lseek(descriptor, tail_start, os.SEEK_SET)
            spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_RAM_CAP, mode="w+b")
            try:
                content_hash, pending_bytes = _spool_window_bytes(
                    descriptor,
                    spool,
                    maximum=max_file_bytes,
                )
            except DiagnosticError as error:
                # File grew past the admitted window mid-read: unstable, retry.
                if (
                    error.code == "E_LIMIT_EXCEEDED"
                    and os.fstat(descriptor).st_size > before_stat.st_size
                ):
                    continue
                raise
            observed = _fingerprint(before_stat, content_hash)
            if hook:
                hook("after-read", attempt, safe)
            os.lseek(descriptor, 0, os.SEEK_SET)
            second_head = _read_exact_descriptor(descriptor, len(first_head))
            if tail_start > 0:
                os.lseek(descriptor, tail_start - 1, os.SEEK_SET)
                probe_verify = os.read(descriptor, 1)
            else:
                probe_verify = None
            try:
                verified_hash, verified_size = _hash_descriptor_window(
                    descriptor,
                    start=tail_start,
                    maximum=max_file_bytes,
                )
            except DiagnosticError as error:
                # Verification-time growth: retry, not hard-fail.
                if (
                    error.code == "E_LIMIT_EXCEEDED"
                    and os.fstat(descriptor).st_size > before_stat.st_size
                ):
                    continue
                raise
            verified = _fingerprint(os.fstat(descriptor), verified_hash)
            if hook:
                hook("after-verify-read", attempt, safe)
            middle_entry = _target_entry_fingerprint(parent, basename, root=base)
            os.lseek(descriptor, 0, os.SEEK_SET)
            third_head = _read_exact_descriptor(descriptor, len(first_head))
            if tail_start > 0:
                os.lseek(descriptor, tail_start - 1, os.SEEK_SET)
                probe_final = os.read(descriptor, 1)
            else:
                probe_final = None
            try:
                final_hash, final_size = _hash_descriptor_window(
                    descriptor,
                    start=tail_start,
                    maximum=max_file_bytes,
                )
            except DiagnosticError as error:
                # Verification-time growth: retry.
                if (
                    error.code == "E_LIMIT_EXCEEDED"
                    and os.fstat(descriptor).st_size > before_stat.st_size
                ):
                    continue
                raise
            final_stat = os.fstat(descriptor)
            final = _fingerprint(final_stat, final_hash)
            after_entry = _target_entry_fingerprint(parent, basename, root=base)
            if not (
                observed == verified == final
                and before_entry == middle_entry == after_entry
                and _entry_identity_matches(before_entry, before_stat)
                and _entry_identity_matches(after_entry, final_stat)
                and pending_bytes == verified_size == final_size
                == before_stat.st_size - tail_start
                and boundary_probe == probe_verify == probe_final
                and first_head == second_head == third_head
            ):
                continue
            # Hand off spool for post-close replay so the source fd is never
            # held open while yielding to callers.
            verified_spool = spool
            spool = None
            stable_head = first_head
        finally:
            os.close(descriptor)
            if spool is not None:
                spool.close()
        if verified_spool is not None:
            try:
                effective_budget.consume_bytes(
                    pending_bytes + min(len(stable_head or b""), tail_start)
                )
                if on_stable_head is not None:
                    on_stable_head(
                        stable_head or b"",
                        before_stat.st_size <= len(stable_head or b""),
                    )
                total = _count_window_lines(
                    verified_spool,
                    max_line_bytes=line_limit,
                    discard_first=starts_mid_line,
                )
                if charge_transcript:
                    record_max = min(
                        effective_budget.limits.transcript_records,
                        DEFAULT_BOUNDS.transcript_records,
                    )
                    remaining_records = record_max - effective_budget.transcript_records_read
                else:
                    record_max = min(
                        effective_budget.limits.scanned_records,
                        DEFAULT_BOUNDS.scanned_records,
                    )
                    remaining_records = record_max - effective_budget.records
                skip = max(0, total - remaining_records)
                admitted = total - skip
                if charge_transcript:
                    effective_budget.consume_transcript_records(admitted)
                else:
                    effective_budget.consume_records(admitted)
                for line in _parse_window_lines(
                    verified_spool,
                    max_line_bytes=line_limit,
                    discard_first=starts_mid_line,
                    skip=skip,
                ):
                    yield line
            finally:
                verified_spool.close()
            return
    family = (os.path.basename(safe),)
    raise DiagnosticError.source_busy(attempts=attempts, family=family)


def stable_read_windows(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    head_bytes: int = 4 * 1024 * 1024,
    tail_bytes: int = 64 * 1024,
    max_bytes: int = DEFAULT_BOUNDS.source_read_bytes,
    attempts: int = DEFAULT_BOUNDS.snapshot_attempts,
    membership_limit: int = DEFAULT_BOUNDS.scanned_records,
    budget: ReadBudget | None = None,
    hook: AttemptHook | None = None,
    require_size_within_max: bool = True,
) -> StableWindows:
    """Read bounded head/tail metadata without copying or loading a transcript.

    When ``require_size_within_max`` is true (default), files larger than
    ``max_bytes`` fail closed. Codex discovery may set it false to admit only
    the head/tail of multi-GB rollouts without changing other adapters' contracts.
    """

    if (
        head_bytes < 0
        or head_bytes > 4 * 1024 * 1024
        or tail_bytes < 0
        or tail_bytes > 64 * 1024
        or max_bytes < 0
        or max_bytes > DEFAULT_BOUNDS.source_read_bytes
        or not 1 <= attempts <= DEFAULT_BOUNDS.snapshot_attempts
        or not 0 <= membership_limit <= DEFAULT_BOUNDS.scanned_records
    ):
        raise DiagnosticError.invalid()
    safe, base = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    _ = membership_limit  # API compat; exact windows no longer enumerate siblings (#16)
    for attempt in range(1, attempts + 1):
        try:
            before_entry = _target_entry_fingerprint(parent, basename, root=base)
            descriptor = _open_no_follow(safe, base)
            try:
                before_stat = os.fstat(descriptor)
                if not _entry_identity_matches(before_entry, before_stat):
                    continue
                if require_size_within_max and before_stat.st_size > max_bytes:
                    raise DiagnosticError.limit_exceeded()
                if hook:
                    hook("before-read", attempt, safe)
                first = _read_descriptor_windows(
                    descriptor,
                    size=before_stat.st_size,
                    head_bytes=head_bytes,
                    tail_bytes=tail_bytes,
                )
                if hook:
                    hook("after-read", attempt, safe)
                second = _read_descriptor_windows(
                    descriptor,
                    size=before_stat.st_size,
                    head_bytes=head_bytes,
                    tail_bytes=tail_bytes,
                )
                second_stat = os.fstat(descriptor)
                if hook:
                    hook("after-verify-read", attempt, safe)
                middle_entry = _target_entry_fingerprint(parent, basename, root=base)
                third = _read_descriptor_windows(
                    descriptor,
                    size=before_stat.st_size,
                    head_bytes=head_bytes,
                    tail_bytes=tail_bytes,
                )
                final_stat = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            after_entry = _target_entry_fingerprint(parent, basename, root=base)
        except DiagnosticError as error:
            if error.code == "E_SOURCE_BUSY":
                continue
            raise
        window_hash = hashlib.sha256(first[0] + b"\0" + first[1]).hexdigest()
        observed = _fingerprint(before_stat)
        verified = _fingerprint(second_stat)
        final = _fingerprint(final_stat)
        if (
            observed == verified == final
            and first == second == third
            and before_entry == middle_entry == after_entry
            and _entry_identity_matches(before_entry, before_stat)
            and _entry_identity_matches(after_entry, final_stat)
        ):
            head, tail, tail_offset, unique_bytes = first
            if budget is not None:
                budget.consume_bytes(unique_bytes)
            return StableWindows(
                head=head,
                tail=tail,
                tail_offset=tail_offset,
                fingerprint=observed,
                window_sha256=window_hash,
                attempts=attempt,
            )
    raise DiagnosticError.source_busy(attempts=attempts, family=(os.path.basename(safe),))


def snapshot_regular_file(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    bounds: Bounds = DEFAULT_BOUNDS,
    attempts: int | None = None,
    membership_limit: int | None = None,
    budget: ReadBudget | None = None,
    hook: AttemptHook | None = None,
    provider: str | None = None,
) -> FileSnapshot:
    """Stream a stable regular file into a private 0700/0600 snapshot."""

    maximum_attempts = attempts if attempts is not None else bounds.snapshot_attempts
    member_limit = membership_limit if membership_limit is not None else bounds.scanned_records
    if (
        bounds.source_read_bytes < 0
        or bounds.source_read_bytes > DEFAULT_BOUNDS.source_read_bytes
        or bounds.snapshot_attempts < 1
        or bounds.snapshot_attempts > DEFAULT_BOUNDS.snapshot_attempts
        or bounds.scanned_records < 0
        or bounds.scanned_records > DEFAULT_BOUNDS.scanned_records
        or not 1 <= maximum_attempts <= bounds.snapshot_attempts
        or not 0 <= member_limit <= bounds.scanned_records
    ):
        raise DiagnosticError.invalid()
    safe, base = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    family = (basename,)
    _ = member_limit  # API compat; exact snapshot no longer enumerates siblings (#16)
    for attempt in range(1, maximum_attempts + 1):
        descriptor: int | None = None
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            before_entry = _target_entry_fingerprint(parent, basename, root=base)
            descriptor = _open_no_follow(safe, base)
            temporary = tempfile.TemporaryDirectory(prefix="portable-resume-file-")
            os.chmod(temporary.name, 0o700)
            destination = os.path.join(temporary.name, basename)
            before_stat = os.fstat(descriptor)
            if not _entry_identity_matches(before_entry, before_stat):
                raise DiagnosticError.source_busy(
                    attempts=attempt,
                    family=family,
                    provider=provider,
                )
            if before_stat.st_size > bounds.source_read_bytes:
                raise DiagnosticError.limit_exceeded()
            if hook:
                hook("before-copy", attempt, safe)
            try:
                copied_hash, copied_size = _copy_bounded_descriptor(
                    descriptor,
                    destination,
                    maximum=bounds.source_read_bytes,
                )
            except DiagnosticError as error:
                if error.code == "E_LIMIT_EXCEEDED":
                    raise DiagnosticError.source_busy(
                        attempts=attempt,
                        family=family,
                        provider=provider,
                    ) from error
                raise
            observed = _fingerprint(before_stat, copied_hash)
            if copied_size != before_stat.st_size:
                raise DiagnosticError.source_busy(
                    attempts=attempt,
                    family=family,
                    provider=provider,
                )
            if hook:
                hook("after-copy", attempt, safe)
            try:
                verified = _hash_descriptor(descriptor, maximum=bounds.source_read_bytes)
            except DiagnosticError as error:
                if error.code == "E_LIMIT_EXCEEDED":
                    raise DiagnosticError.source_busy(
                        attempts=attempt,
                        family=family,
                        provider=provider,
                    ) from error
                raise
            verified_fingerprint = _fingerprint(os.fstat(descriptor), verified[0])
            if hook:
                hook("after-verify-read", attempt, safe)
            middle_entry = _target_entry_fingerprint(parent, basename, root=base)
            try:
                final = _hash_descriptor(descriptor, maximum=bounds.source_read_bytes)
            except DiagnosticError as error:
                if error.code == "E_LIMIT_EXCEEDED":
                    raise DiagnosticError.source_busy(
                        attempts=attempt,
                        family=family,
                        provider=provider,
                    ) from error
                raise
            final_stat = os.fstat(descriptor)
            final_fingerprint = _fingerprint(final_stat, final[0])
            after_entry = _target_entry_fingerprint(parent, basename, root=base)
            if (
                observed == verified_fingerprint == final_fingerprint
                and copied_size == verified[1] == final[1] == before_stat.st_size
                and before_entry == middle_entry == after_entry
                and _entry_identity_matches(before_entry, before_stat)
                and _entry_identity_matches(after_entry, final_stat)
            ):
                if budget is not None:
                    budget.consume_bytes(copied_size)
                result = FileSnapshot(
                    directory=temporary.name,
                    path=destination,
                    source_name=os.path.basename(safe),
                    fingerprint=observed,
                    attempts=attempt,
                    _temporary=temporary,
                )
                temporary = None
                return result
        except DiagnosticError as error:
            if error.code != "E_SOURCE_BUSY":
                raise
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                temporary.cleanup()
    raise DiagnosticError.source_busy(attempts=maximum_attempts, family=family, provider=provider)


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


def _read_descriptor_windows(
    descriptor: int,
    *,
    size: int,
    head_bytes: int,
    tail_bytes: int,
) -> tuple[bytes, bytes, int, int]:
    head_size = min(size, head_bytes)
    tail_offset = max(0, size - tail_bytes)
    os.lseek(descriptor, 0, os.SEEK_SET)
    head = _read_exact_descriptor(descriptor, head_size)
    os.lseek(descriptor, tail_offset, os.SEEK_SET)
    tail = _read_exact_descriptor(descriptor, size - tail_offset)
    overlap = max(0, min(head_size, size) - tail_offset)
    if overlap:
        tail = tail[overlap:]
        tail_offset += overlap
    return head, tail, tail_offset, len(head) + len(tail)


def _read_exact_descriptor(descriptor: int, amount: int) -> bytes:
    chunks: list[bytes] = []
    remaining = amount
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining:
        raise DiagnosticError.source_busy()
    return b"".join(chunks)


def _copy_bounded_descriptor(descriptor: int, destination: str, *, maximum: int) -> tuple[str, int]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    write_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_BINARY", 0)
    )
    target = os.open(destination, write_flags, 0o600)
    try:
        while True:
            block = os.read(descriptor, 64 * 1024)
            if not block:
                break
            total += len(block)
            if total > maximum:
                raise DiagnosticError.limit_exceeded()
            digest.update(block)
            view = memoryview(block)
            while view:
                written = os.write(target, view)
                if written <= 0:
                    raise DiagnosticError.source_busy()
                view = view[written:]
        os.fsync(target)
    finally:
        os.close(target)
    return digest.hexdigest(), total


def _hash_descriptor(descriptor: int, *, maximum: int) -> tuple[str, int]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        block = os.read(descriptor, 64 * 1024)
        if not block:
            break
        total += len(block)
        if total > maximum:
            raise DiagnosticError.limit_exceeded()
        digest.update(block)
    return digest.hexdigest(), total


def _hash_descriptor_window(descriptor: int, *, start: int, maximum: int) -> tuple[str, int]:
    """SHA-256 of one bounded ``[start, EOF)`` window (no whole-file hash).

    Used by the end-anchored tail scanner (#258) so verification never reads
    bytes before ``start`` (a multi-GB file must not be hashed in full).
    """

    os.lseek(descriptor, start, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        block = os.read(descriptor, 64 * 1024)
        if not block:
            break
        total += len(block)
        if total > maximum:
            raise DiagnosticError.limit_exceeded()
        digest.update(block)
    return digest.hexdigest(), total


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
    """Capture SQLite family entry identities without enumerating all siblings.

    Tracks only main/wal/shm/journal basenames under the DB parent (#16).
    """

    parent = os.path.dirname(database)
    membership_rows: list[tuple[str, FileFingerprint]] = []
    values: list[tuple[str, FileFingerprint | None]] = []
    for label, path in _family_paths(database).items():
        basename = os.path.basename(path)
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            values.append((label, None))
            continue
        except OSError as error:
            raise DiagnosticError.source_busy(family=(basename,)) from error
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise DiagnosticError.unsafe_path()
        require_regular_no_symlinks(path, root)
        entry = _target_entry_fingerprint(parent, basename, root=root)
        membership_rows.append((basename, entry))
        observation = stable_read_bytes(
            path,
            root=root,
            max_bytes=bounds.sqlite_snapshot_bytes,
            attempts=1,
            membership_limit=bounds.scanned_records,
        )
        values.append((label, observation.fingerprint))
    membership_rows.sort(key=lambda item: item[0])
    return tuple(membership_rows), tuple(values)


def _family_names(database: str) -> tuple[str, ...]:
    return tuple(os.path.basename(path) for path in _family_paths(database).values())


def _snapshot_sqlite_family_impl(
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
    last_busy_family = family_names
    for attempt in range(1, maximum_attempts + 1):
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
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
                # O_BINARY required on Windows so private copies keep exact bytes
                # (same integrity rule as output_write staging).
                write_flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_BINARY", 0)
                )
                descriptor = os.open(destination, write_flags, 0o600)
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
            if temporary is not None:
                temporary.cleanup()
            if error.code not in {"E_SOURCE_BUSY"}:
                raise
            if error.family:
                last_busy_family = error.family
        except BaseException:
            if temporary is not None:
                temporary.cleanup()
            raise
        else:
            if temporary is not None:
                temporary.cleanup()
    raise DiagnosticError.source_busy(
        attempts=maximum_attempts,
        family=last_busy_family,
        provider=provider,
    )


def snapshot_sqlite_family(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    bounds: Bounds = DEFAULT_BOUNDS,
    attempts: int | None = None,
    hook: AttemptHook | None = None,
    provider: str | None = None,
) -> SQLiteSnapshot:
    """Snapshot SQLite main+journal family via the platform backend (#205).

    On POSIX the backend delegates to the descriptor-safe impl. Extra kwargs
    (attempts/hook/provider/custom Bounds) always use the full impl path.
    """

    from .platform_fs import get_filesystem_backend

    use_impl = (
        attempts is not None
        or hook is not None
        or provider is not None
        or bounds is not DEFAULT_BOUNDS
    )
    if use_impl:
        return _snapshot_sqlite_family_impl(
            database,
            root=root,
            bounds=bounds,
            attempts=attempts,
            hook=hook,
            provider=provider,
        )
    backend = get_filesystem_backend()
    # Default-bounds path: backend may use platform-specific snapshotting.
    if backend.capabilities.sqlite_snapshots:
        return backend.sqlite_family_snapshot(
            database,
            root=root,
            max_bytes=bounds.sqlite_snapshot_bytes,
        )
    return _snapshot_sqlite_family_impl(
        database,
        root=root,
        bounds=bounds,
        attempts=attempts,
        hook=hook,
        provider=provider,
    )


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
def private_sqlite_connection_live_wal_cow(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    bounds: Bounds = DEFAULT_BOUNDS,
    attempts: int | None = None,
    hook: AttemptHook | None = None,
    provider: str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a private Darwin/APFS clone plus validated live-WAL prefix.

    The implementation import is intentionally lazy: ``sqlite_cow`` reuses
    descriptor helpers from this module, while unsupported installed hosts must
    still be able to import the stdlib-only runtime normally.
    """

    from .sqlite_cow import private_sqlite_connection_live_wal_cow_impl

    with private_sqlite_connection_live_wal_cow_impl(
        database,
        root=root,
        bounds=bounds,
        attempts=attempts,
        hook=hook,
        provider=provider,
    ) as connection:
        yield connection


@contextlib.contextmanager
def query_only_live_sqlite(
    database: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    provider: str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Read-only connection to a pinned live DB descriptor without copying it.

    Used when the main DB exceeds ``sqlite_snapshot_bytes`` (e.g. OpenCode homes
    >1GiB). The main file is opened no-follow first and SQLite receives only the
    process-local descriptor path, closing the validation-to-open pathname race.
    Live sidecars are refused because a descriptor URI cannot safely preserve
    SQLite's basename-based WAL/SHM family lookup. Before yielding, the helper
    establishes a read transaction; that pinned SQLite snapshot is the point at
    which later legal source writes are assigned to the next reader run.
    """

    safe, base = require_regular_no_symlinks(database, root)
    try:
        initially_validated = _fingerprint(os.lstat(safe))
    except OSError as error:
        raise DiagnosticError("E_SOURCE_BUSY", provider=provider) from error
    descriptor = _open_no_follow(safe, base)
    expected = _fingerprint(os.fstat(descriptor))
    if expected != initially_validated:
        os.close(descriptor)
        raise DiagnosticError.source_busy(
            attempts=0,
            family=(os.path.basename(safe),),
            provider=provider,
        )

    def reject_live_sidecars() -> None:
        present: dict[str, str] = {}
        # Validate every present sidecar before classifying the family. Unsafe
        # symlink/non-regular members take precedence over advisory diagnostics.
        for suffix in ("-journal", "-wal", "-shm"):
            member = f"{safe}{suffix}"
            if not os.path.lexists(member):
                continue
            try:
                mode = os.lstat(member).st_mode
            except OSError as error:
                raise DiagnosticError.source_busy(
                    attempts=0,
                    family=(os.path.basename(member),),
                    provider=provider,
                ) from error
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise DiagnosticError.unsafe_path()
            require_regular_no_symlinks(member, base)
            present[suffix] = os.path.basename(member)
        if "-journal" in present:
            raise DiagnosticError(
                "E_SQLITE_HOT_JOURNAL",
                provider=provider,
                attempts=0,
                family=(present["-journal"],),
            )
        live_family = tuple(present[suffix] for suffix in ("-wal", "-shm") if suffix in present)
        if live_family:
            # A descriptor URI pins the main inode, but SQLite derives sidecar
            # names from the URI path. Refuse live sidecars rather than omit
            # committed WAL.
            raise DiagnosticError(
                "E_SQLITE_LIVE_WAL",
                provider=provider,
                attempts=0,
                family=live_family,
            )

    def verify_main_entry() -> None:
        verification = _open_no_follow(safe, base)
        try:
            if _fingerprint(os.fstat(verification)) != expected:
                raise DiagnosticError.source_busy(
                    attempts=0,
                    family=(os.path.basename(safe),),
                    provider=provider,
                )
        finally:
            os.close(verification)

    def reject_persistent_wal_header() -> None:
        """Refuse a WAL-mode main before SQLite can recreate source sidecars.

        SQLite persists WAL mode in file-header read/write version bytes 18-19.
        A read transaction against a writable source directory may create a new
        ``-wal``/``-shm`` pair even when the prior pair was removed normally.
        This oversized live helper therefore must not connect to that source at
        all; the private COW backend is the only safe WAL-mode path.
        """

        try:
            if hasattr(os, "pread"):
                first = os.pread(descriptor, 100, 0)
                second = os.pread(descriptor, 100, 0)
            else:
                os.lseek(descriptor, 0, os.SEEK_SET)
                first = os.read(descriptor, 100)
                os.lseek(descriptor, 0, os.SEEK_SET)
                second = os.read(descriptor, 100)
                os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError as error:
            raise DiagnosticError.source_busy(
                attempts=0,
                family=(os.path.basename(safe),),
                provider=provider,
            ) from error
        if first != second:
            raise DiagnosticError.source_busy(
                attempts=0,
                family=(os.path.basename(safe),),
                provider=provider,
            )
        if (
            len(first) >= 20
            and first[:16] == b"SQLite format 3\x00"
            and (first[18] == 2 or first[19] == 2)
        ):
            raise DiagnosticError(
                "E_SQLITE_LIVE_WAL",
                provider=provider,
                attempts=0,
                family=(os.path.basename(safe),),
            )

    try:
        reject_live_sidecars()
        verify_main_entry()
        reject_persistent_wal_header()
        verify_main_entry()
    except BaseException:
        os.close(descriptor)
        raise
    descriptor_path = next(
        (
            candidate
            for candidate in (f"/proc/self/fd/{descriptor}", f"/dev/fd/{descriptor}")
            if os.path.exists(candidate)
        ),
        None,
    )
    if descriptor_path is None:
        os.close(descriptor)
        raise DiagnosticError.unsafe_path()

    uri = f"file:{quote(descriptor_path, safe='/')}?mode=ro&cache=private"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True)
        # Detect family changes during sqlite3.connect. The connection itself
        # is already pinned to ``descriptor`` and never follows a replacement,
        # but a newly created source WAL would otherwise be invisible through
        # the descriptor URI.
        reject_live_sidecars()
        verify_main_entry()
        connection.execute("PRAGMA query_only=ON")
        value = connection.execute("PRAGMA query_only").fetchone()
        if value is None or value[0] != 1:
            raise DiagnosticError("E_INVARIANT", provider=provider)
        reject_live_sidecars()
        verify_main_entry()
        # Establish the SQLite read snapshot before returning control. The
        # descriptor and SQLite transaction are the linearization boundary:
        # a sidecar that appears before this point is caught by the checks
        # below, while a legal write after it belongs to a later source state
        # and cannot change the active read transaction.
        connection.execute("BEGIN")
        connection.execute("SELECT COUNT(*) FROM sqlite_schema").fetchone()
        reject_live_sidecars()
        verify_main_entry()
        yield connection
    finally:
        if connection is not None:
            connection.close()
        os.close(descriptor)


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Test/audit helper; it never participates in source discovery."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
