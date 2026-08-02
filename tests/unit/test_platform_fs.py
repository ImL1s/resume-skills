"""Unit tests for safe cross-platform filesystem backend contract (PR 1)."""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import unittest
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.discover_doctor import doctor_report
from portable_resume.platform_fs import (
    FilesystemBackend,
    FilesystemCapabilities,
    FilesystemIdentity,
    get_filesystem_backend,
)
from portable_resume.platform_fs.posix import PosixFilesystemBackend
from portable_resume.platform_fs.select import _reset_backend_cache
from portable_resume.platform_fs.windows import WindowsFilesystemBackend


class PlatformFsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_backend_cache()

    def tearDown(self) -> None:
        _reset_backend_cache()

    def test_backend_selection_deterministic(self) -> None:
        backend = get_filesystem_backend()
        self.assertIsInstance(backend, FilesystemBackend)
        if os.name == "nt":
            self.assertIsInstance(backend, WindowsFilesystemBackend)
            self.assertTrue(backend.identity.is_windows)
            self.assertFalse(backend.identity.is_posix)
        else:
            self.assertIsInstance(backend, PosixFilesystemBackend)
            self.assertTrue(backend.identity.is_posix)
            self.assertFalse(backend.identity.is_windows)

    def test_backend_selection_anti_spoofing(self) -> None:
        """Environment variables must never alter backend selection or capabilities."""
        with mock.patch.dict(
            os.environ,
            {
                "PORTABLE_RESUME_FS": "posix",
                "OS": "Linux",
                "PLATFORM": "darwin",
                "BACKEND": "PosixFilesystemBackend",
            },
            clear=False,
        ):
            _reset_backend_cache()
            backend = get_filesystem_backend()
            if os.name == "nt":
                self.assertIsInstance(backend, WindowsFilesystemBackend)
            else:
                self.assertIsInstance(backend, PosixFilesystemBackend)

    def test_capabilities_immutability(self) -> None:
        backend = get_filesystem_backend()
        caps = backend.capabilities
        with self.assertRaises((dataclasses.FrozenInstanceError, AttributeError)):
            caps.descriptor_relative = not caps.descriptor_relative  # type: ignore[misc]

    def test_identity_immutability(self) -> None:
        backend = get_filesystem_backend()
        ident = backend.identity
        with self.assertRaises((dataclasses.FrozenInstanceError, AttributeError)):
            ident.backend_name = "TamperedBackend"  # type: ignore[misc]

    def test_capabilities_to_dict_closed_keys(self) -> None:
        backend = get_filesystem_backend()
        d = backend.capabilities.to_dict()
        expected_keys = {
            "descriptor_relative",
            "nofollow_reads",
            "relative_mutations",
            "sqlite_snapshots",
            "atomic_output",
            "exclusive_locking",
            "reparse_points",
            "handle_locking",
        }
        self.assertEqual(set(d.keys()), expected_keys)
        self.assertTrue(all(isinstance(v, bool) for v in d.values()))

    def test_identity_to_dict_closed_keys(self) -> None:
        backend = get_filesystem_backend()
        d = backend.identity.to_dict()
        expected_keys = {
            "os_name",
            "sys_platform",
            "is_posix",
            "is_windows",
            "backend_name",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_windows_backend_fail_closed_policy(self) -> None:
        win_backend = WindowsFilesystemBackend()
        self.assertFalse(win_backend.capabilities.relative_mutations)
        self.assertFalse(win_backend.capabilities.exclusive_locking)

        with tempfile.TemporaryDirectory() as tmp_dir:
            target_sub = os.path.join(tmp_dir, "sub")
            with self.assertRaises(DiagnosticError) as caught:
                win_backend.mkdirs_beneath(target_sub, root=tmp_dir)
            self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

            file_path = os.path.join(tmp_dir, "test.txt")
            with open(file_path, "wb") as fp:
                fp.write(b"data")

            with self.assertRaises(DiagnosticError) as caught:
                win_backend.unlink_beneath(file_path, root=tmp_dir)
            self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

            target_path = os.path.join(tmp_dir, "dest.txt")
            with self.assertRaises(DiagnosticError) as caught:
                win_backend.replace_beneath(file_path, target_path, root=tmp_dir)
            self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

            lock_path = os.path.join(tmp_dir, "test.lock")
            with self.assertRaises(DiagnosticError) as caught:
                with win_backend.acquire_exclusive_lock(lock_path):
                    pass
            self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

    def test_windows_backend_read_and_output(self) -> None:
        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "sample.txt")
            content = b"hello windows safe read"
            with open(file_path, "wb") as fp:
                fp.write(content)

            stable = win_backend.read_regular_stable(file_path, root=tmp_dir)
            self.assertEqual(stable.data, content)

            output_path = os.path.join(tmp_dir, "output.txt")
            written = win_backend.atomic_replace_output(output_path, b"output data")
            self.assertTrue(os.path.exists(written))
            with open(written, "rb") as fp:
                self.assertEqual(fp.read(), b"output data")

    def test_windows_backend_read_charges_budget(self) -> None:
        from portable_resume.bounds import ReadBudget
        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "sample.txt")
            content = b"budget test content"
            with open(file_path, "wb") as fp:
                fp.write(content)

            budget = ReadBudget()
            win_backend.read_regular_stable(file_path, root=tmp_dir, budget=budget)
            self.assertEqual(budget.bytes_read, len(content))

    def test_sqlite_family_snapshot_max_bytes_limit(self) -> None:
        posix_backend = PosixFilesystemBackend()
        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            with open(db_path, "wb") as fp:
                fp.write(b"sqlite data")

            with self.assertRaises(DiagnosticError) as caught:
                win_backend.sqlite_family_snapshot(db_path, root=tmp_dir, max_bytes=-1)
            self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_posix_backend_selection_under_mock(self) -> None:
        with mock.patch("os.name", "posix"):
            _reset_backend_cache()
            backend = get_filesystem_backend()
            self.assertIsInstance(backend, PosixFilesystemBackend)
            self.assertTrue(backend.identity.is_posix)
            self.assertFalse(backend.identity.is_windows)
            self.assertTrue(backend.capabilities.descriptor_relative)
            self.assertFalse(backend.capabilities.relative_mutations)
            self.assertTrue(backend.capabilities.exclusive_locking)

    def test_doctor_report_includes_filesystem_backend(self) -> None:
        report = doctor_report()
        self.assertIn("filesystem", report)
        self.assertIn("identity", report["filesystem"])
        self.assertIn("capabilities", report["filesystem"])
        fs_checks = [c for c in report["checks"] if c["id"] == "filesystem_backend"]
        self.assertEqual(len(fs_checks), 1)
        self.assertIn(fs_checks[0]["status"], ("pass", "info"))


if __name__ == "__main__":
    unittest.main()
