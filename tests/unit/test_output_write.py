"""Unit tests for atomic no-clobber output writers (Lane B)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.output_write import (
    OutputToStdout,
    _commit_staged_output,
    _stage_output_bytes,
    write_output_bytes,
    write_output_text,
)


class WriteOutputTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_write_once_succeeds_with_exact_content(self) -> None:
        dest = self.root / "out.txt"
        written = write_output_text(str(dest), "hello portable\n")
        self.assertEqual(written, os.path.abspath(str(dest)))
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_text(encoding="utf-8"), "hello portable\n")
        # Best-effort private mode on platforms that support it.
        mode = dest.stat().st_mode & 0o777
        if os.name == "posix":
            self.assertEqual(mode & 0o077, 0, f"expected no group/other bits, got {oct(mode)}")

    def test_second_write_without_clobber_fails_and_preserves(self) -> None:
        dest = self.root / "keep.txt"
        write_output_text(str(dest), "original-body\n")
        with self.assertRaises(DiagnosticError) as caught:
            write_output_text(str(dest), "should-not-land\n", clobber=False)
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        self.assertEqual(dest.read_text(encoding="utf-8"), "original-body\n")

    def test_clobber_true_overwrites_with_full_new_content(self) -> None:
        dest = self.root / "rewrite.txt"
        write_output_text(str(dest), "old-content-that-is-longer-than-new\n")
        written = write_output_text(str(dest), "NEW\n", clobber=True)
        self.assertEqual(written, os.path.abspath(str(dest)))
        self.assertEqual(dest.read_text(encoding="utf-8"), "NEW\n")

    def test_path_dash_raises_output_to_stdout(self) -> None:
        with self.assertRaises(OutputToStdout):
            write_output_text("-", "stdout-payload\n")
        with self.assertRaises(OutputToStdout):
            write_output_bytes("-", b"stdout-payload\n")

    def test_empty_path_is_invalid(self) -> None:
        with self.assertRaises(DiagnosticError) as caught:
            write_output_text("", "x")
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_missing_parent_is_invalid(self) -> None:
        missing = self.root / "no-such-dir" / "out.txt"
        with self.assertRaises(DiagnosticError) as caught:
            write_output_text(str(missing), "x\n")
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_symlink_destination_without_clobber_refused(self) -> None:
        real = self.root / "real.txt"
        real.write_text("via-symlink\n", encoding="utf-8")
        link = self.root / "link.txt"
        link.symlink_to(real)
        with self.assertRaises(DiagnosticError) as caught:
            write_output_text(str(link), "clobber-link\n", clobber=False)
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        self.assertEqual(real.read_text(encoding="utf-8"), "via-symlink\n")
        self.assertTrue(link.is_symlink())

    def test_write_output_bytes_roundtrip(self) -> None:
        dest = self.root / "bin.out"
        payload = b"\x00\x01\xff binary"
        written = write_output_bytes(str(dest), payload)
        self.assertEqual(written, os.path.abspath(str(dest)))
        self.assertEqual(dest.read_bytes(), payload)


class CrashBeforeReplaceTests(unittest.TestCase):
    """Mid-flight failures must not truncate or create a half-written final."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_staged_temp_does_not_create_final_path(self) -> None:
        final = self.root / "final.txt"
        payload = b"staged-only\n"
        tmp_path = _stage_output_bytes(str(self.root), payload)
        self.addCleanup(lambda: _unlink_quiet(tmp_path))
        self.assertTrue(os.path.isfile(tmp_path))
        self.assertEqual(Path(tmp_path).read_bytes(), payload)
        self.assertFalse(final.exists())
        self.assertFalse(os.path.lexists(str(final)))

    def test_failed_replace_leaves_existing_content_unchanged(self) -> None:
        dest = self.root / "stable.txt"
        write_output_text(str(dest), "stable-original\n")
        with mock.patch(
            "portable_resume.output_write.os.replace",
            side_effect=OSError("simulated crash before replace"),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                write_output_text(str(dest), "truncated?\n", clobber=True)
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        self.assertEqual(dest.read_text(encoding="utf-8"), "stable-original\n")
        # No durable temp left after failed commit cleanup.
        leftovers = [
            name
            for name in os.listdir(self.root)
            if name.startswith(".portable-resume-output-") and name.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_failed_replace_when_final_absent_does_not_create_final(self) -> None:
        dest = self.root / "never-created.txt"
        with mock.patch(
            "portable_resume.output_write.os.replace",
            side_effect=OSError("simulated crash before replace"),
        ):
            with self.assertRaises(DiagnosticError):
                write_output_text(str(dest), "should-not-appear\n")
        self.assertFalse(dest.exists())
        self.assertFalse(os.path.lexists(str(dest)))

    def test_commit_after_stage_is_atomic_replace(self) -> None:
        dest = self.root / "committed.txt"
        dest.write_text("before\n", encoding="utf-8")
        tmp = _stage_output_bytes(str(self.root), b"after-commit\n")
        _commit_staged_output(tmp, os.path.abspath(str(dest)), clobber=True)
        self.assertEqual(dest.read_text(encoding="utf-8"), "after-commit\n")
        self.assertFalse(os.path.lexists(tmp))


class OutputPathPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_directory_destination_refused_even_with_clobber(self) -> None:
        directory = self.root / "subdir"
        directory.mkdir()
        with self.assertRaises(DiagnosticError) as caught:
            write_output_text(str(directory), "nope\n", clobber=True)
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        self.assertTrue(directory.is_dir())

    def test_clobber_replaces_symlink_leaf_without_following(self) -> None:
        real = self.root / "target.txt"
        real.write_text("real-body\n", encoding="utf-8")
        link = self.root / "alias.txt"
        link.symlink_to(real)
        write_output_text(str(link), "new-leaf\n", clobber=True)
        # Symlink leaf replaced; original target file body unchanged.
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(encoding="utf-8"), "new-leaf\n")
        self.assertEqual(real.read_text(encoding="utf-8"), "real-body\n")


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


if __name__ == "__main__":
    unittest.main()
