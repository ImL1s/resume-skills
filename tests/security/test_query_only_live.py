"""Characterization tests for query_only_live_sqlite (large-DB path)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_main_rename_symlink_swap_before_sqlite_open_fails_closed(self) -> None:
        attacker = self.root / "attacker.sqlite"
        connection = sqlite3.connect(attacker)
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        connection.execute("INSERT INTO t(v) VALUES ('attacker')")
        connection.commit()
        connection.close()

        original = self.root / "original.sqlite"
        real_connect = sqlite3.connect
        swapped = False
        opened_uri = ""

        def swap_then_connect(*args, **kwargs):
            nonlocal opened_uri, swapped
            opened_uri = str(args[0])
            if not swapped:
                self.db.rename(original)
                self.db.symlink_to(attacker)
                swapped = True
            return real_connect(*args, **kwargs)

        with mock.patch("portable_resume.snapshot.sqlite3.connect", side_effect=swap_then_connect):
            with self.assertRaises(DiagnosticError) as ctx:
                with query_only_live_sqlite(str(self.db), root=str(self.root), provider="test"):
                    self.fail("swapped source path must never be yielded")

        self.assertTrue(swapped)
        self.assertRegex(opened_uri, r"^file:/(?:proc/self|dev)/fd/\d+\?")
        self.assertNotIn(str(self.db), opened_uri)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")


if __name__ == "__main__":
    unittest.main()
