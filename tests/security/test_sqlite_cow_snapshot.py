"""Security and coherence tests for the Darwin/APFS SQLite COW path."""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import hashlib
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest import mock

import portable_resume.sqlite_cow as cow_module
from portable_resume.bounds import DEFAULT_BOUNDS
from portable_resume.diagnostics import DiagnosticError
from portable_resume.platform_fs.darwin_apfs import DarwinCloneUnavailable, is_apfs_fd
from portable_resume.snapshot import private_sqlite_connection_live_wal_cow


class SQLiteCowSnapshotTests(unittest.TestCase):
    def test_scratch_nonempty_check_stops_after_first_unknown_entry(self) -> None:
        class HostileEntries:
            def __init__(self) -> None:
                self.calls = 0

            def __enter__(self) -> "HostileEntries":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def __iter__(self) -> "HostileEntries":
                return self

            def __next__(self) -> object:
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(name="attacker-entry")
                raise AssertionError("cleanup must not enumerate a second entry")

        entries = HostileEntries()
        with mock.patch.object(cow_module.os, "scandir", return_value=entries):
            self.assertFalse(cow_module._scratch_directory_empty(123))
        self.assertEqual(entries.calls, 1)

    def _live_database(self, root: Path, *, subdirectory: bool = False) -> tuple[Path, sqlite3.Connection]:
        parent = root / "store" if subdirectory else root
        parent.mkdir(exist_ok=True)
        database = parent / "opencode.db"
        writer = sqlite3.connect(database)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE session(id TEXT PRIMARY KEY, value TEXT)")
        writer.execute("INSERT INTO session VALUES ('anchor', 'visible')")
        writer.commit()
        self.assertTrue(Path(str(database) + "-wal").is_file())
        self.assertTrue(Path(str(database) + "-shm").is_file())
        return database, writer

    def _require_real_apfs(self, path: Path) -> None:
        if sys.platform != "darwin":
            self.skipTest("real fclonefileat proof runs on Darwin")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            if not is_apfs_fd(descriptor):
                self.skipTest("real fclonefileat proof requires APFS")
        finally:
            os.close(descriptor)

    @staticmethod
    def _scratch_entries() -> set[str]:
        root = Path(tempfile.gettempdir())
        return {str(path) for path in root.glob("portable-resume-cow-*")}

    @staticmethod
    def _file_state(path: Path) -> tuple[tuple[int, int, int, int, int], str, tuple[tuple[str, bytes], ...]]:
        current = path.lstat()
        names: list[str] = []
        getxattr = getattr(os, "getxattr", None)
        if hasattr(os, "listxattr"):
            try:
                names = sorted(os.listxattr(path, follow_symlinks=False))
            except OSError:
                names = []
        attributes: list[tuple[str, bytes]] = []
        for name in names:
            try:
                if callable(getxattr):
                    attributes.append(
                        (name, getxattr(path, name, follow_symlinks=False))
                    )
            except OSError:
                pass
        identity = (
            current.st_dev,
            current.st_ino,
            stat.S_IMODE(current.st_mode),
            current.st_size,
            current.st_mtime_ns,
        )
        return identity, hashlib.sha256(path.read_bytes()).hexdigest(), tuple(attributes)

    def test_private_query_only_connection_uses_unlinked_descriptor_and_passes_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            try:
                with private_sqlite_connection_live_wal_cow(
                    database,
                    root=root,
                    provider="opencode-sqlite-v1",
                ) as connection:
                    self.assertEqual(connection.execute("PRAGMA query_only").fetchone(), (1,))
                    self.assertEqual(connection.execute("PRAGMA integrity_check(1)").fetchone(), ("ok",))
                    self.assertEqual(
                        connection.execute("SELECT value FROM session WHERE id='anchor'").fetchone(),
                        ("visible",),
                    )
                    private_database = Path(connection.execute("PRAGMA database_list").fetchone()[2])
                    self.assertNotEqual(private_database, database)
                    self.assertFalse(str(private_database).startswith(str(root)))
                    self.assertTrue(str(private_database).startswith("/dev/fd/"))
                    self.assertFalse(Path(str(private_database) + "-shm").exists())
            finally:
                writer.close()

    def test_unsupported_linux_other_non_apfs_and_missing_symbol_fail_live_wal_contract(self) -> None:
        scenarios = (
            (mock.patch("portable_resume.sqlite_cow.sys.platform", "linux"),),
            (
                mock.patch("portable_resume.sqlite_cow.sys.platform", "darwin"),
                mock.patch("portable_resume.sqlite_cow.is_apfs_fd", return_value=False),
            ),
            (
                mock.patch("portable_resume.sqlite_cow.sys.platform", "darwin"),
                mock.patch("portable_resume.sqlite_cow.is_apfs_fd", return_value=True),
                mock.patch(
                    "portable_resume.sqlite_cow.unique_unlink_supported",
                    return_value=False,
                ),
            ),
            (
                mock.patch("portable_resume.sqlite_cow.sys.platform", "darwin"),
                mock.patch("portable_resume.sqlite_cow.is_apfs_fd", return_value=True),
                mock.patch(
                    "portable_resume.sqlite_cow.unique_unlink_supported",
                    return_value=True,
                ),
                mock.patch(
                    "portable_resume.sqlite_cow.clone_file_from_fd",
                    side_effect=DarwinCloneUnavailable("missing"),
                ),
            ),
            (
                # Linux CI emulates the Darwin capability branch above.  The
                # failed clone must use the real host's safe cleanup primitive
                # rather than trying Darwin-only unlinkat symbols and masking
                # E_SQLITE_LIVE_WAL with E_INVARIANT.
                mock.patch("portable_resume.sqlite_cow.sys.platform", "darwin"),
                mock.patch("portable_resume.sqlite_cow._RUNTIME_IS_DARWIN", False),
                mock.patch("portable_resume.sqlite_cow.is_apfs_fd", return_value=True),
                mock.patch(
                    "portable_resume.sqlite_cow.unique_unlink_supported",
                    return_value=True,
                ),
                mock.patch(
                    "portable_resume.sqlite_cow.clone_file_from_fd",
                    side_effect=DarwinCloneUnavailable("missing"),
                ),
            ),
        )
        for patches in scenarios:
            with self.subTest(count=len(patches)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                database, writer = self._live_database(root)
                before = self._scratch_entries()
                try:
                    with contextlib.ExitStack() as stack:
                        for patcher in patches:
                            stack.enter_context(patcher)
                        with self.assertRaises(DiagnosticError) as caught:
                            with private_sqlite_connection_live_wal_cow(
                                database,
                                root=root,
                                provider="opencode-sqlite-v1",
                            ):
                                self.fail("unsupported backend must not yield")
                        self.assertEqual(caught.exception.code, "E_SQLITE_LIVE_WAL")
                        self.assertEqual(caught.exception.exit_code, 6)
                        self.assertEqual(caught.exception.attempts, 0)
                        self.assertEqual(caught.exception.provider, "opencode-sqlite-v1")
                        self.assertIn("opencode.db-wal", caught.exception.family)
                        self.assertIsNotNone(caught.exception.hint)
                        self.assertEqual(self._scratch_entries(), before)
                finally:
                    writer.close()

    def test_missing_unique_unlink_degrades_before_scratch_without_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database, writer = self._live_database(root)
            members = (
                database,
                Path(str(database) + "-wal"),
                Path(str(database) + "-shm"),
            )
            before = {path.name: self._file_state(path) for path in members}
            before_entries = tuple(sorted(path.name for path in root.iterdir()))
            before_scratch = self._scratch_entries()

            def forbidden_scratch(*_args: object, **_kwargs: object) -> object:
                raise AssertionError("scratch must not be allocated without AT_UNIQUE")

            try:
                with (
                    mock.patch("portable_resume.sqlite_cow.sys.platform", "darwin"),
                    mock.patch("portable_resume.sqlite_cow.is_apfs_fd", return_value=True),
                    mock.patch(
                        "portable_resume.sqlite_cow.unique_unlink_supported",
                        return_value=False,
                    ),
                    mock.patch(
                        "portable_resume.sqlite_cow._create_scratch_in",
                        side_effect=forbidden_scratch,
                    ),
                ):
                    with self.assertRaises(DiagnosticError) as caught:
                        with private_sqlite_connection_live_wal_cow(
                            database,
                            root=root,
                            provider="opencode-sqlite-v1",
                        ):
                            self.fail("missing AT_UNIQUE must not yield")
                self.assertEqual(caught.exception.code, "E_SQLITE_LIVE_WAL")
                self.assertNotEqual(caught.exception.code, "E_INVARIANT")
                self.assertEqual(caught.exception.exit_code, 6)
                self.assertEqual(caught.exception.attempts, 0)
                self.assertEqual(caught.exception.provider, "opencode-sqlite-v1")
                self.assertEqual(
                    {path.name: self._file_state(path) for path in members},
                    before,
                )
                self.assertEqual(
                    tuple(sorted(path.name for path in root.iterdir())),
                    before_entries,
                )
                self.assertEqual(self._scratch_entries(), before_scratch)
            finally:
                writer.close()

    def test_append_beyond_accepted_prefix_is_deferred_without_losing_committed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            appended = False

            def hook(stage: str, _attempt: int, _source: str) -> None:
                nonlocal appended
                if stage == "after-wal-prefix" and not appended:
                    writer.execute("INSERT INTO session VALUES ('future', 'later')")
                    writer.commit()
                    appended = True

            try:
                with private_sqlite_connection_live_wal_cow(
                    database,
                    root=root,
                    attempts=1,
                    hook=hook,
                    provider="opencode-sqlite-v1",
                ) as connection:
                    self.assertEqual(
                        connection.execute("SELECT value FROM session WHERE id='anchor'").fetchone(),
                        ("visible",),
                    )
                    # The transaction committed strictly after N is explicitly
                    # permitted to wait for the next reader run.
                    self.assertIsNone(
                        connection.execute("SELECT value FROM session WHERE id='future'").fetchone()
                    )
            finally:
                writer.close()

    def test_restarted_wal_stale_tail_survives_repeated_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            try:
                # Populate and checkpoint a longer first generation. SQLite
                # subsequently restarts this file in place and leaves its old
                # frames beyond the new logical end.
                for index in range(8):
                    writer.execute(
                        "INSERT INTO session VALUES (?, ?)",
                        (f"seed-{index}", "seed"),
                    )
                    writer.commit()
                self.assertEqual(writer.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()[0], 0)
                physical_size = Path(str(database) + "-wal").stat().st_size

                for cycle in range(3):
                    session_id = f"restart-{cycle}"
                    writer.execute(
                        "INSERT INTO session VALUES (?, ?)",
                        (session_id, "visible"),
                    )
                    writer.commit()
                    self.assertEqual(Path(str(database) + "-wal").stat().st_size, physical_size)
                    fired = False

                    def hook(stage: str, _attempt: int, _source: str) -> None:
                        nonlocal fired
                        if stage == "after-family-pin" and not fired:
                            fired = True
                            self.assertEqual(
                                writer.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()[0],
                                0,
                            )

                    with private_sqlite_connection_live_wal_cow(
                        database,
                        root=root,
                        attempts=1,
                        hook=hook,
                        provider="opencode-sqlite-v1",
                    ) as connection:
                        self.assertEqual(
                            connection.execute(
                                "SELECT value FROM session WHERE id=?",
                                (session_id,),
                            ).fetchone(),
                            ("visible",),
                        )
                    self.assertTrue(fired)
            finally:
                writer.close()

    def test_generation_reset_truncate_replace_and_prefix_mutation_are_busy_and_cleanup(self) -> None:
        scenarios = (
            "truncate_during_copy",
            "truncate_regrow",
            "wal_replace",
            "header_salt",
            "prefix_mutation",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._require_real_apfs(root)
                database, writer = self._live_database(root)
                wal = Path(str(database) + "-wal")
                saved = wal.with_suffix(wal.suffix + ".saved")
                before_scratch = self._scratch_entries()
                fired = False

                def hook(stage: str, _attempt: int, _source: str) -> None:
                    nonlocal fired
                    if scenario == "truncate_during_copy":
                        target_stage = "after-wal-prefix"
                    else:
                        target_stage = (
                            "after-wal-copy" if scenario != "header_salt" else "after-clone"
                        )
                    if fired or stage != target_stage:
                        return
                    fired = True
                    data = wal.read_bytes()
                    if scenario == "truncate_during_copy":
                        descriptor = os.open(wal, os.O_RDWR)
                        try:
                            os.ftruncate(descriptor, 32)
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                    elif scenario == "truncate_regrow":
                        time.sleep(0.002)
                        descriptor = os.open(wal, os.O_RDWR)
                        try:
                            os.ftruncate(descriptor, 32)
                            os.fsync(descriptor)
                            os.pwrite(descriptor, data[32:], 32)
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                    elif scenario == "wal_replace":
                        wal.rename(saved)
                        wal.write_bytes(data)
                    elif scenario == "header_salt":
                        descriptor = os.open(wal, os.O_RDWR)
                        try:
                            os.pwrite(descriptor, bytes([data[16] ^ 1]), 16)
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                    else:
                        descriptor = os.open(wal, os.O_RDWR)
                        try:
                            os.pwrite(descriptor, bytes([data[56] ^ 1]), 56)
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)

                try:
                    with self.assertRaises(DiagnosticError) as caught:
                        with private_sqlite_connection_live_wal_cow(
                            database,
                            root=root,
                            attempts=1,
                            hook=hook,
                            provider="opencode-sqlite-v1",
                        ):
                            self.fail("mutated generation must not yield")
                    self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
                    self.assertEqual(caught.exception.attempts, 1)
                    self.assertEqual(self._scratch_entries(), before_scratch)
                finally:
                    if saved.exists():
                        if wal.exists():
                            wal.unlink()
                        saved.rename(wal)
                    try:
                        writer.close()
                    except sqlite3.Error:
                        pass

    def test_source_main_wal_shm_symlink_and_nonregular_are_unsafe_without_side_effect(self) -> None:
        for member in ("main", "wal", "shm"):
            for kind in ("symlink", "directory"):
                with self.subTest(member=member, kind=kind), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    database, writer = self._live_database(root)
                    target = {
                        "main": database,
                        "wal": Path(str(database) + "-wal"),
                        "shm": Path(str(database) + "-shm"),
                    }[member]
                    saved = target.with_name(target.name + ".saved")
                    target.rename(saved)
                    if kind == "symlink":
                        target.symlink_to(saved.name)
                    else:
                        target.mkdir()
                    entries = tuple(sorted(path.name for path in root.iterdir()))
                    try:
                        with self.assertRaises(DiagnosticError) as caught:
                            with private_sqlite_connection_live_wal_cow(
                                database,
                                root=root,
                                attempts=1,
                                provider="opencode-sqlite-v1",
                            ):
                                self.fail("unsafe family must not yield")
                        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")
                        self.assertEqual(tuple(sorted(path.name for path in root.iterdir())), entries)
                    finally:
                        if target.is_symlink():
                            target.unlink()
                        elif target.is_dir():
                            target.rmdir()
                        saved.rename(target)
                        try:
                            writer.close()
                        except sqlite3.Error:
                            pass

    def test_source_parent_main_wal_and_scratch_path_swaps_fail_closed(self) -> None:
        for scenario in ("parent", "main", "wal"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._require_real_apfs(root)
                database, writer = self._live_database(root, subdirectory=True)
                parent = database.parent
                saved_parent = root / "store.saved"
                target = database if scenario == "main" else Path(str(database) + "-wal")
                saved_target = target.with_name(target.name + ".saved")
                fired = False

                def hook(stage: str, _attempt: int, _source: str) -> None:
                    nonlocal fired
                    if fired or stage != "after-wal-copy":
                        return
                    fired = True
                    if scenario == "parent":
                        parent.rename(saved_parent)
                        parent.mkdir()
                    else:
                        data = target.read_bytes()
                        target.rename(saved_target)
                        target.write_bytes(data)

                try:
                    with self.assertRaises(DiagnosticError) as caught:
                        with private_sqlite_connection_live_wal_cow(
                            database,
                            root=root,
                            attempts=1,
                            hook=hook,
                            provider="opencode-sqlite-v1",
                        ):
                            self.fail("source pathname swap must not yield")
                    self.assertIn(caught.exception.code, {"E_SOURCE_BUSY", "E_UNSAFE_PATH"})
                finally:
                    if scenario == "parent" and saved_parent.exists():
                        if parent.exists():
                            parent.rmdir()
                        saved_parent.rename(parent)
                    elif saved_target.exists():
                        if target.exists():
                            target.unlink()
                        saved_target.rename(target)
                    try:
                        writer.close()
                    except sqlite3.Error:
                        pass

        with self.subTest(scenario="scratch"), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            baseline = self._scratch_entries()
            replacement: Path | None = None
            moved: Path | None = None

            def swap_scratch(stage: str, _attempt: int, _source: str) -> None:
                nonlocal replacement, moved
                if stage != "before-private-connect" or replacement is not None:
                    return
                created = self._scratch_entries() - baseline
                self.assertEqual(len(created), 1)
                replacement = Path(next(iter(created)))
                moved = replacement.with_name(replacement.name + ".moved")
                replacement.rename(moved)
                replacement.mkdir(mode=0o700)

            try:
                with self.assertRaises(DiagnosticError) as caught:
                    with private_sqlite_connection_live_wal_cow(
                        database,
                        root=root,
                        attempts=1,
                        hook=swap_scratch,
                        provider="opencode-sqlite-v1",
                    ):
                        self.fail("scratch pathname swap must not yield")
                self.assertEqual(caught.exception.code, "E_INVARIANT")
                self.assertIsNotNone(moved)
                assert moved is not None
                self.assertFalse(moved.exists())  # pinned reader-owned scratch was cleaned
                self.assertIsNotNone(replacement)
                assert replacement is not None
                self.assertTrue(replacement.is_dir())  # attacker replacement was not touched
            finally:
                if replacement is not None and replacement.exists():
                    replacement.rmdir()
                if moved is not None and moved.exists():
                    moved.rmdir()
                writer.close()
            self.assertEqual(self._scratch_entries(), baseline)

    def test_transient_main_path_swap_restore_cannot_change_fd_clone_source(self) -> None:
        import portable_resume.sqlite_cow as cow

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            saved = database.with_name("pinned-main.saved")
            decoy = database.with_name("decoy-main.sqlite")
            replacement = sqlite3.connect(decoy)
            replacement.execute("CREATE TABLE decoy(value TEXT)")
            replacement.execute("INSERT INTO decoy VALUES ('wrong')")
            replacement.commit()
            replacement.close()
            original_clone = cow.clone_file_from_fd
            fired = False

            def clone(
                source_fd: int,
                destination_fd: int,
                name: str,
                *,
                deadline_check: Callable[[], None] | None = None,
            ) -> int:
                nonlocal fired
                database.rename(saved)
                decoy.rename(database)
                try:
                    clone_id = original_clone(
                        source_fd,
                        destination_fd,
                        name,
                        deadline_check=deadline_check,
                    )
                    fired = True
                    return clone_id
                finally:
                    database.rename(decoy)
                    saved.rename(database)

            try:
                with mock.patch.object(cow, "clone_file_from_fd", side_effect=clone):
                    with private_sqlite_connection_live_wal_cow(
                        database,
                        root=root,
                        attempts=1,
                        provider="opencode-sqlite-v1",
                    ) as connection:
                        self.assertEqual(
                            connection.execute("SELECT value FROM session WHERE id='anchor'").fetchone(),
                            ("visible",),
                        )
                        self.assertTrue(fired)
            finally:
                writer.close()

    def test_private_clone_destination_swap_is_rejected_before_wal_materialization(self) -> None:
        import portable_resume.sqlite_cow as cow

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database = root / "opencode.db"
            writer = sqlite3.connect(database)
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE session(id TEXT PRIMARY KEY, value TEXT)")
            writer.execute("CREATE TABLE sentinel(value TEXT)")
            writer.execute("INSERT INTO session VALUES ('anchor', 'visible')")
            writer.execute("INSERT INTO sentinel VALUES ('source')")
            writer.commit()
            self.assertEqual(writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0], 0)
            writer.execute("INSERT INTO session VALUES ('future', 'later')")
            writer.commit()

            attacker = root / "attacker.db"
            shutil.copyfile(database, attacker)
            replacement = sqlite3.connect(attacker)
            replacement.execute("UPDATE sentinel SET value='attacker'")
            replacement.commit()
            self.assertEqual(
                replacement.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0],
                0,
            )
            replacement.close()
            self.assertEqual(attacker.stat().st_size, database.stat().st_size)
            immutable = sqlite3.connect(
                f"file:{attacker}?mode=ro&immutable=1", uri=True
            )
            try:
                self.assertEqual(
                    immutable.execute("SELECT value FROM sentinel").fetchone(),
                    ("attacker",),
                )
            finally:
                immutable.close()

            baseline = self._scratch_entries()
            original_clone = cow.clone_file_from_fd
            saved_clone: Path | None = None
            attacker_entry: Path | None = None

            def clone(
                source_fd: int,
                destination_fd: int,
                name: str,
                *,
                deadline_check: Callable[[], None] | None = None,
            ) -> int:
                nonlocal saved_clone, attacker_entry
                clone_id = original_clone(
                    source_fd,
                    destination_fd,
                    name,
                    deadline_check=deadline_check,
                )
                created = self._scratch_entries() - baseline
                self.assertEqual(len(created), 1)
                scratch = Path(next(iter(created)))
                attacker_entry = scratch / name
                saved_clone = scratch.with_name(scratch.name + ".saved-clone")
                attacker_entry.rename(saved_clone)
                shutil.copyfile(attacker, attacker_entry)
                return clone_id

            source_before = {
                path.name: self._file_state(path)
                for path in (database, Path(str(database) + "-wal"), Path(str(database) + "-shm"))
            }
            try:
                with (
                    mock.patch.object(cow, "clone_file_from_fd", side_effect=clone),
                    mock.patch.object(
                        cow,
                        "materialize_wal_prefix",
                        wraps=cow.materialize_wal_prefix,
                    ) as materialize,
                ):
                    with self.assertRaises(DiagnosticError) as caught:
                        with private_sqlite_connection_live_wal_cow(
                            database,
                            root=root,
                            attempts=1,
                            provider="opencode-sqlite-v1",
                        ):
                            self.fail("attacker-selected clone destination must not yield")
                self.assertEqual(caught.exception.code, "E_INVARIANT")
                materialize.assert_not_called()
                self.assertIsNotNone(attacker_entry)
                assert attacker_entry is not None
                self.assertFalse(attacker_entry.exists())
                self.assertIsNotNone(saved_clone)
                assert saved_clone is not None
                self.assertTrue(saved_clone.is_file())
                source_after = {
                    path.name: self._file_state(path)
                    for path in (
                        database,
                        Path(str(database) + "-wal"),
                        Path(str(database) + "-shm"),
                    )
                }
                self.assertEqual(source_after, source_before)
            finally:
                writer.close()
                if attacker_entry is not None and attacker_entry.exists():
                    attacker_entry.unlink()
                    for suffix in ("-wal", "-shm", "-journal"):
                        Path(str(attacker_entry) + suffix).unlink(missing_ok=True)
                    attacker_entry.parent.rmdir()
                if saved_clone is not None and saved_clone.exists():
                    saved_clone.unlink()
                attacker.unlink(missing_ok=True)
            self.assertEqual(self._scratch_entries(), baseline)

    def test_private_clone_retained_attacker_fd_mutation_is_rejected(self) -> None:
        import portable_resume.sqlite_cow as cow

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            baseline = self._scratch_entries()
            original_clone = cow.clone_file_from_fd
            attacker_fd: int | None = None
            mutated = False

            def clone(
                source_fd: int,
                destination_fd: int,
                name: str,
                *,
                deadline_check: Callable[[], None] | None = None,
            ) -> int:
                nonlocal attacker_fd
                clone_id = original_clone(
                    source_fd,
                    destination_fd,
                    name,
                    deadline_check=deadline_check,
                )
                attacker_fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=destination_fd)
                return clone_id

            def hook(stage: str, _attempt: int, _source: str) -> None:
                nonlocal mutated
                if stage == "after-clone" and not mutated:
                    assert attacker_fd is not None
                    os.pwrite(attacker_fd, b"attacker", 0)
                    os.fsync(attacker_fd)
                    mutated = True

            try:
                with mock.patch.object(cow, "clone_file_from_fd", side_effect=clone):
                    with self.assertRaises(DiagnosticError) as caught:
                        with private_sqlite_connection_live_wal_cow(
                            database,
                            root=root,
                            attempts=1,
                            hook=hook,
                            provider="opencode-sqlite-v1",
                        ):
                            self.fail("retained attacker FD mutation must not yield")
                self.assertTrue(mutated)
                self.assertEqual(caught.exception.code, "E_INVARIANT")
            finally:
                if attacker_fd is not None:
                    os.close(attacker_fd)
                writer.close()
            self.assertEqual(self._scratch_entries(), baseline)

    def test_private_main_path_injection_cannot_change_descriptor_bound_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            baseline = self._scratch_entries()
            replacement_main: Path | None = None
            swapped = False

            def hook(stage: str, _attempt: int, _source: str) -> None:
                nonlocal replacement_main, swapped
                created = self._scratch_entries() - baseline
                if len(created) != 1:
                    return
                scratch = Path(next(iter(created)))
                main = scratch / "snapshot.sqlite"
                if stage == "before-private-connect" and not swapped:
                    replacement_main = main
                    self.assertFalse(main.exists())
                    replacement = sqlite3.connect(replacement_main)
                    replacement.execute(
                        "CREATE TABLE session(id TEXT PRIMARY KEY, value TEXT)"
                    )
                    replacement.execute(
                        "INSERT INTO session VALUES ('anchor', 'attacker')"
                    )
                    replacement.commit()
                    replacement.close()
                    swapped = True
                elif stage == "after-private-connect" and swapped:
                    assert replacement_main is not None
                    replacement_main.unlink()

            try:
                with private_sqlite_connection_live_wal_cow(
                    database,
                    root=root,
                    attempts=1,
                    hook=hook,
                    provider="opencode-sqlite-v1",
                ) as connection:
                    self.assertTrue(swapped)
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM session WHERE id='anchor'"
                        ).fetchone(),
                        ("visible",),
                    )
            finally:
                if replacement_main is not None and replacement_main.exists():
                    replacement_main.unlink()
                writer.close()

    def test_private_scratch_swap_during_connect_cannot_redirect_query(self) -> None:
        import portable_resume.sqlite_cow as cow

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            baseline = self._scratch_entries()
            real_connect = cow.sqlite3.connect
            saved_scratch: Path | None = None
            replacement_scratch: Path | None = None
            swapped = False

            def restore() -> None:
                if replacement_scratch is not None and replacement_scratch.exists():
                    for child in replacement_scratch.iterdir():
                        child.unlink()
                    replacement_scratch.rmdir()
                if saved_scratch is not None and saved_scratch.exists():
                    assert replacement_scratch is not None
                    saved_scratch.rename(replacement_scratch)

            def connect(
                database_arg: str, *args: object, **kwargs: object
            ) -> sqlite3.Connection:
                nonlocal saved_scratch, replacement_scratch, swapped
                created = self._scratch_entries() - baseline
                self.assertEqual(len(created), 1)
                replacement_scratch = Path(next(iter(created)))
                token = replacement_scratch.name.removeprefix("portable-resume-cow-")
                saved_scratch = replacement_scratch.with_name(
                    "issue263-saved-scratch-" + token
                )
                replacement_scratch.rename(saved_scratch)
                replacement_scratch.mkdir(mode=0o700)
                attacker = real_connect(replacement_scratch / "snapshot.sqlite")
                try:
                    attacker.execute(
                        "CREATE TABLE session(id TEXT PRIMARY KEY, value TEXT)"
                    )
                    attacker.execute(
                        "INSERT INTO session VALUES ('anchor', 'attacker')"
                    )
                    attacker.commit()
                finally:
                    attacker.close()
                try:
                    connection = real_connect(  # type: ignore[call-overload]
                        database_arg, *args, **kwargs
                    )
                    swapped = True
                    return connection
                finally:
                    restore()

            try:
                with mock.patch.object(cow.sqlite3, "connect", side_effect=connect):
                    with private_sqlite_connection_live_wal_cow(
                        database,
                        root=root,
                        attempts=1,
                        provider="opencode-sqlite-v1",
                    ) as connection:
                        self.assertTrue(swapped)
                        self.assertEqual(
                            connection.execute(
                                "SELECT value FROM session WHERE id='anchor'"
                            ).fetchone(),
                            ("visible",),
                        )
            finally:
                restore()
                writer.close()
            self.assertEqual(self._scratch_entries(), baseline)

    def test_cleanup_rmdir_swap_removes_owned_inode_not_replacement(self) -> None:
        import portable_resume.sqlite_cow as cow

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            baseline = self._scratch_entries()
            real_unlink = cow.unlink_volume_inode
            replacement: Path | None = None
            moved: Path | None = None

            def unlink(descriptor: int, *, directory: bool = False) -> None:
                nonlocal replacement, moved
                if directory and replacement is None:
                    created = self._scratch_entries() - baseline
                    if len(created) == 1:
                        replacement = Path(next(iter(created)))
                        moved = replacement.with_name(replacement.name + ".moved")
                        replacement.rename(moved)
                        replacement.mkdir(mode=0o700)
                real_unlink(descriptor, directory=directory)

            try:
                with mock.patch.object(cow, "unlink_volume_inode", side_effect=unlink):
                    with self.assertRaises(DiagnosticError) as caught:
                        with private_sqlite_connection_live_wal_cow(
                            database,
                            root=root,
                            attempts=1,
                            provider="opencode-sqlite-v1",
                        ):
                            pass
                self.assertEqual(caught.exception.code, "E_INVARIANT")
                self.assertIsNotNone(replacement)
                assert replacement is not None
                self.assertTrue(replacement.is_dir())
                self.assertIsNotNone(moved)
                assert moved is not None
                self.assertFalse(moved.exists())
            finally:
                if replacement is not None and replacement.exists():
                    replacement.rmdir()
                if moved is not None and moved.exists():
                    moved.rmdir()
                writer.close()
            self.assertEqual(self._scratch_entries(), baseline)

    def test_quiescent_source_main_wal_shm_digest_inode_mode_mtime_xattr_and_entries_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            members = (database, Path(str(database) + "-wal"), Path(str(database) + "-shm"))
            if hasattr(os, "setxattr"):
                try:
                    os.setxattr(database, "com.portable-resume.synthetic", b"fixture")
                except OSError:
                    pass
            before = {path.name: self._file_state(path) for path in members}
            before_entries = tuple(sorted(path.name for path in root.iterdir()))
            try:
                with private_sqlite_connection_live_wal_cow(
                    database,
                    root=root,
                    attempts=1,
                    provider="opencode-sqlite-v1",
                ) as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM session").fetchone(), (1,))
                after = {path.name: self._file_state(path) for path in members}
                self.assertEqual(after, before)
                self.assertEqual(tuple(sorted(path.name for path in root.iterdir())), before_entries)
            finally:
                writer.close()

    def test_reader_mutation_and_connect_audit_never_targets_source_root(self) -> None:
        import portable_resume.sqlite_cow as cow

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            real_connect = cow.sqlite3.connect
            uris: list[str] = []
            appended = False

            def audited_connect(database_arg: str, *args: object, **kwargs: object) -> sqlite3.Connection:
                uris.append(str(database_arg))
                return real_connect(  # type: ignore[call-overload]
                    database_arg, *args, **kwargs
                )

            def hook(stage: str, _attempt: int, _source: str) -> None:
                nonlocal appended
                if stage == "after-wal-prefix" and not appended:
                    writer.execute("INSERT INTO session VALUES ('writer', 'owned')")
                    writer.commit()
                    appended = True

            try:
                with mock.patch.object(cow.sqlite3, "connect", side_effect=audited_connect):
                    with private_sqlite_connection_live_wal_cow(
                        database,
                        root=root,
                        attempts=1,
                        hook=hook,
                        provider="opencode-sqlite-v1",
                    ) as connection:
                        self.assertEqual(connection.execute("SELECT COUNT(*) FROM session").fetchone(), (1,))
                self.assertTrue(uris)
                self.assertTrue(all(str(root) not in uri for uri in uris))
                self.assertEqual(writer.execute("SELECT value FROM session WHERE id='writer'").fetchone(), ("owned",))
            finally:
                writer.close()

    def test_same_volume_free_space_headroom_deadline_cancellation_and_cleanup(self) -> None:
        import portable_resume.sqlite_cow as cow

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            before = self._scratch_entries()
            try:
                too_small = dataclasses.replace(
                    DEFAULT_BOUNDS,
                    sqlite_cow_logical_bytes=max(0, database.stat().st_size - 1),
                )
                with self.assertRaises(DiagnosticError) as logical:
                    with private_sqlite_connection_live_wal_cow(
                        database, root=root, bounds=too_small, attempts=1
                    ):
                        self.fail("logical bound must reject")
                self.assertEqual(logical.exception.code, "E_LIMIT_EXCEEDED")

                expired = dataclasses.replace(DEFAULT_BOUNDS, sqlite_snapshot_deadline_ms=0)
                with self.assertRaises(DiagnosticError) as deadline:
                    with private_sqlite_connection_live_wal_cow(
                        database, root=root, bounds=expired, attempts=1
                    ):
                        self.fail("deadline must reject")
                self.assertEqual(deadline.exception.code, "E_SOURCE_BUSY")

                no_space = SimpleNamespace(f_frsize=4096, f_bsize=4096, f_bavail=0)
                with mock.patch.object(cow.os, "fstatvfs", return_value=no_space):
                    with self.assertRaises(DiagnosticError) as space:
                        with private_sqlite_connection_live_wal_cow(
                            database, root=root, attempts=1
                        ):
                            self.fail("free-space preflight must reject")
                self.assertEqual(space.exception.code, "E_LIMIT_EXCEEDED")

                class ConsumerCancelled(Exception):
                    pass

                with self.assertRaises(ConsumerCancelled):
                    with private_sqlite_connection_live_wal_cow(
                        database, root=root, attempts=1
                    ):
                        raise ConsumerCancelled()
                self.assertEqual(self._scratch_entries(), before)
            finally:
                writer.close()

    def test_clone_errno_capability_mapping(self) -> None:
        import portable_resume.sqlite_cow as cow

        cases = {
            getattr(errno, "ENOTSUP", errno.EINVAL): "E_SQLITE_LIVE_WAL",
            errno.EXDEV: "E_SQLITE_LIVE_WAL",
            errno.ENOSPC: "E_LIMIT_EXCEEDED",
            errno.EFBIG: "E_LIMIT_EXCEEDED",
            errno.EBUSY: "E_SOURCE_BUSY",
            errno.EIO: "E_SOURCE_BUSY",
            errno.ENOENT: "E_UNSAFE_PATH",
            9999: "E_SQLITE_LIVE_WAL",
        }
        for number, expected in cases.items():
            with self.subTest(errno=number), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                database, writer = self._live_database(root)
                before = self._scratch_entries()
                try:
                    with (
                        mock.patch.object(cow.sys, "platform", "darwin"),
                        mock.patch.object(cow, "is_apfs_fd", return_value=True),
                        mock.patch.object(
                            cow,
                            "unique_unlink_supported",
                            return_value=True,
                        ),
                        mock.patch.object(
                            cow,
                            "clone_file_from_fd",
                            side_effect=OSError(number, "synthetic"),
                        ),
                    ):
                        with self.assertRaises(DiagnosticError) as caught:
                            with private_sqlite_connection_live_wal_cow(
                                database, root=root, attempts=1, provider="opencode-sqlite-v1"
                            ):
                                self.fail("clone error must not yield")
                    self.assertEqual(caught.exception.code, expected)
                    self.assertEqual(self._scratch_entries(), before)
                finally:
                    writer.close()

    def test_rollback_journal_created_between_validation_and_acceptance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._require_real_apfs(root)
            database, writer = self._live_database(root)
            journal = Path(str(database) + "-journal")
            fired = False

            def hook(stage: str, _attempt: int, _source: str) -> None:
                nonlocal fired
                if stage == "before-accept" and not fired:
                    journal.write_bytes(b"synthetic-hot-journal")
                    fired = True

            try:
                with self.assertRaises(DiagnosticError) as caught:
                    with private_sqlite_connection_live_wal_cow(
                        database,
                        root=root,
                        attempts=1,
                        hook=hook,
                        provider="opencode-sqlite-v1",
                    ):
                        self.fail("late journal must not yield")
                self.assertEqual(caught.exception.code, "E_SQLITE_HOT_JOURNAL")
            finally:
                journal.unlink(missing_ok=True)
                writer.close()


if __name__ == "__main__":
    unittest.main()
