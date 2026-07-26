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
    _open_directory_under_root,
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

    @unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd commit path")
    def test_symlinked_skill_root_install_succeeds(self) -> None:
        """Dotfiles-style skill root symlink must still install on POSIX."""
        real_root = Path(self._tmpdir.name) / "real-skills"
        real_root.mkdir()
        link_root = Path(self._tmpdir.name) / "link-skills"
        link_root.symlink_to(real_root, target_is_directory=True)
        plan = plan_install(host="claude", scope="project", root=str(link_root))
        report = execute_install(plan)
        self.assertTrue(report.get("ok"), msg=repr(report))
        skill_md = real_root / "resume-claude" / "SKILL.md"
        self.assertTrue(skill_md.is_file(), msg=f"missing {skill_md}; report={report!r}")
        self.assertFalse(skill_md.is_symlink())

    def test_commit_fails_closed_without_descriptor_relative_support(self) -> None:
        stage = Path(self._tmpdir.name) / "stage"
        stage.mkdir()
        staged = stage / "SKILL.md"
        staged.write_bytes(b"hello\n")
        root = Path(self._tmpdir.name) / "skill-root"
        root.mkdir()
        with mock.patch.object(
            transaction_module,
            "_supports_descriptor_relative_commit",
            return_value=False,
        ):
            with self.assertRaises(DiagnosticError) as ctx:
                _commit_payload_file(
                    root=str(root),
                    root_fd=None,
                    rel="SKILL.md",
                    staged_src=str(staged),
                )
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        self.assertFalse((root / "SKILL.md").exists())

    @unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd commit path")
    def test_open_directory_under_root_closes_intermediate_fds(self) -> None:
        """Multi-component open must close intermediates and keep only the leaf."""
        root = Path(self._tmpdir.name) / "skill-root"
        nested = root / "a" / "b" / "c"
        nested.mkdir(parents=True)
        root_fd = _open_skill_root_descriptor(str(root))
        opened: list[int] = []
        closed: list[int] = []
        real_open = os.open
        real_close = os.close

        def tracking_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def tracking_close(fd: int) -> None:
            closed.append(fd)
            return real_close(fd)

        try:
            with mock.patch.object(os, "open", side_effect=tracking_open), mock.patch.object(
                os, "close", side_effect=tracking_close
            ):
                leaf_fd = _open_directory_under_root(root_fd, os.path.join("a", "b", "c"))
            self.assertEqual(len(opened), 3)
            self.assertEqual(closed, opened[:2])
            self.assertEqual(leaf_fd, opened[-1])
            self.assertNotIn(leaf_fd, closed)
            real_close(leaf_fd)
        finally:
            real_close(root_fd)


if __name__ == "__main__":
    unittest.main()
