from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from collections.abc import Iterator, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping
from unittest import mock

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.openclaw import ADAPTER, FORMAT_ID
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/openclaw")
CWD = "/tmp/project"


class _NoFetchAllCursor:
    def __init__(self, rows: Sequence[tuple[object, ...]]) -> None:
        self._rows = tuple(rows)

    def __iter__(self) -> Iterator[tuple[object, ...]]:
        return iter(self._rows)

    def fetchall(self) -> list[tuple[object, ...]]:
        raise AssertionError("bounded OpenClaw queries must stream rows")


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="openclaw",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class OpenClawAdapterTests(unittest.TestCase):
    def _copy_fixture(self, temporary: str, case: str = "s-oc-01-basic") -> Path:
        root = Path(temporary) / case
        shutil.copytree(fixture_root(case), root)
        return root

    def _add_session_nodes(
        self,
        root: Path,
        *,
        count: int,
        session_id: str | None = None,
    ) -> None:
        database = root / "agents/main/agent/openclaw-agent.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            for index in range(count):
                current_id = session_id or f"sess-extra-{index:04d}"
                session_key = f"agent:main:direct:extra-{index:04d}"
                connection.execute(
                    """
                    INSERT INTO session_nodes (
                      session_key, current_session_id, entry_json, updated_at,
                      created_at, created_via, display_name, last_interaction_at
                    ) VALUES (?, ?, ?, ?, ?, 'operator', ?, ?)
                    """,
                    (
                        session_key,
                        current_id,
                        '{"cwd":"/tmp/project","redacted":true}',
                        1_700_000_100_000 + index,
                        1_700_000_100_000 + index,
                        f"Extra {index}",
                        1_700_000_100_000 + index,
                    ),
                )
            connection.commit()

    def test_list_and_show_basic_fixture(self) -> None:
        root = fixture_root("s-oc-01-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, "main:sess-basic-0001")
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        self.assertEqual(summaries[0].title, "Synthetic basic")
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            [
                "Resume context from /tmp/project",
                "Synthetic assistant reply",
            ],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_multi_agent_composite_ids(self) -> None:
        root = fixture_root("s-oc-02-multi-agent")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        ids = sorted(item.session_id for item in summaries)
        self.assertEqual(ids, ["main:sess-main-0001", "worker:sess-worker-0001"])
        worker = next(item for item in summaries if item.session_id.startswith("worker:"))
        session = ADAPTER.show(ResolvedRef.from_summary(worker), current, ReadBudget())
        self.assertEqual(session.session_id, "worker:sess-worker-0001")
        self.assertEqual(
            [turn.content for turn in session.turns],
            [
                "Resume context from /tmp/project",
                "Synthetic assistant reply",
            ],
        )

    def test_compaction_reset_lists_current_window_only(self) -> None:
        root = fixture_root("s-oc-03-compaction-reset")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["main:sess-compact-reset"])
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        contents = [turn.content for turn in session.turns]
        # Compaction summary is inert recovered context on the active window.
        self.assertEqual(
            contents,
            [
                "Long thread before compaction",
                "Synthetic compaction kept first message",
                "Post-reset assistant line",
            ],
        )
        combined = " ".join(contents)
        self.assertNotIn("side-task", combined)

    def test_exact_historical_window_id_is_selectable(self) -> None:
        root = fixture_root("s-oc-03-compaction-reset")
        current = query(root, ref="main:sess-compact-initial")
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["main:sess-compact-initial"])

    def test_internal_and_cron_hidden_unless_exact(self) -> None:
        root = fixture_root("s-oc-04-internal-filter")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["main:sess-operator-01"])
        exact = ADAPTER.list(query(root, ref="main:sess-cron-01"), ReadBudget())
        self.assertEqual([item.session_id for item in exact], ["main:sess-cron-01"])

    def test_corrupt_meta_is_unsupported(self) -> None:
        root = fixture_root("s-oc-05-corrupt-meta")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "unsupported")
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_probe_supported_on_basic(self) -> None:
        root = fixture_root("s-oc-01-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")
        self.assertEqual(report.format_id, FORMAT_ID)

    def test_listing_fails_closed_at_caller_lowered_sql_scan_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy_fixture(temporary)
            self._add_session_nodes(root, count=49)
            before = tree_snapshot(root)
            budget = ReadBudget(Bounds(scanned_records=5))

            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(query(root), budget)

            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
            self.assertEqual(tree_snapshot(root), before)

    def test_list_debits_shared_record_and_byte_budget(self) -> None:
        root = fixture_root("s-oc-01-basic")
        budget = ReadBudget(Bounds(scanned_records=5, source_read_bytes=1024))

        summaries = ADAPTER.list(query(root), budget)

        self.assertEqual([item.session_id for item in summaries], ["main:sess-basic-0001"])
        self.assertGreater(budget.records, 0)
        self.assertGreater(budget.bytes_read, 0)

    def test_listing_streams_and_charges_rows_past_output_cap(self) -> None:
        from portable_resume.adapters import openclaw as oc

        small_entry = '{"cwd":"/tmp/project"}'
        oversized_entry = "x" * 129
        rows = [
            ("key-1", "session-1", small_entry, 1, 1, "operator", "one", None, 1),
            ("key-2", "session-2", oversized_entry, 0, 0, "operator", "two", None, 0),
        ]
        connection = mock.Mock()
        connection.execute.return_value = _NoFetchAllCursor(rows)
        budget = ReadBudget(
            Bounds(
                listed_sessions=1,
                scanned_records=5,
                record_bytes=128,
                source_read_bytes=1024,
            )
        )

        with self.assertRaises(DiagnosticError) as caught:
            oc._list_nodes(
                connection,
                agent_id="main",
                database="synthetic.sqlite",
                query=query(fixture_root("s-oc-01-basic")),
                include_internal=False,
                budget=budget,
            )

        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
        self.assertEqual(budget.records, 2)

    def test_exact_ref_streams_before_enforcing_byte_budget(self) -> None:
        from portable_resume.adapters import openclaw as oc

        rows = [
            ("session-1", '{"cwd":"/tmp/project"}', 1, 1, "one", 1, None, "operator"),
            ("session-1", "x" * 129, 0, 0, "two", 0, None, "operator"),
        ]
        connection = mock.Mock()
        connection.execute.return_value = _NoFetchAllCursor(rows)
        budget = ReadBudget(
            Bounds(scanned_records=5, record_bytes=128, source_read_bytes=1024)
        )

        with self.assertRaises(DiagnosticError) as caught:
            oc._exact_session_summaries(
                connection,
                agent_id="main",
                database="synthetic.sqlite",
                session_filter="session-1",
                query=query(fixture_root("s-oc-01-basic")),
                budget=budget,
            )

        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
        self.assertEqual(budget.records, 2)

    def test_exact_ref_is_bounded_and_debits_shared_budget(self) -> None:
        root = fixture_root("s-oc-01-basic")
        budget = ReadBudget(Bounds(scanned_records=5, source_read_bytes=1024))

        summaries = ADAPTER.list(query(root, ref="main:sess-basic-0001"), budget)

        self.assertEqual([item.session_id for item in summaries], ["main:sess-basic-0001"])
        self.assertEqual(budget.records, 1)
        self.assertGreater(budget.bytes_read, 0)

        with tempfile.TemporaryDirectory() as temporary:
            crowded = self._copy_fixture(temporary)
            self._add_session_nodes(crowded, count=5, session_id="sess-basic-0001")
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(
                    query(crowded, ref="main:sess-basic-0001"),
                    ReadBudget(Bounds(scanned_records=5)),
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_exact_ref_bypasses_zero_ordinary_listing_cap(self) -> None:
        root = fixture_root("s-oc-01-basic")
        budget = ReadBudget(
            Bounds(listed_sessions=0, scanned_records=5, source_read_bytes=1024)
        )

        summaries = ADAPTER.list(query(root, ref="main:sess-basic-0001"), budget)

        self.assertEqual([item.session_id for item in summaries], ["main:sess-basic-0001"])

    def test_show_without_source_path_bypasses_zero_ordinary_listing_cap(self) -> None:
        root = fixture_root("s-oc-01-basic")
        budget = ReadBudget(
            Bounds(
                listed_sessions=0,
                scanned_records=5,
                transcript_records=5,
                source_read_bytes=1024,
            )
        )

        session = ADAPTER.show(
            ResolvedRef(session_id="main:sess-basic-0001"),
            query(root),
            budget,
        )

        self.assertEqual(session.session_id, "main:sess-basic-0001")
        self.assertEqual(len(session.turns), 2)

    def test_lowered_snapshot_limit_selects_query_only_live_connection(self) -> None:
        from portable_resume.adapters import openclaw as oc

        root = fixture_root("s-oc-01-basic")
        database = root / "agents/main/agent/openclaw-agent.sqlite"
        budget = ReadBudget(Bounds(sqlite_snapshot_bytes=0))
        live_connection = object()
        with (
            mock.patch.object(oc, "query_only_live_sqlite", return_value=live_connection) as live,
            mock.patch.object(oc, "private_sqlite_connection") as private,
        ):
            selected = oc._open_connection(str(database), str(root), budget)

        self.assertIs(selected, live_connection)
        live.assert_called_once_with(str(database), root=str(root), provider=FORMAT_ID)
        private.assert_not_called()

        snapshot_budget = ReadBudget()
        private_connection = object()
        with (
            mock.patch.object(oc, "query_only_live_sqlite") as live,
            mock.patch.object(
                oc, "private_sqlite_connection", return_value=private_connection
            ) as private,
        ):
            selected = oc._open_connection(str(database), str(root), snapshot_budget)

        self.assertIs(selected, private_connection)
        private.assert_called_once_with(
            str(database),
            root=str(root),
            bounds=snapshot_budget.limits,
            provider=FORMAT_ID,
        )
        live.assert_not_called()

    def test_agent_directory_enumeration_honors_lowered_scan_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(6):
                (root / "agents" / f"agent-{index}" / "agent").mkdir(parents=True)

            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(query(root), ReadBudget(Bounds(scanned_records=5)))

            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_show_debits_shared_transcript_and_byte_budget(self) -> None:
        root = fixture_root("s-oc-01-basic")
        database = root / "agents/main/agent/openclaw-agent.sqlite"
        budget = ReadBudget(Bounds(transcript_records=5, source_read_bytes=1024))

        session = ADAPTER.show(
            ResolvedRef(session_id="main:sess-basic-0001", source_path=str(database)),
            query(root, ref="main:sess-basic-0001"),
            budget,
        )

        self.assertEqual(len(session.turns), 2)
        self.assertEqual(budget.transcript_records_read, 2)
        self.assertGreater(budget.bytes_read, 0)

    def test_nested_message_payload_and_compaction_retention(self) -> None:
        from portable_resume.adapters import openclaw as oc

        nested = {
            "type": "message",
            "id": "n1",
            "parentId": None,
            "message": {"role": "user", "content": "nested user"},
        }
        self.assertEqual(oc._event_role(nested), "user")
        self.assertEqual(oc._message_text(nested), "nested user")

        events: list[Mapping[str, Any]] = [
            {"type": "message", "id": "a", "parentId": None, "role": "user", "text": "old"},
            {"type": "message", "id": "b", "parentId": "a", "role": "assistant", "text": "replaced"},
            {
                "type": "compaction",
                "id": "c",
                "parentId": "b",
                "firstKeptEntryId": "a",
                "summary": "compacted",
            },
            {"type": "message", "id": "d", "parentId": "c", "role": "user", "text": "after"},
        ]
        path = oc._active_branch_events(events)
        ids = [item.get("id") for item in path]
        # Retains compaction summary and firstKept entry; skips replaced sibling path.
        self.assertEqual(ids, ["a", "c", "d"])
        self.assertNotIn("b", ids)

        with_branch: list[Mapping[str, Any]] = [
            {"type": "message", "id": "a", "parentId": None, "role": "user", "text": "root"},
            {"type": "branch_summary", "id": "bs", "parentId": "a", "branch": "side"},
            {"type": "message", "id": "z", "parentId": "bs", "role": "assistant", "text": "leaf"},
        ]
        path2 = oc._active_branch_events(with_branch)
        self.assertEqual([item.get("id") for item in path2], ["a", "z"])


if __name__ == "__main__":
    unittest.main()
