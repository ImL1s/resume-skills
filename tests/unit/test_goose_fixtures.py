from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GOOSE_FIXTURES = Path("tests/fixtures/goose")
_SUPPORTED_CASES = frozenset(
    {
        "s-go-01-user-basic",
        "s-go-02-session-types",
        "s-go-03-parent-subagent",
        "s-go-04-archived",
    }
)
_UNSUPPORTED_CASES = frozenset({"s-go-05-unsupported-schema"})
_EXPECTED_SESSION_TYPES = frozenset(
    {"user", "scheduled", "sub_agent", "hidden", "gateway", "acp"}
)


def _schema_version(db_path: Path) -> int | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])
    finally:
        conn.close()


def _session_types(db_path: Path) -> set[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT DISTINCT session_type FROM sessions").fetchall()
        return {str(row[0]) for row in rows}
    finally:
        conn.close()


class GooseFixtureTests(unittest.TestCase):
    def test_paths_are_clean_and_manifests_are_synthetic(self) -> None:
        manifests = sorted(GOOSE_FIXTURES.glob("s-go-*/fixture.json"))
        self.assertEqual(len(manifests), 5)
        for manifest_path in manifests:
            for path in manifest_path.parent.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("/Users/", text, msg=str(path))
                self.assertNotIn("/home/", text, msg=str(path))
            manifest_text = manifest_path.read_text(encoding="utf-8")
            compact = re.sub(r"\s+", "", manifest_text)
            self.assertIn('"synthetic":true', compact, msg=str(manifest_path))
            payload = json.loads(manifest_text)
            self.assertTrue(payload["synthetic"], msg=str(manifest_path))
            self.assertEqual(payload["source"], "goose")

    def test_schema_versions_match_supported_expectations(self) -> None:
        for manifest_path in sorted(GOOSE_FIXTURES.glob("s-go-*/fixture.json")):
            case = json.loads(manifest_path.read_text(encoding="utf-8"))["case"]
            db_path = manifest_path.parent / "sessions" / "sessions.db"
            self.assertTrue(db_path.is_file(), msg=case)
            version = _schema_version(db_path)
            if case in _SUPPORTED_CASES:
                self.assertEqual(version, 15, msg=case)
            elif case in _UNSUPPORTED_CASES:
                self.assertNotEqual(version, 15, msg=case)
            else:
                self.fail(f"unexpected goose fixture case: {case}")

    def test_session_types_fixture_covers_upstream_values(self) -> None:
        manifest_path = GOOSE_FIXTURES / "s-go-02-session-types" / "fixture.json"
        db_path = manifest_path.parent / "sessions" / "sessions.db"
        types = _session_types(db_path)
        self.assertEqual(types, _EXPECTED_SESSION_TYPES)

    def test_fixture_manifests_validate(self) -> None:
        from tests.helpers.fixture_manifest import validate_fixture_tree

        manifests = validate_fixture_tree(GOOSE_FIXTURES)
        self.assertEqual(len(manifests), 5)
        self.assertTrue(all(item.source == "goose" for item in manifests))

    def test_builder_rebuilds_into_temp_root(self) -> None:
        builder = GOOSE_FIXTURES / "build_fixtures.py"
        with tempfile.TemporaryDirectory() as temporary:
            out_root = Path(temporary) / "goose"
            completed = subprocess.run(
                [sys.executable, str(builder), "--root", str(out_root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
            rebuilt = sorted(out_root.rglob("sessions.db"))
            self.assertEqual(len(rebuilt), 5)
            for db_path in rebuilt:
                version = _schema_version(db_path)
                if "s-go-05-unsupported-schema" in db_path.parts:
                    self.assertNotEqual(version, 15, msg=str(db_path))
                else:
                    self.assertEqual(version, 15, msg=str(db_path))


if __name__ == "__main__":
    unittest.main()
