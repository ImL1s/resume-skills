"""Installer payload commit containment (#31)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.catalog import resolve_skill_root
import portable_resume.install.transaction as transaction_module
from portable_resume.install.transaction import execute_install, plan_install


class InstallCommitContainmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name) / "home"
        self.project = Path(self._tmpdir.name) / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.root = resolve_skill_root(
            host="claude",
            scope="project",
            project_dir=str(self.project),
            home_dir=str(self.home),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_parent_directory_symlink_swap_during_commit_fails_closed(self) -> None:
        outside = Path(self._tmpdir.name) / "outside-escape"
        outside.mkdir()
        marker = outside / "escaped.txt"

        execute_install(plan_install(host="claude", scope="project", root=self.root))
        skill_md = Path(self.root) / "resume-claude" / "SKILL.md"
        skill_md.write_bytes(skill_md.read_bytes() + b"\n# tamper\n")
        plan = plan_install(host="claude", scope="project", root=self.root)

        original_commit = transaction_module._commit_payload_file

        def commit_with_parent_symlink_swap(*args, **kwargs):
            parent = Path(self.root) / "resume-claude"
            if parent.is_dir() and not parent.is_symlink():
                backup = Path(self.root) / "resume-claude.bak"
                if backup.exists():
                    shutil.rmtree(backup)
                parent.rename(backup)
                parent.symlink_to(outside, target_is_directory=True)
            return original_commit(*args, **kwargs)

        with mock.patch.object(
            transaction_module,
            "_commit_payload_file",
            side_effect=commit_with_parent_symlink_swap,
        ):
            with self.assertRaises(DiagnosticError) as ctx:
                execute_install(plan)
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        self.assertFalse(marker.exists())
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
