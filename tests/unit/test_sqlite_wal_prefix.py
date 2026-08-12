"""Pure SQLite WAL header/frame validation for issue #263."""

from __future__ import annotations

import os
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.sqlite_wal import materialize_wal_prefix, validate_wal_prefix


def _checksum(data: bytes, *, big_endian: bool, state: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    order = ">" if big_endian else "<"
    words = struct.unpack(f"{order}{len(data) // 4}I", data)
    s0, s1 = state
    for index in range(0, len(words), 2):
        s0 = (s0 + words[index] + s1) & 0xFFFFFFFF
        s1 = (s1 + words[index + 1] + s0) & 0xFFFFFFFF
    return s0, s1


def _wal_bytes(
    frames: list[tuple[int, int, bytes]],
    *,
    magic: int = 0x377F0682,
    page_size: int = 512,
    checkpoint_sequence: int = 7,
    salts: tuple[int, int] = (11, 13),
) -> bytes:
    first = struct.pack(
        ">6I",
        magic,
        3_007_000,
        page_size,
        checkpoint_sequence,
        salts[0],
        salts[1],
    )
    state = _checksum(first, big_endian=magic == 0x377F0683)
    output = bytearray(first + struct.pack(">2I", *state))
    for page_number, database_pages, page in frames:
        if len(page) != page_size:
            raise AssertionError("test page has wrong size")
        first_eight = struct.pack(">2I", page_number, database_pages)
        state = _checksum(first_eight + page, big_endian=magic == 0x377F0683, state=state)
        output.extend(first_eight)
        output.extend(struct.pack(">2I", *salts))
        output.extend(struct.pack(">2I", *state))
        output.extend(page)
    return bytes(output)


class WalPrefixTests(unittest.TestCase):
    def _validate(self, data: bytes, *, suffix: bytes = b""):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "db-wal"
            path.write_bytes(data + suffix)
            descriptor = os.open(path, os.O_RDONLY)
            try:
                return validate_wal_prefix(
                    descriptor,
                    source_size=len(data) + len(suffix),
                    max_bytes=1024 * 1024,
                    max_frames=100,
                )
            finally:
                os.close(descriptor)

    def test_complete_checksum_valid_prefix_tracks_last_commit(self) -> None:
        page = b"a" * 512
        data = _wal_bytes(
            [
                (1, 1, page),
                (2, 0, b"b" * 512),
                (3, 3, b"c" * 512),
                (4, 0, b"d" * 512),
            ]
        )

        prefix = self._validate(data, suffix=b"partial-frame")

        self.assertEqual(prefix.length, len(data))
        self.assertEqual(prefix.page_size, 512)
        self.assertEqual(prefix.frame_count, 4)
        self.assertEqual(prefix.last_commit_frame, 3)
        self.assertEqual(prefix.committed_pages, 3)
        self.assertEqual(prefix.raw_header, data[:32])

    def test_restarted_wal_excludes_previous_generation_physical_tail(self) -> None:
        current = _wal_bytes(
            [(1, 1, b"a" * 512)],
            checkpoint_sequence=8,
            salts=(17, 19),
        )
        previous = _wal_bytes(
            [(2, 2, b"b" * 512), (3, 3, b"c" * 512)],
            checkpoint_sequence=7,
            salts=(11, 13),
        )

        prefix = self._validate(current + previous[32:])

        self.assertEqual(prefix.length, len(current))
        self.assertEqual(prefix.frame_count, 1)
        self.assertEqual(prefix.last_commit_frame, 1)
        self.assertEqual(prefix.committed_pages, 1)

    def test_previous_generation_tail_requires_current_commit_boundary(self) -> None:
        current_uncommitted = _wal_bytes(
            [(1, 0, b"a" * 512)],
            checkpoint_sequence=8,
            salts=(17, 19),
        )
        previous = _wal_bytes(
            [(2, 2, b"b" * 512)],
            checkpoint_sequence=7,
            salts=(11, 13),
        )

        with self.assertRaises(DiagnosticError) as caught:
            self._validate(current_uncommitted + previous[32:])

        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_reset_shrink_header_salt_and_interior_rewrite_rejected(self) -> None:
        data = bytearray(_wal_bytes([(1, 1, b"a" * 512)]))
        cases: dict[str, bytes] = {}
        header = bytearray(data)
        header[16] ^= 1
        cases["salt"] = bytes(header)
        interior = bytearray(data)
        interior[-1] ^= 1
        cases["interior"] = bytes(interior)
        zero_page = bytearray(data)
        zero_page[32:36] = b"\0\0\0\0"
        cases["zero-page"] = bytes(zero_page)

        for name, corrupt in cases.items():
            with self.subTest(name=name), self.assertRaises(DiagnosticError) as caught:
                self._validate(corrupt)
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_materialize_applies_only_committed_private_wal_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.sqlite"
            private = root / "private.sqlite"
            writer = sqlite3.connect(source)
            try:
                writer.execute("PRAGMA page_size=512")
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT)")
                writer.execute("INSERT INTO records VALUES (1, 'base')")
                writer.commit()
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                private.write_bytes(source.read_bytes())
                writer.execute("INSERT INTO records VALUES (2, 'committed')")
                writer.commit()
                writer.execute("INSERT INTO records VALUES (3, 'uncommitted')")

                wal = Path(str(source) + "-wal")
                wal_fd = os.open(wal, os.O_RDONLY | os.O_NOFOLLOW)
                main_fd = os.open(private, os.O_RDWR | os.O_NOFOLLOW)
                try:
                    prefix = validate_wal_prefix(
                        wal_fd,
                        source_size=wal.stat().st_size,
                        max_bytes=1024 * 1024,
                        max_frames=100,
                    )
                    materialize_wal_prefix(
                        main_fd,
                        wal_fd,
                        prefix,
                        max_logical_bytes=1024 * 1024,
                    )
                finally:
                    os.close(main_fd)
                    os.close(wal_fd)

                reader = sqlite3.connect(f"file:{private}?mode=ro&immutable=1", uri=True)
                try:
                    self.assertEqual(
                        reader.execute("SELECT id, value FROM records ORDER BY id").fetchall(),
                        [(1, "base"), (2, "committed")],
                    )
                    self.assertEqual(reader.execute("PRAGMA integrity_check(1)").fetchone(), ("ok",))
                finally:
                    reader.close()
            finally:
                writer.rollback()
                writer.close()


if __name__ == "__main__":
    unittest.main()
