"""Residual honesty contract for issue #125 (Windows mutating install Policy B).

#125 **product** install/uninstall/recover is NOT claimed complete. Phase 1 may
ship an exclusive-lock primitive on WindowsFilesystemBackend, but:

- relative_mutations stays False; mkdirs/unlink/replace_beneath fail closed
- require_mutating_install_platform and doctor windows_mutating_install still
  report unsupported on nt (transaction gate remains Policy B)
- Full RootLock wire + reparse-safe install transaction is out of scope here
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from portable_resume.adapters.base import CapabilityReport
from portable_resume.diagnostics import DiagnosticError, ExitCode
from portable_resume.discover_doctor import doctor_report
from portable_resume.install.transaction import require_mutating_install_platform
from portable_resume.platform_fs import get_filesystem_backend
from portable_resume.platform_fs.posix import PosixFilesystemBackend
from portable_resume.platform_fs.select import _reset_backend_cache
from portable_resume.platform_fs.windows import WindowsFilesystemBackend


def _stub_load_adapter(source: str):
    """Content-free adapter so doctor never lists sessions."""

    class _Adapter:
        key = source

        def probe(self, query):  # noqa: ANN001
            return CapabilityReport(source, f"{source}-fmt", "unavailable")

        def list(self, query, budget):  # noqa: ANN001
            raise AssertionError("doctor residual contract must not list sessions")

    return _Adapter()


class Issue125ResidualWindowsBackendContractTests(unittest.TestCase):
    """WindowsFilesystemBackend residual capabilities + fail-closed mutations."""

    def test_windows_backend_capabilities_mutations_disabled_lock_phase1(self) -> None:
        backend = WindowsFilesystemBackend()
        caps = backend.capabilities
        # Phase 1 may enable exclusive/handle locking; relative mutations stay off.
        self.assertIs(caps.relative_mutations, False)
        self.assertIs(caps.exclusive_locking, True)
        self.assertIs(caps.handle_locking, True)
        self.assertEqual(backend.identity.backend_name, "WindowsFilesystemBackend")

    def test_windows_mutating_surfaces_raise_e_install_unsupported_platform(self) -> None:
        """Relative mutations stay fail-closed; lock is Phase-1-only (not install gate)."""
        backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            sub = os.path.join(tmp_dir, "nested")
            leaf = os.path.join(tmp_dir, "leaf.txt")
            dest = os.path.join(tmp_dir, "dest.txt")
            lock_path = os.path.join(tmp_dir, "install.lock")
            with open(leaf, "wb") as handle:
                handle.write(b"payload")

            with self.assertRaises(DiagnosticError) as ctx:
                backend.mkdirs_beneath(sub, root=tmp_dir)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)

            with self.assertRaises(DiagnosticError) as ctx:
                backend.unlink_beneath(leaf, root=tmp_dir)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

            with self.assertRaises(DiagnosticError) as ctx:
                backend.replace_beneath(leaf, dest, root=tmp_dir)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

            # Phase 1: exclusive lock is implemented only where Win32 APIs exist.
            # On non-nt hosts, WindowsFilesystemBackend still fail-closes the lock
            # path (no kernel32); product install remains gated elsewhere.
            if os.name == "nt":
                with backend.acquire_exclusive_lock(lock_path) as fd:
                    self.assertIsInstance(fd, int)
                    self.assertGreaterEqual(fd, 0)
            else:
                with self.assertRaises(DiagnosticError) as ctx:
                    with backend.acquire_exclusive_lock(lock_path):
                        pass
                self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
                self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)


class Issue125ResidualPlatformGateContractTests(unittest.TestCase):
    """Installer platform gate + doctor honesty for residual Policy B."""

    def test_require_mutating_install_platform_raises_on_nt_mock(self) -> None:
        with mock.patch("portable_resume.install.transaction.os.name", "nt"):
            with self.assertRaises(DiagnosticError) as ctx:
                require_mutating_install_platform()
        self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)

    def test_require_mutating_install_platform_ok_on_posix_mock(self) -> None:
        with mock.patch("portable_resume.install.transaction.os.name", "posix"):
            require_mutating_install_platform()

    def test_doctor_report_windows_mutating_install_false_on_nt_mock(self) -> None:
        with mock.patch("portable_resume.discover_doctor.os.name", "nt"):
            report = doctor_report(cwd=os.getcwd(), load_adapter=_stub_load_adapter)
        self.assertIs(report["platform"]["windows_mutating_install"], False)
        self.assertEqual(report["platform"]["os_name"], "nt")
        policy = next(c for c in report["checks"] if c["id"] == "windows_install_policy")
        self.assertEqual(policy["status"], "info")
        self.assertIn("fail-closed", policy["detail"])


class Issue125ResidualRealHostContractTests(unittest.TestCase):
    """Host-truth residual: real os.name must match backend + doctor claims."""

    def setUp(self) -> None:
        _reset_backend_cache()

    def tearDown(self) -> None:
        _reset_backend_cache()

    def test_real_host_backend_and_doctor_align_with_os_name(self) -> None:
        backend = get_filesystem_backend()
        report = doctor_report(cwd=os.getcwd(), load_adapter=_stub_load_adapter)
        windows_mutating = report["platform"]["windows_mutating_install"]

        if os.name == "nt":
            self.assertIsInstance(backend, WindowsFilesystemBackend)
            # Phase 1: exclusive/handle locking true; relative mutations still off.
            self.assertIs(backend.capabilities.exclusive_locking, True)
            self.assertIs(backend.capabilities.handle_locking, True)
            self.assertIs(backend.capabilities.relative_mutations, False)
            # Product install gate stays fail-closed regardless of lock caps.
            self.assertIs(windows_mutating, False)
            with self.assertRaises(DiagnosticError) as ctx:
                require_mutating_install_platform()
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
        else:
            # POSIX residual path: exclusive locking is available; doctor must
            # report mutating install supported (windows_mutating_install True).
            self.assertIsInstance(backend, PosixFilesystemBackend)
            self.assertIs(backend.capabilities.exclusive_locking, True)
            self.assertIs(windows_mutating, True)
            require_mutating_install_platform()


if __name__ == "__main__":
    unittest.main()
