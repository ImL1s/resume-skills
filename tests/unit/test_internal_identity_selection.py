"""#61: selection uses raw structural identity; public output is a projection."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from portable_resume.adapters.base import CapabilityReport, ResolvedRef
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query, Session, SessionSummary
from portable_resume.reader import run
from portable_resume.sanitize import sanitize_summary, validate_structural_summary
from portable_resume.select import AmbiguousSelection, select_session


def _secret_id(suffix: str = "abcdefghijklmnopqrstuvwxyz") -> str:
    return "sk-" + suffix


class _SyntheticAdapter:
    key = "claude"

    def __init__(self, summaries: list[SessionSummary], sessions: dict[str, Session] | None = None):
        self._summaries = summaries
        self._sessions = sessions or {}
        self.show_refs: list[ResolvedRef] = []

    def probe(self, query: Query) -> CapabilityReport:
        return CapabilityReport(source=self.key, format_id="synthetic-v1", state="supported")

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        return list(self._summaries)

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        self.show_refs.append(ref)
        if ref.session_id in self._sessions:
            return self._sessions[ref.session_id]
        return Session(
            source=self.key,
            session_id=ref.session_id,
            source_path=ref.source_path,
            cwd=ref.cwd,
            title=ref.title,
            turns=(),
        )


class InternalIdentitySelectionTests(unittest.TestCase):
    def test_secret_shaped_session_id_selectable_after_public_sanitize(self) -> None:
        sid = _secret_id()
        raw = SessionSummary(
            source="claude",
            session_id=sid,
            cwd="/tmp/project",
            source_path="/tmp/api_key=abcdefghijklmnop/session.jsonl",
            updated_at="2026-01-01T00:00:00Z",
        )
        public, warnings = sanitize_summary(raw)
        self.assertEqual(public.session_id, sid)
        self.assertNotIn(sid, public.source_path or "")
        self.assertIn("[REDACTED]", public.source_path or "")
        self.assertIn("W_METADATA_REDACTED", warnings)
        selected = select_session([raw], ref=sid, cwd="/tmp/project")
        self.assertEqual(selected.selected.session_id, sid)
        # Public projection alone must still preserve the exact selection token.
        selected_public = select_session([public], ref=sid, cwd=None)
        self.assertEqual(selected_public.selected.session_id, sid)

    def test_secret_shaped_cwd_isolation_uses_raw(self) -> None:
        sid = "session-1"
        secret_cwd = "/tmp/token=abcdefghijklmnop/project"
        raw = SessionSummary(
            source="claude",
            session_id=sid,
            cwd=secret_cwd,
            updated_at="2026-01-01T00:00:00Z",
        )
        public, _ = sanitize_summary(raw)
        self.assertNotEqual(public.cwd, secret_cwd)
        # Raw cwd still matches query cwd isolation.
        selected = select_session([raw], ref="latest", cwd=secret_cwd)
        self.assertEqual(selected.selected.session_id, sid)
        # Sanitized cwd would break isolation if used for selection.
        with self.assertRaises(DiagnosticError) as caught:
            select_session([public], ref="latest", cwd=secret_cwd)
        self.assertEqual(caught.exception.code, "E_NO_MATCH")

    def test_two_secret_ids_remain_distinct_candidates(self) -> None:
        a = SessionSummary(source="claude", session_id=_secret_id("a" * 26), title="same", updated_at="2026-01-01T00:00:00Z")
        b = SessionSummary(source="claude", session_id=_secret_id("b" * 26), title="same", updated_at="2026-01-01T00:00:00Z")
        with self.assertRaises(AmbiguousSelection) as caught:
            select_session([a, b], ref="same", cwd=None)
        ids = {item.session_id for item in caught.exception.candidates}
        self.assertEqual(ids, {a.session_id, b.session_id})
        public_a, _ = sanitize_summary(a)
        public_b, _ = sanitize_summary(b)
        self.assertNotEqual(public_a.session_id, public_b.session_id)

    def test_overlong_session_id_fails_validation(self) -> None:
        raw = SessionSummary(source="claude", session_id="x" * 10_000)
        with self.assertRaises(DiagnosticError) as caught:
            validate_structural_summary(raw)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_reader_show_passes_raw_path_to_adapter(self) -> None:
        sid = _secret_id()
        secret_path = "/tmp/api_key=abcdefghijklmnop/session.jsonl"
        summary = SessionSummary(
            source="claude",
            session_id=sid,
            cwd="/tmp/project",
            source_path=secret_path,
            updated_at="2026-01-02T00:00:00Z",
        )
        adapter = _SyntheticAdapter([summary])

        def _load(_source: str) -> Any:
            return adapter

        stdout = __import__("io").StringIO()
        stderr = __import__("io").StringIO()
        with mock.patch("portable_resume.reader._load_adapter", side_effect=_load):
            code = run(
                ["claude", "show", sid, "--cwd", "/tmp/project", "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(len(adapter.show_refs), 1)
        self.assertEqual(adapter.show_refs[0].session_id, sid)
        self.assertEqual(adapter.show_refs[0].source_path, secret_path)
        payload = json.loads(stdout.getvalue())
        # Public envelope redacts path content but keeps native session_id token.
        session = payload["sessions"][0]
        self.assertEqual(session["session_id"], sid)
        self.assertEqual(session["source_path"], "/tmp/api_key=[REDACTED]")
        self.assertNotIn("api_key=abcdefghijklmnop", json.dumps(session))


if __name__ == "__main__":
    unittest.main()
