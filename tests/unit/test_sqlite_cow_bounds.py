"""Finite lower-only bounds for the issue #263 COW path."""

from __future__ import annotations

import unittest
from dataclasses import replace

from portable_resume.bounds import DEFAULT_BOUNDS, Bounds
from portable_resume.diagnostics import DiagnosticError


class SQLiteCowBoundsTests(unittest.TestCase):
    def test_defaults_are_finite_cover_observed_store_and_callers_cannot_raise(self) -> None:
        self.assertEqual(DEFAULT_BOUNDS.sqlite_cow_logical_bytes, 2_147_483_648)
        self.assertEqual(DEFAULT_BOUNDS.sqlite_wal_bytes, 268_435_456)
        self.assertEqual(DEFAULT_BOUNDS.sqlite_wal_frames, 524_288)
        self.assertEqual(DEFAULT_BOUNDS.sqlite_snapshot_deadline_ms, 30_000)
        self.assertGreater(DEFAULT_BOUNDS.sqlite_cow_logical_bytes, 1_414_021_120)

        lowered = replace(
            DEFAULT_BOUNDS,
            sqlite_cow_logical_bytes=1_414_021_120,
            sqlite_wal_bytes=64 * 1024 * 1024,
            sqlite_wal_frames=10_000,
            sqlite_snapshot_deadline_ms=1_000,
        )
        self.assertIsInstance(lowered, Bounds)

        for name in (
            "sqlite_cow_logical_bytes",
            "sqlite_wal_bytes",
            "sqlite_wal_frames",
            "sqlite_snapshot_deadline_ms",
        ):
            with self.subTest(name=name), self.assertRaises(DiagnosticError) as caught:
                replace(DEFAULT_BOUNDS, **{name: getattr(DEFAULT_BOUNDS, name) + 1})
            self.assertEqual(caught.exception.code, "E_INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
