"""#17: Bounds / ReadBudget reject caller-raised global ceilings."""

from __future__ import annotations

import unittest
from dataclasses import fields, replace

from portable_resume.bounds import DEFAULT_BOUNDS, Bounds, ReadBudget, validate_bounds
from portable_resume.diagnostics import DiagnosticError


class BoundsRaiseRejectTests(unittest.TestCase):
    def test_default_bounds_accepted(self) -> None:
        self.assertIs(validate_bounds(DEFAULT_BOUNDS), DEFAULT_BOUNDS)
        budget = ReadBudget()
        self.assertEqual(budget.limits, DEFAULT_BOUNDS)

    def test_every_ceiling_accepts_lower_valid_value(self) -> None:
        for item in fields(Bounds):
            with self.subTest(field=item.name):
                default = getattr(DEFAULT_BOUNDS, item.name)
                if item.name == "snapshot_attempts":
                    lowered = max(1, default - 1)
                else:
                    lowered = 0
                limits = replace(DEFAULT_BOUNDS, **{item.name: lowered})
                self.assertEqual(getattr(limits, item.name), lowered)
                ReadBudget(limits=limits)

    def test_every_ceiling_rejects_default_plus_one(self) -> None:
        for item in fields(Bounds):
            with self.subTest(field=item.name):
                raised = getattr(DEFAULT_BOUNDS, item.name) + 1
                with self.assertRaises(DiagnosticError) as caught:
                    replace(DEFAULT_BOUNDS, **{item.name: raised})
                self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_negative_values_rejected(self) -> None:
        for item in fields(Bounds):
            with self.subTest(field=item.name):
                with self.assertRaises(DiagnosticError) as caught:
                    replace(DEFAULT_BOUNDS, **{item.name: -1})
                self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_snapshot_attempts_zero_and_above_default_rejected(self) -> None:
        with self.assertRaises(DiagnosticError):
            replace(DEFAULT_BOUNDS, snapshot_attempts=0)
        with self.assertRaises(DiagnosticError):
            replace(DEFAULT_BOUNDS, snapshot_attempts=DEFAULT_BOUNDS.snapshot_attempts + 1)
        ok = replace(DEFAULT_BOUNDS, snapshot_attempts=1)
        self.assertEqual(ok.snapshot_attempts, 1)

    def test_bool_not_accepted_as_int_ceiling(self) -> None:
        with self.assertRaises(DiagnosticError):
            replace(DEFAULT_BOUNDS, scanned_records=True)  # type: ignore[arg-type]

    def test_readbudget_rejects_raised_limits_before_io(self) -> None:
        with self.assertRaises(DiagnosticError) as caught:
            ReadBudget(limits=Bounds(scanned_records=DEFAULT_BOUNDS.scanned_records + 1))
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_consume_paths_still_cap_at_default_for_lowered_limits(self) -> None:
        tight = Bounds(
            scanned_records=3,
            source_read_bytes=10,
            normalized_turns=2,
            transcript_records=4,
        )
        budget = ReadBudget(limits=tight)
        budget.consume_records(3)
        with self.assertRaises(DiagnosticError) as caught:
            budget.consume_records(1)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

        budget = ReadBudget(limits=tight)
        budget.consume_bytes(10)
        with self.assertRaises(DiagnosticError):
            budget.consume_bytes(1)

        budget = ReadBudget(limits=tight)
        budget.consume_turns(2)
        with self.assertRaises(DiagnosticError):
            budget.consume_turns(1)

        budget = ReadBudget(limits=tight)
        budget.consume_transcript_records(4)
        with self.assertRaises(DiagnosticError):
            budget.consume_transcript_records(1)

    def test_error_serialization_content_free(self) -> None:
        try:
            Bounds(scanned_records=DEFAULT_BOUNDS.scanned_records + 99)
        except DiagnosticError as error:
            payload = error.to_dict()
            self.assertEqual(payload["code"], "E_INVALID_INPUT")
            self.assertNotIn("scanned_records", payload.get("message", ""))
            self.assertNotIn(str(DEFAULT_BOUNDS.scanned_records + 99), payload.get("message", ""))
        else:
            self.fail("expected DiagnosticError")


if __name__ == "__main__":
    unittest.main()
