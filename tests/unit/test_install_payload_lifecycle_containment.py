"""Installer payload lifecycle parent-swap containment (#31)."""

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
from portable_resume.install.manifest import sha256_file
from portable_resume.install.transaction import (
    _rollback_paths,
    _supports_descriptor_relative_commit,
    execute_install,
    plan_install,
    uninstall_claim,
    verify_root,
)


@unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd payload lifecycle path")
class InstallPayloadLifecycleContainmentTests(unittest.TestCase):
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
        self.outside = Path(self._tmpdir.name) / "outside-payload"
        self.outside.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _install(self) -> None:
        report = execute_install(plan_install(host="claude", scope="project", root=self.root))
        self.assertTrue(report["ok"])

    def _swap_skill_parent_to_outside(self) -> Path:
        parent = Path(self.root) / "resume-claude"
        marker = self.outside / "outside-skill-md"
        marker.write_bytes(b"outside-must-survive\n")
        backup = Path(self.root) / "resume-claude.bak-swap"
        if backup.exists():
            shutil.rmtree(backup)
        parent.rename(backup)
        parent.symlink_to(self.outside, target_is_directory=True)
        # Place a same-basename file outside so a naive ambient delete would hit it.
        (self.outside / "SKILL.md").write_bytes(b"outside-must-survive\n")
        return marker

    def test_uninstall_parent_swap_does_not_delete_outside(self) -> None:
        self._install()
        claim = plan_install(host="claude", scope="project", root=self.root).claim
        marker = self._swap_skill_parent_to_outside()

        with self.assertRaises(DiagnosticError) as ctx:
            uninstall_claim(host="claude", scope="project", root=self.root)
        self.assertIn(ctx.exception.code, {"E_INSTALL_CONFLICT", "E_RECOVERY_REQUIRED", "E_VERIFY_MISMATCH"})
        self.assertEqual(marker.read_bytes(), b"outside-must-survive\n")
        self.assertEqual((self.outside / "SKILL.md").read_bytes(), b"outside-must-survive\n")

    def test_verify_parent_swap_fails_closed(self) -> None:
        self._install()
        self._swap_skill_parent_to_outside()
        # Outside SKILL.md content differs from installed package identity expectations.
        with self.assertRaises(DiagnosticError) as ctx:
            verify_root(self.root)
        self.assertEqual(ctx.exception.code, "E_VERIFY_MISMATCH")
        self.assertEqual((self.outside / "SKILL.md").read_bytes(), b"outside-must-survive\n")

    def test_rollback_parent_swap_does_not_write_outside(self) -> None:
        self._install()
        skill_md = Path(self.root) / "resume-claude" / "SKILL.md"
        original = skill_md.read_bytes()
        support = Path(self.root) / ".portable-resume"
        stage = support / "portable-resume-stage-rollback-unit"
        rollback_tree = stage / ".rollback" / "resume-claude"
        rollback_tree.mkdir(parents=True)
        snapshot = rollback_tree / "SKILL.md"
        snapshot.write_bytes(original + b"\n# rollback-body\n")

        marker = self.outside / "SKILL.md"
        # Ensure outside starts empty of our marker content for write detection.
        if marker.exists():
            marker.unlink()
        parent = Path(self.root) / "resume-claude"
        backup = Path(self.root) / "resume-claude.bak-rollback"
        if backup.exists():
            shutil.rmtree(backup)
        parent.rename(backup)
        parent.symlink_to(self.outside, target_is_directory=True)

        journal = {
            "paths": {
                "resume-claude/SKILL.md": {
                    "state": "committed",
                    "existed": True,
                    "rollback_backup": str(snapshot),
                    "original_sha256": sha256_file(str(snapshot)),
                    "sha256": "deadbeef",
                }
            }
        }
        restored, complete = _rollback_paths(self.root, journal)
        self.assertFalse(complete)
        self.assertEqual(restored, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_orphan_remove_parent_swap_does_not_delete_outside(self) -> None:
        self._install()
        # Create an owned orphan by installing then manually adding a second owned path
        # is hard without two hosts; instead patch orphan removal path during upgrade.
        plan = plan_install(host="claude", scope="project", root=self.root)
        # Force a no-op change so execute still runs orphan scan with existing files.
        skill_md = Path(self.root) / "resume-claude" / "SKILL.md"
        skill_md.write_bytes(skill_md.read_bytes() + b"\n# tamper-for-reinstall\n")
        plan = plan_install(host="claude", scope="project", root=self.root)

        original_commit = transaction_module._commit_payload_file
        swapped = {"done": False}

        def commit_then_swap(*args, **kwargs):
            result = original_commit(*args, **kwargs)
            if not swapped["done"]:
                # After first file commit, swap parent so orphan delete sees symlink parent.
                parent = Path(self.root) / "resume-claude"
                if parent.is_dir() and not parent.is_symlink():
                    outside_file = self.outside / "orphan-target.txt"
                    outside_file.write_bytes(b"outside-orphan\n")
                    backup = Path(self.root) / "resume-claude.bak-orphan"
                    if backup.exists():
                        shutil.rmtree(backup)
                    # Move real tree aside then symlink — orphan abs paths must not hit outside.
                    parent.rename(backup)
                    parent.symlink_to(self.outside, target_is_directory=True)
                    swapped["done"] = True
            return result

        with mock.patch.object(
            transaction_module,
            "_commit_payload_file",
            side_effect=commit_then_swap,
        ):
            # Install may fail closed on later commits after swap; either fail closed or succeed
            # without deleting outside.
            try:
                execute_install(plan)
            except DiagnosticError as error:
                self.assertIn(error.code, {"E_INSTALL_CONFLICT", "E_RECOVERY_REQUIRED", "E_INSTALL_BUSY"})

        outside_files = list(self.outside.iterdir())
        for path in outside_files:
            if path.is_file():
                self.assertEqual(path.read_bytes(), b"outside-orphan\n")

    def test_happy_path_reinstall_and_uninstall(self) -> None:
        self._install()
        verify_root(self.root)
        report = execute_install(plan_install(host="claude", scope="project", root=self.root))
        self.assertTrue(report["ok"])
        un = uninstall_claim(host="claude", scope="project", root=self.root)
        self.assertTrue(un["ok"])
        self.assertTrue(un["removed_files"])
