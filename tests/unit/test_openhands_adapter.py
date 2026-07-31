from __future__ import annotations

import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.openhands import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/openhands")
CWD = "/tmp/project"
BASIC_ID = "oh000101010141018101010101010101"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="openhands",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class OpenHandsAdapterTests(unittest.TestCase):
    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-oh-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            [
                "synthetic openhands user prompt",
                "synthetic openhands assistant reply",
            ],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported(self) -> None:
        root = fixture_root("s-oh-01-user-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")
        self.assertEqual(report.format_id, FORMAT_ID)

    def test_unsupported_content_bearing_kind(self) -> None:
        root = fixture_root("s-oh-02-unsupported-kind")
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(
                ResolvedRef(session_id=BASIC_ID, source_path=""),
                query(root, ref=BASIC_ID),
                ReadBudget(),
            )
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_exact_id_selection(self) -> None:
        root = fixture_root("s-oh-01-user-basic")
        summaries = ADAPTER.list(query(root, ref=BASIC_ID), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])


if __name__ == "__main__":
    unittest.main()
