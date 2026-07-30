from __future__ import annotations

import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.goose import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/goose")
CWD = "/tmp/project"
BASIC_ID = "go000101-0101-4101-8101-010101010101"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="goose",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class GooseAdapterTests(unittest.TestCase):
    def test_list_and_show_basic_user_session(self) -> None:
        root = fixture_root("s-go-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        self.assertEqual(summaries[0].title, "basic user session")
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic goose user prompt", "synthetic goose assistant reply"],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_default_list_filters_non_user_types(self) -> None:
        root = fixture_root("s-go-02-session-types")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, "go020201-0201-4201-8201-020202020201")
        exact = ADAPTER.list(query(root, ref="go020203-0203-4203-8203-020202020203"), ReadBudget())
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].session_id, "go020203-0203-4203-8203-020202020203")

    def test_parent_user_listed_subagent_hidden(self) -> None:
        root = fixture_root("s-go-03-parent-subagent")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["go030301-0301-4301-8301-030303030301"])
        parent = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), query(root), ReadBudget())
        self.assertEqual([turn.content for turn in parent.turns], ["synthetic parent prompt"])

    def test_archived_hidden_unless_exact(self) -> None:
        root = fixture_root("s-go-04-archived")
        self.assertEqual(ADAPTER.list(query(root), ReadBudget()), [])
        exact = ADAPTER.list(query(root, ref="go040401-0401-4401-8401-040404040401"), ReadBudget())
        self.assertEqual(len(exact), 1)

    def test_unsupported_schema_fails_closed(self) -> None:
        root = fixture_root("s-go-05-unsupported-schema")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "unsupported")
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_probe_supported_on_basic(self) -> None:
        root = fixture_root("s-go-01-user-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")
        self.assertEqual(report.format_id, FORMAT_ID)


if __name__ == "__main__":
    unittest.main()
