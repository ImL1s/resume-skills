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
from portable_resume.reader import main as reader_main
from tests.helpers.core import tree_snapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CWD = "/workspace/project"


def fixture_root(case: str) -> Path:
    return (FIXTURES / "grok" / case / "root").resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(source="grok", ref=ref, cwd=CWD, source_root=str(root), **kwargs)


def resolve(items, session_id: str):
    return ResolvedRef.from_summary(next(item for item in items if item.session_id == session_id))


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

    def test_show_latest_via_reader_cli(self) -> None:
        root = fixture_root("s-gro-07")
        code = reader_main(
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
            ]
        )
        self.assertEqual(code, 0)

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
                / "cp-001.json"
            )
            sidecar.unlink()
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT", "E_UNSAFE_PATH"})

    def test_path_escape_checkpoint_file_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(fixture_root("s-gro-07"), root, dirs_exist_ok=True)
            updates = root / "sessions" / "%2Fworkspace%2Fproject" / "grok-compact" / "updates.jsonl"
            lines = updates.read_text(encoding="utf-8").splitlines()
            out = []
            for line in lines:
                obj = json.loads(line)
                update = obj["params"]["update"]
                if update.get("sessionUpdate") == "compaction_checkpoint":
                    update["checkpoint_file"] = "../summary.json"
                out.append(json.dumps(obj, separators=(",", ":")))
            updates.write_text("\n".join(out) + "\n", encoding="utf-8")
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolve(items, "grok-compact"), query(root, "grok-compact"), ReadBudget())
            self.assertIn(caught.exception.code, {"E_UNSAFE_PATH", "E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"})

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
                / "cp-001.json"
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
                / "cp-001.json"
            )
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["checkpoint_id"] = "other-id"
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
                / "cp-001.json"
            )
            sidecar.unlink()
            adapter = GrokAdapter(root=str(root))
            items = adapter.list(query(root), ReadBudget())
            self.assertEqual([item.session_id for item in items], ["grok-compact"])


if __name__ == "__main__":
    unittest.main()
