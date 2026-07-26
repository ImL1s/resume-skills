# tests/unit/test_bounds_raise_reject.py
from __future__ import annotations

import unittest

from portable_resume.bounds import DEFAULT_BOUNDS, Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError


class BoundsRaiseRejectTests(unittest.TestCase):
    def test_consume_records_clamps_to_default_ceiling(self) -> None:
        raised = Bounds(
            scanned_records=DEFAULT_BOUNDS.scanned_records * 2,
            transcript_records=DEFAULT_BOUNDS.transcript_records,
            source_read_bytes=DEFAULT_BOUNDS.source_read_bytes,
            normalized_turns=DEFAULT_BOUNDS.normalized_turns,
        )
        budget = ReadBudget(limits=raised)
        # Filling exactly DEFAULT scanned_records must succeed; +1 must fail.
        budget.consume_records(DEFAULT_BOUNDS.scanned_records)
        with self.assertRaises(DiagnosticError):
            budget.consume_records(1)

    def test_consume_bytes_and_turns_also_reject_raise(self) -> None:
        raised = Bounds(
            source_read_bytes=DEFAULT_BOUNDS.source_read_bytes * 2,
            normalized_turns=DEFAULT_BOUNDS.normalized_turns * 2,
        )
        budget = ReadBudget(limits=raised)
        budget.consume_bytes(DEFAULT_BOUNDS.source_read_bytes)
        with self.assertRaises(DiagnosticError):
            budget.consume_bytes(1)
        budget2 = ReadBudget(limits=raised)
        budget2.consume_turns(DEFAULT_BOUNDS.normalized_turns)
        with self.assertRaises(DiagnosticError):
            budget2.consume_turns(1)


if __name__ == "__main__":
    unittest.main()
