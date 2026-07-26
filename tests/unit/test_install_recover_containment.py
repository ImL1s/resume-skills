"""Installer recover_root containment for complete journals (#20)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.transaction import (
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


if __name__ == "__main__":
    unittest.main()
