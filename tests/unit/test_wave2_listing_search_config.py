"""Wave-2 product surfaces: time range, workspace, search, config, pick."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import CapabilityReport, ResolvedRef
from portable_resume.config_layer import init_config, resolve_effective, validate_config
from portable_resume.model import Session, SessionSummary, Turn
from portable_resume.reader import run
from portable_resume.search_sessions import search_report
from portable_resume.time_range import (
    encode_cursor,
    page_summaries,
    parse_time_token,
    resolve_window,
)
from portable_resume.workspace import explain_project, filter_by_workspace, resolve_workspace


def _summary(source: str, sid: str, updated: str, cwd: str | None = None) -> SessionSummary:
    return SessionSummary(
        source=source,
        session_id=sid,
        title=f"t-{sid}",
        cwd=cwd,
        updated_at=updated,
    )


class TimeRangeTests(unittest.TestCase):
    def test_parse_relative_and_iso(self) -> None:
        now = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
        dt = parse_time_token("7d", now=now)
        self.assertEqual(dt.day, 26)
        iso = parse_time_token("2026-07-01T00:00:00Z", now=now)
        self.assertEqual(iso.month, 7)
        with self.assertRaises(Exception):
            parse_time_token("2026-07-01T00:00:00")  # naive rejected

    def test_page_cursor_continuation(self) -> None:
        rows = [
            _summary("claude", "a", "2026-08-02T12:00:00Z"),
            _summary("claude", "b", "2026-08-01T12:00:00Z"),
            _summary("claude", "c", "2026-07-31T12:00:00Z"),
        ]
        page1, cursor, meta = page_summaries(
            rows, limit=2, cursor=None, since_dt=None, until_dt=None
        )
        self.assertEqual(len(page1), 2)
        self.assertTrue(meta["has_more"])
        self.assertIsNotNone(cursor)
        page2, cursor2, meta2 = page_summaries(
            rows, limit=2, cursor=cursor, since_dt=None, until_dt=None
        )
        self.assertEqual(len(page2), 1)
        self.assertEqual(page2[0].session_id, "c")
        self.assertFalse(meta2["has_more"])

    def test_within_min_conflicts_with_since(self) -> None:
        with self.assertRaises(Exception):
            resolve_window(since="7d", until=None, within_min=60)


class WorkspaceTests(unittest.TestCase):
    def test_exact_and_explain(self) -> None:
        cwd = os.getcwd()
        identity = resolve_workspace(cwd, mode="exact")
        self.assertEqual(identity.mode, "exact")
        rows = [
            _summary("claude", "1", "2026-08-01T00:00:00Z", cwd=cwd),
            _summary("claude", "2", "2026-08-01T00:00:00Z", cwd="/tmp/other-unrelated"),
        ]
        matched = filter_by_workspace(rows, identity)
        ids = {r.session_id for r, _ in matched}
        self.assertIn("1", ids)
        report = explain_project(cwd)
        self.assertEqual(report["schema_version"], "portable-resume/project-explain-v1")
        self.assertIn("modes", report)


class ConfigTests(unittest.TestCase):
    def test_init_show_validate_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            project = Path(tmp) / "proj"
            project.mkdir()
            path = init_config(scope="project", project=str(project), home=str(home))
            self.assertTrue(Path(path).is_file())
            report = validate_config(project=str(project), home=str(home))
            self.assertTrue(report["ok"])
            eff = resolve_effective(
                project=str(project),
                home=str(home),
                preset="daily",
                cli={"format": "json"},
            )
            self.assertEqual(eff.values["format"], "json")
            self.assertEqual(eff.sources["format"], "cli")
            self.assertEqual(eff.sources.get("within_min"), "preset:daily")


class SearchAndPickCliTests(unittest.TestCase):
    def test_search_finds_public_text(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return [
                        SessionSummary(
                            source=source,
                            session_id="s1",
                            title="auth work",
                            cwd=query.cwd,
                            updated_at="2026-08-01T12:00:00Z",
                        )
                    ]

                def show(self, ref, query, budget):  # noqa: ANN001
                    return Session(
                        source=source,
                        session_id=ref.session_id,
                        turns=(
                            Turn(ordinal=0, role="user", content="authentication migration plan"),
                            Turn(ordinal=1, role="assistant", content="done"),
                        ),
                    )

            return _Adapter()

        report = search_report(
            "authentication migration",
            cwd=os.getcwd(),
            sources=["claude"],
            load_adapter=fake_load,
        )
        self.assertEqual(report["schema_version"], "portable-resume/search-v1")
        self.assertEqual(len(report["hits"]), 1)
        self.assertEqual(report["hits"][0]["token"], "claude:s1")

    def test_pick_json_and_select(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return [
                        SessionSummary(
                            source=source,
                            session_id="pick-1",
                            title="one",
                            cwd=query.cwd,
                            updated_at="2026-08-01T12:00:00Z",
                        )
                    ]

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            stdout = io.StringIO()
            code = run(
                ["pick", "--source", "claude", "--format", "json", "--select", "1"],
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "portable-resume/pick-v1")
        self.assertEqual(payload["selected"]["session_id"], "pick-1")

    def test_list_limit_since_json_pagination(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return [
                        _summary(source, "new", "2026-08-01T12:00:00Z", cwd=query.cwd),
                        _summary(source, "old", "2020-01-01T12:00:00Z", cwd=query.cwd),
                    ]

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            stdout = io.StringIO()
            code = run(
                [
                    "claude",
                    "list",
                    "--format",
                    "json",
                    "--limit",
                    "1",
                    "--since",
                    "30d",
                    "--cwd",
                    os.getcwd(),
                ],
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(code, 0, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertIn("pagination", payload)
        self.assertEqual(payload["pagination"]["limit"], 1)


class MaterializeSourcesTests(unittest.TestCase):
    def test_subset_sources_omits_other_skills(self) -> None:
        from portable_resume.install.render import materialize_plan, _reset_plan_cache

        _reset_plan_cache()
        files = materialize_plan("claude", sources=("claude", "codex"))
        skill_dirs = {
            p.split("/")[0]
            for p in files
            if p.startswith("resume-") and p.endswith("/SKILL.md")
        }
        self.assertEqual(skill_dirs, {"resume-claude", "resume-codex"})


if __name__ == "__main__":
    unittest.main()
