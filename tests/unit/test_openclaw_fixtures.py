from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path


OPENCLAW_FIXTURES = Path("tests/fixtures/openclaw")
_BUILDER = OPENCLAW_FIXTURES / "build_fixtures.py"
_AGENT_DB = re.compile(r"agents/[^/]+/agent/openclaw-agent\.sqlite$")
_CORRUPT_CASE = "s-oc-05-corrupt-meta"
_ABSURD_SCHEMA_VERSION = 99_999
_SCHEMA_VERSION = 11
_REQUIRED_TABLES = frozenset(
    {
        "schema_meta",
        "session_nodes",
        "session_windows",
        "conversations",
        "session_conversations",
        "transcript_events",
    }
)


def _load_builder():
    spec = importlib.util.spec_from_file_location("openclaw_build_fixtures", _BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load openclaw fixture builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpenClawFixtureTests(unittest.TestCase):
    def test_paths_are_clean_and_manifests_are_synthetic(self) -> None:
        manifests = sorted(OPENCLAW_FIXTURES.glob("s-oc-*/fixture.json"))
        self.assertEqual(len(manifests), 5)
        for manifest_path in manifests:
            for path in manifest_path.parent.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_bytes()
                self.assertNotIn(b"/Users/", text, msg=str(path))
                self.assertNotIn(b"/home/", text, msg=str(path))
            manifest_text = manifest_path.read_text(encoding="utf-8")
            compact = re.sub(r"\s+", "", manifest_text)
            self.assertIn('"synthetic":true', compact, msg=str(manifest_path))
            payload = json.loads(manifest_text)
            self.assertTrue(payload["synthetic"], msg=str(manifest_path))
            self.assertEqual(payload["source"], "openclaw")
            self.assertEqual(payload["format_id"], "openclaw-agent-sqlite-v1")

    def test_builder_rebuilds_agent_databases(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(_BUILDER)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
        for db_path in sorted(OPENCLAW_FIXTURES.rglob("openclaw-agent.sqlite")):
            self.assertTrue(db_path.is_file(), msg=str(db_path))
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertTrue(_REQUIRED_TABLES.issubset(tables), msg=str(db_path))
                meta = connection.execute(
                    """
                    SELECT role, schema_version, agent_id
                    FROM schema_meta
                    WHERE meta_key = 'primary'
                    """
                ).fetchone()
                self.assertIsNotNone(meta, msg=str(db_path))
                self.assertEqual(meta[0], "agent", msg=str(db_path))
                agent_folder = db_path.parts[db_path.parts.index("agents") + 1]
                self.assertEqual(meta[2], agent_folder, msg=str(db_path))
                user_version = connection.execute("PRAGMA user_version").fetchone()[0]
                if db_path.parts[-5] == _CORRUPT_CASE:
                    self.assertEqual(meta[1], _ABSURD_SCHEMA_VERSION, msg=str(db_path))
                    self.assertEqual(user_version, _SCHEMA_VERSION, msg=str(db_path))
                else:
                    self.assertEqual(meta[1], _SCHEMA_VERSION, msg=str(db_path))
                    self.assertEqual(user_version, _SCHEMA_VERSION, msg=str(db_path))
            finally:
                connection.close()

    def test_multi_agent_fixture_has_two_agent_databases(self) -> None:
        case_root = OPENCLAW_FIXTURES / "s-oc-02-multi-agent"
        databases = sorted(case_root.glob("agents/*/agent/openclaw-agent.sqlite"))
        self.assertEqual(len(databases), 2)
        agent_ids = set()
        for db_path in databases:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                agent_ids.add(
                    connection.execute(
                        "SELECT agent_id FROM schema_meta WHERE meta_key = 'primary'"
                    ).fetchone()[0]
                )
            finally:
                connection.close()
        self.assertEqual(agent_ids, {"main", "worker"})

    def test_corrupt_meta_case_is_detectable(self) -> None:
        db_path = OPENCLAW_FIXTURES / _CORRUPT_CASE / "agents/main/agent/openclaw-agent.sqlite"
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            meta_version, user_version = connection.execute(
                """
                SELECT schema_version, (SELECT user_version FROM pragma_user_version)
                FROM schema_meta
                WHERE meta_key = 'primary'
                """
            ).fetchone()
            self.assertGreater(meta_version, _SCHEMA_VERSION)
            self.assertNotEqual(meta_version, user_version)
        finally:
            connection.close()

    def test_fixture_manifests_validate(self) -> None:
        from tests.helpers.fixture_manifest import validate_fixture_tree

        manifests = validate_fixture_tree(OPENCLAW_FIXTURES)
        self.assertEqual(len(manifests), 5)
        self.assertTrue(all(item.source == "openclaw" for item in manifests))

    def test_builder_module_matches_checked_in_constants(self) -> None:
        module = _load_builder()
        self.assertEqual(module.SCHEMA_VERSION, _SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
