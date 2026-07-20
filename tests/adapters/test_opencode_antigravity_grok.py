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
from portable_resume.bounds import DEFAULT_BOUNDS, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
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


class FixtureManifestTests(unittest.TestCase):
    def test_all_lane_fixture_manifests_are_strict_and_complete(self) -> None:
        expected = {
            "opencode": {f"s-ope-{index:02d}" for index in range(1, 8)},
            "antigravity": {f"s-ant-{index:02d}" for index in range(1, 7)},
            "grok": {f"s-gro-{index:02d}" for index in range(1, 7)},
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

    def test_membership_race_exhausts_snapshot_without_source_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(fixture_root("opencode", "s-ope-01") / "opencode.db", root / "opencode.db")

            def race(phase: str, attempt: int, _path: str) -> None:
                if phase == "after-copy":
                    (root / f"race-{attempt}").write_text("membership changed")

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


class GrokAdapterTests(unittest.TestCase):
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
        for payload in (
            '{"timestamp":\n',
            json.dumps(
                {
                    "timestamp": 1,
                    "method": "_x.ai/session/update",
                    "params": {
                        "sessionId": "grok-one",
                        "update": {"sessionUpdate": "rewind_marker", "target_prompt_index": 0},
                    },
                }
            )
            + "\n",
        ):
            with self.subTest(payload=payload[:20]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(fixture_root("grok", "s-gro-01"), root, dirs_exist_ok=True)
                updates = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-one" / "updates.jsonl"
                updates.write_text(payload + updates.read_text())
                adapter = GrokAdapter(root=str(root))
                with self.assertRaises(DiagnosticError) as caught:
                    adapter.list(query("grok", root, "grok-one"), ReadBudget())
                self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"})

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
