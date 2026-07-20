"""Claude parent-chain bridge through non-conversation nodes."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from portable_resume.adapters.claude import ClaudeAdapter, _logical_lineage
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import ReadBudget
from portable_resume.model import Query


class ClaudeBridgeTests(unittest.TestCase):
    def test_lineage_hops_attachment_parent(self) -> None:
        u1, a1, s1 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        records = [
            {
                "type": "user",
                "uuid": u1,
                "parentUuid": None,
                "timestamp": "2026-07-20T00:00:00.000Z",
                "message": {"role": "user", "content": "hello"},
            },
            {"type": "attachment", "uuid": a1, "parentUuid": u1},
            {
                "type": "assistant",
                "uuid": s1,
                "parentUuid": a1,
                "timestamp": "2026-07-20T00:00:01.000Z",
                "message": {"role": "assistant", "content": "world"},
            },
        ]
        lineage, warnings = _logical_lineage(records)
        self.assertEqual([item["uuid"] for item in lineage], [u1, s1])
        self.assertNotIn("W_BROKEN_CHAIN", warnings)

    def test_true_break_still_warns(self) -> None:
        u1, s1 = str(uuid.uuid4()), str(uuid.uuid4())
        missing = str(uuid.uuid4())
        records = [
            {
                "type": "user",
                "uuid": u1,
                "parentUuid": None,
                "timestamp": "2026-07-20T00:00:00.000Z",
                "message": {"role": "user", "content": "root"},
            },
            {
                "type": "assistant",
                "uuid": s1,
                "parentUuid": missing,
                "timestamp": "2026-07-20T00:00:01.000Z",
                "message": {"role": "assistant", "content": "orphan-tail"},
            },
        ]
        lineage, warnings = _logical_lineage(records)
        self.assertEqual([item["uuid"] for item in lineage], [s1])
        self.assertIn("W_BROKEN_CHAIN", warnings)

    def test_show_through_attachment_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cwd = root / "proj"
            cwd.mkdir()
            session_id = str(uuid.uuid4())
            from portable_resume.adapters.claude import _slugify_cwd

            slug = _slugify_cwd(str(cwd))
            path = root / "projects" / slug / f"{session_id}.jsonl"
            path.parent.mkdir(parents=True)
            u1, a1, s1 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            rows = [
                {
                    "type": "user",
                    "uuid": u1,
                    "parentUuid": None,
                    "sessionId": session_id,
                    "cwd": str(cwd),
                    "timestamp": "2026-07-20T00:00:00.000Z",
                    "message": {"role": "user", "content": "bridge me"},
                },
                {"type": "attachment", "uuid": a1, "parentUuid": u1, "sessionId": session_id},
                {
                    "type": "assistant",
                    "uuid": s1,
                    "parentUuid": a1,
                    "sessionId": session_id,
                    "cwd": str(cwd),
                    "timestamp": "2026-07-20T00:00:01.000Z",
                    "message": {"role": "assistant", "content": "bridged"},
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            query = Query("claude", cwd=str(cwd), source_root=str(root))
            session = ClaudeAdapter().show(
                ResolvedRef(session_id=session_id, source_path=str(path), provider="claude-jsonl-v1"),
                query,
                ReadBudget(),
            )
            roles = [turn.role for turn in session.turns]
            self.assertEqual(roles, ["user", "assistant"])
            self.assertNotIn("W_BROKEN_CHAIN", session.warnings)
            self.assertIn("bridge me", session.last_user_request or "")


if __name__ == "__main__":
    unittest.main()
