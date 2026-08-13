"""Bounded, descriptor-only validation of SQLite WAL prefixes."""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Callable

from .diagnostics import DiagnosticError

_WAL_HEADER_BYTES = 32
_WAL_FRAME_HEADER_BYTES = 24
_WAL_VERSION = 3_007_000
_WAL_MAGIC_LITTLE = 0x377F0682
_WAL_MAGIC_BIG = 0x377F0683
_UINT32_MASK = 0xFFFFFFFF

DeadlineCheck = Callable[[], None]


@dataclass(frozen=True, slots=True)
class WalHeader:
    raw: bytes
    checkpoint_sequence: int
    page_size: int
    salt1: int
    salt2: int
    big_endian_checksum: bool
    checksum: tuple[int, int]


@dataclass(frozen=True, slots=True)
class WalPrefix:
    """Validated, physically complete prefix from one pinned WAL descriptor."""

    raw_header: bytes
    length: int
    page_size: int
    frame_count: int
    last_commit_frame: int
    committed_pages: int
    sha256: str


def _busy() -> DiagnosticError:
    return DiagnosticError.source_busy()


def _pread_exact(descriptor: int, amount: int, offset: int) -> bytes:
    output = bytearray()
    try:
        while len(output) < amount:
            block = os.pread(descriptor, amount - len(output), offset + len(output))
            if not block:
                raise _busy()
            output.extend(block)
    except DiagnosticError:
        raise
    except OSError as error:
        raise _busy() from error
    return bytes(output)


def _checksum(
    data: bytes,
    *,
    big_endian: bool,
    state: tuple[int, int] = (0, 0),
) -> tuple[int, int]:
    if len(data) % 8:
        raise DiagnosticError("E_INVARIANT")
    order = ">" if big_endian else "<"
    words = struct.unpack(f"{order}{len(data) // 4}I", data)
    s0, s1 = state
    for index in range(0, len(words), 2):
        s0 = (s0 + words[index] + s1) & _UINT32_MASK
        s1 = (s1 + words[index + 1] + s0) & _UINT32_MASK
    return s0, s1


def _page_size(encoded: int) -> int:
    value = 65_536 if encoded == 1 else encoded
    if value < 512 or value > 65_536 or value & (value - 1):
        raise _busy()
    return value


def validate_wal_header(
    descriptor: int,
    *,
    deadline_check: DeadlineCheck | None = None,
) -> WalHeader:
    """Validate and return the complete 32-byte header from a pinned WAL."""

    if type(descriptor) is not int or descriptor < 0:
        raise DiagnosticError.invalid()
    check = deadline_check or (lambda: None)
    check()
    raw = _pread_exact(descriptor, _WAL_HEADER_BYTES, 0)
    magic, version, encoded_page_size, sequence, salt1, salt2, stored0, stored1 = struct.unpack(
        ">8I", raw
    )
    if magic not in {_WAL_MAGIC_LITTLE, _WAL_MAGIC_BIG} or version != _WAL_VERSION:
        raise _busy()
    page_size = _page_size(encoded_page_size)
    big_endian = magic == _WAL_MAGIC_BIG
    state = _checksum(raw[:24], big_endian=big_endian)
    if state != (stored0, stored1):
        raise _busy()
    check()
    return WalHeader(
        raw=raw,
        checkpoint_sequence=sequence,
        page_size=page_size,
        salt1=salt1,
        salt2=salt2,
        big_endian_checksum=big_endian,
        checksum=state,
    )


