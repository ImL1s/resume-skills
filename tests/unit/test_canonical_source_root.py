"""canonical_source_root accepts dir or regular file for CLI --source-root."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.paths import canonical_root, canonical_source_root


class CanonicalSourceRootTests(unittest.TestCase):
    def test_directory_matches_canonical_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            self.assertEqual(canonical_source_root(path), str(path))
            self.assertEqual(canonical_source_root(path), canonical_root(path))

    def test_regular_file_is_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            file_path = Path(temporary) / "events.jsonl"
            file_path.write_text("{}\n", encoding="utf-8")
            approved = canonical_source_root(file_path)
            self.assertEqual(approved, str(file_path.resolve()))
            with self.assertRaises(DiagnosticError) as caught:
                canonical_root(file_path)
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_missing_path_is_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "nope"
            with self.assertRaises(DiagnosticError) as caught:
                canonical_source_root(missing)
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_fifo_is_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "pipe"
            try:
                os.mkfifo(fifo)
            except (AttributeError, OSError):
                self.skipTest("mkfifo unavailable")
            if not stat.S_ISFIFO(os.lstat(fifo).st_mode):
                self.skipTest("not a fifo")
            with self.assertRaises(DiagnosticError) as caught:
                canonical_source_root(fifo)
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")


if __name__ == "__main__":
    unittest.main()
