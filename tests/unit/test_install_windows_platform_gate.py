"""Windows mutating installer ops must fail closed without exclusive lock (#29)."""

from __future__ import annotations

import os
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
            require_mutating_install_platform()  # no raise

    def test_root_lock_does_not_create_support_on_windows(self) -> None:
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
            self.assertFalse(Path(root).exists() or any(Path(root).rglob("*") if Path(root).exists() else []))

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

    def test_uninstall_mutation_fails_closed_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            Path(root).mkdir()
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                with self.assertRaises(DiagnosticError) as ctx:
                    uninstall_claim(host="claude", scope="project", root=root)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

    def test_recover_with_journal_fails_closed_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            support = root / ".portable-resume" / ".state"
            support.mkdir(parents=True)
            (support / "journal.json").write_text("{}", encoding="utf-8")
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                with self.assertRaises(DiagnosticError) as ctx:
                    recover_root(str(root))
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")

    def test_recover_without_journal_noop_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            root.mkdir()
            with mock.patch("portable_resume.install.transaction.os.name", "nt"):
                result = recover_root(str(root))
            self.assertEqual(result, {"ok": True, "recovered": False})


if __name__ == "__main__":
    unittest.main()
