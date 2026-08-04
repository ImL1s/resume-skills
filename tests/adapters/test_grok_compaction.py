"""Grok compaction_checkpoint reducer (#238)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.grok import FORMAT_ID, GrokAdapter
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from portable_resume.reader import run as reader_run
from tests.helpers.core import tree_snapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CWD = "/workspace/project"


def fixture_root(case: str) -> Path:
    return (FIXTURES / "grok" / case / "root").resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(source="grok", ref=ref, cwd=CWD, source_root=str(root), **kwargs)


def resolve(items, session_id: str):
    return ResolvedRef.from_summary(next(item for item in items if item.session_id == session_id))


def mutate_checkpoint_event(root: Path, mutation) -> None:
    updates = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-compact" / "updates.jsonl"
    lines = []
    for line in updates.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        update = obj["params"]["update"]
        if update.get("sessionUpdate") == "compaction_checkpoint":
            mutation(update)
        lines.append(json.dumps(obj, separators=(",", ":")))
    updates.write_text("\n".join(lines) + "\n", encoding="utf-8")


class GrokCompactionTests(unittest.TestCase):
    def test_show_success_projects_compacted_and_post_public_once(self) -> None:
        root = fixture_root("s-gro-07")
        before = tree_snapshot(root)
        adapter = GrokAdapter(root=str(root))
        items = adapter.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in items], ["grok-compact"])
        session = adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
        texts = [(turn.role, turn.content) for turn in session.turns if turn.tool_name is None]
        # Consecutive same-role public entries coalesce (same as live chunk stream).
        self.assertEqual(
            texts,
            [
                ("user", "Compacted public user"),
                ("assistant", "Compacted public assistantCompacted structured assistant"),
                ("user", "Post-compact user"),
                ("assistant", "Post-compact assistant"),
            ],
        )
        joined = "\n".join(t for _, t in texts)
        self.assertNotIn("PRIVATE", joined)
        self.assertNotIn("Pre-compact user (raw stream)", joined)
        self.assertNotIn("Pre-compact assistant (raw stream)", joined)
        self.assertEqual(tree_snapshot(root), before)

    def test_legacy_basename_checkpoint_file_still_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            mutate_checkpoint_event(
                root,
                lambda update: update.__setitem__(
                    "checkpoint_file", "11111111-1111-4111-8111-111111111111.json"
                ),
            )
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            session = adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertEqual(session.turns[0].content, "Compacted public user")

    def test_show_latest_via_reader_cli(self) -> None:
        import io

        root = fixture_root("s-gro-07")
        buf = io.StringIO()
        err = io.StringIO()
        code = reader_run(
            [
                "grok",
                "show",
                "latest",
                "--cwd",
                CWD,
                "--source-root",
                str(root),
                "--format",
                "json",
            ],
            stdout=buf,
            stderr=err,
        )
        self.assertEqual(code, 0, msg=err.getvalue())
        payload = json.loads(buf.getvalue())
        sessions = payload.get("sessions") or []
        self.assertEqual(len(sessions), 1)
        turns = sessions[0].get("turns") or []
        contents = [turn.get("content") for turn in turns]
        self.assertIn("Compacted public user", contents)
        self.assertTrue(any(isinstance(c, str) and "Post-compact assistant" in c for c in contents))
        joined = "\n".join(c for c in contents if isinstance(c, str))
        self.assertNotIn("PRIVATE", joined)
        self.assertNotIn("Pre-compact user (raw stream)", joined)

    def test_multi_checkpoint_final_projection_without_duplicates(self) -> None:
        root = fixture_root("s-gro-08")
        adapter = GrokAdapter(root=str(root))
        items = adapter.list(query(root), ReadBudget())
        session = adapter.show(resolve(items, "grok-multi"), query(root, "grok-multi"), ReadBudget())
        texts = [turn.content for turn in session.turns if turn.tool_name is None]
        self.assertEqual(texts, ["C2 user", "C2 asst", "U2 after second", "A2 after second"])
        self.assertNotIn("U0", texts)
        self.assertNotIn("C1 user", texts)
        self.assertNotIn("U1 mid", texts)

    def test_rewind_marker_still_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-01"), root, dirs_exist_ok=True)
            updates = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-one" / "updates.jsonl"
            payload = (
                json.dumps(
                    {
                        "timestamp": 1,
                        "method": "session/update",
                        "params": {
                            "sessionId": "grok-one",
                            "update": {"sessionUpdate": "rewind_marker", "target_prompt_index": 0},
                        },
                    }
                )
                + "\n"
            )
            updates.write_text(payload + updates.read_text(encoding="utf-8"), encoding="utf-8")
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root, "grok-one"), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-one"), query(root, "grok-one"), ReadBudget())
            self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_missing_sidecar_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            sidecar = (
                root
                / "sessions"
                / "%2Fworkspace%2Fproject"
                / "grok-compact"
                / "compaction_checkpoints"
                / "11111111-1111-4111-8111-111111111111.json"
            )
            sidecar.unlink()
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT", "E_UNSAFE_PATH"})

    def test_adversarial_checkpoint_paths_fail_closed(self) -> None:
        hostile_paths = (
            "/tmp/11111111-1111-4111-8111-111111111111.json",
            "compaction_checkpoints\\11111111-1111-4111-8111-111111111111.json",
            "../summary.json",
            "./11111111-1111-4111-8111-111111111111.json",
            "compaction_checkpoints/../summary.json",
            "compaction_checkpoints/./11111111-1111-4111-8111-111111111111.json",
            "compaction_checkpoints/nested/11111111-1111-4111-8111-111111111111.json",
            "other/11111111-1111-4111-8111-111111111111.json",
        )
        for checkpoint_file in hostile_paths:
            with self.subTest(checkpoint_file=checkpoint_file), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
                mutate_checkpoint_event(
                    root,
                    lambda update, value=checkpoint_file: update.__setitem__("checkpoint_file", value),
                )
                adapter = GrokAdapter(root=str(root))
                items = adapter.list(query(root), ReadBudget())
                with self.assertRaises(DiagnosticError) as caught:
                    adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
                self.assertIn(caught.exception.code, {"E_UNSAFE_PATH", "E_CORRUPT_RECORD"})

    def test_unknown_checkpoint_event_key_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            mutate_checkpoint_event(root, lambda update: update.__setitem__("unknown_control", True))
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_checkpoint_created_at_requires_qualified_timestamp(self) -> None:
        for created_at in (None, 1767225611, True, "not-a-timestamp", "2026-01-01T00:00:00"):
            with self.subTest(created_at=created_at), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
                mutate_checkpoint_event(
                    root,
                    lambda update, value=created_at: update.__setitem__("created_at", value),
                )
                adapter = GrokAdapter(root=str(root))
                items = adapter.list(query(root), ReadBudget())
                with self.assertRaises(DiagnosticError) as caught:
                    adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
                self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_symlinked_checkpoint_file_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            sidecar = (
                root
                / "sessions"
                / "%2Fworkspace%2Fproject"
                / "grok-compact"
                / "compaction_checkpoints"
                / "11111111-1111-4111-8111-111111111111.json"
            )
            target = sidecar.with_name("target.json")
            sidecar.rename(target)
            try:
                sidecar.symlink_to(target.name)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks unavailable")
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertIn(caught.exception.code, {"E_UNSAFE_PATH", "E_CORRUPT_RECORD"})

    def test_schema_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            sidecar = (
                root
                / "sessions"
                / "%2Fworkspace%2Fproject"
                / "grok-compact"
                / "compaction_checkpoints"
                / "11111111-1111-4111-8111-111111111111.json"
            )
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["schema_version"] = 99
            sidecar.write_text(json.dumps(data), encoding="utf-8")
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertIn(caught.exception.code, {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD"})

    def test_checkpoint_id_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            sidecar = (
                root
                / "sessions"
                / "%2Fworkspace%2Fproject"
                / "grok-compact"
                / "compaction_checkpoints"
                / "11111111-1111-4111-8111-111111111111.json"
            )
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["checkpoint_id"] = "other-id"
            sidecar.write_text(json.dumps(data), encoding="utf-8")
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_checkpoint_prompt_index_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            sidecar = (
                root
                / "sessions"
                / "%2Fworkspace%2Fproject"
                / "grok-compact"
                / "compaction_checkpoints"
                / "11111111-1111-4111-8111-111111111111.json"
            )
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["prompt_index_at_compaction"] += 1
            sidecar.write_text(json.dumps(data), encoding="utf-8")
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_list_does_not_require_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            # Break summary so list may fall through to updates scan for timestamps
            summary = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-compact" / "summary.json"
            summary.unlink()
            sidecar = (
                root
                / "sessions"
                / "%2Fworkspace%2Fproject"
                / "grok-compact"
                / "compaction_checkpoints"
                / "11111111-1111-4111-8111-111111111111.json"
            )
            sidecar.unlink()
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            self.assertEqual([item.session_id for item in items], ["grok-compact"])

    def test_encrypted_checkpoint_control_fail_closed(self) -> None:
        """Checkpoint controls with encrypted-looking keys must not soft-skip (#238 P1)."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            updates = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-compact" / "updates.jsonl"
            lines = []
            for line in updates.read_text(encoding="utf-8").splitlines():
                obj = json.loads(line)
                update = obj["params"]["update"]
                if update.get("sessionUpdate") == "compaction_checkpoint":
                    update["signature"] = "synthetic-not-a-secret"
                lines.append(json.dumps(obj, separators=(",", ":")))
            updates.write_text("\n".join(lines) + "\n", encoding="utf-8")
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_checkpoint_resets_turn_budget_charges(self) -> None:
        """Surviving projection is bounded; superseded pre-checkpoint turns are not double-counted."""
        from portable_resume.bounds import Bounds

        root = fixture_root("s-gro-07")
        adapter = GrokAdapter(root=str(root))
        items = adapter.list(query(root), ReadBudget())
        # Ceiling tight enough that double-counting pre+post would fail, but true
        # final projection (4 public turns after coalesce) still fits.
        tight = ReadBudget(limits=Bounds(normalized_turns=4))
        session = adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), tight)
        self.assertEqual(len([t for t in session.turns if t.tool_name is None]), 4)
        self.assertEqual(tight.turns, 4)

    def test_precharged_budget_accumulates_surviving_turns(self) -> None:
        """Reused budgets keep prior charges and add surviving projection (Codex P2)."""
        from portable_resume.bounds import Bounds

        root = fixture_root("s-gro-07")
        adapter = GrokAdapter(root=str(root))
        items = adapter.list(query(root), ReadBudget())
        # Prior 3 + surviving 4 would be 7; ceiling 4 must fail closed.
        precharged = ReadBudget(limits=Bounds(normalized_turns=4))
        precharged.consume_turns(3)
        with self.assertRaises(DiagnosticError) as caught:
            adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), precharged)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
        # Room for surviving 4 after prior 0: still succeeds.
        fresh = ReadBudget(limits=Bounds(normalized_turns=4))
        session = adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), fresh)
        self.assertEqual(len([t for t in session.turns if t.tool_name is None]), 4)
        self.assertEqual(fresh.turns, 4)

    def test_pre_checkpoint_stream_over_limit_still_projects(self) -> None:
        """Long pre-checkpoint stream must not starve a smaller post-compaction projection."""
        from portable_resume.bounds import Bounds

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sess = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-long"
            ck = sess / "compaction_checkpoints"
            ck.mkdir(parents=True)
            (sess / "summary.json").write_text(
                json.dumps({"info": {"id": "grok-long", "cwd": "/workspace/project"}, "generated_title": "long"}),
                encoding="utf-8",
            )
            sid = "grok-long"
            lines = []
            for i in range(6):
                role = "user_message_chunk" if i % 2 == 0 else "agent_message_chunk"
                text = f"pre-{i}"
                lines.append(
                    json.dumps(
                        {
                            "timestamp": i + 1,
                            "method": "session/update",
                            "params": {
                                "sessionId": sid,
                                "update": {
                                    "sessionUpdate": role,
                                    "content": {"type": "text", "text": text},
                                },
                            },
                        },
                        separators=(",", ":"),
                    )
                )
            lines.append(
                json.dumps(
                    {
                        "timestamp": 10,
                        "method": "session/update",
                        "params": {
                            "sessionId": sid,
                            "update": {
                                "sessionUpdate": "compaction_checkpoint",
                                "checkpoint_id": "cp-long",
                                "schema_version": 1,
                                "prompt_index_at_compaction": 3,
                                "checkpoint_file": "cp-long.json",
                                "created_at": "2026-01-01T00:00:10Z",
                            },
                        },
                    },
                    separators=(",", ":"),
                )
            )
            lines.append(
                json.dumps(
                    {
                        "timestamp": 11,
                        "method": "session/update",
                        "params": {
                            "sessionId": sid,
                            "update": {
                                "sessionUpdate": "user_message_chunk",
                                "content": {"type": "text", "text": "after"},
                            },
                        },
                    },
                    separators=(",", ":"),
                )
            )
            (sess / "updates.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            (ck / "cp-long.json").write_text(
                json.dumps(
                    {
                        "checkpoint_id": "cp-long",
                        "schema_version": 1,
                        "prompt_index_at_compaction": 3,
                        "created_at": 10,
                        "compacted_history": [
                            {"role": "user", "content": "kept-user"},
                            {"role": "assistant", "content": "kept-asst"},
                        ],
                        "original_user_info": {},
                        "reread_file_paths": [],
                    }
                ),
                encoding="utf-8",
            )
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            # 6 pre chunks would exceed limit=3 if charged mid-stream; final projection is 3 turns.
            tight = ReadBudget(limits=Bounds(normalized_turns=3))
            session = adapter.show(resolve(items, "grok-long"), query(root, "grok-long"), tight)
            texts = [turn.content for turn in session.turns if turn.tool_name is None]
            self.assertEqual(texts, ["kept-user", "kept-asst", "after"])


if __name__ == "__main__":
    unittest.main()