def validate_wal_prefix(
    descriptor: int,
    *,
    source_size: int,
    max_bytes: int,
    max_frames: int,
    deadline_check: DeadlineCheck | None = None,
) -> WalPrefix:
    """Validate the current generation's complete WAL prefix.

    The source descriptor is never reopened by path. A partial final frame is
    excluded. SQLite may restart a WAL in place after checkpointing without
    shrinking the file, so a first frame with different salts terminates the
    current generation and leaves the previous generation's physical tail
    unadmitted. Every frame with current salts must satisfy SQLite's cumulative
    checksum rules. Callers revalidate generation and prefix digest before
    accepting a paired private main-file clone.
    """

    if (
        type(descriptor) is not int
        or descriptor < 0
        or type(source_size) is not int
        or source_size < _WAL_HEADER_BYTES
        or type(max_bytes) is not int
        or max_bytes < _WAL_HEADER_BYTES
        or type(max_frames) is not int
        or max_frames < 0
    ):
        raise DiagnosticError.invalid()
    check = deadline_check or (lambda: None)
    header = validate_wal_header(descriptor, deadline_check=check)
    page_size = header.page_size
    state = header.checksum

    frame_size = _WAL_FRAME_HEADER_BYTES + page_size
    physical_frame_count = (source_size - _WAL_HEADER_BYTES) // frame_size
    physical_prefix_length = _WAL_HEADER_BYTES + physical_frame_count * frame_size
    if physical_prefix_length > max_bytes or physical_frame_count > max_frames:
        raise DiagnosticError.limit_exceeded()

    digest = hashlib.sha256(header.raw)
    frame_count = 0
    last_commit_frame = 0
    committed_pages = 0
    for frame_number in range(1, physical_frame_count + 1):
        check()
        offset = _WAL_HEADER_BYTES + (frame_number - 1) * frame_size
        frame = _pread_exact(descriptor, frame_size, offset)
        page_number, database_pages, frame_salt1, frame_salt2, checksum0, checksum1 = struct.unpack(
            ">6I", frame[:_WAL_FRAME_HEADER_BYTES]
        )
        if (frame_salt1, frame_salt2) != (header.salt1, header.salt2):
            # SQLite reuses a checkpointed WAL in place.  Bytes beyond the
            # current mxFrame keep the prior generation's salts and are not
            # part of the current logical WAL even though they remain physical
            # complete frames.  Same-generation corruption never takes this
            # branch and remains a closed failure below.
            if last_commit_frame == 0:
                # A previous-generation tail is useful only after the current
                # generation has established a complete committed boundary.
                # Otherwise a rewritten header could make an arbitrary WAL
                # disappear into a header-only snapshot.
                raise _busy()
            break
        if page_number == 0:
            raise _busy()
        state = _checksum(
            frame[:8] + frame[_WAL_FRAME_HEADER_BYTES:],
            big_endian=header.big_endian_checksum,
            state=state,
        )
        if state != (checksum0, checksum1):
            raise _busy()
        frame_count = frame_number
        if database_pages:
            last_commit_frame = frame_number
            committed_pages = database_pages
        digest.update(frame)
    check()
    prefix_length = _WAL_HEADER_BYTES + frame_count * frame_size
    return WalPrefix(
        raw_header=header.raw,
        length=prefix_length,
        page_size=page_size,
        frame_count=frame_count,
        last_commit_frame=last_commit_frame,
        committed_pages=committed_pages,
        sha256=digest.hexdigest(),
    )


def materialize_wal_prefix(
    main_descriptor: int,
    wal_descriptor: int,
    prefix: WalPrefix,
    *,
    max_logical_bytes: int,
    deadline_check: DeadlineCheck | None = None,
) -> None:
    """Apply the last committed WAL state to one pinned private main file.

    ``prefix`` has already been accepted against the source family.  This
    function revalidates the copied private WAL descriptor byte-for-byte,
    overlays frames only through its final commit marker, and truncates the
    private main file to that commit's declared page count.  It never receives
    or opens a source pathname.
    """

    if (
        type(main_descriptor) is not int
        or main_descriptor < 0
        or type(wal_descriptor) is not int
        or wal_descriptor < 0
        or not isinstance(prefix, WalPrefix)
        or type(max_logical_bytes) is not int
        or max_logical_bytes < 0
    ):
        raise DiagnosticError.invalid()
    check = deadline_check or (lambda: None)
    verified = validate_wal_prefix(
        wal_descriptor,
        source_size=prefix.length,
        max_bytes=prefix.length,
        max_frames=prefix.frame_count,
        deadline_check=check,
    )
    if verified != prefix:
        raise _busy()

    header = _pread_exact(main_descriptor, 100, 0)
    if header[:16] != b"SQLite format 3\0":
        raise _busy()
    encoded_main_page_size = struct.unpack(">H", header[16:18])[0]
    if _page_size(encoded_main_page_size) != prefix.page_size:
        raise _busy()
    if prefix.last_commit_frame == 0:
        check()
        return

    logical_size = prefix.committed_pages * prefix.page_size
    if logical_size <= 0 or logical_size > max_logical_bytes:
        raise DiagnosticError.limit_exceeded()
    frame_size = _WAL_FRAME_HEADER_BYTES + prefix.page_size
    for frame_number in range(1, prefix.last_commit_frame + 1):
        check()
        offset = _WAL_HEADER_BYTES + (frame_number - 1) * frame_size
        frame = _pread_exact(wal_descriptor, frame_size, offset)
        page_number = struct.unpack(">I", frame[:4])[0]
        if page_number == 0:
            raise _busy()
        if page_number > prefix.committed_pages:
            continue
        page = memoryview(frame)[_WAL_FRAME_HEADER_BYTES:]
        destination_offset = (page_number - 1) * prefix.page_size
        while page:
            try:
                written = os.pwrite(main_descriptor, page, destination_offset)
            except OSError as error:
                raise _busy() from error
            if written <= 0:
                raise _busy()
            destination_offset += written
            page = page[written:]
    try:
        os.ftruncate(main_descriptor, logical_size)
        os.fsync(main_descriptor)
    except OSError as error:
        raise _busy() from error
    check()
