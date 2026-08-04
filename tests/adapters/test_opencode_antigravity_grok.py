from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from portable_resume.adapters.antigravity import AntigravityAdapter, FORMAT_ID as ANT_FORMAT
from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.grok import FORMAT_ID as GROK_FORMAT, GrokAdapter
from portable_resume.adapters.opencode import (
    EXPORT_PROVIDER,
    FILE_FORMAT,
    SQLITE_FORMAT,
    OpenCodeAdapter,
)
from portable_resume.bounds import Bounds, DEFAULT_BOUNDS, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.handoff import render_handoff
from portable_resume.model import Envelope, Query
from portable_resume.select import AmbiguousSelection, select_session
from tests.helpers.core import tree_snapshot
from tests.helpers.fixture_manifest import validate_fixture_tree


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CWD = "/workspace/project"


def fixture_root(source: str, case: str) -> Path:
    return (FIXTURES / source / case / "root").resolve()


def query(source: str, root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(source=source, ref=ref, cwd=CWD, source_root=str(root), **kwargs)


def resolve(items, session_id: str):
    return ResolvedRef.from_summary(next(item for item in items if item.session_id == session_id))


def _opencode_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE session (
            id TEXT NOT NULL,
            directory TEXT NOT NULL,
            title TEXT,
            time_created INTEGER,
            time_updated INTEGER
        );
        CREATE TABLE message (
            id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER,
            data TEXT
        );
        CREATE TABLE part (
            id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER,
            data TEXT
        );
        """
    )


def _write_opencode_db(
    path: Path,
    *,
    sessions: list[tuple[str, str, str | None, int, int]],
    messages: list[tuple[str, str, int, str]] | None = None,
    parts: list[tuple[str, str, str, int, str]] | None = None,
) -> None:
    connection = sqlite3.connect(path)
    try:
        _opencode_schema(connection)
        connection.executemany(
            "INSERT INTO session(id,directory,title,time_created,time_updated) VALUES (?,?,?,?,?)",
            sessions,
        )
        if messages:
            connection.executemany(
                "INSERT INTO message(id,session_id,time_created,data) VALUES (?,?,?,?)",
                messages,
            )
        if parts:
            connection.executemany(
                "INSERT INTO part(id,message_id,session_id,time_created,data) VALUES (?,?,?,?,?)",
                parts,
            )
        connection.commit()
    finally:
        connection.close()


class FixtureManifestTests(unittest.TestCase):
    def test_all_lane_fixture_manifests_are_strict_and_complete(self) -> None:
        expected = {
            "opencode": {f"s-ope-{index:02d}" for index in range(1, 8)},
            "antigravity": {f"s-ant-{index:02d}" for index in range(1, 8)},
            "grok": {f"s-gro-{index:02d}" for index in range(1, 9)},
        }
        for source, cases in expected.items():
            with self.subTest(source=source):
                manifests = validate_fixture_tree(FIXTURES / source)
                self.assertEqual({item.case for item in manifests}, cases)
                self.assertTrue(all(item.synthetic for item in manifests))


class OpenCodeAdapterTests(unittest.TestCase):
    def test_sqlite_signature_list_show_join_order_and_immutability(self) -> None:
        root = fixture_root("opencode", "s-ope-01")
        before = tree_snapshot(root)
        adapter = OpenCodeAdapter(root=str(root))
        current = query("opencode", root, "ses-sql")
        self.assertEqual(adapter.probe(current).format_id, SQLITE_FORMAT)
        budget = ReadBudget()
        summaries = adapter.list(current, budget)
        self.assertEqual([item.session_id for item in summaries], ["ses-sql"])
        session = adapter.show(resolve(summaries, "ses-sql"), current, budget)
        self.assertEqual([turn.role for turn in session.turns], ["user", "assistant", "tool"])
        self.assertEqual(session.last_user_request, "Please inspect the synthetic parser.")
        self.assertEqual(session.last_assistant_action, "I inspected only synthetic evidence.")
        self.assertEqual(tree_snapshot(root), before)

    def test_sqlite_is_opened_only_as_private_uri_query_only(self) -> None:
        root = fixture_root("opencode", "s-ope-01")
        source_db = str(root / "opencode.db")
        calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
        original = sqlite3.connect

        def audited(database, *args, **kwargs):
            calls.append((database, args, kwargs))
            return original(database, *args, **kwargs)

        adapter = OpenCodeAdapter(root=str(root))
        with mock.patch("sqlite3.connect", side_effect=audited):
            summaries = adapter.list(query("opencode", root, "ses-sql"), ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertTrue(calls)
        for database, _, kwargs in calls:
            self.assertIsInstance(database, str)
            self.assertTrue(str(database).startswith("file:"))
            self.assertIn("mode=ro&cache=private", str(database))
            self.assertNotIn(source_db, str(database))
            self.assertIs(kwargs.get("uri"), True)

    def test_legacy_file_store_and_explicit_export(self) -> None:
        file_root = fixture_root("opencode", "s-ope-02")
        file_adapter = OpenCodeAdapter(root=str(file_root))
        current = query("opencode", file_root, "ses-file")
        summaries = file_adapter.list(current, ReadBudget())
        self.assertEqual(summaries[0].provider, FILE_FORMAT)
        session = file_adapter.show(resolve(summaries, "ses-file"), current, ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["Legacy file prompt", "Legacy file response"])

        export_root = fixture_root("opencode", "s-ope-06")
        export_path = export_root / "exports" / "session.json"
        export_adapter = OpenCodeAdapter(root=str(export_root))
        export_query = query("opencode", export_root, str(export_path))
        exports = export_adapter.list(export_query, ReadBudget())
        self.assertEqual(exports[0].provider, EXPORT_PROVIDER)
        exported = export_adapter.show(resolve(exports, "ses-export"), export_query, ReadBudget())
        self.assertEqual(exported.last_user_request, "Export prompt")

    def test_reasoning_binary_and_orphan_are_not_guessed(self) -> None:
        filtered_root = fixture_root("opencode", "s-ope-03")
        filtered_adapter = OpenCodeAdapter(root=str(filtered_root))
        current = query("opencode", filtered_root, "ses-sql")
        values = filtered_adapter.list(current, ReadBudget())
        session = filtered_adapter.show(resolve(values, "ses-sql"), current, ReadBudget())
        self.assertNotIn("private chain", " ".join(turn.content for turn in session.turns))
        self.assertIn("W_BINARY_OMITTED", session.warnings)

        orphan_root = fixture_root("opencode", "s-ope-04")
        orphan_adapter = OpenCodeAdapter(root=str(orphan_root))
        orphan_query = query("opencode", orphan_root, "ses-sql")
        orphan_values = orphan_adapter.list(orphan_query, ReadBudget())
        orphan = orphan_adapter.show(resolve(orphan_values, "ses-sql"), orphan_query, ReadBudget())
        self.assertIn("W_BROKEN_CHAIN", orphan.warnings)
        self.assertNotIn("orphan", " ".join(turn.content for turn in orphan.turns))

    def test_schema_drift_and_hot_journal_fail_closed(self) -> None:
        drift_root = fixture_root("opencode", "s-ope-05")
        drift = OpenCodeAdapter(root=str(drift_root))
        self.assertEqual(drift.probe(query("opencode", drift_root)).state, "unsupported")
        with self.assertRaises(DiagnosticError) as caught:
            drift.list(query("opencode", drift_root), ReadBudget())
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

        hot_root = fixture_root("opencode", "s-ope-07")
        before = tree_snapshot(hot_root)
        hot = OpenCodeAdapter(root=str(hot_root))
        with self.assertRaises(DiagnosticError) as caught:
            hot.list(query("opencode", hot_root), ReadBudget())
        self.assertEqual(caught.exception.code, "E_SQLITE_HOT_JOURNAL")
        self.assertEqual(tree_snapshot(hot_root), before)

    def test_family_entry_race_exhausts_snapshot_without_source_connection(self) -> None:
        """Unrelated siblings no longer invalidate SQLite snapshots (#16); mutate the DB."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "opencode.db"
            shutil.copy2(fixture_root("opencode", "s-ope-01") / "opencode.db", db)
            original = db.read_bytes()
            original_mtime = db.stat().st_mtime_ns

            def race(phase: str, attempt: int, _path: str) -> None:
                if phase == "after-copy":
                    # Same-size flip so coarse stats can match while content drifts.
                    flipped = bytes((b ^ 0xFF) for b in original[: min(64, len(original))]) + original[min(64, len(original)) :]
                    if len(flipped) != len(original):
                        flipped = original[::-1] if original else b"x"
                    db.write_bytes(flipped if attempt % 2 else original)
                    os.utime(db, ns=(original_mtime, original_mtime))

            adapter = OpenCodeAdapter(root=str(root), sqlite_hook=race)
            with self.assertRaises(DiagnosticError) as caught:
                adapter.list(query("opencode", root), ReadBudget())
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_tool_output_obeys_query_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_dir = root / "exports"
            export_dir.mkdir()
            payload = {
                "info": {"id": "tool-bound", "directory": CWD, "time": {"created": 1, "updated": 2}},
                "messages": [
                    {
                        "info": {"id": "m", "sessionID": "tool-bound", "role": "assistant", "time": {"created": 1}},
                        "parts": [{"id": "p", "type": "tool", "tool": "shell", "content": "0123456789"}],
                    }
                ],
            }
            (export_dir / "bounded.json").write_text(json.dumps(payload))
            adapter = OpenCodeAdapter(root=str(root))
            current = query("opencode", root, "tool-bound", max_tool_chars=4)
            summaries = adapter.list(current, ReadBudget())
            session = adapter.show(resolve(summaries, "tool-bound"), current, ReadBudget())
            self.assertEqual(session.turns[0].content, "0123")
            self.assertTrue(session.turns[0].truncated)
            self.assertIn("W_TRUNCATED", session.warnings)


class OpenCodeIssue13Tests(unittest.TestCase):
    """P0 regressions for exact-ID SQL, transcript show budget, scoped file store, export bound."""

    def test_exact_id_older_than_newest_list_window_is_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "opencode.db"
            # 55 sessions same cwd; exact target is oldest and outside listed_sessions=50.
            sessions = [
                (f"ses-{index:03d}", CWD, f"t{index}", index, index) for index in range(55)
            ]
            _write_opencode_db(db, sessions=sessions)
            adapter = OpenCodeAdapter(root=str(root))
            current = query("opencode", root, "ses-000", within_min=0)
            before = tree_snapshot(root)
            summaries = adapter.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], ["ses-000"])
            selection = select_session(summaries, ref="ses-000", cwd=CWD, approved_roots=(str(root),))
            self.assertIsNotNone(selection.selected)
            assert selection.selected is not None
            self.assertEqual(selection.selected.session_id, "ses-000")
            self.assertEqual(tree_snapshot(root), before)

            # Without exact ref, newest window must not claim the oldest id.
            latest = adapter.list(query("opencode", root, within_min=0), ReadBudget())
            self.assertNotIn("ses-000", {item.session_id for item in latest})
            self.assertEqual(len(latest), DEFAULT_BOUNDS.listed_sessions)

    def test_sqlite_show_uses_transcript_not_scanned_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "opencode.db"
            session_id = "ses-long"
            messages = [
                (
                    "msg-u",
                    session_id,
                    1,
                    json.dumps({"role": "user"}, separators=(",", ":")),
                ),
                (
                    "msg-a",
                    session_id,
                    2,
                    json.dumps({"role": "assistant"}, separators=(",", ":")),
                ),
            ]
            # 30 joined part rows: exceeds scanned_records=20, under transcript_records=100.
            parts: list[tuple[str, str, str, int, str]] = [
                (
                    "p-user",
                    "msg-u",
                    session_id,
                    1,
                    json.dumps(
                        {"type": "text", "text": "long prompt"},
                        separators=(",", ":"),
                    ),
                )
            ]
            for index in range(29):
                parts.append(
                    (
                        f"p-a{index}",
                        "msg-a",
                        session_id,
                        2 + index,
                        json.dumps(
                            {"type": "text", "text": f"chunk {index}"},
                            separators=(",", ":"),
                        ),
                    )
                )
            _write_opencode_db(
                db,
                sessions=[(session_id, CWD, "long", 1, 100)],
                messages=messages,
                parts=parts,
            )
            adapter = OpenCodeAdapter(root=str(root))
            current = query("opencode", root, session_id, within_min=0)
            summaries = adapter.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [session_id])
            # Old bug: LIMIT scanned_records+1 would reject 21+ joined rows.
            tight_scan = ReadBudget(Bounds(scanned_records=20, transcript_records=100))
            shown = adapter.show(resolve(summaries, session_id), current, tight_scan)
            self.assertEqual(shown.turns[0].content, "long prompt")
            self.assertGreaterEqual(len(shown.turns), 2)
            self.assertGreater(tight_scan.transcript_records_read, 20)
            self.assertEqual(tight_scan.records, 0)

            # Overflow probe: transcript_records+1 fails closed (no partial Session).
            # scanned_records must stay at/under DEFAULT_BOUNDS (no raised ceilings).
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(
                    resolve(summaries, session_id),
                    current,
                    ReadBudget(Bounds(transcript_records=10, scanned_records=20)),
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_sqlite_show_preserves_tail_near_transcript_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "opencode.db"
            session_id = "ses-tail"
            messages = [
                (
                    "msg-u",
                    session_id,
                    1,
                    json.dumps({"role": "user"}, separators=(",", ":")),
                ),
                (
                    "msg-a",
                    session_id,
                    2,
                    json.dumps({"role": "assistant"}, separators=(",", ":")),
                ),
            ]
            # 8 joined rows; ceiling 8 admits all including last assistant text.
            parts = [
                (
                    "p-u",
                    "msg-u",
                    session_id,
                    1,
                    json.dumps({"type": "text", "text": "tail prompt"}, separators=(",", ":")),
                )
            ]
            for index in range(7):
                text = "final assistant answer" if index == 6 else f"mid {index}"
                parts.append(
                    (
                        f"p{index}",
                        "msg-a",
                        session_id,
                        10 + index,
                        json.dumps({"type": "text", "text": text}, separators=(",", ":")),
                    )
                )
            _write_opencode_db(
                db,
                sessions=[(session_id, CWD, "tail", 1, 2)],
                messages=messages,
                parts=parts,
            )
            adapter = OpenCodeAdapter(root=str(root))
            current = query("opencode", root, session_id, within_min=0)
            summaries = adapter.list(current, ReadBudget())
            shown = adapter.show(
                resolve(summaries, session_id),
                current,
                ReadBudget(Bounds(transcript_records=8)),
            )
            self.assertEqual(shown.last_user_request, "tail prompt")
            self.assertEqual(shown.last_assistant_action, "final assistant answer")
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(
                    resolve(summaries, session_id),
                    current,
                    ReadBudget(Bounds(transcript_records=7)),
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_file_store_show_scopes_to_session_message_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "storage"
            session_id = "ses-target"
            (storage / "session" / "project").mkdir(parents=True)
            (storage / "message" / session_id).mkdir(parents=True)
            (storage / "part" / "msg-t-u").mkdir(parents=True)
            (storage / "part" / "msg-t-a").mkdir(parents=True)
            session_path = storage / "session" / "project" / f"{session_id}.json"
            session_path.write_text(
                json.dumps(
                    {
                        "id": session_id,
                        "directory": CWD,
                        "title": "target",
                        "time": {"created": 1, "updated": 2},
                    }
                ),
                encoding="utf-8",
            )
            (storage / "message" / session_id / "msg-t-u.json").write_text(
                json.dumps(
                    {
                        "id": "msg-t-u",
                        "sessionID": session_id,
                        "role": "user",
                        "time": {"created": 1},
                    }
                ),
                encoding="utf-8",
            )
            (storage / "message" / session_id / "msg-t-a.json").write_text(
                json.dumps(
                    {
                        "id": "msg-t-a",
                        "sessionID": session_id,
                        "role": "assistant",
                        "time": {"created": 2},
                    }
                ),
                encoding="utf-8",
            )
            (storage / "part" / "msg-t-u" / "p1.json").write_text(
                json.dumps(
                    {
                        "id": "p1",
                        "sessionID": session_id,
                        "messageID": "msg-t-u",
                        "type": "text",
                        "text": "scoped prompt",
                        "time": {"created": 1},
                    }
                ),
                encoding="utf-8",
            )
            (storage / "part" / "msg-t-a" / "p2.json").write_text(
                json.dumps(
                    {
                        "id": "p2",
                        "sessionID": session_id,
                        "messageID": "msg-t-a",
                        "type": "text",
                        "text": "scoped answer",
                        "time": {"created": 2},
                    }
                ),
                encoding="utf-8",
            )
            # Unrelated histories would exhaust scanned_records if message/ were fully walked.
            noise = DEFAULT_BOUNDS.scanned_records + 200
            for index in range(noise):
                other = f"ses-noise-{index}"
                other_dir = storage / "message" / other
                other_dir.mkdir(parents=True, exist_ok=True)
                (other_dir / "m.json").write_text(
                    json.dumps({"id": "m", "sessionID": other, "role": "user", "time": {"created": 1}}),
                    encoding="utf-8",
                )
            adapter = OpenCodeAdapter(root=str(root))
            current = query("opencode", root, session_id, within_min=0)
            before = tree_snapshot(root)
            ref = ResolvedRef(
                session_id=session_id,
                source_path=str(session_path.resolve()),
                provider=FILE_FORMAT,
                cwd=CWD,
            )
            shown = adapter.show(ref, current, ReadBudget())
            self.assertEqual([turn.content for turn in shown.turns], ["scoped prompt", "scoped answer"])
            self.assertEqual(tree_snapshot(root), before)

    def test_export_uses_source_read_bytes_not_record_bytes(self) -> None:
        """Product decision: explicit export is one source document under source_read_bytes."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_dir = root / "exports"
            export_dir.mkdir()
            # Small structural export with a large text field so file size sits between
            # a lowered record_bytes and source_read_bytes.
            pad = "x" * 800
            payload = {
                "info": {
                    "id": "ses-export-bound",
                    "directory": CWD,
                    "title": "bound",
                    "time": {"created": 1, "updated": 2},
                },
                "messages": [
                    {
                        "info": {
                            "id": "m1",
                            "sessionID": "ses-export-bound",
                            "role": "user",
                            "time": {"created": 1},
                        },
                        "parts": [
                            {
                                "id": "p1",
                                "type": "text",
                                "text": f"export-prompt {pad}",
                                "time": {"created": 1},
                            }
                        ],
                    }
                ],
            }
            export_path = export_dir / "large.json"
            export_path.write_text(json.dumps(payload), encoding="utf-8")
            size = export_path.stat().st_size
            self.assertGreater(size, 200)
            self.assertLess(size, 4_000)

            adapter = OpenCodeAdapter(root=str(root))
            current = query("opencode", root, "ses-export-bound", within_min=0)
            # Would fail if export still inherited record_bytes=200.
            list_budget = ReadBudget(Bounds(record_bytes=200, source_read_bytes=4_000))
            summaries = adapter.list(current, list_budget)
            self.assertEqual([item.session_id for item in summaries], ["ses-export-bound"])
            # Fresh show budget matches reader CLI (list and show do not share counters).
            shown = adapter.show(
                resolve(summaries, "ses-export-bound"),
                current,
                ReadBudget(Bounds(record_bytes=200, source_read_bytes=4_000)),
            )
            self.assertTrue(shown.last_user_request and shown.last_user_request.startswith("export-prompt"))

            with self.assertRaises(DiagnosticError) as caught:
                adapter.list(
                    current,
                    ReadBudget(Bounds(record_bytes=16 * 1024 * 1024, source_read_bytes=100)),
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


class AntigravityAdapterTests(unittest.TestCase):
    def test_indexed_list_show_filters_internal_and_preserves_source(self) -> None:
        root = fixture_root("antigravity", "s-ant-03")
        before = tree_snapshot(root)
        adapter = AntigravityAdapter(root=str(root))
        current = query("antigravity", root, "conv-one")
        summaries = adapter.list(current, ReadBudget())
        session = adapter.show(resolve(summaries, "conv-one"), current, ReadBudget())
        content = " ".join(turn.content for turn in session.turns)
        self.assertNotIn("secret system", content)
        self.assertNotIn("secret thought", content)
        self.assertEqual([turn.role for turn in session.turns], ["user", "assistant"])
        self.assertEqual(tree_snapshot(root), before)

    def test_missing_index_exact_id_and_path_work_as_partial(self) -> None:
        root = fixture_root("antigravity", "s-ant-02")
        transcript = root / "brain" / "conv-one" / ".system_generated" / "logs" / "transcript.jsonl"
        adapter = AntigravityAdapter(root=str(root))
        by_id = query("antigravity", root, "conv-one")
        self.assertEqual(adapter.probe(by_id).state, "partial")
        values = adapter.list(by_id, ReadBudget())
        self.assertEqual([item.session_id for item in values], ["conv-one"])
        by_path = query("antigravity", root, str(transcript))
        values_by_path = adapter.list(by_path, ReadBudget())
        selected = select_session(values_by_path, ref=str(transcript), cwd=CWD, approved_roots=(str(root),))
        self.assertEqual(selected.selected.session_id, "conv-one")

    def test_tool_output_bound_and_partial_tail_warning(self) -> None:
        tool_root = fixture_root("antigravity", "s-ant-04")
        adapter = AntigravityAdapter(root=str(tool_root))
        current = query("antigravity", tool_root, "conv-one", max_tool_chars=16)
        values = adapter.list(current, ReadBudget())
        session = adapter.show(resolve(values, "conv-one"), current, ReadBudget())
        tool = next(turn for turn in session.turns if turn.role == "tool")
        self.assertEqual(len(tool.content), 16)
        self.assertTrue(tool.truncated)
        self.assertIn("W_TRUNCATED", session.warnings)

        tail_root = fixture_root("antigravity", "s-ant-05")
        tail_adapter = AntigravityAdapter(root=str(tail_root))
        tail_query = query("antigravity", tail_root, "conv-one")
        tail_values = tail_adapter.list(tail_query, ReadBudget())
        tail = tail_adapter.show(resolve(tail_values, "conv-one"), tail_query, ReadBudget())
        self.assertIn("W_PARTIAL_TAIL", tail.warnings)

    def test_interior_corruption_fails_and_stale_index_fabricates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("antigravity", "s-ant-01"), root, dirs_exist_ok=True)
            transcript = root / "brain" / "conv-one" / ".system_generated" / "logs" / "transcript.jsonl"
            original = transcript.read_text()
            transcript.write_text('{"type":"session"\n' + original)
            adapter = AntigravityAdapter(root=str(root))
            with self.assertRaises(DiagnosticError) as caught:
                adapter.list(query("antigravity", root, "conv-one"), ReadBudget())
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

        stale_root = fixture_root("antigravity", "s-ant-06")
        stale_adapter = AntigravityAdapter(root=str(stale_root))
        current = query("antigravity", stale_root, "conv-one")
        report = stale_adapter.probe(current)
        self.assertIn("W_STALE_INDEX", report.warnings)
        values = stale_adapter.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in values], ["conv-one"])
        self.assertNotIn("missing-conv", [item.session_id for item in values])

    def test_changing_transcript_fails_busy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("antigravity", "s-ant-02"), root, dirs_exist_ok=True)

            def race(phase: str, _attempt: int, path: str) -> None:
                if phase == "after-read" and path.endswith("transcript.jsonl"):
                    with open(path, "ab") as handle:
                        handle.write(b" ")

            adapter = AntigravityAdapter(root=str(root), read_hook=race)
            with self.assertRaises(DiagnosticError) as caught:
                adapter.list(query("antigravity", root, "conv-one"), ReadBudget())
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_exact_show_survives_oversized_optional_index(self) -> None:
        """Exact transcript path must not require rediscovering brain/index.json (#15)."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("antigravity", "s-ant-01"), root, dirs_exist_ok=True)
            index = root / "brain" / "index.json"
            # Oversized index would E_LIMIT_EXCEEDED if required for show.
            index.write_bytes(b'{"format":"antigravity-index-v1","conversations":[' + b"x" * 100 + b"]}")
            adapter = AntigravityAdapter(root=str(root))
            current = query("antigravity", root, "conv-one")
            transcript = root / "brain" / "conv-one" / ".system_generated" / "logs" / "transcript.jsonl"
            ref = ResolvedRef(
                session_id="conv-one",
                source_path=str(transcript),
                provider=ANT_FORMAT,
            )
            session = adapter.show(ref, current, ReadBudget())
            self.assertEqual(session.session_id, "conv-one")
            self.assertTrue(session.turns)
            self.assertIn("W_STALE_INDEX", session.warnings)

    def test_cli_empty_transcript_uses_history_and_messages_lane(self) -> None:
        """#248: empty transcript.jsonl recovers via history.jsonl + messages/*."""
        root = fixture_root("antigravity", "s-ant-07")
        before = tree_snapshot(root)
        adapter = AntigravityAdapter(root=str(root))
        list_q = query("antigravity", root, None, within_min=0)
        summaries = adapter.list(list_q, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["conv-cli"])
        self.assertIn("W_CLI_MESSAGES_LANE", summaries[0].warnings)
        show_q = query("antigravity", root, "conv-cli", within_min=0)
        session = adapter.show(resolve(summaries, "conv-cli"), show_q, ReadBudget())
        self.assertEqual(session.session_id, "conv-cli")
        roles = [turn.role for turn in session.turns]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)
        # Chronological handoff: user prompts and assistant replies interleaved by time.
        self.assertEqual(
            [(turn.role, turn.content.splitlines()[0][:40]) for turn in session.turns],
            [
                ("user", "fix the windows packager"),
                ("user", "open WIP PR with size table"),
                ("assistant", "Message from packaging agent"),
            ],
        )
        joined = " ".join(turn.content for turn in session.turns)
        self.assertIn("fix the windows packager", joined)
        self.assertIn("Lite channel", joined)
        self.assertNotIn("internal timer cancelled noise", joined)
        self.assertIn("W_CLI_MESSAGES_LANE", session.warnings)
        self.assertEqual(session.updated_at, "2026-08-04T15:23:51Z")
        self.assertEqual(tree_snapshot(root), before)

    def test_cli_messages_lane_merges_history_and_messages_chronologically(self) -> None:
        """#249: merge history + messages before ordinals (not all-users-then-assistants)."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "conv-interleave"
            brain = root / "brain" / session_id / ".system_generated"
            (brain / "logs").mkdir(parents=True)
            (brain / "messages").mkdir(parents=True)
            (brain / "logs" / "transcript.jsonl").write_bytes(b"")
            history = [
                {
                    "display": "first user",
                    "timestamp": 1_785_856_851_015,
                    "workspace": CWD,
                    "conversationId": session_id,
                },
                {
                    "display": "second user",
                    "timestamp": 1_785_856_971_015,
                    "workspace": CWD,
                    "conversationId": session_id,
                },
            ]
            (root / "history.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in history),
                encoding="utf-8",
            )
            # Assistant between the two user prompts (by timestamp).
            (brain / "messages" / "a1.json").write_text(
                json.dumps(
                    {
                        "id": "a1",
                        "content": "first assistant",
                        "timestamp": "2026-08-04T15:21:51Z",
                        "hideFromUser": False,
                    }
                ),
                encoding="utf-8",
            )
            (brain / "messages" / "a2.json").write_text(
                json.dumps(
                    {
                        "id": "a2",
                        "content": "second assistant",
                        "timestamp": "2026-08-04T15:24:51Z",
                        "hideFromUser": False,
                    }
                ),
                encoding="utf-8",
            )
            before = tree_snapshot(root)
            adapter = AntigravityAdapter(root=str(root))
            list_q = query("antigravity", root, None, within_min=0)
            summaries = adapter.list(list_q, ReadBudget())
            session = adapter.show(
                resolve(summaries, session_id),
                query("antigravity", root, session_id, within_min=0),
                ReadBudget(),
            )
            self.assertEqual(
                [(turn.role, turn.content) for turn in session.turns],
                [
                    ("user", "first user"),
                    ("assistant", "first assistant"),
                    ("user", "second user"),
                    ("assistant", "second assistant"),
                ],
            )
            self.assertEqual(session.updated_at, "2026-08-04T15:24:51Z")
            self.assertEqual(tree_snapshot(root), before)
            # List mode: later messages-dir activity must win over older history prompts.
            messages_dir = brain / "messages"
            late = 1_785_857_100.0  # 2026-08-04T15:25:00Z approx
            os.utime(messages_dir, (late, late))
            listed = adapter.list(list_q, ReadBudget())
            self.assertEqual(len(listed), 1)
            self.assertGreaterEqual(listed[0].updated_at or "", "2026-08-04T15:24:00Z")

    def test_cli_history_overflow_fails_closed(self) -> None:
        """#249: history.jsonl scan overflow must not silently drop user prompts."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "conv-overflow"
            brain = root / "brain" / session_id / ".system_generated"
            (brain / "logs").mkdir(parents=True)
            (brain / "messages").mkdir(parents=True)
            (brain / "logs" / "transcript.jsonl").write_bytes(b"")
            (brain / "messages" / "a1.json").write_text(
                json.dumps(
                    {
                        "id": "a1",
                        "content": "assistant only without prompts would be wrong",
                        "timestamp": "2026-08-04T15:23:51Z",
                        "hideFromUser": False,
                    }
                ),
                encoding="utf-8",
            )
            # Exceed scanned_records so stable_scan_lines raises E_LIMIT_EXCEEDED
            # before replaying any verified history lines.
            lines = []
            for index in range(DEFAULT_BOUNDS.scanned_records + 5):
                lines.append(
                    json.dumps(
                        {
                            "display": f"prompt-{index}",
                            "timestamp": 1_785_856_851_015 + index,
                            "workspace": CWD,
                            "conversationId": session_id,
                        }
                    )
                )
            (root / "history.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            adapter = AntigravityAdapter(root=str(root))
            with self.assertRaises(DiagnosticError) as caught:
                adapter.list(query("antigravity", root, None, within_min=0), ReadBudget())
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


class GrokAdapterTests(unittest.TestCase):
    def test_exact_show_ignores_large_nonpublic_raw_output_array(self) -> None:
        """Ignored provider deltas must not borrow the discovery-record ceiling (#178)."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_dir = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-raw-output"
            session_dir.mkdir(parents=True)
            updates = session_dir / "updates.jsonl"
            ignored_marker = "ignored-provider-delta"
            record = {
                "timestamp": 1,
                "method": "session/update",
                "params": {
                    "sessionId": "grok-raw-output",
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "synthetic-tool",
                        "content": "public tool result",
                        "rawOutput": {
                            "output_delta": [
                                {"signature": ignored_marker},
                                *([ignored_marker] * 2_872),
                            ],
                        },
                    },
                },
            }
            encoded = json.dumps(record, separators=(",", ":")).encode("utf-8")
            self.assertLess(len(encoded), DEFAULT_BOUNDS.record_bytes)
            updates.write_bytes(encoded + b"\n")
            before = tree_snapshot(root)

            adapter = GrokAdapter(root=str(root))
            current = query("grok", root, "grok-raw-output", within_min=0)
            values = adapter.list(current, ReadBudget())
            session = adapter.show(resolve(values, "grok-raw-output"), current, ReadBudget())

            self.assertEqual([turn.content for turn in session.turns], ["public tool result"])
            normalized = json.dumps(session.to_dict(), sort_keys=True)
            handoff = render_handoff(
                Envelope.create(
                    operation="show",
                    query=current,
                    sessions=(session,),
                    generated_at="2026-08-01T00:00:00Z",
                )
            )
            self.assertNotIn("rawOutput", normalized)
            self.assertNotIn(ignored_marker, normalized)
            self.assertNotIn(ignored_marker, handoff)
            self.assertEqual(tree_snapshot(root), before)

    def test_grok_public_and_physical_record_bounds_remain_fail_closed(self) -> None:
        def show_record(encoded: bytes, budget: ReadBudget, *, max_tool_chars: int = 8_000):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                session_dir = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-bounds"
                session_dir.mkdir(parents=True)
                updates = session_dir / "updates.jsonl"
                updates.write_bytes(encoded + b"\n")
                return GrokAdapter(root=str(root)).show(
                    ResolvedRef(
                        session_id="grok-bounds",
                        source_path=str(updates),
                        provider=GROK_FORMAT,
                    ),
                    query(
                        "grok",
                        root,
                        "grok-bounds",
                        within_min=0,
                        max_tool_chars=max_tool_chars,
                    ),
                    budget,
                )

        public_array = {
            "timestamp": 1,
            "method": "session/update",
            "params": {
                "sessionId": "grok-bounds",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "content": [{"type": "text", "text": "x"}] * 2_001,
                },
            },
        }
        public_encoded = json.dumps(public_array, separators=(",", ":")).encode("utf-8")
        with self.assertRaises(DiagnosticError) as public_error:
            show_record(public_encoded, ReadBudget())
        self.assertEqual(public_error.exception.code, "E_LIMIT_EXCEEDED")

        valid_record = {
            "timestamp": 1,
            "method": "session/update",
            "params": {
                "sessionId": "grok-bounds",
                "update": {"sessionUpdate": "tool_call_update", "content": "bounded"},
            },
        }
        valid_encoded = json.dumps(valid_record, separators=(",", ":")).encode("utf-8")
        truncated = show_record(valid_encoded, ReadBudget(), max_tool_chars=4)
        self.assertEqual(truncated.turns[0].content, "boun")
        self.assertTrue(truncated.turns[0].truncated)
        self.assertIn("W_TRUNCATED", truncated.warnings)
        with self.assertRaises(DiagnosticError) as physical_error:
            show_record(
                valid_encoded,
                ReadBudget(Bounds(record_bytes=len(valid_encoded) - 1)),
            )
        self.assertEqual(physical_error.exception.code, "E_LIMIT_EXCEEDED")

    def test_grok_ignored_raw_output_retains_structural_guards(self) -> None:
        def show_update(update: object) -> None:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                session_dir = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-shape"
                session_dir.mkdir(parents=True)
                updates = session_dir / "updates.jsonl"
                record = {
                    "timestamp": 1,
                    "method": "session/update",
                    "params": {"sessionId": "grok-shape", "update": update},
                }
                updates.write_text(json.dumps(record, separators=(",", ":")) + "\n")
                GrokAdapter(root=str(root)).show(
                    ResolvedRef(
                        session_id="grok-shape",
                        source_path=str(updates),
                        provider=GROK_FORMAT,
                    ),
                    query("grok", root, "grok-shape", within_min=0),
                    ReadBudget(),
                )

        nested: object = "leaf"
        for _ in range(34):
            nested = [nested]
        cases = {
            "depth": {
                "sessionUpdate": "tool_call_update",
                "content": "bounded",
                "rawOutput": nested,
            },
            "map-width": {
                "sessionUpdate": "tool_call_update",
                "content": "bounded",
                "rawOutput": {f"k{index}": index for index in range(513)},
            },
        }
        for name, update in cases.items():
            with self.subTest(name=name), self.assertRaises(DiagnosticError) as caught:
                show_update(update)
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

        duplicate = (
            b'{"timestamp":1,"method":"session/update","params":{"sessionId":"grok-shape",'
            b'"update":{"sessionUpdate":"tool_call_update","content":"one","content":"two"}}}'
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_dir = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-shape"
            session_dir.mkdir(parents=True)
            updates = session_dir / "updates.jsonl"
            updates.write_bytes(duplicate + b"\n")
            adapter = GrokAdapter(root=str(root))
            with self.assertRaises(DiagnosticError) as duplicate_error:
                adapter.show(
                    ResolvedRef("grok-shape", str(updates), GROK_FORMAT),
                    query("grok", root, "grok-shape", within_min=0),
                    ReadBudget(),
                )
            self.assertEqual(duplicate_error.exception.code, "E_CORRUPT_RECORD")

    def test_encoded_cwd_summary_and_public_updates_normalize(self) -> None:
        root = fixture_root("grok", "s-gro-01")
        before = tree_snapshot(root)
        adapter = GrokAdapter(root=str(root))
        current = query("grok", root, "grok-one")
        self.assertEqual(adapter.probe(current).format_id, GROK_FORMAT)
        values = adapter.list(current, ReadBudget())
        self.assertEqual(values[0].cwd, CWD)
        self.assertEqual(values[0].branch, "main")
        session = adapter.show(resolve(values, "grok-one"), current, ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["Grok prompt", "Grok answer"])
        self.assertEqual(tree_snapshot(root), before)

    def test_missing_summary_unknown_nonessential_partial_tail_and_filtered_content(self) -> None:
        cases = {
            "s-gro-02": "W_MISSING_BLOB",
            "s-gro-03": "W_BROKEN_CHAIN",
            "s-gro-05": "W_PARTIAL_TAIL",
        }
        for case, warning in cases.items():
            with self.subTest(case=case):
                root = fixture_root("grok", case)
                adapter = GrokAdapter(root=str(root))
                current = query("grok", root, "grok-one")
                values = adapter.list(current, ReadBudget())
                session = adapter.show(resolve(values, "grok-one"), current, ReadBudget())
                self.assertIn(warning, session.warnings)

        filtered_root = fixture_root("grok", "s-gro-04")
        filtered = GrokAdapter(root=str(filtered_root))
        current = query("grok", filtered_root, "grok-one")
        values = filtered.list(current, ReadBudget())
        session = filtered.show(resolve(values, "grok-one"), current, ReadBudget())
        text = " ".join(turn.content for turn in session.turns)
        self.assertNotIn("hidden", text)
        self.assertIn("Grok prompt", text)

    def test_interior_corruption_and_essential_timeline_event_fail_closed(self) -> None:
        # List is metadata-first (#15); show still fail-closed on corrupt/essential events.
        for payload in (
            '{"timestamp":\n',
            *(
                json.dumps(
                    {
                        "timestamp": 1,
                        "method": "_x.ai/session/update",
                        "params": {
                            "sessionId": "grok-one",
                            "update": {"sessionUpdate": kind, "target_prompt_index": 0},
                        },
                    }
                )
                + "\n"
                for kind in ("rewind_marker", "compaction_checkpoint")
            ),
        ):
            with self.subTest(payload=payload[:20]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(fixture_root("grok", "s-gro-01"), root, dirs_exist_ok=True)
                updates = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-one" / "updates.jsonl"
                updates.write_text(payload + updates.read_text())
                adapter = GrokAdapter(root=str(root))
                values = adapter.list(query("grok", root, "grok-one"), ReadBudget())
                self.assertEqual([item.session_id for item in values], ["grok-one"])
                with self.assertRaises(DiagnosticError) as caught:
                    adapter.show(resolve(values, "grok-one"), query("grok", root, "grok-one"), ReadBudget())
                self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"})

    def test_list_does_not_parse_updates_when_summary_is_complete(self) -> None:
        """Metadata-first list must not open updates.jsonl when summary.json is enough (#15)."""

        root = fixture_root("grok", "s-gro-01")
        adapter = GrokAdapter(root=str(root))
        with mock.patch.object(
            adapter,
            "_parse_updates",
            side_effect=AssertionError("list must not full-parse updates when summary exists"),
        ):
            values = adapter.list(query("grok", root, "grok-one"), ReadBudget())
        self.assertEqual([item.session_id for item in values], ["grok-one"])
        self.assertEqual(values[0].cwd, CWD)

    def test_hash_cwd_marker_is_stable_read_and_exact_path_selects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_dir = root / "sessions" / "project-0123456789abcdef" / "hash-one"
            session_dir.mkdir(parents=True)
            (session_dir.parent / ".cwd").write_text(CWD)
            updates = session_dir / "updates.jsonl"
            updates.write_text(
                json.dumps(
                    {
                        "timestamp": 1,
                        "method": "session/update",
                        "params": {
                            "sessionId": "hash-one",
                            "update": {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "hash cwd"}},
                        },
                    }
                )
                + "\n"
            )
            adapter = GrokAdapter(root=str(root))
            current = query("grok", root, str(updates))
            values = adapter.list(current, ReadBudget())
            self.assertEqual(values[0].cwd, CWD)
            selected = select_session(values, ref=str(updates), cwd=CWD, approved_roots=(str(root),))
            self.assertEqual(selected.selected.session_id, "hash-one")


class CommonAdapterContractTests(unittest.TestCase):
    def test_selection_latest_id_text_ambiguous_no_match_and_cwd_filter(self) -> None:
        root = fixture_root("opencode", "s-ope-02")
        adapter = OpenCodeAdapter(root=str(root))
        values = adapter.list(query("opencode", root, within_min=10 * 365 * 24 * 60), ReadBudget())
        self.assertEqual(select_session(values, ref="latest", cwd=CWD).selected.session_id, "ses-file")
        self.assertEqual(select_session(values, ref="ses-file", cwd=CWD).selected.session_id, "ses-file")
        self.assertEqual(select_session(values, ref="File synthetic", cwd=CWD).selected.session_id, "ses-file")
        with self.assertRaises(DiagnosticError) as no_match:
            select_session(values, ref="missing", cwd=CWD)
        self.assertEqual(no_match.exception.code, "E_NO_MATCH")
        self.assertEqual(adapter.list(Query(source="opencode", cwd="/different", source_root=str(root)), ReadBudget()), [])
        duplicate = [values[0], replace(values[0], session_id="ses-other")]
        with self.assertRaises(AmbiguousSelection):
            select_session(duplicate, ref="File synthetic", cwd=CWD)

    def test_injection_text_remains_inert_and_no_source_process_api_is_used(self) -> None:
        roots_and_adapters = [
            ("opencode", fixture_root("opencode", "s-ope-01"), OpenCodeAdapter, "ses-sql"),
            ("antigravity", fixture_root("antigravity", "s-ant-01"), AntigravityAdapter, "conv-one"),
            ("grok", fixture_root("grok", "s-gro-06"), GrokAdapter, "grok-one"),
        ]
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("source process")), mock.patch.object(
            subprocess, "run", side_effect=AssertionError("source process")
        ), mock.patch.object(subprocess, "check_output", side_effect=AssertionError("source process")), mock.patch.object(
            os, "system", side_effect=AssertionError("source shell")
        ):
            for source, root, adapter_type, session_id in roots_and_adapters:
                with self.subTest(source=source):
                    adapter = adapter_type(root=str(root))
                    current = query(source, root, session_id)
                    values = adapter.list(current, ReadBudget())
                    session = adapter.show(resolve(values, session_id), current, ReadBudget())
                    self.assertTrue(session.inert)
                    self.assertTrue(session.untrusted_content)
                    self.assertTrue(all(turn.inert and turn.untrusted_content for turn in session.turns))

    def test_source_symlink_escape_is_never_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            brain = root / "brain" / "escape" / ".system_generated" / "logs"
            brain.mkdir(parents=True)
            target = Path(outside) / "transcript.jsonl"
            target.write_text('{"type":"session","conversation_id":"escape","cwd":"/workspace/project"}\n')
            os.symlink(target, brain / "transcript.jsonl")
            adapter = AntigravityAdapter(root=str(root))
            with self.assertRaises(DiagnosticError) as caught:
                adapter.list(query("antigravity", root, str(brain / "transcript.jsonl")), ReadBudget())
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")


if __name__ == "__main__":
    unittest.main()
