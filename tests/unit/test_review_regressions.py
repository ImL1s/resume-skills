"""Regression tests from post-push code review (improve-deep follow-up)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from portable_resume.adapters import cursor as cursor_mod
from portable_resume.adapters.cursor import CursorAdapter
from portable_resume.adapters.grok import GrokAdapter
from portable_resume.bounds import DEFAULT_BOUNDS, ReadBudget
from portable_resume.install.manifest import FileEntry, sha256_bytes, sha256_file, validate_rel_path
from portable_resume.install.transaction import execute_install, load_manifest, manifest_path, plan_install
from portable_resume.model import Query, SessionSummary
from portable_resume.select import select_session
from portable_resume.sanitize import sanitize_text


class ReviewRegressionTests(unittest.TestCase):
    def test_select_session_uppercase_uuid(self) -> None:
        sid = str(uuid.uuid4())
        summary = SessionSummary(
            source="codex",
            session_id=sid,
            source_path="/tmp/x",
            cwd="/workspace/project",
            updated_at="2026-07-20T00:00:00.000000Z",
        )
        result = select_session([summary], ref=sid.upper(), cwd="/workspace/project")
        self.assertIsNotNone(result.selected)
        assert result.selected is not None
        self.assertEqual(result.selected.session_id, sid)

    def test_sha256_file_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "real.txt"
            target.write_bytes(b"payload")
            link = Path(tmp) / "link.txt"
            os.symlink(target, link)
            with self.assertRaises(OSError):
                sha256_file(str(link))

    def test_validate_rel_path_rejects_escape(self) -> None:
        with self.assertRaises(ValueError):
            validate_rel_path("../escape")
        with self.assertRaises(ValueError):
            validate_rel_path("/abs")

    def test_grok_coalesce_caps_total_content(self) -> None:
        turns: list = []
        warnings: list[str] = []
        budget = ReadBudget()
        query = Query(source="grok", cwd="/workspace/project", within_min=0)
        # Two half-limit chunks must coalesce to at most one limit-sized turn.
        half = DEFAULT_BOUNDS.normalized_content_bytes // 2 + 10
        chunk = "x" * half
        for _ in range(3):
            GrokAdapter._append_chunk(turns, "user", chunk, None, query, budget, warnings)
        self.assertEqual(len(turns), 1)
        self.assertLessEqual(len(turns[0].content), DEFAULT_BOUNDS.normalized_content_bytes)
        self.assertTrue(turns[0].truncated)

    def test_aiza_shape_redacted(self) -> None:
        token = "AIza" + ("B" * 24)
        result = sanitize_text("key " + token, max_chars=200)
        self.assertNotIn(token, result.text)
        self.assertIn("W_METADATA_REDACTED", result.warnings)

    def test_cursor_live_list_ranks_newest_not_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".cursor"
            root.mkdir()
            cwd = "/workspace/project"
            h = cursor_mod._cwd_hash(cwd)
            bucket = root / "chats" / h
            bucket.mkdir(parents=True)
            # Create 55 sessions; alphabetically first ids are older.
            ids: list[str] = []
            base = int(time.time())
            for i in range(55):
                sid = str(uuid.UUID(int=i + 1))
                ids.append(sid)
                session_dir = bucket / sid
                session_dir.mkdir()
                store = session_dir / "store.db"
                conn = sqlite3.connect(store)
                conn.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
                conn.commit()
                conn.close()
                # Older first UUIDs, newest last UUID by mtime via meta updatedAtMs
                meta = {
                    "cwd": cwd,
                    "title": f"s{i}",
                    "createdAtMs": (base - 55 + i) * 1000,
                    "updatedAtMs": (base - 55 + i) * 1000,
                }
                (session_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            newest = ids[-1]
            adapter = CursorAdapter()
            query = Query(source="cursor", cwd=cwd, source_root=str(root), within_min=0)
            summaries = adapter.list(query, ReadBudget())
            self.assertGreaterEqual(len(summaries), 50)
            # Latest by updated_at must be the newest session, not name-order first.
            ordered = sorted(
                summaries,
                key=lambda s: (s.updated_at is None, s.updated_at or "", s.session_id),
                reverse=True,
            )
            self.assertEqual(ordered[0].session_id, newest)
            from portable_resume.select import select_session

            selected = select_session(summaries, ref="latest", cwd=cwd)
            self.assertIsNotNone(selected.selected)
            assert selected.selected is not None
            self.assertEqual(selected.selected.session_id, newest)

    def test_dest_under_root_rejects_escape(self) -> None:
        from portable_resume.diagnostics import DiagnosticError
        from portable_resume.install.transaction import _dest_under_root

        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp) / "skills")
            Path(root).mkdir()
            with self.assertRaises(DiagnosticError):
                _dest_under_root(root, "../../escape")

    def test_install_upgrade_removes_owned_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp) / "skills")
            execute_install(plan_install(host="claude", scope="project", root=root))
            orphan = Path(root) / "resume-claude" / "ORPHAN_MARKER.txt"
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan.write_bytes(b"stale")
            man = load_manifest(root)
            assert man is not None
            claim = next(iter(man.claims))
            man.files["resume-claude/ORPHAN_MARKER.txt"] = FileEntry(
                path="resume-claude/ORPHAN_MARKER.txt",
                sha256=sha256_bytes(b"stale"),
                claims=[claim],
                mode=0o644,
            )
            Path(manifest_path(root)).write_text(man.dumps(), encoding="utf-8")
            result = execute_install(plan_install(host="claude", scope="project", root=root))
            self.assertTrue(result.get("ok"))
            self.assertFalse(orphan.exists())


if __name__ == "__main__":
    unittest.main()
