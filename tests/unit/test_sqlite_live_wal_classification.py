from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from portable_resume.adapters import cline, crush, goose, hermes, openclaw
from portable_resume.bounds import DEFAULT_BOUNDS, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query


class SqliteLiveWalClassificationTests(unittest.TestCase):
    def test_probe_classifies_live_wal_as_unsafe_not_unsupported(self) -> None:
        cases = (
            (goose, "goose", Path("tests/fixtures/goose/s-go-01-user-basic"), "sessions/sessions.db"),
            (crush, "crush", Path("tests/fixtures/crush/s-cr-01-user-basic"), ".crush/crush.db"),
            (hermes, "hermes", Path("tests/fixtures/hermes/s-hm-01-user-basic"), "state.db"),
            (cline, "cline", Path("tests/fixtures/cline/s-cl-01-user-basic"), "data/db/sessions.db"),
            (
                openclaw,
                "openclaw",
                Path("tests/fixtures/openclaw/s-oc-01-basic"),
                "agents/main/agent/openclaw-agent.sqlite",
            ),
        )
        lowered = replace(DEFAULT_BOUNDS, sqlite_snapshot_bytes=1)
        for module, source, fixture, relative_database in cases:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "root"
                shutil.copytree(fixture, root)
                database = root / relative_database
                Path(f"{database}-wal").write_bytes(b"synthetic wal")
                Path(f"{database}-shm").write_bytes(b"synthetic shm")
                cwd = str(root) if source == "crush" else "/tmp/project"
                query = Query(source=source, cwd=cwd, source_root=str(root), within_min=0)
                with mock.patch.object(module, "DEFAULT_BOUNDS", lowered):
                    report = module.ADAPTER.probe(query)
                self.assertEqual(report.state, "unsafe")

    def test_list_preserves_live_wal_exit_six_diagnostic(self) -> None:
        lowered = replace(DEFAULT_BOUNDS, sqlite_snapshot_bytes=1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            shutil.copytree(Path("tests/fixtures/goose/s-go-01-user-basic"), root)
            database = root / "sessions/sessions.db"
            Path(f"{database}-wal").write_bytes(b"synthetic wal")
            Path(f"{database}-shm").write_bytes(b"synthetic shm")
            query = Query(
                source="goose",
                cwd="/tmp/project",
                source_root=str(root),
                within_min=0,
            )
            with mock.patch.object(goose, "DEFAULT_BOUNDS", lowered):
                with self.assertRaises(DiagnosticError) as caught:
                    goose.ADAPTER.list(query, ReadBudget(lowered))
            self.assertEqual(caught.exception.code, "E_SQLITE_LIVE_WAL")
            self.assertEqual(caught.exception.exit_code, 6)


if __name__ == "__main__":
    unittest.main()
