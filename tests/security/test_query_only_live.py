"""Characterization tests for query_only_live_sqlite (large-DB path)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import query_only_live_sqlite


class QueryOnlyLiveSqliteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "data.sqlite"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t(v) VALUES ('ok')")
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_query_only_select_works(self) -> None:
        with query_only_live_sqlite(str(self.db), root=str(self.root), provider="test") as connection:
            row = connection.execute("SELECT v FROM t").fetchone()
            self.assertEqual(row, ("ok",))
            value = connection.execute("PRAGMA query_only").fetchone()
            self.assertEqual(value[0], 1)

    def test_hot_journal_rejected(self) -> None:
        journal = Path(str(self.db) + "-journal")
        journal.write_bytes(b"hot")
        with self.assertRaises(DiagnosticError) as ctx:
            with query_only_live_sqlite(str(self.db), root=str(self.root), provider="test"):
                pass
        self.assertEqual(ctx.exception.code, "E_SQLITE_HOT_JOURNAL")

    def test_wal_symlink_rejected(self) -> None:
        outside = self.root / "outside.wal"
        outside.write_bytes(b"x")
        wal = Path(str(self.db) + "-wal")
        os.symlink(outside, wal)
        with self.assertRaises(DiagnosticError) as ctx:
            with query_only_live_sqlite(str(self.db), root=str(self.root), provider="test"):
                pass
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")


if __name__ == "__main__":
    unittest.main()
