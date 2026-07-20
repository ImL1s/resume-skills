"""Installer journal recovery, mutation blocking, and claim lifecycle (shipped APIs)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.transaction import (
    execute_install,
    journal_path,
    load_manifest,
    plan_install,
    recover_root,
    require_no_pending_journal,
    uninstall_claim,
    verify_root,
    _write_journal,
)


class InstallerTransactionTests(unittest.TestCase):
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

    def test_pending_journal_blocks_mutation_until_recover(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        execute_install(plan)
        verify_root(self.root)
        # simulate crash mid-commit
        os.makedirs(os.path.join(self.root, ".portable-resume"), exist_ok=True)
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "committing",
                "generation": 99,
                "claim": "synthetic",
                "stage_dir": os.path.join(self.root, ".portable-resume", "stage-missing"),
                "backup_root": os.path.join(self.root, ".portable-resume", "backups", "x"),
                "paths": {},
            },
        )
        with self.assertRaises(DiagnosticError) as ctx:
            require_no_pending_journal(self.root)
        self.assertEqual(ctx.exception.code, "E_RECOVERY_REQUIRED")
        with self.assertRaises(DiagnosticError) as ctx2:
            execute_install(plan_install(host="claude", scope="project", root=self.root))
        self.assertEqual(ctx2.exception.code, "E_RECOVERY_REQUIRED")
        with self.assertRaises(DiagnosticError) as ctx3:
            verify_root(self.root)
        self.assertEqual(ctx3.exception.code, "E_RECOVERY_REQUIRED")

        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
        self.assertTrue(recovered["recovered"])
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        # mutations allowed again
        verify_root(self.root)
        plan2 = plan_install(host="claude", scope="project", root=self.root)
        result = execute_install(plan2)
        self.assertTrue(result["ok"])

    def test_complete_stale_journal_is_cleared_by_recover(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        execute_install(plan)
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "complete",
                "generation": 1,
                "claim": "x",
                "stage_dir": None,
                "backup_root": None,
                "paths": {},
            },
        )
        out = recover_root(self.root)
        self.assertEqual(out.get("action"), "cleared_complete_journal")
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        verify_root(self.root)

    def test_journal_path_escape_is_ignored_on_recover(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        execute_install(plan)
        os.makedirs(os.path.join(self.root, ".portable-resume"), exist_ok=True)
        outside = Path(self._tmpdir.name) / "outside.txt"
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "committing",
                "generation": 2,
                "claim": "x",
                "stage_dir": None,
                "backup_root": None,
                "paths": {
                    "../outside.txt": {
                        "state": "committed",
                        "sha256": "00",
                        "backup": str(outside),
                    }
                },
            },
        )
        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
        self.assertFalse(outside.exists())

    def test_uninstall_preserves_unrelated_claim_on_shared_explicit_root(self) -> None:
        # two claims on distinct host roots — uninstall only selected claim
        root_a = str(self.project / "skills-a")
        root_b = str(self.project / "skills-b")
        execute_install(plan_install(host="claude", scope="project", root=root_a))
        execute_install(plan_install(host="grok", scope="project", root=root_b))
        uninstall_claim(host="claude", scope="project", root=root_a)
        self.assertIsNone(load_manifest(root_a))
        self.assertIsNotNone(load_manifest(root_b))
        verify_root(root_b)


if __name__ == "__main__":
    unittest.main()
