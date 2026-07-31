from __future__ import annotations

import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.cline import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/cline")
CWD = "/tmp/project"
BASIC_ID = "cl000101-0101-4101-8101-010101010101"
CHILD_ID = "cl000102-0202-4202-8202-020202020202"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="cline",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class ClineAdapterTests(unittest.TestCase):
    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic cline user prompt", "synthetic cline assistant reply"],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")
        self.assertEqual(report.format_id, FORMAT_ID)

    def test_default_list_hides_subagent(self) -> None:
        root = fixture_root("s-cl-02-parent-subagent")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
        child = ADAPTER.show(
            ResolvedRef(session_id=CHILD_ID, source_path=""),
            query(root, ref=CHILD_ID),
            ReadBudget(),
        )
        self.assertEqual(child.session_id, CHILD_ID)
        self.assertIn("child should hide", child.turns[0].content)

    def test_unsupported_messages_version(self) -> None:
        root = fixture_root("s-cl-03-unsupported-messages")
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(
                ResolvedRef(session_id=BASIC_ID, source_path=""),
                query(root, ref=BASIC_ID),
                ReadBudget(),
            )
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_cwd_mismatch_filtered(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        other = Query(
            source="cline",
            cwd="/tmp/other",
            source_root=str(root),
            within_min=0,
        )
        self.assertEqual(ADAPTER.list(other, ReadBudget()), [])

    def test_sessions_dir_only_lists_without_index(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        sessions_only = root / "data" / "sessions"
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(sessions_only),
            within_min=0,
        )
        report = ADAPTER.probe(current)
        self.assertIn(report.state, {"partial", "supported"})
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(session.session_id, BASIC_ID)
        self.assertTrue(session.turns)

    def test_prompt_only_without_messages_not_listed(self) -> None:
        import tempfile
        import sqlite3
        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            db_path = data / "db" / "sessions.db"
            sessions_dir = data / "sessions"
            conn = bf._connect(db_path)
            # Index has prompt but no messages file on disk.
            bf._insert_session(
                conn,
                session_id=BASIC_ID,
                prompt="stale prompt only",
                messages_path="",
                updated_at="2024-06-01T12:00:00.000000Z",
            )
            # Older valid session should win latest.
            other = "cl000199-0101-4101-8101-010101010199"
            path = bf._write_session_files(
                sessions_dir,
                session_id=other,
                messages=[
                    {"id": "u", "role": "user", "content": "older valid user"},
                    {"id": "a", "role": "assistant", "content": "older valid asst"},
                ],
            )
            bf._insert_session(
                conn,
                session_id=other,
                prompt="older valid user",
                messages_path="",
                updated_at="2024-01-01T12:00:00.000000Z",
            )
            conn.commit()
            conn.close()
            current = Query(
                source="cline",
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            )
            summaries = ADAPTER.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [other])

    def test_exact_sessions_db_source_root_can_show(self) -> None:
        """Direct sessions.db path must still reach sibling messages JSON (Codex P2)."""
        root = fixture_root("s-cl-01-user-basic")
        db_path = root / "data" / "db" / "sessions.db"
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(db_path),
            within_min=0,
        )
        report = ADAPTER.probe(current)
        self.assertEqual(report.state, "supported")
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic cline user prompt", "synthetic cline assistant reply"],
        )


if __name__ == "__main__":
    unittest.main()
