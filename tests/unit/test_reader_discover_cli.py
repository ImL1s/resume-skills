"""CLI wiring for discover / doctor (issue #120)."""

from __future__ import annotations

import io
import json
import os
import unittest
from unittest import mock

from portable_resume.adapters.base import CapabilityReport
from portable_resume.diagnostics import DiagnosticError, SOURCE_KEYS
from portable_resume.model import SessionSummary
from portable_resume.reader import run


class DiscoverDoctorCliTests(unittest.TestCase):
    def test_discover_json_schema_and_source_tokens(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return [
                        SessionSummary(
                            source=source,
                            session_id=f"{source}-sess-1",
                            title=f"t-{source}",
                            cwd=query.cwd,
                            updated_at="2026-08-01T12:00:00Z",
                        )
                    ]

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = run(
                ["discover", "--json", "--sources", "claude,codex"],
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "portable-resume/discover-v1")
        self.assertTrue(payload["ok"])
        tokens = {row["token"] for row in payload["candidates"]}
        self.assertIn("claude:claude-sess-1", tokens)
        self.assertIn("codex:codex-sess-1", tokens)
        for row in payload["candidates"]:
            self.assertTrue(row["token"].startswith(row["source"] + ":"))
            self.assertIn("follow_up", row)
            self.assertNotIn("turns", row)

    def test_discover_isolates_source_failure(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    if source == "codex":
                        raise DiagnosticError("E_UNSAFE_PATH", source=source)
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return [
                        SessionSummary(
                            source=source,
                            session_id="ok-1",
                            title="ok",
                            cwd=query.cwd,
                            updated_at="2026-08-01T12:00:00Z",
                        )
                    ]

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            stdout = io.StringIO()
            code = run(
                ["discover", "--json", "--sources", "claude,codex"],
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["sources"]["codex"]["state"], "error")
        self.assertEqual(payload["sources"]["claude"]["state"], "supported")
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(payload["candidates"][0]["source"], "claude")

    def test_discover_unknown_source_is_invalid(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            ["discover", "--sources", "not-a-real-source"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertIn("E_INVALID_INPUT", stderr.getvalue())

    def test_doctor_json_has_checks_no_session_bodies(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "unavailable")

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            stdout = io.StringIO()
            code = run(["doctor", "--json"], stdout=stdout, stderr=io.StringIO())
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "portable-resume/doctor-v1")
        self.assertIn("checks", payload)
        self.assertIn("matrix_dimensions", payload)
        self.assertEqual(set(payload["sources"]), set(SOURCE_KEYS))
        blob = json.dumps(payload)
        self.assertNotIn("tool_use", blob)
        self.assertNotIn('"turns"', blob)
        check_ids = {item["id"] for item in payload["checks"]}
        self.assertIn("registry_valid", check_ids)
        self.assertIn("sources_probe_completed", check_ids)

    def test_closed_parsers_reject_unknown_flags(self) -> None:
        for command in ("discover", "doctor"):
            code = run([command, "--nope"], stdout=io.StringIO(), stderr=io.StringIO())
            self.assertEqual(code, 2, command)

    def test_discover_does_not_invoke_source_cli_shims(self) -> None:
        # Even with a poisoned PATH, discover must only use adapters (mocked here).
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "unavailable")

                def list(self, query, budget):  # noqa: ANN001
                    return []

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}, clear=False):
                code = run(
                    ["discover", "--json", "--sources", "claude"],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
