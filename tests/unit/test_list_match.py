"""Plan 043: list --match free-text filter on the bounded listing window."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import CapabilityReport
from portable_resume.bounds import DEFAULT_BOUNDS
from portable_resume.model import SessionSummary
from portable_resume.reader import run
from portable_resume.select import summary_matches

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "claude"
    / "s-cla-01-ordered-parent-chain"
    / "root"
)
_CWD = "/workspace/project"


def _summaries(*titles: str) -> list[SessionSummary]:
    rows: list[SessionSummary] = []
    for index, title in enumerate(titles):
        rows.append(
            SessionSummary(
                source="claude",
                session_id=f"id-{index:04d}",
                title=title,
                cwd=_CWD,
                branch="main" if index % 2 == 0 else "feature/needle",
                updated_at=f"2026-07-20T08:{index:02d}:00Z",
            )
        )
    return rows


class _RecordingAdapter:
    """Adapter that records Query.ref and returns a fixed list."""

    key = "claude"

    def __init__(self, rows: list[SessionSummary]) -> None:
        self.rows = rows
        self.seen_refs: list[str | None] = []

    def probe(self, query) -> CapabilityReport:  # noqa: ANN001
        return CapabilityReport(self.key, "fixture", "supported")

    def list(self, query, budget):  # noqa: ANN001
        self.seen_refs.append(query.ref)
        return list(self.rows)

    def show(self, ref, query, budget):  # noqa: ANN001
        raise AssertionError("show must not run for list --match tests")


class SummaryMatchesTests(unittest.TestCase):
    def test_four_fields(self) -> None:
        row = SessionSummary(
            source="claude",
            session_id="abc-title-id",
            title="Hello World",
            cwd="/tmp/workspace/project",
            branch="feat/db",
            updated_at="2026-01-01T00:00:00Z",
        )
        self.assertTrue(summary_matches(row, "abc-title".casefold()))
        self.assertTrue(summary_matches(row, "hello".casefold()))
        self.assertTrue(summary_matches(row, "workspace".casefold()))
        self.assertTrue(summary_matches(row, "feat/db".casefold()))
        self.assertFalse(summary_matches(row, "nope".casefold()))

    def test_case_insensitivity(self) -> None:
        row = SessionSummary(
            source="claude",
            session_id="s1",
            title="Database Migration",
            cwd=_CWD,
            branch="Main",
            updated_at="2026-01-01T00:00:00Z",
        )
        self.assertTrue(summary_matches(row, "DATABASE".casefold()))
        self.assertTrue(summary_matches(row, "migration".casefold()))
        self.assertTrue(summary_matches(row, "MAIN".casefold()))


class ListMatchCliTests(unittest.TestCase):
    def test_fixture_match_filters_title(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            [
                "claude",
                "list",
                "--cwd",
                _CWD,
                "--source-root",
                str(_FIXTURE_ROOT),
                "--format",
                "json",
                "--match",
                "synthetic",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["operation"], "list")
        self.assertIsNone(payload["query"]["ref"])
        self.assertGreaterEqual(len(payload["sessions"]), 1)

    def test_fixture_empty_match_is_empty_list_not_no_match(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            [
                "claude",
                "list",
                "--cwd",
                _CWD,
                "--source-root",
                str(_FIXTURE_ROOT),
                "--format",
                "json",
                "--match",
                "zzzz-no-such-token",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["sessions"], [])
        self.assertIsNone(payload["query"]["ref"])
        self.assertNotIn("E_NO_MATCH", stderr.getvalue())

    def test_match_filters_each_of_four_fields(self) -> None:
        rows = [
            SessionSummary(
                source="claude",
                session_id="sid-alpha-unique",
                title="other",
                cwd="/tmp/a",
                branch="main",
                updated_at="2026-07-20T01:00:00Z",
            ),
            SessionSummary(
                source="claude",
                session_id="sid-beta",
                title="title-gamma-unique",
                cwd="/tmp/b",
                branch="main",
                updated_at="2026-07-20T02:00:00Z",
            ),
            SessionSummary(
                source="claude",
                session_id="sid-delta",
                title="other",
                cwd="/tmp/cwd-epsilon-unique",
                branch="main",
                updated_at="2026-07-20T03:00:00Z",
            ),
            SessionSummary(
                source="claude",
                session_id="sid-zeta",
                title="other",
                cwd="/tmp/c",
                branch="branch-eta-unique",
                updated_at="2026-07-20T04:00:00Z",
            ),
        ]
        cases = (
            ("alpha-unique", "sid-alpha-unique"),
            ("gamma-unique", "sid-beta"),
            ("epsilon-unique", "sid-delta"),
            ("eta-unique", "sid-zeta"),
        )
        for needle, expected_id in cases:
            with self.subTest(needle=needle):
                adapter = _RecordingAdapter(rows)
                stdout = io.StringIO()
                stderr = io.StringIO()
                with mock.patch("portable_resume.reader._load_adapter", return_value=adapter):
                    code = run(
                        [
                            "claude",
                            "list",
                            "--cwd",
                            _CWD,
                            "--format",
                            "json",
                            "--match",
                            needle,
                        ],
                        stdout=stdout,
                        stderr=stderr,
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                payload = json.loads(stdout.getvalue())
                self.assertEqual([s["session_id"] for s in payload["sessions"]], [expected_id])
                self.assertEqual(adapter.seen_refs, [None])
                self.assertIsNone(payload["query"]["ref"])

    def test_match_case_insensitive_cli(self) -> None:
        rows = [
            SessionSummary(
                source="claude",
                session_id="s-case",
                title="Database Migration",
                cwd=_CWD,
                branch="main",
                updated_at="2026-07-20T01:00:00Z",
            ),
            SessionSummary(
                source="claude",
                session_id="s-other",
                title="unrelated",
                cwd=_CWD,
                branch="main",
                updated_at="2026-07-20T02:00:00Z",
            ),
        ]
        adapter = _RecordingAdapter(rows)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("portable_resume.reader._load_adapter", return_value=adapter):
            code = run(
                [
                    "claude",
                    "list",
                    "--cwd",
                    _CWD,
                    "--format",
                    "json",
                    "--match",
                    "DATABASE",
                ],
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual([s["session_id"] for s in payload["sessions"]], ["s-case"])
        self.assertEqual(adapter.seen_refs, [None])

    def test_match_with_show_is_invalid(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            [
                "claude",
                "show",
                "latest",
                "--cwd",
                _CWD,
                "--source-root",
                str(_FIXTURE_ROOT),
                "--match",
                "x",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertIn("E_INVALID_INPUT", stderr.getvalue())

    def test_match_with_request_file_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "req.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "portable-resume/request-v1",
                        "source": "claude",
                        "action": "show",
                        "resume_ref": "latest",
                        "cwd": _CWD,
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = run(
                [
                    "--request-file",
                    str(path),
                    "--expected-source",
                    "claude",
                    "--match",
                    "x",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 2)
            self.assertIn("E_INVALID_INPUT", stderr.getvalue())

    def test_overlong_match_rejected(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            [
                "claude",
                "list",
                "--cwd",
                _CWD,
                "--source-root",
                str(_FIXTURE_ROOT),
                "--match",
                "x" * (DEFAULT_BOUNDS.ref_chars + 1),
            ],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertIn("E_INVALID_INPUT", stderr.getvalue())

    def test_control_char_match_rejected(self) -> None:
        for needle in ("bad\x00match", "bad\nmatch", "bad\x1bmatch"):
            with self.subTest(needle=repr(needle)):
                stdout = io.StringIO()
                stderr = io.StringIO()
                code = run(
                    [
                        "claude",
                        "list",
                        "--cwd",
                        _CWD,
                        "--source-root",
                        str(_FIXTURE_ROOT),
                        "--match",
                        needle,
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )
                self.assertEqual(code, 2)
                self.assertIn("E_INVALID_INPUT", stderr.getvalue())

    def test_truncated_window_keeps_w_truncated_after_empty_match(self) -> None:
        many = _summaries(*[f"title-{i}" for i in range(DEFAULT_BOUNDS.listed_sessions + 5)])
        many[-1] = SessionSummary(
            source="claude",
            session_id="old-match",
            title="unique-needle-outside-window",
            cwd=_CWD,
            branch="main",
            updated_at="2020-01-01T00:00:00Z",
        )
        adapter = _RecordingAdapter(many)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("portable_resume.reader._load_adapter", return_value=adapter):
            code = run(
                [
                    "claude",
                    "list",
                    "--cwd",
                    _CWD,
                    "--format",
                    "json",
                    "--match",
                    "unique-needle-outside-window",
                ],
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["sessions"], [])
        self.assertIn("W_TRUNCATED", payload.get("warnings") or [])
        self.assertEqual(adapter.seen_refs, [None])
        self.assertIsNone(payload["query"]["ref"])

    def test_truncated_window_keeps_w_truncated_with_hits(self) -> None:
        many = _summaries(*[f"plain-{i}" for i in range(DEFAULT_BOUNDS.listed_sessions + 3)])
        # Newest row (high index in updated_at) keeps a matchable title inside the window.
        many[DEFAULT_BOUNDS.listed_sessions + 2] = SessionSummary(
            source="claude",
            session_id="in-window-hit",
            title="keep-this-needle",
            cwd=_CWD,
            branch="main",
            updated_at="2026-12-31T23:59:00Z",
        )
        adapter = _RecordingAdapter(many)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("portable_resume.reader._load_adapter", return_value=adapter):
            code = run(
                [
                    "claude",
                    "list",
                    "--cwd",
                    _CWD,
                    "--format",
                    "json",
                    "--match",
                    "keep-this-needle",
                ],
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual([s["session_id"] for s in payload["sessions"]], ["in-window-hit"])
        self.assertIn("W_TRUNCATED", payload.get("warnings") or [])
        self.assertEqual(adapter.seen_refs, [None])


if __name__ == "__main__":
    unittest.main()
