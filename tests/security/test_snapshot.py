from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import private_sqlite_connection, snapshot_sqlite_family, stable_read_bytes
from tests.helpers.core import tree_snapshot


class StableSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / "store"
        self.store.mkdir()

    def test_stable_read_preserves_source_tree(self) -> None:
        path = self.store / "record.jsonl"
        path.write_bytes(b"synthetic\n")
        before = tree_snapshot(self.store)
        result = stable_read_bytes(path, root=self.store)
        after = tree_snapshot(self.store)
        self.assertEqual(result.data, b"synthetic\n")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(result.fingerprint.content_sha256 or ""), 64)
        self.assertEqual(before, after)

    def test_detects_one_concurrent_mutation_then_retries(self) -> None:
        path = self.store / "record"
        path.write_bytes(b"before")
        calls = []

        def hook(stage: str, attempt: int, _: str) -> None:
            if stage == "after-read" and attempt == 1:
                path.write_bytes(b"after!")
                calls.append(attempt)

        result = stable_read_bytes(path, root=self.store, hook=hook)
        self.assertEqual(calls, [1])
        self.assertEqual(result.data, b"after!")
        self.assertEqual(result.attempts, 2)

    def test_same_size_mtime_spoof_is_detected_by_second_content_read(self) -> None:
        path = self.store / "record"
        path.write_bytes(b"aaaa")
        original = path.stat().st_mtime_ns

        def hook(stage: str, attempt: int, _: str) -> None:
            if stage == "after-read":
                path.write_bytes(b"bbbb" if attempt % 2 else b"aaaa")
                os.utime(path, ns=(original, original))

        with self.assertRaises(DiagnosticError) as caught:
            stable_read_bytes(path, root=self.store, hook=hook)
        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
        self.assertEqual(caught.exception.attempts, 3)

    def test_detects_parent_membership_change(self) -> None:
        path = self.store / "record"
        path.write_bytes(b"same")

        def hook(stage: str, attempt: int, _: str) -> None:
            if stage == "after-read" and attempt == 1:
                (self.store / "new-member").write_text("x")

        result = stable_read_bytes(path, root=self.store, hook=hook)
        self.assertEqual(result.attempts, 2)

    def test_every_attempt_mutates_fails_busy_without_partial_data(self) -> None:
        path = self.store / "record"
        path.write_bytes(b"0")

        def hook(stage: str, attempt: int, _: str) -> None:
            if stage == "after-read":
                path.write_text(str(attempt))

        with self.assertRaises(DiagnosticError) as caught:
            stable_read_bytes(path, root=self.store, hook=hook)
        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_u015_symlink_chain_escape_rejected_before_target_read(self) -> None:
        outside = self.root / "outside"
        outside.write_text("TOP SECRET")
        link = self.store / "link"
        link.symlink_to(outside)
        with self.assertRaises(DiagnosticError) as caught:
            stable_read_bytes(link, root=self.store)
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_u016_fifo_directory_and_socket_like_inputs_rejected(self) -> None:
        directory = self.store / "directory"
        directory.mkdir()
        with self.assertRaises(DiagnosticError):
            stable_read_bytes(directory, root=self.store)
        if hasattr(os, "mkfifo"):
            fifo = self.store / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(DiagnosticError):
                stable_read_bytes(fifo, root=self.store)

    def create_database(self) -> Path:
        database = self.store / "synthetic db.sqlite"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE items (value TEXT NOT NULL)")
        connection.execute("INSERT INTO items VALUES ('synthetic')")
        connection.commit()
        connection.close()
        return database

    def test_sqlite_private_copy_uri_query_only_and_source_immutable(self) -> None:
        database = self.create_database()
        before = tree_snapshot(self.store)
        real_connect = sqlite3.connect
        calls: list[tuple[object, dict]] = []

        def recording_connect(target: object, *args: object, **kwargs: object):
            calls.append((target, kwargs))
            return real_connect(target, *args, **kwargs)

        with mock.patch("portable_resume.snapshot.sqlite3.connect", side_effect=recording_connect):
            with private_sqlite_connection(database, root=self.store, provider="synthetic-sqlite-v1") as connection:
                self.assertEqual(connection.execute("PRAGMA query_only").fetchone(), (1,))
                self.assertEqual(connection.execute("SELECT value FROM items").fetchone(), ("synthetic",))
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("INSERT INTO items VALUES ('forbidden')")
        after = tree_snapshot(self.store)
        self.assertEqual(before, after)
        self.assertEqual(len(calls), 1)
        target, kwargs = calls[0]
        self.assertIsInstance(target, str)
        self.assertNotIn(str(database), target)
        self.assertIn("mode=ro", target)
        self.assertIn("cache=private", target)
        self.assertTrue(kwargs.get("uri"))

    def test_sqlite_wal_copied_shm_monitored_not_copied(self) -> None:
        database = self.create_database()
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        wal.write_bytes(b"synthetic-wal")
        shm.write_bytes(b"synthetic-shm")
        with snapshot_sqlite_family(database, root=self.store) as snapshot:
            self.assertTrue(Path(snapshot.database).exists())
            self.assertTrue(Path(str(snapshot.database) + "-wal").exists())
            self.assertFalse(Path(str(snapshot.database) + "-shm").exists())
            self.assertIn(database.name, snapshot.family)
            self.assertIn(wal.name, snapshot.family)
            private_dir = snapshot.directory
        self.assertFalse(Path(private_dir).exists())
        self.assertEqual(shm.read_bytes(), b"synthetic-shm")

    def test_sqlite_rollback_journal_fails_closed(self) -> None:
        database = self.create_database()
        journal = Path(str(database) + "-journal")
        journal.write_bytes(b"unproven")
        with self.assertRaises(DiagnosticError) as caught:
            snapshot_sqlite_family(database, root=self.store, provider="synthetic")
        self.assertEqual(caught.exception.code, "E_SQLITE_HOT_JOURNAL")
        self.assertEqual(caught.exception.family, (journal.name.replace(" ", ""),))

    def test_sqlite_family_race_retries_then_busy_and_cleans_private_dirs(self) -> None:
        database = self.create_database()
        initial_temp = set(Path(tempfile.gettempdir()).glob("portable-resume-sqlite-*"))

        def hook(stage: str, attempt: int, _: str) -> None:
            if stage == "after-copy":
                database.write_bytes(database.read_bytes() + bytes([attempt]))

        with self.assertRaises(DiagnosticError) as caught:
            snapshot_sqlite_family(database, root=self.store, hook=hook, provider="synthetic")
        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
        self.assertEqual(caught.exception.attempts, 3)
        self.assertEqual(initial_temp, set(Path(tempfile.gettempdir()).glob("portable-resume-sqlite-*")))

    def test_private_snapshot_cleanup_on_consumer_exception(self) -> None:
        database = self.create_database()
        private_dir = None
        with self.assertRaisesRegex(RuntimeError, "cancel"):
            with snapshot_sqlite_family(database, root=self.store) as snapshot:
                private_dir = snapshot.directory
                raise RuntimeError("cancel")
        self.assertIsNotNone(private_dir)
        self.assertFalse(Path(private_dir).exists())


if __name__ == "__main__":
    unittest.main()
