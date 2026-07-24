"""Regression tests for bounded, newest-honest live-store discovery."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from portable_resume.adapters import antigravity, codex, cursor as _cursor, grok
from portable_resume.adapters import cursor_live
from portable_resume.bounds import DEFAULT_BOUNDS
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query


class BoundedDiscoveryTests(unittest.TestCase):
    def test_cursor_scandir_is_bounded_before_sorting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("z", "a", "m"):
                (directory / name).touch()
            with mock.patch.object(cursor_live, "DEFAULT_BOUNDS", replace(DEFAULT_BOUNDS, scanned_records=2)):
                with self.assertRaises(DiagnosticError) as caught:
                    cursor_live._bounded_names(str(directory), [0])
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_cursor_metadata_reads_have_an_aggregate_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cwd = "/workspace/project"
            session = root / "chats" / cursor_live._cwd_hash(cwd) / str(uuid.uuid4())
            session.mkdir(parents=True)
            (session / "store.db").touch()
            (session / "meta.json").write_text(
                json.dumps({"cwd": cwd, "title": "larger than one byte"}),
                encoding="utf-8",
            )
            limits = replace(DEFAULT_BOUNDS, source_read_bytes=1)
            with mock.patch.object(cursor_live, "DEFAULT_BOUNDS", limits):
                with self.assertRaises(DiagnosticError) as caught:
                    cursor_live._list_live_cli_stores(
                        str(root),
                        Query(source="cursor", cwd=cwd, source_root=str(root), within_min=0),
                    )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_grok_refuses_a_partial_directory_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / "sessions"
            for name in ("z", "a", "m"):
                (sessions / name).mkdir(parents=True)
            adapter = grok.GrokAdapter(root=str(root))
            with mock.patch.object(grok, "DEFAULT_BOUNDS", replace(DEFAULT_BOUNDS, scanned_records=2)):
                with self.assertRaises(DiagnosticError) as caught:
                    adapter._session_paths(str(root))
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_grok_exact_cwd_avoids_unrelated_bucket_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cwd = "/workspace/project"
            bucket = root / "sessions" / quote(cwd, safe="")
            updates = bucket / "session-one" / "updates.jsonl"
            updates.parent.mkdir(parents=True)
            updates.touch()
            for index in range(5):
                (root / "sessions" / f"unrelated-{index}").mkdir()
            adapter = grok.GrokAdapter(root=str(root))
            with mock.patch.object(grok, "DEFAULT_BOUNDS", replace(DEFAULT_BOUNDS, scanned_records=1)):
                self.assertEqual(adapter._session_paths(str(root), prefer_cwd=cwd), [(str(bucket), str(updates))])

    def test_antigravity_refuses_lexical_truncation_before_mtime_rank(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            brain = root / "brain"
            for name in ("z", "a", "m"):
                (brain / name).mkdir(parents=True)
            adapter = antigravity.AntigravityAdapter(root=str(root))
            with mock.patch.object(
                antigravity,
                "DEFAULT_BOUNDS",
                replace(DEFAULT_BOUNDS, scanned_records=2),
            ):
                with self.assertRaises(DiagnosticError) as caught:
                    adapter._scan_brain_transcripts(str(brain), str(root))
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_codex_walk_has_one_aggregate_tree_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / "sessions"
            sessions.mkdir()
            for index in range(3):
                identifier = uuid.uuid4()
                (sessions / f"rollout-2026-01-01T00-00-0{index}-{identifier}.jsonl").touch()
            with mock.patch.object(codex, "DEFAULT_BOUNDS", replace(DEFAULT_BOUNDS, scanned_records=2)):
                with self.assertRaises(DiagnosticError) as caught:
                    codex._walk_rollouts(str(sessions), str(root))
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_discovery_paths_do_not_use_unbounded_listdir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "brain").mkdir()
            with mock.patch.object(os, "listdir", side_effect=AssertionError("unbounded listdir")):
                self.assertEqual(
                    antigravity.AntigravityAdapter(root=str(root))._scan_brain_transcripts(
                        str(root / "brain"),
                        str(root),
                    ),
                    [],
                )
                self.assertEqual(codex._walk_rollouts(str(root / "missing"), str(root)), [])


if __name__ == "__main__":
    unittest.main()
