"""Synthetic live Cursor store.db / meta fixtures."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from portable_resume.adapters.cursor import LIVE_CLI_FORMAT, CursorAdapter
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from portable_resume.adapters.base import ResolvedRef


class CursorLiveStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ".cursor"
        self.root.mkdir()
        self.cwd = "/workspace/project"
        # cwd hash used by live list
        import hashlib

        h = hashlib.md5(self.cwd.encode("utf-8")).hexdigest()  # noqa: S324 — match product hash if different
        # Use adapter's hash if available
        from portable_resume.adapters import cursor as cursor_mod

        h = cursor_mod._cwd_hash(self.cwd)
        sid = str(uuid.uuid4())
        session_dir = self.root / "chats" / h / sid
        session_dir.mkdir(parents=True)
        self.session_id = sid
        self.store = session_dir / "store.db"
        conn = sqlite3.connect(self.store)
        conn.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
        for i, (role, text) in enumerate(
            (("user", "hello live"), ("assistant", "world live"))
        ):
            payload = json.dumps({"role": role, "content": text}).encode("utf-8")
            conn.execute("INSERT INTO blobs(id, data) VALUES (?, ?)", (f"b{i}", payload))
        conn.commit()
        conn.close()
        meta = {
            "cwd": self.cwd,
            "title": "live-fixture",
            "createdAtMs": 1_700_000_000_000,
            "updatedAtMs": 1_700_000_100_000,
        }
        (session_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        self.adapter = CursorAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_and_show_live_store(self) -> None:
        query = Query(source="cursor", cwd=self.cwd, source_root=str(self.root), within_min=0)
        budget = ReadBudget()
        summaries = self.adapter.list(query, budget)
        self.assertTrue(any(s.session_id == self.session_id for s in summaries))
        hit = next(s for s in summaries if s.session_id == self.session_id)
        self.assertEqual(hit.provider, LIVE_CLI_FORMAT)
        session = self.adapter.show(ResolvedRef.from_summary(hit), query, ReadBudget())
        roles = [t.role for t in session.turns]
        self.assertIn("user", roles)
        # Deterministic ORDER BY rowid: first inserted is user
        if session.turns:
            self.assertEqual(session.turns[0].role, "user")

    def test_symlink_meta_not_followed(self) -> None:
        secret = Path(self._tmp.name) / "secret.txt"
        secret.write_text("should-not-leak", encoding="utf-8")
        # Replace meta with symlink
        import hashlib
        from portable_resume.adapters import cursor as cursor_mod

        h = cursor_mod._cwd_hash(self.cwd)
        meta = self.root / "chats" / h / self.session_id / "meta.json"
        meta.unlink()
        os.symlink(secret, meta)
        query = Query(source="cursor", cwd=self.cwd, source_root=str(self.root), within_min=0)
        # list should not raise and must not surface secret as title
        summaries = self.adapter.list(query, ReadBudget())
        for s in summaries:
            self.assertNotEqual(s.title, "should-not-leak")


if __name__ == "__main__":
    unittest.main()
