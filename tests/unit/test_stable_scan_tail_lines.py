from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import _collect_scanned_lines


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
