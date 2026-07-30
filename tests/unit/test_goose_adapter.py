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

    def test_empty_user_session_does_not_win_latest(self) -> None:
        import tempfile
        from tests.fixtures.goose import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "sessions" / "sessions.db"
            conn = bf._connect(db_path)
            bf._create_core_schema(conn)
            bf._insert_schema_versions(conn, range(1, 16))
            old_id = "goempty01-0101-4101-8101-010101010101"
            new_id = "goempty02-0202-4202-8202-020202020202"
            empty_json_id = "goempty03-0303-4303-8303-030303030303"
            bf._insert_session(conn, session_id=old_id, name="old with messages", session_type="user")
            bf._insert_message(
                conn,
                session_id=old_id,
                message_id="old-msg",
                role="user",
                text="keep me",
            )
            # Newer empty session must not crowd out recoverable history.
            conn.execute(
                """
                INSERT INTO sessions (
                    id, name, description, user_set_name, session_type, working_dir,
                    created_at, updated_at, extension_data, goose_mode
                ) VALUES (?, 'empty newer', 'empty newer', 0, 'user', ?, ?, ?, '{}', 'auto')
                """,
                (new_id, CWD, "2024-01-02 12:00:00", "2024-01-02 12:00:00"),
            )
            # Newer session with non-extractable payload (empty content array).
            conn.execute(
                """
                INSERT INTO sessions (
                    id, name, description, user_set_name, session_type, working_dir,
                    created_at, updated_at, extension_data, goose_mode
                ) VALUES (?, 'empty json', 'empty json', 0, 'user', ?, ?, ?, '{}', 'auto')
                """,
                (empty_json_id, CWD, "2024-01-03 12:00:00", "2024-01-03 12:00:00"),
            )
            conn.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content_json, created_timestamp, timestamp)
                VALUES ('empty-json', ?, 'user', '[]', 1, ?)
                """,
                (empty_json_id, "2024-01-03 12:00:00"),
            )
            conn.commit()
            conn.close()
            summaries = ADAPTER.list(query(root), ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [old_id])

    def test_malformed_message_json_fails_closed(self) -> None:
        import tempfile
        from tests.fixtures.goose import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "sessions" / "sessions.db"
            conn = bf._connect(db_path)
            bf._create_core_schema(conn)
            bf._insert_schema_versions(conn, range(1, 16))
            session_id = "gocorrupt-0101-4101-8101-010101010101"
            bf._insert_session(conn, session_id=session_id, name="corrupt", session_type="user")
            conn.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content_json, created_timestamp, timestamp)
                VALUES ('bad', ?, 'user', '{not-json', 1, ?)
                """,
                (session_id, "2024-01-01 12:00:00"),
            )
            conn.commit()
            conn.close()
            current = query(root, ref=session_id)
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.show(ResolvedRef(session_id=session_id, source_path=str(db_path)), current, ReadBudget())
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_corrupt_newer_session_fails_list_not_silent_fallback(self) -> None:
        """Latest eligibility must not skip a newer corrupt session for an older good one."""
        import tempfile
        from tests.fixtures.goose import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "sessions" / "sessions.db"
            conn = bf._connect(db_path)
            bf._create_core_schema(conn)
            bf._insert_schema_versions(conn, range(1, 16))
            old_id = "gocorrlat-0101-4101-8101-010101010101"
            new_id = "gocorrlat-0202-4202-8202-020202020202"
            bf._insert_session(conn, session_id=old_id, name="old good", session_type="user")
            bf._insert_message(
                conn,
                session_id=old_id,
                message_id="old-msg",
                role="user",
                text="recoverable history",
            )
            conn.execute(
                """
                INSERT INTO sessions (
                    id, name, description, user_set_name, session_type, working_dir,
                    created_at, updated_at, extension_data, goose_mode
                ) VALUES (?, 'corrupt newer', 'corrupt newer', 0, 'user', ?, ?, ?, '{}', 'auto')
                """,
                (new_id, CWD, "2024-01-02 12:00:00", "2024-01-02 12:00:00"),
            )
            conn.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content_json, created_timestamp, timestamp)
                VALUES ('bad-new', ?, 'user', '{not-json', 1, ?)
                """,
                (new_id, "2024-01-02 12:00:00"),
            )
            conn.commit()
            conn.close()
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(query(root), ReadBudget())
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_listed_sessions_zero_returns_empty(self) -> None:
        from portable_resume.bounds import Bounds

        root = fixture_root("s-go-01-user-basic")
        summaries = ADAPTER.list(query(root), ReadBudget(Bounds(listed_sessions=0)))
        self.assertEqual(summaries, [])

    def test_show_charges_shared_budget(self) -> None:
        from portable_resume.bounds import Bounds

        root = fixture_root("s-go-01-user-basic")
        db_path = root / "sessions" / "sessions.db"
        budget = ReadBudget(Bounds(transcript_records=1, source_read_bytes=8 * 1024 * 1024))
        budget.consume_transcript_records()  # already at ceiling
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(
                ResolvedRef(session_id=BASIC_ID, source_path=str(db_path)),
                query(root, ref=BASIC_ID),
                budget,
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
