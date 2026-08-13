#!/usr/bin/env python3
"""Real APFS proof for issue #263's identity-bound SQLite COW backend.

The emitted artifact contains only platform/build identifiers and counters. It
never includes a source path, session identifier, or recovered row content.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import hashlib
import json
import os
import platform
import queue
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Iterator, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from portable_resume.diagnostics import DiagnosticError  # noqa: E402
from portable_resume.paths import is_within  # noqa: E402
from portable_resume.platform_fs.darwin_apfs import (  # noqa: E402
    CLONE_NOFOLLOW,
    CLONE_NOOWNERCOPY,
    is_apfs_fd,
    unique_unlink_supported,
)
from portable_resume.snapshot import private_sqlite_connection_live_wal_cow  # noqa: E402

import portable_resume.sqlite_cow as cow_module  # noqa: E402

MINIMUM_ITERATIONS = 200
CONTINUOUS_SUCCESSES = 100
CHECKPOINT_BEFORE_SUCCESSES = 25
CHECKPOINT_AFTER_SUCCESSES = 25
PRIVATE_PATH_SWAP_SUCCESSES = 20
REJECTIONS_PER_SCENARIO = 20
PROOF_SCHEMA = "portable-resume/issue-263-apfs-proof-v3"
REJECTION_SCENARIOS = (
    "clone_destination_swap",
    "restart_reset",
    "truncate_reset",
    "wal_replace",
    "header_salt_change",
    "accepted_prefix_mutation",
    "source_pathname_replacement",
)


class ProofFailure(RuntimeError):
    pass


def _noop() -> None:
    """Default cleanup callback for rejection scenarios without restoration."""


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _fd_count() -> int:
    gc.collect()
    return len(os.listdir("/dev/fd"))


def _scratch_entries() -> set[str]:
    return {
        path.name
        for path in Path(tempfile.gettempdir()).glob("portable-resume-cow-*")
    }


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _xattrs(path: Path) -> tuple[tuple[str, str], ...]:
    getxattr = getattr(os, "getxattr", None)
    if not hasattr(os, "listxattr") or not callable(getxattr):
        return ()
    try:
        names = sorted(os.listxattr(path, follow_symlinks=False))
    except OSError:
        return ()
    output: list[tuple[str, str]] = []
    for name in names:
        try:
            value = getxattr(path, name, follow_symlinks=False)
        except OSError:
            continue
        output.append((name, hashlib.sha256(value).hexdigest()))
    return tuple(output)


def _source_state(root: Path, database: Path) -> tuple[object, ...]:
    members = (database, Path(str(database) + "-wal"), Path(str(database) + "-shm"))
    rows: list[object] = [tuple(sorted(path.name for path in root.iterdir()))]
    for path in members:
        value = path.lstat()
        rows.append(
            (
                path.name,
                value.st_dev,
                value.st_ino,
                stat.S_IMODE(value.st_mode),
                value.st_size,
                value.st_mtime_ns,
                _sha(path),
                _xattrs(path),
            )
        )
    return tuple(rows)


class _Writer:
    """One real SQLite connection owned by a separate writer thread."""

    def __init__(self, database: Path, owner: threading.local) -> None:
        self._database = database
        self._owner = owner
        self._requests: queue.Queue[tuple[str, threading.Event, list[BaseException]]] = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="issue263-writer", daemon=True)
        self._thread.start()
        if not self._ready.wait(10):
            raise ProofFailure("writer startup timeout")

    def _run(self) -> None:
        self._owner.value = "writer"
        connection = sqlite3.connect(self._database)
        connection.execute("PRAGMA wal_autocheckpoint=0")
        sequence = 0
        self._ready.set()
        try:
            while True:
                action, completed, errors = self._requests.get()
                try:
                    if action == "stop":
                        return
                    if action == "commit":
                        sequence += 1
                        connection.execute(
                            "INSERT INTO records(value) VALUES (?)",
                            (f"writer-{sequence}",),
                        )
                        connection.commit()
                    elif action == "checkpoint":
                        connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                    elif action == "reset":
                        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                        sequence += 1
                        connection.execute(
                            "INSERT INTO records(value) VALUES (?)",
                            (f"reset-{sequence}",),
                        )
                        connection.commit()
                    else:
                        raise ProofFailure("unknown writer action")
                except BaseException as error:
                    errors.append(error)
                finally:
                    completed.set()
        finally:
            connection.close()

    def action(self, name: str) -> None:
        completed = threading.Event()
        errors: list[BaseException] = []
        self._requests.put((name, completed, errors))
        if not completed.wait(10):
            raise ProofFailure("writer action timeout")
        if errors:
            raise ProofFailure("writer action failed") from errors[0]

    def close(self) -> None:
        if self._thread.is_alive():
            self.action("stop")
            self._thread.join(10)
        if self._thread.is_alive():
            raise ProofFailure("writer shutdown timeout")


class _Fixture:
    def __init__(self, owner: threading.local) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="issue263-proof-source-")
        self.root = Path(self._temporary.name)
        self.database = self.root / "source.sqlite"
        setup = sqlite3.connect(self.database)
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("PRAGMA wal_autocheckpoint=0")
        setup.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        setup.execute("INSERT INTO records(value) VALUES ('anchor')")
        setup.commit()
        self.writer = _Writer(self.database, owner)
        setup.close()
        # Closing the setup connection can checkpoint and remove its WAL even
        # while another idle connection exists.  Make one writer-owned commit
        # after that close so every proof case starts from a real live family.
        self.writer.action("commit")
        if not Path(str(self.database) + "-wal").is_file():
            raise ProofFailure("fixture WAL missing")
        if not Path(str(self.database) + "-shm").is_file():
            raise ProofFailure("fixture SHM missing")

    def close(self) -> None:
        try:
            self.writer.close()
        finally:
            self._temporary.cleanup()

    def __enter__(self) -> "_Fixture":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class _MutationAudit:
    def __init__(self) -> None:
        self.owner = threading.local()
        self.owner.value = "fixture"
        self.active = False
        self.source_roots: set[str] = set()
        self.reader_source_mutations = 0
        self.reader_source_sqlite_connects = 0
        self.reader_descriptor_bound_sqlite_connects = 0
        self.clone_destinations_under_source = 0
        self.real_clone_calls = 0
        self.clone_destination_swaps = 0
        self.swap_next_clone_destination = False
        self.exact_private_unlinks = 0
        self._original_open = os.open
        self._original_clone = cow_module.clone_file_from_fd
        self._original_unlink_volume_inode = cow_module.unlink_volume_inode
        sys.addaudithook(self._audit)

    @contextlib.contextmanager
    def as_owner(self, value: str) -> Iterator[None]:
        previous = getattr(self.owner, "value", "fixture")
        self.owner.value = value
        try:
            yield
        finally:
            self.owner.value = previous

    @staticmethod
    def _descriptor_path(descriptor: int) -> str | None:
        if descriptor < 0:
            return None
        try:
            import fcntl

            raw = fcntl.fcntl(descriptor, getattr(fcntl, "F_GETPATH", 50), bytes(1_024))
            return os.fsdecode(raw.split(b"\0", 1)[0])
        except (ImportError, OSError, ValueError):
            return None

    def _resolved_path(self, value: object, directory_fd: object = None) -> str | None:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return None
        try:
            path = os.fsdecode(value)
        except (TypeError, ValueError):
            return None
        if not os.path.isabs(path) and isinstance(directory_fd, int) and directory_fd >= 0:
            parent = self._descriptor_path(directory_fd)
            if parent is None:
                return None
            path = os.path.join(parent, path)
        return os.path.abspath(path)

    def _under_source(self, value: object, directory_fd: object = None) -> bool:
        path = self._resolved_path(value, directory_fd)
        if path is None:
            return False
        return any(is_within(path, root) for root in self.source_roots)

    def _audit(self, event: str, args: tuple[object, ...]) -> None:
        if not self.active or getattr(self.owner, "value", "reader") != "reader":
            return
        if event == "sqlite3.connect" and args:
            if self._under_source(args[0]) or any(root in str(args[0]) for root in self.source_roots):
                self.reader_source_sqlite_connects += 1
            if str(args[0]).startswith("file:/dev/fd/"):
                self.reader_descriptor_bound_sqlite_connects += 1
            return
        if event == "open" and len(args) >= 3:
            mode = args[1]
            flags = args[2]
            mutating_mode = isinstance(mode, str) and any(char in mode for char in "wax+")
            mutating_flags = isinstance(flags, int) and bool(
                flags
                & (
                    os.O_WRONLY
                    | os.O_RDWR
                    | os.O_CREAT
                    | os.O_TRUNC
                    | os.O_APPEND
                )
            )
            if (mutating_mode or mutating_flags) and self._under_source(args[0]):
                self.reader_source_mutations += 1
            return
        if event == "os.mkdir" and args:
            directory_fd = args[2] if len(args) >= 3 else None
            if self._under_source(args[0], directory_fd):
                self.reader_source_mutations += 1
            return
        if event in {"os.remove", "os.rmdir", "os.unlink"} and args:
            directory_fd = args[1] if len(args) >= 2 else None
            if self._under_source(args[0], directory_fd):
                self.reader_source_mutations += 1
            return
        if event in {"os.rename", "os.replace"} and len(args) >= 2:
            source_fd = args[2] if len(args) >= 3 else None
            destination_fd = args[3] if len(args) >= 4 else None
            if self._under_source(args[0], source_fd) or self._under_source(
                args[1], destination_fd
            ):
                self.reader_source_mutations += 1

    def audited_open(
        self,
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if (
            self.active
            and getattr(self.owner, "value", "reader") == "reader"
            and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            and self._under_source(path, dir_fd)
        ):
            self.reader_source_mutations += 1
        if dir_fd is None:
            return self._original_open(path, flags, mode)
        return self._original_open(path, flags, mode, dir_fd=dir_fd)

    def audited_clone(
        self,
        source_fd: int,
        destination_dir_fd: int,
        destination_name: str,
        *,
        deadline_check: Callable[[], None] | None = None,
    ) -> int:
        self.real_clone_calls += 1
        try:
            import fcntl

            raw = fcntl.fcntl(destination_dir_fd, getattr(fcntl, "F_GETPATH", 50), bytes(1_024))
            destination = os.fsdecode(raw.split(b"\0", 1)[0])
        except (ImportError, OSError, ValueError):
            raise ProofFailure("cannot bind clone destination")
        if any(is_within(destination, root) for root in self.source_roots):
            self.clone_destinations_under_source += 1
        source_clone_id = self._original_clone(
            source_fd,
            destination_dir_fd,
            destination_name,
            deadline_check=deadline_check,
        )
        if self.swap_next_clone_destination:
            self.swap_next_clone_destination = False
            destination_path = os.path.join(destination, destination_name)
            with self.as_owner("fixture"):
                os.unlink(destination_path)
                replacement = self._original_open(
                    destination_path,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    offset = 0
                    source_size = os.fstat(source_fd).st_size
                    while offset < source_size:
                        block = os.pread(source_fd, min(64 * 1024, source_size - offset), offset)
                        if not block:
                            raise ProofFailure("clone swap source copy ended early")
                        view = memoryview(block)
                        while view:
                            written = os.write(replacement, view)
                            if written <= 0:
                                raise ProofFailure("clone swap replacement write failed")
                            view = view[written:]
                        offset += len(block)
                    os.fsync(replacement)
                finally:
                    os.close(replacement)
                crafted = sqlite3.connect(destination_path)
                try:
                    changed = crafted.execute(
                        "UPDATE records SET value='forged' WHERE id=1"
                    ).rowcount
                    if changed != 1:
                        raise ProofFailure("clone swap replacement row missing")
                    crafted.commit()
                    checkpoint = crafted.execute(
                        "PRAGMA wal_checkpoint(TRUNCATE)"
                    ).fetchone()
                    if checkpoint is None or checkpoint[0] != 0:
                        raise ProofFailure("clone swap replacement checkpoint failed")
                    if crafted.execute("PRAGMA integrity_check(1)").fetchone() != (
                        "ok",
                    ):
                        raise ProofFailure("clone swap replacement integrity failed")
                finally:
                    crafted.close()
                for suffix in ("-wal", "-shm", "-journal"):
                    Path(destination_path + suffix).unlink(missing_ok=True)
                if os.stat(destination_path, follow_symlinks=False).st_size != source_size:
                    raise ProofFailure("clone swap replacement size changed")
            self.clone_destination_swaps += 1
        return source_clone_id

    def audited_unlink_volume_inode(self, descriptor: int, *, directory: bool = False) -> None:
        current = self._descriptor_path(descriptor)
        if current is None:
            raise ProofFailure("cannot bind exact private cleanup target")
        if any(is_within(current, root) for root in self.source_roots):
            self.reader_source_mutations += 1
        self._original_unlink_volume_inode(descriptor, directory=directory)
        self.exact_private_unlinks += 1


def _assert_runtime_capability() -> tuple[bool, bool, bool]:
    if sys.platform != "darwin":
        raise ProofFailure("Darwin required")
    unique_unlink = unique_unlink_supported()
    if not unique_unlink:
        raise ProofFailure("unlinkat(AT_UNIQUE) required")
    with tempfile.TemporaryDirectory(prefix="issue263-proof-capability-") as temporary:
        root = Path(temporary)
        source_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        scratch_fd = os.open(tempfile.gettempdir(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            source_apfs = is_apfs_fd(source_fd)
            scratch_apfs = is_apfs_fd(scratch_fd)
            same_volume = os.fstat(source_fd).st_dev == os.fstat(scratch_fd).st_dev
        finally:
            os.close(scratch_fd)
            os.close(source_fd)
    if not source_apfs or not scratch_apfs or not same_volume:
        raise ProofFailure("same-volume APFS required")
    return source_apfs and scratch_apfs, same_volume, unique_unlink


def _run_success(
    fixture: _Fixture,
    audit: _MutationAudit,
    *,
    stage: str | None = None,
    action: str | None = None,
    private_path_swap: bool = False,
) -> tuple[int, int]:
    scratch_before = _scratch_entries()
    fds_before = _fd_count()
    fired = False
    private_swap_fired = False
    saved_scratch: Path | None = None
    replacement_scratch: Path | None = None
    real_connect = sqlite3.connect

    def restore_private_directory() -> None:
        if replacement_scratch is not None and replacement_scratch.exists():
            for child in replacement_scratch.iterdir():
                child.unlink()
            replacement_scratch.rmdir()
        if saved_scratch is not None and saved_scratch.exists():
            if replacement_scratch is None:
                raise ProofFailure("private scratch restore target missing")
            saved_scratch.rename(replacement_scratch)

    def hook(current: str, _attempt: int, _source: str) -> None:
        nonlocal fired
        if current == stage and action is not None and not fired:
            fired = True
            fixture.writer.action(action)

    def swapped_connect(
        database_arg: str, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        nonlocal private_swap_fired, saved_scratch, replacement_scratch
        created = _scratch_entries() - scratch_before
        if len(created) != 1:
            raise ProofFailure("cannot identify private swap scratch")
        replacement_scratch = Path(tempfile.gettempdir()) / next(iter(created))
        token = replacement_scratch.name.removeprefix("portable-resume-cow-")
        saved_scratch = replacement_scratch.with_name(
            "issue263-proof-saved-scratch-" + token
        )
        replacement_scratch.rename(saved_scratch)
        replacement_scratch.mkdir(mode=0o700)
        with audit.as_owner("fixture"):
            replacement = real_connect(replacement_scratch / "snapshot.sqlite")
            try:
                replacement.execute(
                    "CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                )
                replacement.execute("INSERT INTO records VALUES (1, 'attacker')")
                replacement.commit()
            finally:
                replacement.close()
        try:
            connection = cast(Callable[..., sqlite3.Connection], real_connect)(
                database_arg, *args, **kwargs
            )
            private_swap_fired = True
            return connection
        finally:
            with audit.as_owner("fixture"):
                restore_private_directory()

    audit.source_roots.add(str(fixture.root.resolve()))
    audit.owner.value = "reader"
    audit.active = True
    if private_path_swap:
        setattr(cow_module.sqlite3, "connect", swapped_connect)
    try:
        with private_sqlite_connection_live_wal_cow(
            fixture.database,
            root=fixture.root,
            attempts=1,
            hook=hook if stage is not None else None,
            provider="opencode-sqlite-v1",
        ) as connection:
            if connection.execute("PRAGMA integrity_check(1)").fetchone() != ("ok",):
                raise ProofFailure("private integrity failed")
            if connection.execute("SELECT value FROM records WHERE id=1").fetchone() != ("anchor",):
                raise ProofFailure("anchor commit missing")
            private_database = Path(connection.execute("PRAGMA database_list").fetchone()[2])
            if is_within(private_database, fixture.root):
                raise ProofFailure("private SQLite opened below source root")
            if not str(private_database).startswith("/dev/fd/"):
                raise ProofFailure("private SQLite did not use a descriptor URI")
    finally:
        setattr(cow_module.sqlite3, "connect", real_connect)
        audit.active = False
        audit.owner.value = "fixture"
        restore_private_directory()
    if action is not None and not fired:
        raise ProofFailure("success hook did not run")
    if private_path_swap and not private_swap_fired:
        raise ProofFailure("private pathname swap hook did not run")
    if _scratch_entries() != scratch_before:
        raise ProofFailure("private scratch leak")
    if _fd_count() != fds_before:
        raise ProofFailure("descriptor leak")
    return fixture.database.stat().st_size, Path(str(fixture.database) + "-wal").stat().st_size


def _mutate_rejection(
    fixture: _Fixture,
    scenario: str,
    audit: _MutationAudit,
) -> tuple[str, Callable[[], None]]:
    wal = Path(str(fixture.database) + "-wal")
    cleanup: Callable[[], None] = _noop
    if scenario == "restart_reset":
        fixture.writer.action("reset")
    elif scenario == "truncate_reset":
        descriptor = os.open(wal, os.O_RDWR | os.O_NOFOLLOW)
        try:
            os.ftruncate(descriptor, 32)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    elif scenario == "wal_replace":
        saved = wal.with_name("source.sqlite-wal.saved")
        data = wal.read_bytes()
        wal.rename(saved)
        wal.write_bytes(data)

        def restore() -> None:
            if wal.exists():
                wal.unlink()
            if saved.exists():
                saved.rename(wal)

        cleanup = restore
    elif scenario == "header_salt_change":
        data = wal.read_bytes()
        descriptor = os.open(wal, os.O_RDWR | os.O_NOFOLLOW)
        try:
            os.pwrite(descriptor, bytes([data[16] ^ 1]), 16)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    elif scenario == "accepted_prefix_mutation":
        data = wal.read_bytes()
        if len(data) <= 56:
            raise ProofFailure("WAL prefix too short")
        descriptor = os.open(wal, os.O_RDWR | os.O_NOFOLLOW)
        try:
            os.pwrite(descriptor, bytes([data[56] ^ 1]), 56)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    elif scenario == "source_pathname_replacement":
        saved = fixture.database.with_name("source.sqlite.saved")
        decoy = fixture.database.with_name("source.sqlite.decoy")
        connection = sqlite3.connect(decoy)
        connection.execute("CREATE TABLE decoy(value TEXT)")
        connection.commit()
        connection.close()
        fixture.database.rename(saved)
        decoy.rename(fixture.database)

        def restore() -> None:
            if fixture.database.exists():
                fixture.database.rename(decoy)
            if saved.exists():
                saved.rename(fixture.database)
            decoy.unlink(missing_ok=True)

        cleanup = restore
    else:
        raise ProofFailure("unknown rejection scenario")
    return "E_SOURCE_BUSY", cleanup


def _run_rejection(fixture: _Fixture, scenario: str, audit: _MutationAudit) -> None:
    stage = {
        "restart_reset": "after-clone",
        "truncate_reset": "after-wal-prefix",
        "wal_replace": "after-wal-copy",
        "header_salt_change": "after-clone",
        "accepted_prefix_mutation": "after-wal-copy",
        "source_pathname_replacement": "after-family-pin",
    }.get(scenario)
    if scenario != "clone_destination_swap" and stage is None:
        raise ProofFailure("unknown rejection scenario")
    scratch_before = _scratch_entries()
    fds_before = _fd_count()
    fired = False
    cleanup: Callable[[], None] = _noop
    clone_swaps_before = audit.clone_destination_swaps

    def hook(current: str, _attempt: int, _source: str) -> None:
        nonlocal fired, cleanup
        if stage is not None and current == stage and not fired:
            fired = True
            with audit.as_owner("fixture"):
                _expected, cleanup = _mutate_rejection(fixture, scenario, audit)

    audit.source_roots.add(str(fixture.root.resolve()))
    audit.owner.value = "reader"
    audit.active = True
    if scenario == "clone_destination_swap":
        audit.swap_next_clone_destination = True
    try:
        try:
            with private_sqlite_connection_live_wal_cow(
                fixture.database,
                root=fixture.root,
                attempts=1,
                hook=hook,
                provider="opencode-sqlite-v1",
            ):
                raise ProofFailure("forced rejection yielded a connection")
        except DiagnosticError as error:
            expected_code = (
                "E_INVARIANT" if scenario == "clone_destination_swap" else "E_SOURCE_BUSY"
            )
            expected_attempts = None if scenario == "clone_destination_swap" else 1
            if error.code != expected_code or error.attempts != expected_attempts:
                raise ProofFailure(
                    f"forced rejection {scenario} returned {error.code} "
                    f"with attempts={error.attempts!r}"
                ) from error
    finally:
        audit.swap_next_clone_destination = False
        audit.active = False
        audit.owner.value = "fixture"
        cleanup()
    if scenario == "clone_destination_swap":
        fired = audit.clone_destination_swaps == clone_swaps_before + 1
    if not fired:
        raise ProofFailure("rejection hook did not run")
    if _scratch_entries() != scratch_before:
        raise ProofFailure("rejection scratch leak")
    if _fd_count() != fds_before:
        raise ProofFailure("rejection descriptor leak")


def _write_output(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    serialized = (canonical + "\n").encode("ascii")
    path.write_bytes(serialized)
    checksum = hashlib.sha256(serialized).hexdigest()
    path.with_name(path.name + ".sha256").write_text(
        f"{checksum}  {path.name}\n",
        encoding="ascii",
    )
    print(canonical)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=MINIMUM_ITERATIONS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.iterations < MINIMUM_ITERATIONS:
        raise ProofFailure("iterations below proof minimum")
    sha = _git("rev-parse", "HEAD")
    expected_sha = os.environ.get("ISSUE263_EXPECTED_SHA")
    if expected_sha and sha != expected_sha:
        raise ProofFailure("proof HEAD does not match expected SHA")
    if _git("status", "--porcelain"):
        raise ProofFailure("proof requires a clean exact HEAD")

    apfs, same_volume, unique_unlink = _assert_runtime_capability()
    audit = _MutationAudit()
    os.open = audit.audited_open  # type: ignore[assignment]
    cow_module.clone_file_from_fd = audit.audited_clone
    cow_module.unlink_volume_inode = audit.audited_unlink_volume_inode
    scratch_baseline = _scratch_entries()
    global_fds = _fd_count()
    max_main = 0
    max_wal = 0
    integrity_successes = 0
    cleanup_count = 0
    try:
        with _Fixture(audit.owner) as fixture:
            before = _source_state(fixture.root, fixture.database)
            main_size, wal_size = _run_success(fixture, audit)
            after = _source_state(fixture.root, fixture.database)
            if after != before:
                raise ProofFailure("quiescent source changed")
            integrity_successes += 1
            cleanup_count += 1
            max_main = max(max_main, main_size)
            max_wal = max(max_wal, wal_size)

            for _ in range(CONTINUOUS_SUCCESSES):
                main_size, wal_size = _run_success(
                    fixture,
                    audit,
                    stage="after-wal-prefix",
                    action="commit",
                )
                integrity_successes += 1
                cleanup_count += 1
                max_main = max(max_main, main_size)
                max_wal = max(max_wal, wal_size)

            for _ in range(CHECKPOINT_BEFORE_SUCCESSES):
                fixture.writer.action("commit")
                main_size, wal_size = _run_success(
                    fixture,
                    audit,
                    stage="after-family-pin",
                    action="checkpoint",
                )
                integrity_successes += 1
                cleanup_count += 1
                max_main = max(max_main, main_size)
                max_wal = max(max_wal, wal_size)

            for _ in range(CHECKPOINT_AFTER_SUCCESSES):
                fixture.writer.action("commit")
                main_size, wal_size = _run_success(
                    fixture,
                    audit,
                    stage="after-clone",
                    action="checkpoint",
                )
                integrity_successes += 1
                cleanup_count += 1
                max_main = max(max_main, main_size)
                max_wal = max(max_wal, wal_size)

            for _ in range(PRIVATE_PATH_SWAP_SUCCESSES):
                main_size, wal_size = _run_success(
                    fixture,
                    audit,
                    private_path_swap=True,
                )
                integrity_successes += 1
                cleanup_count += 1
                max_main = max(max_main, main_size)
                max_wal = max(max_wal, wal_size)

        rejection_counts: dict[str, int] = {}
        for scenario in REJECTION_SCENARIOS:
            count = 0
            for _ in range(REJECTIONS_PER_SCENARIO):
                with _Fixture(audit.owner) as fixture:
                    _run_rejection(fixture, scenario, audit)
                count += 1
                cleanup_count += 1
            rejection_counts[scenario] = count
    finally:
        os.open = audit._original_open  # type: ignore[assignment]
        cow_module.clone_file_from_fd = audit._original_clone
        cow_module.unlink_volume_inode = audit._original_unlink_volume_inode

    if audit.reader_source_mutations:
        raise ProofFailure("reader-owned source mutation observed")
    if audit.reader_source_sqlite_connects:
        raise ProofFailure("reader SQLite connection targeted source")
    if audit.clone_destinations_under_source:
        raise ProofFailure("clone destination entered source root")
    if audit.real_clone_calls < cleanup_count:
        raise ProofFailure("real clone count below exercised snapshots")
    if audit.reader_descriptor_bound_sqlite_connects != integrity_successes:
        raise ProofFailure("descriptor-bound SQLite open count mismatch")
    if audit.exact_private_unlinks < cleanup_count * 2:
        raise ProofFailure("exact private cleanup count below exercised snapshots")
    if _scratch_entries() != scratch_baseline:
        raise ProofFailure("global scratch leak")
    if _fd_count() != global_fds:
        raise ProofFailure("global descriptor leak")

    run_url = None
    if os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_RUN_ID"):
        run_url = (
            f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        )
    evidence: dict[str, object] = {
        "schema": PROOF_SCHEMA,
        "commit_sha": sha,
        "actions_run": run_url,
        "iterations_requested": args.iterations,
        "platform": {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "backend": {
            "name": "darwin-apfs-fclonefileat",
            "clone_nofollow": CLONE_NOFOLLOW,
            "clone_noownercopy": CLONE_NOOWNERCOPY,
            "apfs": apfs,
            "same_volume": same_volume,
            "real_clone_calls": audit.real_clone_calls,
            "descriptor_fd_uri": True,
            "clone_data_id_bound": True,
            "clone_destination_swap_rejected": True,
            "private_main_unlinked_before_materialization": True,
            "private_immutable": True,
            "wal_materialized": True,
            "unique_unlink": unique_unlink,
        },
        "successes": {
            "quiescent_immutability": 1,
            "continuous_append": CONTINUOUS_SUCCESSES,
            "checkpoint_before_clone": CHECKPOINT_BEFORE_SUCCESSES,
            "checkpoint_after_clone": CHECKPOINT_AFTER_SUCCESSES,
            "private_path_swap": PRIVATE_PATH_SWAP_SUCCESSES,
            "integrity_ok": integrity_successes,
            "anchor_visible": integrity_successes,
            "materialized_committed_state": integrity_successes,
            "descriptor_bound_open": audit.reader_descriptor_bound_sqlite_connects,
        },
        "rejections": rejection_counts,
        "safety": {
            "reader_source_mutations": audit.reader_source_mutations,
            "reader_source_sqlite_connects": audit.reader_source_sqlite_connects,
            "clone_destinations_under_source": audit.clone_destinations_under_source,
            "scratch_leaks": 0,
            "fd_leaks": 0,
            "cleanup_count": cleanup_count,
            "exact_private_unlinks": audit.exact_private_unlinks,
        },
        "bounds_observed": {
            "max_main_logical_bytes": max_main,
            "max_source_wal_bytes": max_wal,
        },
    }
    _write_output(args.output, evidence)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as error:
        print(
            json.dumps(
                {
                    "schema": PROOF_SCHEMA,
                    "ok": False,
                    "reason": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
