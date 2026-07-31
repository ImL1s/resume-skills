from __future__ import annotations

import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.hermes import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/hermes")
CWD = "/tmp/project"
BASIC_ID = "hm000101-0101-4101-8101-010101010101"
CHILD_ID = "hm000102-0202-4202-8202-020202020202"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="hermes",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class HermesAdapterTests(unittest.TestCase):
    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-hm-01-user-basic")
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
            ["synthetic hermes user prompt", "synthetic hermes assistant reply"],
        )
        # Reasoning must not appear
        joined = " ".join(turn.content for turn in session.turns)
        self.assertNotIn("secret reasoning", joined)
        self.assertNotIn("system prompt", joined.lower())
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported(self) -> None:
        root = fixture_root("s-hm-01-user-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")

    def test_default_list_hides_child(self) -> None:
        root = fixture_root("s-hm-02-parent-child")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
        child = ADAPTER.show(
            ResolvedRef(session_id=CHILD_ID, source_path=""),
            query(root, ref=CHILD_ID),
            ReadBudget(),
        )
        self.assertEqual(child.session_id, CHILD_ID)
        self.assertIn("child should hide", child.turns[0].content)

    def test_unsupported_schema(self) -> None:
        root = fixture_root("s-hm-03-unsupported-schema")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "unsupported")
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_exact_state_db_source_root(self) -> None:
        root = fixture_root("s-hm-01-user-basic")
        db = root / "state.db"
        current = Query(
            source="hermes",
            cwd=CWD,
            source_root=str(db),
            within_min=0,
        )
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        session = ADAPTER.show(
            ResolvedRef.from_summary(summaries[0]), current, ReadBudget()
        )
        self.assertTrue(session.turns)


if __name__ == "__main__":
    unittest.main()
