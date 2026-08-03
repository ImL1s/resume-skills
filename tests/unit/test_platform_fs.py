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
    FilesystemObjectIdentity,
    UnsupportedFilesystemBackend,
    get_filesystem_backend,
)
from portable_resume.platform_fs.posix import PosixFilesystemBackend
from portable_resume.platform_fs.select import _reset_backend_cache
from portable_resume.platform_fs.windows import (
    WindowsFilesystemBackend,
    _handle_is_invalid,
    _invalid_handle_value,
)


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

    def test_unsupported_os_fails_closed_with_unsupported_backend(self) -> None:
        """Unknown platforms must select UnsupportedFilesystemBackend and fail closed."""
        with mock.patch("os.name", "unknown_os"), mock.patch("sys.platform", "unknown_os"):
            _reset_backend_cache()
            backend = get_filesystem_backend()
            self.assertIsInstance(backend, UnsupportedFilesystemBackend)
            self.assertFalse(backend.identity.is_posix)
            self.assertFalse(backend.identity.is_windows)

            d = backend.capabilities.to_dict()
            self.assertTrue(all(v is False for v in d.values()))

            with tempfile.TemporaryDirectory() as tmp_dir:
                file_path = os.path.join(tmp_dir, "test.txt")
                with self.assertRaises(DiagnosticError) as caught:
                    backend.read_regular_stable(file_path, root=tmp_dir)
                self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

                with self.assertRaises(DiagnosticError) as caught:
                    backend.inspect_object_identity(file_path, root=tmp_dir)
                self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

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

    def test_filesystem_object_identity_closed_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "node.txt")
            with open(file_path, "wb") as fp:
                fp.write(b"content")

            backend = get_filesystem_backend()
            obj_ident = backend.inspect_object_identity(file_path, root=tmp_dir)
            self.assertIsInstance(obj_ident, FilesystemObjectIdentity)
            self.assertEqual(obj_ident.object_type, "file")
            self.assertEqual(obj_ident.size, 7)
            self.assertTrue(isinstance(obj_ident.stable_id, str))
            self.assertTrue(isinstance(obj_ident.volume_id, str))

            d = obj_ident.to_dict()
            expected_keys = {
                "object_type",
                "stable_id",
                "volume_id",
                "size",
                "mtime_ns",
                "digest",
            }
            self.assertEqual(set(d.keys()), expected_keys)

    def test_windows_backend_phase4_relative_mutations(self) -> None:
        """Phase 4 advertises relative_mutations=True and functional relative mutations."""
        win_backend = WindowsFilesystemBackend()
        self.assertTrue(win_backend.capabilities.relative_mutations)
        self.assertTrue(win_backend.capabilities.exclusive_locking)
        self.assertTrue(win_backend.capabilities.handle_locking)
        self.assertTrue(win_backend.capabilities.sqlite_snapshots)
        self.assertTrue(win_backend.capabilities.atomic_output)
        self.assertTrue(win_backend.capabilities.nofollow_reads)

        with tempfile.TemporaryDirectory() as tmp_dir:
            target_sub = os.path.join(tmp_dir, "sub")
            res = win_backend.mkdirs_beneath(target_sub, root=tmp_dir)
            self.assertTrue(os.path.isdir(res))

            file_path = os.path.join(tmp_dir, "test.txt")
            with open(file_path, "wb") as fp:
                fp.write(b"data")

            target_path = os.path.join(tmp_dir, "dest.txt")
            win_backend.replace_beneath(file_path, target_path, root=tmp_dir)
            self.assertFalse(os.path.exists(file_path))
            self.assertTrue(os.path.exists(target_path))

            win_backend.unlink_beneath(target_path, root=tmp_dir)
            self.assertFalse(os.path.exists(target_path))

            # On non-Windows hosts kernel32 is unavailable → unsupported.
            # On Windows the real LockFileEx path is exercised separately.
            lock_path = os.path.join(tmp_dir, "test.lock")
            if os.name != "nt":
                with self.assertRaises(DiagnosticError) as caught:
                    with win_backend.acquire_exclusive_lock(lock_path):
                        pass
                self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

            # Read-only product surfaces work on the Windows backend even when
            # exercised from a non-Windows host (open/lstat fallback path).
            db_path = os.path.join(tmp_dir, "test.db")
            with open(db_path, "wb") as fp:
                fp.write(b"db-bytes")
            snap = win_backend.sqlite_family_snapshot(db_path, root=tmp_dir)
            try:
                self.assertTrue(os.path.isfile(snap.database))
                with open(snap.database, "rb") as fp:
                    self.assertEqual(fp.read(), b"db-bytes")
            finally:
                snap.close()

            output_path = os.path.join(tmp_dir, "out.txt")
            written = win_backend.atomic_replace_output(output_path, b"data")
            self.assertTrue(os.path.isfile(written))
            with open(written, "rb") as fp:
                self.assertEqual(fp.read(), b"data")

    def test_windows_backend_read(self) -> None:
        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "sample.txt")
            content = b"hello windows safe read"
            with open(file_path, "wb") as fp:
                fp.write(content)

            stable = win_backend.read_regular_stable(file_path, root=tmp_dir)
            self.assertEqual(stable.data, content)

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
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            with open(db_path, "wb") as fp:
                fp.write(b"sqlite data")

            with self.assertRaises(DiagnosticError) as caught:
                posix_backend.sqlite_family_snapshot(db_path, root=tmp_dir, max_bytes=-1)
            self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_posix_backend_selection_under_mock(self) -> None:
        try:
            with mock.patch("os.name", "posix"):
                _reset_backend_cache()
                backend = get_filesystem_backend()
                self.assertIsInstance(backend, PosixFilesystemBackend)
                self.assertTrue(backend.identity.is_posix)
                self.assertFalse(backend.identity.is_windows)
                self.assertTrue(backend.capabilities.descriptor_relative)
                self.assertFalse(backend.capabilities.relative_mutations)
                self.assertTrue(backend.capabilities.exclusive_locking)
        finally:
            _reset_backend_cache()

    def test_doctor_report_includes_filesystem_backend(self) -> None:
        report = doctor_report()
        self.assertIn("filesystem", report)
        self.assertIn("identity", report["filesystem"])
        self.assertIn("capabilities", report["filesystem"])
        fs_checks = [c for c in report["checks"] if c["id"] == "filesystem_backend"]
        self.assertEqual(len(fs_checks), 1)
    def test_windows_backend_reserved_device_names_rejection(self) -> None:
        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "CON.txt", "NUL.dat"):
                bad_path = os.path.join(tmp_dir, reserved)
                with self.assertRaises(DiagnosticError) as caught:
                    win_backend.read_regular_stable(bad_path, root=tmp_dir)
                self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

                with self.assertRaises(DiagnosticError) as caught:
                    win_backend.inspect_object_identity(bad_path, root=tmp_dir)
                self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_windows_backend_alternate_data_stream_rejection(self) -> None:
        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            ads_path = os.path.join(tmp_dir, "sample.txt:stream")
            with self.assertRaises(DiagnosticError) as caught:
                win_backend.read_regular_stable(ads_path, root=tmp_dir)
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_windows_backend_capabilities_honesty(self) -> None:
        win_backend = WindowsFilesystemBackend()
        self.assertTrue(win_backend.capabilities.nofollow_reads)
        self.assertTrue(win_backend.capabilities.reparse_points)
        self.assertTrue(win_backend.capabilities.sqlite_snapshots)
        self.assertTrue(win_backend.capabilities.atomic_output)
        self.assertTrue(win_backend.capabilities.exclusive_locking)
        self.assertTrue(win_backend.capabilities.handle_locking)
        self.assertFalse(win_backend.capabilities.descriptor_relative)
        self.assertTrue(win_backend.capabilities.relative_mutations)

    def test_windows_exclusive_lock_phase1_on_native_nt(self) -> None:
        """Phase 1: real LockFileEx path when running on Windows.

        Share mode allows concurrent CreateFile; exclusivity must come from
        LockFileEx (second acquire returns E_INSTALL_BUSY). After context exit,
        the lock is released and can be re-acquired.
        """
        if os.name != "nt":
            self.skipTest("native Windows LockFileEx only")
        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = os.path.join(tmp_dir, "phase1.lock")
            with win_backend.acquire_exclusive_lock(lock_path) as fd:
                self.assertIsInstance(fd, int)
                self.assertTrue(os.path.isfile(lock_path))
                # Second exclusive acquire must fail busy while first is held.
                with self.assertRaises(DiagnosticError) as caught:
                    with win_backend.acquire_exclusive_lock(lock_path):
                        pass
                self.assertEqual(caught.exception.code, "E_INSTALL_BUSY")
            # Unlock/close must release: reacquire after context exit.
            with win_backend.acquire_exclusive_lock(lock_path) as fd2:
                self.assertIsInstance(fd2, int)

    def test_handle_is_invalid_pointer_width_only(self) -> None:
        """Phase-2: invalid-handle uses full pointer-width sentinel, not low-32 alone.

        Regression pin: values whose *low* 32 bits are all ones but that are not
        the full-width INVALID_HANDLE_VALUE must be accepted on 64-bit (old code
        rejected them via ``(as_int & 0xFFFFFFFF) == 0xFFFFFFFF``).
        """
        import ctypes

        self.assertTrue(_handle_is_invalid(None))
        self.assertTrue(_handle_is_invalid(0))
        self.assertTrue(_handle_is_invalid(-1))
        self.assertTrue(_handle_is_invalid(_invalid_handle_value()))
        self.assertFalse(_handle_is_invalid(1))
        self.assertFalse(_handle_is_invalid(0x12345678))
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            # These would have been True under the removed low-32 heuristic.
            self.assertFalse(_handle_is_invalid(0xFFFFFFFF))
            self.assertFalse(_handle_is_invalid(0x1FFFFFFFF))
            self.assertFalse(_handle_is_invalid(0x00000001FFFFFFFF))

    def test_lock_source_fails_closed_when_handle_metadata_unproven(self) -> None:
        """Structural: GetFileInformationByHandle failure must not fall through to lock."""
        import inspect
        from portable_resume.platform_fs import windows as win_mod

        src = inspect.getsource(win_mod.WindowsFilesystemBackend.acquire_exclusive_lock)
        self.assertIn("GetFileInformationByHandle", src)
        self.assertIn("E_INSTALL_UNSUPPORTED_PLATFORM", src)
        # Former soft-continue wording must not return.
        self.assertNotIn("Attribute probe failure: continue", src)
        self.assertNotIn("LockFileEx still gates exclusivity", src)

    def test_lock_fails_closed_when_get_file_info_returns_false(self) -> None:
        """Native Windows: mock unproven leaf metadata → fail closed before LockFileEx."""
        if os.name != "nt":
            self.skipTest("requires native kernel32 + msvcrt")
        import portable_resume.platform_fs.windows as win_mod

        win_backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = os.path.join(tmp_dir, "meta-fail.lock")
            real_k32 = win_mod._get_kernel32()
            self.assertIsNotNone(real_k32)

            class _K32:
                def __init__(self, inner: object) -> None:
                    self._inner = inner
                    self.lock_calls = 0

                def CreateFileW(self, *args: object, **kwargs: object) -> object:
                    return self._inner.CreateFileW(*args, **kwargs)

                def GetFileInformationByHandle(self, *args: object, **kwargs: object) -> int:
                    return 0  # fail to prove attributes

                def LockFileEx(self, *args: object, **kwargs: object) -> int:
                    self.lock_calls += 1
                    return 0

                def UnlockFileEx(self, *args: object, **kwargs: object) -> int:
                    return 1

                def CloseHandle(self, *args: object, **kwargs: object) -> int:
                    return self._inner.CloseHandle(*args, **kwargs)

            fake = _K32(real_k32)
            with mock.patch.object(win_mod, "_get_kernel32", return_value=fake):
                with self.assertRaises(DiagnosticError) as caught:
                    with win_backend.acquire_exclusive_lock(lock_path):
                        pass
            self.assertEqual(caught.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(fake.lock_calls, 0, "LockFileEx must not run without proven metadata")


if __name__ == "__main__":
    unittest.main()

