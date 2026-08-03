"""Windows product mutations stay fail-closed despite the Phase-1 lock primitive."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError, ExitCode
from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.transaction import (
    RootLock,
    execute_install,
    plan_install,
    recover_root,
    require_mutating_install_platform,
    uninstall_claim,
    verify_root,
)


class WindowsPlatformGateTests(unittest.TestCase):
    def test_require_mutating_install_platform_fails_on_nt(self) -> None:
        with mock.patch("portable_resume.install.transaction.os.name", "nt"):
            with self.assertRaises(DiagnosticError) as ctx:
                require_mutating_install_platform()
        self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)

    def test_require_mutating_install_platform_ok_on_posix(self) -> None:
        with mock.patch("portable_resume.install.transaction.os.name", "posix"):
            require_mutating_install_platform()

    def test_root_lock_mocked_nt_on_non_windows_fail_closed_no_support(self) -> None:
        """Spoofed os.name==nt on POSIX must not create control state.

        Phase 3: real Windows RootLock uses Win32 exclusive lock (see
        tests/unit/test_rootlock_windows.py). This case only applies when the
        host is *not* real Windows — on real nt, RootLock is allowed to lock.
        """
        if os.name == "nt" and sys.platform.startswith("win"):
            self.skipTest("real Windows: RootLock Phase 3 path is intentional")
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            Path(root).mkdir()
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                with self.assertRaises(DiagnosticError) as ctx:
                    with RootLock(root):
                        pass
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            support = Path(root) / ".portable-resume"
            self.assertFalse(support.exists())

    def test_execute_install_mutation_fails_closed_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            project = Path(temporary) / "project"
            home.mkdir()
            project.mkdir()
            root = resolve_skill_root(
                host="claude",
                scope="project",
                project_dir=str(project),
                home_dir=str(home),
            )
            plan = plan_install(host="claude", scope="project", root=root)
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                with self.assertRaises(DiagnosticError) as ctx:
                    execute_install(plan)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertFalse(
                Path(root).exists()
                or any(Path(root).rglob("*") if Path(root).exists() else [])
            )

    def test_execute_install_dry_run_still_allowed_under_nt_mock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            project = Path(temporary) / "project"
            home.mkdir()
            project.mkdir()
            root = resolve_skill_root(
                host="claude",
                scope="project",
                project_dir=str(project),
                home_dir=str(home),
            )
            plan = plan_install(host="claude", scope="project", root=root, dry_run=True)
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                result = execute_install(plan)
            self.assertTrue(result["dry_run"])
            self.assertTrue(result["ok"])
            self.assertFalse(Path(root).exists(), "dry-run must not create the destination root")

    def test_uninstall_mutation_fails_closed_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            root.mkdir()
            sentinel = root / "keep.txt"
            sentinel.write_bytes(b"unchanged")
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                with self.assertRaises(DiagnosticError) as ctx:
                    uninstall_claim(host="claude", scope="project", root=str(root))
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(sentinel.read_bytes(), b"unchanged")
            self.assertFalse(
                (root / ".portable-resume").exists(),
                "the product gate must run before creating installer control state",
            )

    def test_recover_with_journal_fails_closed_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            support = root / ".portable-resume" / ".state"
            support.mkdir(parents=True)
            journal = support / "journal.json"
            journal.write_text("{}", encoding="utf-8")
            sentinel = root / "keep.txt"
            sentinel.write_bytes(b"unchanged")
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                with self.assertRaises(DiagnosticError) as ctx:
                    recover_root(str(root))
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(journal.read_text(encoding="utf-8"), "{}")
            self.assertEqual(sentinel.read_bytes(), b"unchanged")
            self.assertEqual(
                sorted(path.relative_to(root).as_posix() for path in root.rglob("*")),
                [
                    ".portable-resume",
                    ".portable-resume/.state",
                    ".portable-resume/.state/journal.json",
                    "keep.txt",
                ],
            )

    def test_recover_without_journal_noop_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            root.mkdir()
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                result = recover_root(str(root))
            self.assertEqual(result, {"ok": True, "recovered": False})
            self.assertEqual(list(root.iterdir()), [])

    def test_verify_root_is_observational_on_nt_not_platform_gated(self) -> None:
        """Verify stays read-only on Windows and does not construct RootLock."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            state = root / ".portable-resume" / ".state"
            state.mkdir(parents=True)
            manifest = state / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            root_s = str(root)

            lock_calls: list[str] = []

            class _BoomLock:
                def __init__(self, locked_root: str) -> None:
                    lock_calls.append(locked_root)

                def __enter__(self) -> "_BoomLock":
                    raise AssertionError("RootLock must not be entered on nt")

                def __exit__(self, *args: object) -> None:
                    return None

            with mock.patch("portable_resume.install.transaction.os.name", "nt"), mock.patch(
                "portable_resume.install.transaction.RootLock",
                _BoomLock,
            ):
                with self.assertRaises(DiagnosticError) as ctx:
                    verify_root(root_s)
            self.assertEqual(ctx.exception.code, "E_VERIFY_MISMATCH")
            self.assertNotEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(lock_calls, [], "RootLock must not be constructed on nt")
            self.assertEqual(manifest.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
