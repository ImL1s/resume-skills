"""Residual honesty contract for issue #125 (Windows mutating install Phase 7).

#125 **product** install/uninstall/recover IS claimed complete via Phase 7.
Phases 1–6 established exclusive Win32 locking, reparse-safe mutations,
parent-chain defenses, and adversarial product-path evidence.  Phase 7
lifts the Policy B gate on real Windows.

- relative_mutations is True; mkdirs/unlink/replace_beneath are functional
- require_mutating_install_platform() passes on real Windows
- doctor reports windows_mutating_install = True on real Windows
- Mocked os.name=="nt" on non-Windows hosts still fail-closed
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
    """WindowsFilesystemBackend Phase-4 capabilities + relative mutations."""

    def test_windows_backend_capabilities_phase4(self) -> None:
        backend = WindowsFilesystemBackend()
        caps = backend.capabilities
        self.assertIs(caps.relative_mutations, True)
        self.assertIs(caps.exclusive_locking, True)
        self.assertIs(caps.handle_locking, True)
        self.assertEqual(backend.identity.backend_name, "WindowsFilesystemBackend")

    def test_windows_relative_mutations_functional_under_temp_root(self) -> None:
        backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            sub = root / "nested"
            leaf = root / "leaf.txt"
            dest = root / "dest.txt"
            leaf.write_bytes(b"payload")

            created = backend.mkdirs_beneath(sub, root=root)
            self.assertTrue(Path(created).is_dir())

            backend.replace_beneath(leaf, dest, root=root)
            self.assertFalse(leaf.exists())
            self.assertEqual(dest.read_bytes(), b"payload")

            backend.unlink_beneath(dest, root=root)
            self.assertFalse(dest.exists())

    def test_phase1_lock_is_native_only_and_not_a_relative_mutation_claim(self) -> None:
        backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            lock_path = root / "install.lock"
            baseline = _tree_snapshot(root)

            if os.name == "nt":
                with backend.acquire_exclusive_lock(lock_path) as fd:
                    self.assertIsInstance(fd, int)
                    self.assertGreaterEqual(fd, 0)
                    self.assertTrue(lock_path.is_file())
                self.assertEqual(lock_path.read_bytes(), b"")
                self.assertEqual(
                    _tree_snapshot(root),
                    {"install.lock": ("file", b"")},
                )
            else:
                with self.assertRaises(DiagnosticError) as ctx:
                    with backend.acquire_exclusive_lock(lock_path):
                        pass
                self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
                self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)
                self.assertEqual(_tree_snapshot(root), baseline)


class Issue125ResidualPlatformGateContractTests(unittest.TestCase):
    """Installer platform gate + doctor honesty for residual Policy B."""

    def test_require_mutating_install_platform_raises_on_spoofed_nt(self) -> None:
        """Mocked nt on non-Windows host still fails closed."""
        with mock.patch("portable_resume.install.transaction.os.name", "nt"), \
             mock.patch("portable_resume.install.transaction.sys") as mock_sys:
            mock_sys.platform = "linux"
            with self.assertRaises(DiagnosticError) as ctx:
                require_mutating_install_platform()
        self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)

    def test_require_mutating_install_platform_ok_on_posix_mock(self) -> None:
        with mock.patch("portable_resume.install.transaction.os.name", "posix"):
            require_mutating_install_platform()

    def test_doctor_report_windows_mutating_install_on_nt_mock(self) -> None:
        """Doctor on mocked nt with non-Windows sys.platform reports fail-closed."""
        with mock.patch("portable_resume.discover_doctor.os.name", "nt"), \
             mock.patch("portable_resume.discover_doctor.sys") as mock_sys:
            mock_sys.platform = "linux"
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
            self.assertIs(backend.capabilities.exclusive_locking, True)
            self.assertIs(backend.capabilities.handle_locking, True)
            self.assertIs(backend.capabilities.relative_mutations, True)
            # Phase 7: real Windows now reports windows_mutating_install = True
            self.assertIs(windows_mutating, True)
            # Phase 7: real Windows no longer raises
            require_mutating_install_platform()
        else:
            self.assertIsInstance(backend, PosixFilesystemBackend)
            self.assertIs(backend.capabilities.exclusive_locking, True)
            self.assertIs(windows_mutating, True)
            require_mutating_install_platform()


if __name__ == "__main__":
    unittest.main()
