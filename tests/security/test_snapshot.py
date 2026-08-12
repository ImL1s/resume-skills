from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume import snapshot as snapshot_module
from portable_resume.bounds import DEFAULT_BOUNDS, Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import (
    private_sqlite_connection,
    query_only_live_sqlite,
    snapshot_regular_file,
    snapshot_sqlite_family,
    stable_read_bytes,
    stable_read_windows,
    stable_scan_lines,
)
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

    def test_stable_read_keeps_only_the_returned_payload_buffer(self) -> None:
        path = self.store / "record.jsonl"
        path.write_bytes(b"synthetic\n")
        with mock.patch.object(
            snapshot_module,
            "_read_bounded_descriptor",
            wraps=snapshot_module._read_bounded_descriptor,
        ) as materialized, mock.patch.object(
            snapshot_module,
            "_hash_descriptor",
            wraps=snapshot_module._hash_descriptor,
        ) as hashed:
            result = stable_read_bytes(path, root=self.store)
        self.assertEqual(result.data, b"synthetic\n")
        self.assertEqual(materialized.call_count, 1)
        self.assertEqual(hashed.call_count, 2)

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

    def test_unrelated_sibling_churn_does_not_invalidate_exact_read(self) -> None:
        """Issue #16: parent sibling adds must not force retry/fail of a stable target."""

        path = self.store / "record"
        path.write_bytes(b"same")

        def hook(stage: str, attempt: int, _: str) -> None:
            if stage == "after-read" and attempt == 1:
                (self.store / "new-member").write_text("x")

        result = stable_read_bytes(path, root=self.store, hook=hook)
        self.assertEqual(result.data, b"same")
        self.assertEqual(result.attempts, 1)

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

    def test_stable_scan_lines_symlink_escape_rejected_before_read(self) -> None:
        outside = self.root / "outside.jsonl"
        outside.write_text("TOP SECRET\n", encoding="utf-8")
        link = self.store / "link.jsonl"
        link.symlink_to(outside)
        with self.assertRaises(DiagnosticError) as caught:
            list(stable_scan_lines(link, root=self.store))
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

    def test_metadata_windows_are_bounded_non_overlapping_and_not_full_hashes(self) -> None:
        path = self.store / "large.jsonl"
        path.write_bytes(b"0123456789")
        budget = ReadBudget(Bounds(source_read_bytes=10))
        result = stable_read_windows(
            path,
            root=self.store,
            head_bytes=8,
            tail_bytes=6,
            max_bytes=10,
            budget=budget,
        )
        self.assertEqual(result.head, b"01234567")
        self.assertEqual(result.tail, b"89")
        self.assertEqual(result.tail_offset, 8)
        self.assertEqual(budget.bytes_read, 10)
        self.assertIsNone(result.fingerprint.content_sha256)
        self.assertEqual(len(result.window_sha256), 64)

    def test_exact_read_succeeds_with_many_unrelated_siblings(self) -> None:
        """More than scanned_records siblings must not E_LIMIT_EXCEEDED an exact file (#16)."""

        path = self.store / "session.jsonl"
        path.write_bytes(b"{}\n")
        for index in range(DEFAULT_BOUNDS.scanned_records + 50):
            (self.store / f"sibling-{index:05d}").write_bytes(b"x")
        with mock.patch(
            "portable_resume.snapshot.os.listdir",
            side_effect=AssertionError("exact reads must not listdir the parent"),
        ):
            result = stable_read_windows(path, root=self.store, membership_limit=1)
            body = stable_read_bytes(path, root=self.store, membership_limit=1)
            snap = snapshot_regular_file(path, root=self.store, membership_limit=1)
        self.assertEqual(result.head, b"{}\n")
        self.assertEqual(body.data, b"{}\n")
        with snap:
            self.assertTrue(Path(snap.path).is_file())

    def test_regular_file_snapshot_is_private_stable_and_cleans_up(self) -> None:
        path = self.store / "session.jsonl"
        path.write_bytes(b"synthetic\n")
        before = tree_snapshot(self.store)
        private_dir: str | None = None
        private_path: str | None = None
        with snapshot_regular_file(path, root=self.store) as snapshot:
            private_dir = snapshot.directory
            private_path = snapshot.path
            self.assertEqual(Path(snapshot.path).read_bytes(), b"synthetic\n")
            self.assertEqual(os.stat(snapshot.directory).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(snapshot.path).st_mode & 0o777, 0o600)
            self.assertEqual(tree_snapshot(self.store), before)
            path.write_bytes(b"changed!!\n")
            self.assertEqual(Path(snapshot.path).read_bytes(), b"synthetic\n")
        self.assertIsNotNone(private_dir)
        self.assertIsNotNone(private_path)
        self.assertFalse(Path(private_dir).exists())
        self.assertEqual(path.read_bytes(), b"changed!!\n")

    def test_regular_file_snapshot_retries_mutation_and_cleans_failed_attempts(self) -> None:
        path = self.store / "session.jsonl"
        path.write_bytes(b"before")
        initial = set(Path(tempfile.gettempdir()).glob("portable-resume-file-*"))

        def mutate_once(stage: str, attempt: int, _: str) -> None:
            if stage == "after-copy" and attempt == 1:
                path.write_bytes(b"after!")

        with snapshot_regular_file(path, root=self.store, hook=mutate_once) as snapshot:
            self.assertEqual(snapshot.attempts, 2)
            self.assertEqual(Path(snapshot.path).read_bytes(), b"after!")
        self.assertEqual(initial, set(Path(tempfile.gettempdir()).glob("portable-resume-file-*")))

        def mutate_every_time(stage: str, attempt: int, _: str) -> None:
            if stage == "after-copy":
                path.write_bytes(str(attempt).encode().ljust(6, b"!"))

        with self.assertRaises(DiagnosticError) as caught:
            snapshot_regular_file(path, root=self.store, hook=mutate_every_time)
        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
        self.assertEqual(initial, set(Path(tempfile.gettempdir()).glob("portable-resume-file-*")))

    def test_regular_file_snapshot_enforces_exact_and_lowered_bounds(self) -> None:
        path = self.store / "session.jsonl"
        path.write_bytes(b"1234")
        exact = Bounds(source_read_bytes=4, scanned_records=1, snapshot_attempts=1)
        with snapshot_regular_file(path, root=self.store, bounds=exact) as snapshot:
            self.assertEqual(Path(snapshot.path).read_bytes(), b"1234")
        path.write_bytes(b"12345")
        with self.assertRaises(DiagnosticError) as over:
            snapshot_regular_file(path, root=self.store, bounds=exact)
        self.assertEqual(over.exception.code, "E_LIMIT_EXCEEDED")
        with self.assertRaises(DiagnosticError) as raised_membership:
            snapshot_regular_file(path, root=self.store, bounds=exact, membership_limit=2)
        self.assertEqual(raised_membership.exception.code, "E_INVALID_INPUT")

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

    def test_initial_sqlite_family_state_busy_is_counted_and_retried(self) -> None:
        database = self.create_database()
        original = snapshot_module._family_state
        calls = 0

        def busy_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise DiagnosticError.source_busy(provider="synthetic")
            return original(*args, **kwargs)

        with mock.patch.object(snapshot_module, "_family_state", side_effect=busy_once):
            with snapshot_sqlite_family(database, root=self.store, provider="synthetic") as snapshot:
                self.assertEqual(snapshot.attempts, 2)

    def test_initial_sqlite_family_state_exhaustion_reports_attempts_and_cleans(self) -> None:
        database = self.create_database()
        initial_temp = set(Path(tempfile.gettempdir()).glob("portable-resume-sqlite-*"))
        with mock.patch.object(
            snapshot_module,
            "_family_state",
            side_effect=DiagnosticError.source_busy(family=(database.name,), provider="synthetic"),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                snapshot_sqlite_family(database, root=self.store, provider="synthetic")
        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
        self.assertEqual(caught.exception.attempts, 3)
        self.assertEqual(caught.exception.provider, "synthetic")
        self.assertIn(database.name.replace(" ", ""), caught.exception.family)
        self.assertEqual(initial_temp, set(Path(tempfile.gettempdir()).glob("portable-resume-sqlite-*")))

    def test_live_sqlite_wal_diagnostic_validates_all_sidecars_without_connect(self) -> None:
        database = self.create_database()
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        wal.write_bytes(b"synthetic-wal")
        shm.write_bytes(b"synthetic-shm")
        before = tree_snapshot(self.store)
        with mock.patch.object(snapshot_module.sqlite3, "connect") as connect:
            with self.assertRaises(DiagnosticError) as caught:
                with query_only_live_sqlite(database, root=self.store, provider="synthetic"):
                    pass
        self.assertEqual(caught.exception.code, "E_SQLITE_LIVE_WAL")
        self.assertEqual(caught.exception.attempts, 0)
        self.assertEqual(caught.exception.provider, "synthetic")
        self.assertEqual(
            set(caught.exception.family),
            {wal.name.replace(" ", ""), shm.name.replace(" ", "")},
        )
        connect.assert_not_called()
        self.assertEqual(tree_snapshot(self.store), before)

    def test_live_sqlite_sidecar_symlink_is_unsafe_before_wal_advisory(self) -> None:
        database = self.create_database()
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        wal.write_bytes(b"synthetic-wal")
        shm.symlink_to(wal)
        with mock.patch.object(snapshot_module.sqlite3, "connect") as connect:
            with self.assertRaises(DiagnosticError) as caught:
                with query_only_live_sqlite(database, root=self.store, provider="synthetic"):
                    pass
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")
        connect.assert_not_called()

    def test_live_sqlite_main_replacement_before_open_is_busy_without_connect(self) -> None:
        database = self.create_database()
        replacement = self.store / "replacement.db"
        replacement.write_bytes(database.read_bytes())
        original_lexists = snapshot_module.os.path.lexists
        replaced = False

        def replace_before_sidecar_scan(path: str) -> bool:
            nonlocal replaced
            if not replaced and os.path.basename(path) == f"{database.name}-journal":
                replaced = True
                os.replace(replacement, database)
            return original_lexists(path)

        with mock.patch.object(snapshot_module.os.path, "lexists", side_effect=replace_before_sidecar_scan), mock.patch.object(
            snapshot_module.sqlite3, "connect"
        ) as connect:
            with self.assertRaises(DiagnosticError) as caught:
                with query_only_live_sqlite(database, root=self.store, provider="synthetic"):
                    pass
        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
        self.assertEqual(caught.exception.provider, "synthetic")
        self.assertEqual(caught.exception.attempts, 0)
        self.assertEqual(caught.exception.family, (database.name.replace(" ", ""),))
        connect.assert_not_called()

    def test_live_sqlite_sidecars_created_during_connect_are_rejected_before_yield(self) -> None:
        database = self.create_database()
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        real_connect = snapshot_module.sqlite3.connect

        def connect_then_create_sidecars(*args: object, **kwargs: object) -> sqlite3.Connection:
            connection = real_connect(*args, **kwargs)
            wal.write_bytes(b"synthetic-wal")
            shm.write_bytes(b"synthetic-shm")
            return connection

        yielded = False
        with mock.patch.object(snapshot_module.sqlite3, "connect", side_effect=connect_then_create_sidecars):
            with self.assertRaises(DiagnosticError) as caught:
                with query_only_live_sqlite(database, root=self.store, provider="synthetic"):
                    yielded = True
        self.assertFalse(yielded)
        self.assertEqual(caught.exception.code, "E_SQLITE_LIVE_WAL")
        self.assertEqual(caught.exception.attempts, 0)
        self.assertEqual(
            set(caught.exception.family),
            {wal.name.replace(" ", ""), shm.name.replace(" ", "")},
        )

    def test_live_sqlite_sidecars_created_after_snapshot_during_final_verify_are_later_state(self) -> None:
        database = self.create_database()
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        real_open = snapshot_module._open_no_follow
        opens = 0

        def create_after_snapshot_then_open(path: str, root: str) -> int:
            nonlocal opens
            opens += 1
            if opens == 6:
                wal.write_bytes(b"synthetic-wal")
                shm.write_bytes(b"synthetic-shm")
            return real_open(path, root)

        with mock.patch.object(snapshot_module, "_open_no_follow", side_effect=create_after_snapshot_then_open):
            with query_only_live_sqlite(database, root=self.store, provider="synthetic") as connection:
                self.assertTrue(connection.in_transaction)
                observed = connection.execute("SELECT COUNT(*) FROM items").fetchone()

        self.assertGreaterEqual(opens, 6)
        self.assertTrue(wal.exists())
        self.assertTrue(shm.exists())
        self.assertEqual(observed, (1,))

    def test_live_sqlite_read_transaction_is_linearized_before_yield(self) -> None:
        database = self.create_database()
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")

        with query_only_live_sqlite(database, root=self.store, provider="synthetic") as connection:
            self.assertTrue(connection.in_transaction)
            observed = connection.execute("SELECT COUNT(*) FROM items").fetchone()
            # A family created after the helper established its read snapshot
            # belongs to a later source state and cannot redirect the pinned
            # descriptor or change the active SQLite transaction.
            wal.write_bytes(b"synthetic-later-wal")
            shm.write_bytes(b"synthetic-later-shm")

        self.assertEqual(observed, (1,))

    def test_persistent_wal_mode_without_sidecars_is_rejected_before_connect_or_mutation(self) -> None:
        database = self.store / "persistent-wal.db"
        writer = sqlite3.connect(database)
        try:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            writer.execute("CREATE TABLE stable(value TEXT)")
            writer.execute("INSERT INTO stable VALUES ('source')")
            writer.commit()
        finally:
            writer.close()
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        self.assertFalse(wal.exists())
        self.assertFalse(shm.exists())
        self.assertEqual(database.read_bytes()[18:20], b"\x02\x02")
        before = tree_snapshot(self.store)

        with mock.patch.object(snapshot_module.sqlite3, "connect") as connect:
            with self.assertRaises(DiagnosticError) as caught:
                with query_only_live_sqlite(database, root=self.store, provider="synthetic"):
                    self.fail("persistent WAL mode must not open the source")

        self.assertEqual(caught.exception.code, "E_SQLITE_LIVE_WAL")
        self.assertEqual(caught.exception.attempts, 0)
        self.assertEqual(caught.exception.provider, "synthetic")
        self.assertEqual(caught.exception.family, (database.name.replace(" ", ""),))
        connect.assert_not_called()
        self.assertEqual(tree_snapshot(self.store), before)

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
