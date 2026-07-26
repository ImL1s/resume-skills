"""Installer recover_root containment for complete journals (#20)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.catalog import resolve_skill_root
import portable_resume.install.transaction as transaction_module
from portable_resume.install.transaction import (
    _safe_rmtree_under_support,
    _supports_descriptor_relative_commit,
    _write_journal,
    journal_path,
    recover_root,
)


class RecoverCompleteJournalContainmentTests(unittest.TestCase):
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
        os.makedirs(os.path.join(self.root, ".portable-resume"), exist_ok=True)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_recover_complete_journal_does_not_delete_escaped_stage_dir(self) -> None:
        escaped_stage = Path(self._tmpdir.name) / "escaped-stage"
        escaped_stage.mkdir()
        marker = escaped_stage / "keep-me.txt"
        marker.write_text("must survive recover", encoding="utf-8")

        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "complete",
                "generation": 1,
                "claim": "x",
                "stage_dir": str(escaped_stage),
                "backup_root": None,
                "paths": {},
            },
        )

        with self.assertRaises(DiagnosticError) as ctx:
            recover_root(self.root)
        self.assertEqual(ctx.exception.code, "E_RECOVERY_REQUIRED")
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_text(encoding="utf-8"), "must survive recover")
        self.assertTrue(os.path.isfile(journal_path(self.root)))

    @unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd recovery delete path")
    def test_safe_rmtree_rejects_symlinked_cleanup_target(self) -> None:
        """P1-B: symlinked stage/backup paths must not delete the link target."""
        support = Path(self.root) / ".portable-resume"
        real_target = support / "real-stage"
        real_target.mkdir(parents=True)
        marker = real_target / "keep-me.txt"
        marker.write_text("must survive cleanup", encoding="utf-8")

        symlink_stage = support / "portable-resume-stage-symlink"
        symlink_stage.symlink_to(real_target, target_is_directory=True)

        with self.assertRaises(DiagnosticError) as ctx:
            _safe_rmtree_under_support(self.root, str(symlink_stage))
        self.assertEqual(ctx.exception.code, "E_RECOVERY_REQUIRED")
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_text(encoding="utf-8"), "must survive cleanup")

    @unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd recovery delete path")
    def test_stage_symlink_swap_before_delete_does_not_escape(self) -> None:
        support = Path(self.root) / ".portable-resume"
        stage_dir = support / "portable-resume-stage-test"
        stage_dir.mkdir(parents=True)
        (stage_dir / "staged.txt").write_text("stage payload", encoding="utf-8")

        outside = Path(self._tmpdir.name) / "victim-outside"
        outside.mkdir()
        marker = outside / "keep-me.txt"
        marker.write_text("must survive recover", encoding="utf-8")

        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "complete",
                "generation": 1,
                "claim": "x",
                "stage_dir": str(stage_dir),
                "backup_root": None,
                "paths": {},
            },
        )

        original_try = transaction_module._try_safe_rmtree_under_support

        def try_with_stage_symlink_swap(root: str, path: str) -> None:
            stage_path = Path(path)
            if stage_path.exists() and not stage_path.is_symlink():
                real_stage = stage_path.with_name(stage_path.name + ".real")
                stage_path.rename(real_stage)
                stage_path.symlink_to(outside, target_is_directory=True)
            return original_try(root, path)

        with mock.patch.object(
            transaction_module,
            "_try_safe_rmtree_under_support",
            side_effect=try_with_stage_symlink_swap,
        ):
            result = recover_root(self.root)

        self.assertTrue(result.get("recovered"))
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_text(encoding="utf-8"), "must survive recover")
        self.assertFalse(os.path.isfile(journal_path(self.root)))


if __name__ == "__main__":
    unittest.main()
