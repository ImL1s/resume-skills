"""Unit tests for offline cross-source discover and read-only doctor."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from portable_resume.adapters.base import CapabilityReport
from portable_resume.diagnostics import DiagnosticError
from portable_resume.discover_doctor import (
    discover_report,
    discover_table,
    doctor_report,
    doctor_table,
)
from portable_resume.model import SessionSummary
from portable_resume.registry import enabled_destination_keys, enabled_source_keys, matrix_dimensions


def _summary(
    source: str,
    session_id: str,
    *,
    title: str | None = None,
    updated_at: str | None = None,
    cwd: str | None = "/tmp/project",
    branch: str | None = "main",
) -> SessionSummary:
    return SessionSummary(
        source=source,
        session_id=session_id,
        title=title,
        cwd=cwd,
        branch=branch,
        updated_at=updated_at,
    )


class DiscoverIsolationTests(unittest.TestCase):
    def test_isolation_keeps_healthy_sources_when_one_raises(self) -> None:
        """claude + grok candidates survive; codex error does not wipe others."""

        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, f"{source}-fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    if source == "claude":
                        return [
                            _summary(
                                "claude",
                                "cla-1",
                                title="Claude One",
                                updated_at="2026-07-01T12:00:00Z",
                            ),
                            _summary(
                                "claude",
                                "cla-2",
                                title="Claude Two",
                                updated_at="2026-07-02T12:00:00Z",
                            ),
                        ]
                    if source == "codex":
                        raise DiagnosticError("E_SOURCE_BUSY", source=source)
                    if source == "grok":
                        return [
                            _summary(
                                "grok",
                                "grk-1",
                                title="Grok One",
                                updated_at="2026-07-03T12:00:00Z",
                            ),
                        ]
                    return []

            return _Adapter()

        report = discover_report(
            cwd=os.getcwd(),
            sources=("claude", "codex", "grok"),
            load_adapter=fake_load,
        )
        self.assertEqual(report["schema_version"], "portable-resume/discover-v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["sources"]["claude"]["state"], "supported")
        self.assertEqual(report["sources"]["codex"]["state"], "error")
        self.assertEqual(report["sources"]["codex"].get("code"), "E_SOURCE_BUSY")
        self.assertEqual(report["sources"]["grok"]["state"], "supported")

        tokens = [item["token"] for item in report["candidates"]]
        self.assertIn("claude:cla-1", tokens)
        self.assertIn("claude:cla-2", tokens)
        self.assertIn("grok:grk-1", tokens)
        self.assertEqual(len(tokens), 3)
        # No codex candidate leaked after list failure.
        self.assertTrue(all(not t.startswith("codex:") for t in tokens))
        # Sort: updated_at desc → grok first, then cla-2, then cla-1.
        self.assertEqual(tokens[0], "grok:grk-1")
        self.assertEqual(tokens[1], "claude:cla-2")
        self.assertEqual(tokens[2], "claude:cla-1")

    def test_token_format_is_source_colon_session_id(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    if source == "claude":
                        return [_summary("claude", "native-id-abc", title="T")]
                    return []

            return _Adapter()

        report = discover_report(
            cwd=os.getcwd(),
            sources=("claude",),
            load_adapter=fake_load,
        )
        self.assertEqual(len(report["candidates"]), 1)
        cand = report["candidates"][0]
        self.assertEqual(cand["token"], "claude:native-id-abc")
        self.assertEqual(cand["source"], "claude")
        self.assertEqual(cand["session_id"], "native-id-abc")
        self.assertEqual(
            cand["follow_up"],
            "portable-resume claude show native-id-abc",
        )

    def test_unknown_source_filter_raises_diagnostic_error(self) -> None:
        with self.assertRaises(DiagnosticError) as ctx:
            discover_report(
                cwd=os.getcwd(),
                sources=("claude", "not-a-real-source"),
                load_adapter=lambda s: (_ for _ in ()).throw(AssertionError("unused")),
            )
        self.assertEqual(ctx.exception.code, "E_INVALID_INPUT")

    def test_listed_limit_caps_merged_candidates(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return [
                        _summary(
                            source,
                            f"{source}-{i}",
                            updated_at=f"2026-07-0{i+1}T00:00:00Z",
                        )
                        for i in range(3)
                    ]

            return _Adapter()

        report = discover_report(
            cwd=os.getcwd(),
            sources=("claude", "grok"),
            load_adapter=fake_load,
            listed_limit=2,
        )
        self.assertEqual(len(report["candidates"]), 2)

    def test_discover_table_is_content_free_tsv(self) -> None:
        report = {
            "schema_version": "portable-resume/discover-v1",
            "ok": True,
            "cwd": "/tmp",
            "sources": {"claude": {"state": "supported", "format_id": "x"}},
            "candidates": [
                {
                    "token": "claude:s1",
                    "source": "claude",
                    "session_id": "s1",
                    "title": "Hello",
                    "cwd": "/tmp",
                    "branch": None,
                    "updated_at": "2026-07-01T00:00:00Z",
                    "follow_up": "portable-resume claude show s1",
                }
            ],
        }
        text = discover_table(report)
        self.assertIn("TOKEN\tSOURCE\tSESSION_ID\tUPDATED_AT\tTITLE", text)
        self.assertIn("claude:s1\tclaude\ts1\t", text)
        self.assertIn("claude\tsupported\tx", text)


class DoctorReportTests(unittest.TestCase):
    def test_doctor_report_schema_and_checks_without_session_bodies(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, f"{source}-fmt", "unavailable")

                def list(self, query, budget):  # noqa: ANN001
                    raise AssertionError("doctor must not list sessions")

            return _Adapter()

        report = doctor_report(cwd=os.getcwd(), load_adapter=fake_load)
        self.assertEqual(report["schema_version"], "portable-resume/doctor-v1")
        self.assertIn("ok", report)
        self.assertEqual(report["matrix_dimensions"], matrix_dimensions())
        self.assertEqual(set(report["sources"]), set(enabled_source_keys()))
        self.assertEqual(set(report["destinations"]), set(enabled_destination_keys()))
        self.assertIn("os_name", report["platform"])
        self.assertIn("windows_mutating_install", report["platform"])
        self.assertIsInstance(report["platform"]["windows_mutating_install"], bool)

        check_ids = {c["id"] for c in report["checks"]}
        self.assertEqual(
            check_ids,
            {
                "registry_valid",
                "matrix_cells",
                "schema_file_present",
                "sources_probe_completed",
                "windows_install_policy",
                "filesystem_backend",
            },
        )
        for check in report["checks"]:
            self.assertIn(check["status"], {"pass", "warn", "fail", "info"})
            self.assertIsInstance(check.get("detail"), str)

        # Content-free: no candidates/sessions/turns bodies in the report.
        blob = repr(report)
        self.assertNotIn("turns", blob)
        self.assertNotIn("last_user_request", blob)
        self.assertNotIn("candidates", report)
        self.assertNotIn("sessions", report)

        # Presence rows only — list never called (would assert).
        for row in report["sources"].values():
            self.assertEqual(row["state"], "unavailable")
            self.assertNotIn("listed", row)

    def test_doctor_windows_policy_info_on_nt(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "f", "unavailable")

            return _Adapter()

        with mock.patch("portable_resume.discover_doctor.os.name", "nt"):
            report = doctor_report(cwd=os.getcwd(), load_adapter=fake_load)
        self.assertIs(report["platform"]["windows_mutating_install"], False)
        policy = next(c for c in report["checks"] if c["id"] == "windows_install_policy")
        self.assertEqual(policy["status"], "info")
        self.assertIn("fail-closed", policy["detail"])

    def test_doctor_table_lists_checks(self) -> None:
        report = doctor_report(
            cwd=os.getcwd(),
            load_adapter=lambda source: type(
                "A",
                (),
                {
                    "key": source,
                    "probe": lambda self, query: CapabilityReport(
                        source, "f", "unavailable"
                    ),
                },
            )(),
        )
        text = doctor_table(report)
        self.assertIn("CHECK\tSTATUS\tDETAIL", text)
        self.assertIn("registry_valid\t", text)
        self.assertIn("SOURCE\tSTATE\tFORMAT", text)


if __name__ == "__main__":
    unittest.main()
