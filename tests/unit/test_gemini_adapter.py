from __future__ import annotations

import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.gemini import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/gemini")
CWD = "/tmp/project"
BASIC_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
SUB_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="gemini",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class GeminiAdapterTests(unittest.TestCase):
    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-gm-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        session = ADAPTER.show(
            ResolvedRef.from_summary(summaries[0]), current, ReadBudget()
        )
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic gemini user prompt", "synthetic gemini assistant reply"],
        )
        joined = " ".join(turn.content for turn in session.turns)
        self.assertNotIn("secret", joined)
        self.assertNotIn("must omit", joined)
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported(self) -> None:
        report = ADAPTER.probe(query(fixture_root("s-gm-01-user-basic")))
        self.assertEqual(report.state, "supported")

    def test_default_list_hides_subagent(self) -> None:
        root = fixture_root("s-gm-02-main-and-subagent")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
        child = ADAPTER.show(
            ResolvedRef(session_id=SUB_ID, source_path=""),
            query(root, ref=SUB_ID),
            ReadBudget(),
        )
        self.assertEqual(child.session_id, SUB_ID)
        self.assertIn("subagent should hide", child.turns[0].content)

    def test_corrupt_session_fails_closed(self) -> None:
        root = fixture_root("s-gm-03-corrupt")
        # list skips corrupt; exact show may raise
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(summaries, [])
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(
                ResolvedRef(session_id=BASIC_ID, source_path=""),
                query(root, ref=BASIC_ID),
                ReadBudget(),
            )
        self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_NO_MATCH"})

    def test_not_antigravity_key(self) -> None:
        self.assertEqual(ADAPTER.key, "gemini")
        self.assertNotEqual(FORMAT_ID, "antigravity-transcript-jsonl-v1")


if __name__ == "__main__":
    unittest.main()
