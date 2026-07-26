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
from portable_resume.install.transaction import (
    _commit_payload_file,
    _open_skill_root_descriptor,
    _supports_descriptor_relative_commit,
    execute_install,
    plan_install,
)


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

    @unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd commit path")
    def test_top_level_commits_reuse_root_fd(self) -> None:
        """Committing files at skill root must not close root_fd between files."""
        root = str(Path(self._tmpdir.name) / "skill-root")
        os.makedirs(root, mode=0o755)
        root_fd = _open_skill_root_descriptor(root)
        try:
            stage_dir = Path(self._tmpdir.name) / "stage"
            stage_dir.mkdir()
            first_stage = stage_dir / "first.txt"
            second_stage = stage_dir / "second.txt"
            first_stage.write_bytes(b"first\n")
            second_stage.write_bytes(b"second\n")
            _commit_payload_file(root=root, root_fd=root_fd, rel="first.txt", staged_src=str(first_stage))
            _commit_payload_file(root=root, root_fd=root_fd, rel="second.txt", staged_src=str(second_stage))
        finally:
            os.close(root_fd)
        self.assertEqual((Path(root) / "first.txt").read_bytes(), b"first\n")
        self.assertEqual((Path(root) / "second.txt").read_bytes(), b"second\n")


if __name__ == "__main__":
    unittest.main()
