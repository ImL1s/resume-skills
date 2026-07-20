"""Codex live-parity: skip unknown outer types, compact, tools."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from portable_resume.adapters.codex import CodexAdapter, _normalized_turns, _parse_lines
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import ReadBudget
from portable_resume.model import Query


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class CodexParityTests(unittest.TestCase):
    def test_parse_skips_world_state(self) -> None:
        session_id = str(uuid.uuid4())
        lines = [
            {"type": "session_meta", "payload": {"id": session_id, "cwd": "/tmp/x", "source": "cli"}, "timestamp": _ts()},
            {"type": "world_state", "payload": {"ignored": True}},
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
                "timestamp": _ts(),
            },
        ]
        raw = ("\n".join(json.dumps(item) for item in lines) + "\n").encode()
        records, warnings = _parse_lines(raw, ReadBudget(), "codex-rollout-jsonl-v1")
        self.assertEqual(len(records), 2)
        self.assertIn("W_UNKNOWN_RECORD_SKIPPED", warnings)

    def test_compact_replacement_history(self) -> None:
        records = [
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "old"}]},
            },
            {
                "type": "compacted",
                "payload": {
                    "replacement_history": [
                        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "kept"}]},
                    ]
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "new"}]},
            },
        ]
        turns, _ = _normalized_turns(records)
        texts = [turn["content"] for turn in turns]
        self.assertEqual(texts, ["kept", "new"])

    def test_function_call_inert(self) -> None:
        records = [
            {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "shell", "arguments": "{\"cmd\":\"ls\"}"},
            }
        ]
        turns, _ = _normalized_turns(records)
        self.assertEqual(len(turns), 1)
        self.assertIn("shell", turns[0]["content"])

    def test_show_with_world_state_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = str(uuid.uuid4())
            path = root / "sessions" / f"rollout-2026-07-20T00-00-00-{session_id}.jsonl"
            path.parent.mkdir(parents=True)
            cwd = "/workspace/project"
            rows = [
                {
                    "type": "session_meta",
                    "payload": {"id": session_id, "cwd": cwd, "source": "cli"},
                    "timestamp": "2026-07-20T00:00:00Z",
                },
                {"type": "world_state", "payload": {"x": 1}},
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "codex live"}],
                    },
                    "timestamp": "2026-07-20T00:00:01Z",
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            session = CodexAdapter().show(
                ResolvedRef(session_id=session_id, source_path=str(path), provider="codex-rollout-jsonl-v1"),
                Query("codex", cwd=cwd, source_root=str(root)),
                ReadBudget(),
            )
            self.assertEqual(session.session_id, session_id)
            self.assertIn("codex live", session.last_user_request or "")


if __name__ == "__main__":
    unittest.main()
