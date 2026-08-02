"""Residual honesty contract for issue #125 (Windows mutating install Policy B).

#125 productization (Win32 exclusive handle locking + reparse-safe relative
mutations) is NOT claimed. Until that lands, the residual contract is:

- WindowsFilesystemBackend must advertise no exclusive/handle locking and no
  relative mutations.
- Mutating backend surfaces (lock + mkdirs/unlink/replace_beneath) must fail
  closed with E_INSTALL_UNSUPPORTED_PLATFORM and leave the filesystem unchanged.
- require_mutating_install_platform and doctor_report must honestly report
  Windows mutating install as unsupported (os.name == "nt").

This module strengthens regression coverage so silent unlocked mutation or
support-claim drift cannot land without breaking these assertions. Full Win32
locking is out of scope; STATUS claim boundaries are enforced by check_docs.py.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
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


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    """Return a deterministic content/type snapshot without following symlinks."""

    snapshot: dict[str, tuple[str, bytes | str | None]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[rel] = ("symlink", os.readlink(path))
        elif path.is_file():
            snapshot[rel] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[rel] = ("directory", None)
        else:
            snapshot[rel] = ("other", None)
    return snapshot


class Issue125ResidualWindowsBackendContractTests(unittest.TestCase):
    """WindowsFilesystemBackend residual capabilities + fail-closed mutations."""

    def test_windows_backend_capabilities_lock_and_mutations_disabled(self) -> None:
        backend = WindowsFilesystemBackend()
        caps = backend.capabilities
        self.assertIs(caps.exclusive_locking, False)
        self.assertIs(caps.handle_locking, False)
        self.assertIs(caps.relative_mutations, False)
        self.assertEqual(backend.identity.backend_name, "WindowsFilesystemBackend")

    def test_windows_mutating_surfaces_raise_e_install_unsupported_platform(self) -> None:
        backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            sub = root / "nested"
            leaf = root / "leaf.txt"
            dest = root / "dest.txt"
            lock_path = root / "root.lock"
            leaf.write_bytes(b"payload")
            baseline = _tree_snapshot(root)

            with self.assertRaises(DiagnosticError) as ctx:
                backend.mkdirs_beneath(sub, root=root)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)
            self.assertEqual(_tree_snapshot(root), baseline)

            with self.assertRaises(DiagnosticError) as ctx:
                backend.unlink_beneath(leaf, root=root)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(_tree_snapshot(root), baseline)

            with self.assertRaises(DiagnosticError) as ctx:
                backend.replace_beneath(leaf, dest, root=root)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(_tree_snapshot(root), baseline)

            with self.assertRaises(DiagnosticError) as ctx:
                with backend.acquire_exclusive_lock(lock_path):
                    pass
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)
            self.assertEqual(_tree_snapshot(root), baseline)


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
            self.assertIs(backend.capabilities.exclusive_locking, False)
            self.assertIs(backend.capabilities.handle_locking, False)
            self.assertIs(backend.capabilities.relative_mutations, False)
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
