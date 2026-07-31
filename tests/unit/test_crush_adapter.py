from __future__ import annotations

import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.crush import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/crush")
CWD = "/tmp/project"
BASIC_ID = "cr000101-0101-4101-8101-010101010101"
CHILD_ID = "cr000102-0202-4202-8202-020202020202"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    # Project-layout fixtures bind cwd to the project root (parent of .crush).
    cwd = kwargs.pop("cwd", str(root))
    return Query(
        source="crush",
        ref=ref,
        cwd=cwd,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class CrushAdapterTests(unittest.TestCase):
    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-cr-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        self.assertEqual(summaries[0].title, "basic crush session")
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic crush user prompt", "synthetic crush assistant reply"],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported_on_basic(self) -> None:
        root = fixture_root("s-cr-01-user-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")
        self.assertEqual(report.format_id, FORMAT_ID)

    def test_default_list_hides_child_sessions(self) -> None:
        root = fixture_root("s-cr-02-parent-child")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
        # Exact id still reaches the child.
        child = ADAPTER.show(
            ResolvedRef(session_id=CHILD_ID, source_path=str(root / ".crush" / "crush.db")),
            query(root, ref=CHILD_ID),
            ReadBudget(),
        )
        self.assertEqual(child.session_id, CHILD_ID)
        self.assertEqual(child.turns[0].content, "child should be hidden from default list")

    def test_unsupported_schema(self) -> None:
        root = fixture_root("s-cr-03-unsupported-schema")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "unsupported")

    def test_project_layout_source_root(self) -> None:
        import tempfile
        from tests.fixtures.crush import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = project / ".crush"
            db_path = data / "crush.db"
            conn = bf._connect(db_path)
            bf._create_schema(conn)
            bf._insert_session(
                conn, session_id=BASIC_ID, title="project layout", message_count=1
            )
            bf._insert_message(
                conn,
                message_id="m1",
                session_id=BASIC_ID,
                role="user",
                text="via project root",
            )
            conn.commit()
            conn.close()
            current = Query(
                source="crush",
                cwd=str(project),
                source_root=str(project),
                within_min=0,
            )
            report = ADAPTER.probe(current)
            self.assertEqual(report.state, "supported")
            summaries = ADAPTER.list(current, ReadBudget())
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].cwd, str(project.resolve()))

    def test_cwd_mismatch_on_project_layout_filtered(self) -> None:
        import tempfile
        from tests.fixtures.crush import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "proj-a"
            project.mkdir()
            data = project / ".crush"
            db_path = data / "crush.db"
            conn = bf._connect(db_path)
            bf._create_schema(conn)
            bf._insert_session(
                conn, session_id=BASIC_ID, title="proj a", message_count=1
            )
            bf._insert_message(
                conn,
                message_id="m1",
                session_id=BASIC_ID,
                role="user",
                text="project a context",
            )
            conn.commit()
            conn.close()
            other = Query(
                source="crush",
                cwd="/tmp/other-project",
                source_root=str(project),
                within_min=0,
            )
            self.assertEqual(ADAPTER.list(other, ReadBudget()), [])
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.show(
                    ResolvedRef(session_id=BASIC_ID, source_path=str(db_path)),
                    other,
                    ReadBudget(),
                )
            self.assertEqual(caught.exception.code, "E_NO_MATCH")

    def test_malformed_parts_fail_closed(self) -> None:
        import tempfile
        from tests.fixtures.crush import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "crush.db"
            conn = bf._connect(db_path)
            bf._create_schema(conn)
            bf._insert_session(conn, session_id=BASIC_ID, title="corrupt", message_count=1)
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, role, parts, created_at, updated_at, is_summary_message
                ) VALUES ('bad', ?, 'user', '{not-json', ?, ?, 0)
                """,
                (BASIC_ID, bf.NOW_MS, bf.NOW_MS),
            )
            conn.commit()
            conn.close()
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.show(
                    ResolvedRef(session_id=BASIC_ID, source_path=str(db_path)),
                    query(root, ref=BASIC_ID),
                    ReadBudget(),
                )
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")


if __name__ == "__main__":
    unittest.main()
