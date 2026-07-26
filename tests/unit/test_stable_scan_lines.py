from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import stable_scan_lines


class StableScanLinesTests(unittest.TestCase):
    def test_streams_lines_without_loading_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text('{"id":1}\n{"id":2}\n{"id":3}\n', encoding="utf-8")
            budget = ReadBudget()
            lines = list(stable_scan_lines(str(path), root=str(root), budget=budget))
            self.assertEqual(len(lines), 3)
            self.assertTrue(all(isinstance(item.text, str) for item in lines))
            self.assertGreater(budget.bytes_read, 0)

    def test_stops_at_transcript_record_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "big.jsonl"
            path.write_text('{"n":1}\n' * 5, encoding="utf-8")
            tight = Bounds(transcript_records=3, scanned_records=3)
            budget = ReadBudget(limits=tight)
            with self.assertRaises(DiagnosticError):
                list(
                    stable_scan_lines(
                        str(path),
                        root=str(root),
                        budget=budget,
                        charge_transcript=True,
                    )
                )


if __name__ == "__main__":
    unittest.main()
