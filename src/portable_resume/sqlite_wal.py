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


def validate_wal_prefix(
    descriptor: int,
    *,
    source_size: int,
    max_bytes: int,
    max_frames: int,
    deadline_check: DeadlineCheck | None = None,
) -> WalPrefix:
    """Validate the largest physically complete WAL prefix from ``descriptor``.

    The source descriptor is never reopened by path. A partial final frame is
    excluded; every admitted frame must satisfy SQLite's cumulative checksum
    and salt rules. Callers revalidate generation and prefix digest before
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
    check()
    header = _pread_exact(descriptor, _WAL_HEADER_BYTES, 0)
    magic, version, encoded_page_size, _sequence, salt1, salt2, stored0, stored1 = struct.unpack(
        ">8I", header
    )
    if magic not in {_WAL_MAGIC_LITTLE, _WAL_MAGIC_BIG} or version != _WAL_VERSION:
        raise _busy()
    page_size = _page_size(encoded_page_size)
    big_endian = magic == _WAL_MAGIC_BIG
    state = _checksum(header[:24], big_endian=big_endian)
    if state != (stored0, stored1):
        raise _busy()

    frame_size = _WAL_FRAME_HEADER_BYTES + page_size
    frame_count = (source_size - _WAL_HEADER_BYTES) // frame_size
    prefix_length = _WAL_HEADER_BYTES + frame_count * frame_size
    if prefix_length > max_bytes or frame_count > max_frames:
        raise DiagnosticError.limit_exceeded()

    digest = hashlib.sha256(header)
    last_commit_frame = 0
    committed_pages = 0
    for frame_number in range(1, frame_count + 1):
        check()
        offset = _WAL_HEADER_BYTES + (frame_number - 1) * frame_size
        frame = _pread_exact(descriptor, frame_size, offset)
        page_number, database_pages, frame_salt1, frame_salt2, checksum0, checksum1 = struct.unpack(
            ">6I", frame[:_WAL_FRAME_HEADER_BYTES]
        )
        if page_number == 0 or (frame_salt1, frame_salt2) != (salt1, salt2):
            raise _busy()
        state = _checksum(
            frame[:8] + frame[_WAL_FRAME_HEADER_BYTES:],
            big_endian=big_endian,
            state=state,
        )
        if state != (checksum0, checksum1):
            raise _busy()
        if database_pages:
            last_commit_frame = frame_number
            committed_pages = database_pages
        digest.update(frame)
    check()
    return WalPrefix(
        raw_header=header,
        length=prefix_length,
        page_size=page_size,
        frame_count=frame_count,
        last_commit_frame=last_commit_frame,
        committed_pages=committed_pages,
        sha256=digest.hexdigest(),
    )
