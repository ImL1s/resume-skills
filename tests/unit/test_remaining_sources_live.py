"""Regression tests for remaining-source live discovery fixes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import quote

from portable_resume.adapters.antigravity import AntigravityAdapter
from portable_resume.adapters.grok import GrokAdapter
from portable_resume.bounds import ReadBudget
from portable_resume.model import Query


class GrokPathSkipTests(unittest.TestCase):
    def test_prompt_history_and_search_db_do_not_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / "sessions"
            sessions.mkdir()
            (sessions / "session_search.sqlite").write_bytes(b"not-a-real-db")
            cwd = "/var/app/project"
            bucket = sessions / quote(cwd, safe="")
            bucket.mkdir()
            (bucket / "prompt_history.jsonl").write_text("{}\n", encoding="utf-8")
            sid = str(uuid.uuid4())
            session_dir = bucket / sid
            session_dir.mkdir()
            updates = session_dir / "updates.jsonl"
            # Minimal valid-enough updates for parse; if parse fails still paths found.
            updates.write_text(
                json.dumps(
                    {
                        "type": "session",
                        "session_id": sid,
                        "cwd": cwd,
                        "updated_at": "2026-07-20T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            adapter = GrokAdapter(root=str(root))
            paths = adapter._session_paths(str(root))
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0][1].endswith("updates.jsonl"))


class AntigravityNoIndexScanTests(unittest.TestCase):
    def test_scan_lists_transcript_without_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            brain = root / "brain"
            sid = "conv-no-index-1"
            path = brain / sid / ".system_generated" / "logs" / "transcript.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "type": "session",
                        "conversation_id": sid,
                        "cwd": "/var/app/project",
                        "created_at": "2026-07-20T00:00:00Z",
                        "updated_at": "2026-07-20T00:00:00Z",
                        "title": "no-index",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "message",
                        "role": "user",
                        "content": "hello",
                        "timestamp": "2026-07-20T00:00:01Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            adapter = AntigravityAdapter(root=str(root))
            found = adapter._scan_brain_transcripts(str(brain), str(root))
            self.assertEqual(found, [str(path)])
            values = adapter.list(
                Query("antigravity", cwd="/var/app/project", within_min=0, source_root=str(root)),
                ReadBudget(),
            )
            self.assertEqual(len(values), 1)
            self.assertEqual(values[0].session_id, sid)


if __name__ == "__main__":
    unittest.main()
