from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import (
    _collect_scanned_lines,
    _hash_descriptor_window,
    stable_scan_tail_lines,
)


class CollectScannedTailParamsTests(unittest.TestCase):
    def _descriptor(self, payload: bytes) -> tuple[int, Path]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jsonl"
            path.write_bytes(payload)
            descriptor = os.open(str(path), os.O_RDONLY)
            self.addCleanup(os.close, descriptor)
            return descriptor, path

    def test_discard_first_line_skips_partial_window_head(self) -> None:
        descriptor, _path = self._descriptor(b'{"a":1}\n{"b":2}\n')
        os.lseek(descriptor, 3, os.SEEK_SET)  # mid-line inside {"a":1}
        lines, pending_bytes, pending_records, _ = _collect_scanned_lines(
            descriptor,
            max_line_bytes=1024,
            budget=None,
            charge_transcript=False,
            discard_first_line=True,
        )
        self.assertEqual([line.text for line in lines], ['{"b":2}'])
        self.assertEqual(pending_records, 1)
        self.assertGreater(pending_bytes, 0)

    def test_without_discard_first_line_keeps_complete_first_line(self) -> None:
        descriptor, _path = self._descriptor(b'{"a":1}\n{"b":2}\n')
        os.lseek(descriptor, 8, os.SEEK_SET)  # exactly at the boundary after \n
        lines, _b, pending_records, _ = _collect_scanned_lines(
            descriptor,
            max_line_bytes=1024,
            budget=None,
            charge_transcript=False,
            discard_first_line=False,
        )
        self.assertEqual([line.text for line in lines], ['{"b":2}'])
        self.assertEqual(pending_records, 1)

    def test_enforce_record_budget_false_counts_without_charging(self) -> None:
        descriptor, _path = self._descriptor(b'{"n":1}\n' * 5)
        budget = ReadBudget(Bounds(scanned_records=2, transcript_records=2))
        lines, _b, pending_records, _ = _collect_scanned_lines(
            descriptor,
            max_line_bytes=1024,
            budget=budget,
            charge_transcript=False,
            enforce_record_budget=False,
        )
        self.assertEqual(len(lines), 5)
        self.assertEqual(pending_records, 5)
        self.assertEqual(budget.records, 0)
        self.assertEqual(budget.transcript_records_read, 0)

    def test_enforce_record_budget_true_still_raises_limit(self) -> None:
        descriptor, _path = self._descriptor(b'{"n":1}\n' * 5)
        budget = ReadBudget(Bounds(scanned_records=2, transcript_records=2))
        with self.assertRaises(DiagnosticError) as caught:
            _collect_scanned_lines(
                descriptor,
                max_line_bytes=1024,
                budget=budget,
                charge_transcript=False,
                enforce_record_budget=True,
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


class HashDescriptorWindowTests(unittest.TestCase):
    def test_hashes_only_the_requested_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.jsonl"
            path.write_bytes(b"AAAA\nBBBB\n")
            descriptor = os.open(str(path), os.O_RDONLY)
            self.addCleanup(os.close, descriptor)
            digest, total = _hash_descriptor_window(descriptor, start=5, maximum=1024)
            self.assertEqual(total, 5)  # "BBBB\n"
            self.assertEqual(digest, hashlib.sha256(b"BBBB\n").hexdigest())

    def test_window_over_maximum_raises_limit_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.jsonl"
            path.write_bytes(b"ABCDEF")
            descriptor = os.open(str(path), os.O_RDONLY)
            self.addCleanup(os.close, descriptor)
            with self.assertRaises(DiagnosticError) as caught:
                _hash_descriptor_window(descriptor, start=0, maximum=3)
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


class StableScanTailLinesTests(unittest.TestCase):
    def test_whole_file_when_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(10)), encoding="utf-8")
            budget = ReadBudget(Bounds(transcript_records=100, scanned_records=100))
            lines = list(
                stable_scan_tail_lines(
                    str(path), root=str(root), budget=budget, charge_transcript=True
                )
            )
            self.assertEqual(len(lines), 10)
            self.assertEqual(lines[0].text, '{"n":0}')
            self.assertEqual(lines[-1].text, '{"n":9}')

    def test_admits_only_tail_window_when_file_exceeds_source_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "big.jsonl"
            # Line widths vary: {"n":0}-{"n":9} are 8 bytes, {"n":10}-{"n":99}
            # are 9 bytes, {"n":100}-{"n":199} are 10 bytes; 200 lines = 1890
            # bytes total.
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(200)), encoding="utf-8")
            tight = Bounds(
                source_read_bytes=512,
                transcript_records=5_000,
                scanned_records=500,
            )
            budget = ReadBudget(limits=tight)
            admitted = list(
                stable_scan_tail_lines(
                    str(path), root=str(root), budget=budget, charge_transcript=True
                )
            )
            self.assertGreater(len(admitted), 0)
            self.assertLess(len(admitted), 200)
            # tail_start = 1890-512 = 1378 is mid-line (line 148), which is
            # discarded; the first admitted line is the next complete one.
            self.assertEqual(admitted[0].text, '{"n":149}')
            self.assertEqual(admitted[-1].text, '{"n":199}')
            self.assertLessEqual(budget.bytes_read, 512)

    def test_trims_oldest_records_to_transcript_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "many.jsonl"
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(10)), encoding="utf-8")
            budget = ReadBudget(Bounds(transcript_records=3, scanned_records=100))
            lines = list(
                stable_scan_tail_lines(
                    str(path), root=str(root), budget=budget, charge_transcript=True
                )
            )
            self.assertEqual([line.text for line in lines], ['{"n":7}', '{"n":8}', '{"n":9}'])
            self.assertEqual(budget.transcript_records_read, 3)

    def test_interior_corruption_raises_corrupt_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "bad.jsonl"
            path.write_bytes(b'{"n":1}\n{"n":2}\xff\xfe\n{"n":3}\n')
            with self.assertRaises(DiagnosticError) as caught:
                list(stable_scan_tail_lines(str(path), root=str(root)))
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_oversize_line_raises_limit_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "huge.jsonl"
            path.write_bytes(b'{"n":1}\n' + b"x" * 32 + b"\n")
            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_tail_lines(
                        str(path), root=str(root), max_line_bytes=16
                    )
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_mutation_during_attempt_retries_then_source_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "mut.jsonl"
            path.write_text('{"n":1}\n' * 10, encoding="utf-8")
            budget = ReadBudget(Bounds(transcript_records=100, scanned_records=100))

            def mutate(_stage: str, _attempt: int, _safe: str) -> None:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write('{"n":99}\n')

            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_tail_lines(
                        str(path),
                        root=str(root),
                        budget=budget,
                        charge_transcript=True,
                        hook=mutate,
                    )
                )
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_source_tree_byte_for_byte_unchanged(self) -> None:
        from tests.helpers.core import tree_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "stable.jsonl"
            path.write_text('{"n":1}\n' * 20, encoding="utf-8")
            before = tree_snapshot(str(root))
            list(stable_scan_tail_lines(str(path), root=str(root)))
            self.assertEqual(tree_snapshot(str(root)), before)

    def test_boundary_byte_mutation_retries_then_source_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "boundary.jsonl"
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(200)), encoding="utf-8")
            budget = ReadBudget(
                Bounds(source_read_bytes=512, transcript_records=5_000, scanned_records=500)
            )
            tail_start = path.stat().st_size - 512

            def flip_boundary(_stage: str, _attempt: int, _safe: str) -> None:
                with open(path, "r+b") as handle:
                    handle.seek(tail_start - 1)
                    current = handle.read(1)
                    handle.seek(tail_start - 1)
                    handle.write(b"x" if current == b"\n" else b"\n")

            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_tail_lines(
                        str(path),
                        root=str(root),
                        budget=budget,
                        charge_transcript=True,
                        hook=flip_boundary,
                    )
                )
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_verification_time_growth_retries_then_source_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "grow.jsonl"
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(200)), encoding="utf-8")
            budget = ReadBudget(
                Bounds(source_read_bytes=512, transcript_records=5_000, scanned_records=500)
            )

            def append(_stage: str, _attempt: int, _safe: str) -> None:
                if _stage == "after-read":
                    with open(path, "a", encoding="utf-8") as handle:
                        handle.write('{"n":99}\n')

            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_tail_lines(
                        str(path),
                        root=str(root),
                        budget=budget,
                        charge_transcript=True,
                        hook=append,
                    )
                )
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
