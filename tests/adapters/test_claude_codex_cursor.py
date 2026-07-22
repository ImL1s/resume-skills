from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from portable_resume.adapters import claude, codex, codex_sqlite, cursor
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from portable_resume.reader import run
from tests.helpers.core import tree_snapshot
from tests.helpers.fixture_manifest import validate_fixture_tree


def stamp(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def write_jsonl(path: Path, records: list[object], *, trailing: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(json.dumps(record, separators=(",", ":")).encode() + b"\n" for record in records)
    path.write_bytes(payload + trailing)


class AdapterFixtureManifestTests(unittest.TestCase):
    def test_all_27_lane_manifests_are_strict_synthetic(self) -> None:
        values = [
            value
            for value in validate_fixture_tree("tests/fixtures")
            if value.source in {"claude", "codex", "cursor"}
        ]
        self.assertEqual(len(values), 27)
        self.assertEqual(sum(value.source == "claude" for value in values), 7)
        self.assertEqual(sum(value.source == "codex" for value in values), 12)
        self.assertEqual(sum(value.source == "cursor" for value in values), 8)
        self.assertTrue(all(value.synthetic for value in values))


class ClaudeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()

    def query(self, ref: str | None = None, cwd: Path | None = None) -> Query:
        return Query("claude", ref=ref, cwd=str(cwd or self.cwd), source_root=str(self.root))

    def session(self, records: list[dict], *, identifier: str | None = None, project: str = "project", trailing: bytes = b"") -> tuple[str, Path]:
        identifier = identifier or str(uuid.uuid4())
        path = self.root / "projects" / project / f"{identifier}.jsonl"
        write_jsonl(path, records, trailing=trailing)
        return identifier, path

    def turn(self, kind: str, identifier: str, parent: str | None, content: object, at: int, **extra: object) -> dict:
        return {
            "type": kind,
            "uuid": identifier,
            "parentUuid": parent,
            "sessionId": extra.pop("sessionId", None),
            "cwd": str(self.cwd),
            "timestamp": stamp(at),
            "message": {"role": kind, "content": content},
            **extra,
        }

    def test_s_cla_01_02_parent_chain_and_fork_choose_one_lineage(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, old_id, fork_id = (str(uuid.uuid4()) for _ in range(3))
        records = [
            self.turn("user", user_id, None, "start", 0, sessionId=session_id),
            self.turn("assistant", old_id, user_id, "old branch", 1, sessionId=session_id),
            self.turn("assistant", fork_id, user_id, "selected branch", 2, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        before = tree_snapshot(self.root)
        values = claude.ADAPTER.list(self.query(), ReadBudget())
        session = claude.ADAPTER.show(ResolvedRef.from_summary(values[0]), self.query(), ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["start", "selected branch"])
        self.assertNotIn("old branch", json.dumps(session.to_dict()))
        self.assertEqual(path, Path(session.source_path))
        self.assertEqual(before, tree_snapshot(self.root))

    def test_s_cla_03_compaction_meta_and_system_are_omitted(self) -> None:
        session_id = str(uuid.uuid4())
        before, boundary, after, answer = (str(uuid.uuid4()) for _ in range(4))
        records = [
            self.turn("user", before, None, "stale request", -4, sessionId=session_id),
            {
                "type": "system",
                "subtype": "compact_boundary",
                "uuid": boundary,
                "parentUuid": before,
                "sessionId": session_id,
                "cwd": str(self.cwd),
                "timestamp": stamp(-3),
                "message": {"role": "system", "content": "private compact state"},
            },
            self.turn("user", after, boundary, "fresh request", -2, sessionId=session_id),
            self.turn("assistant", answer, after, "fresh answer", -1, sessionId=session_id),
            {"type": "meta", "summary": "metadata only", "customTitle": "Synthetic title"},
        ]
        self.session(records, identifier=session_id)
        summary = claude.ADAPTER.list(self.query(), ReadBudget())[0]
        session = claude.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["fresh request", "fresh answer"])
        self.assertNotIn("private compact state", json.dumps(session.to_dict()))

    def test_s_cla_04_thinking_signature_and_tool_noise_are_filtered(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, assistant_id, tool_id = (str(uuid.uuid4()) for _ in range(3))
        records = [
            self.turn("user", user_id, None, "question", -3, sessionId=session_id),
            self.turn(
                "assistant",
                assistant_id,
                user_id,
                [
                    {"type": "thinking", "thinking": "secret reasoning", "signature": "secret-signature"},
                    {"type": "text", "text": "answer"},
                ],
                -2,
                sessionId=session_id,
            ),
            self.turn(
                "user",
                tool_id,
                assistant_id,
                [{"type": "tool_result", "content": "tool output", "tool_name": "Read"}],
                -1,
                sessionId=session_id,
            ),
        ]
        self.session(records, identifier=session_id)
        session = claude.ADAPTER.show(
            ResolvedRef.from_summary(claude.ADAPTER.list(self.query(), ReadBudget())[0]),
            self.query(),
            ReadBudget(),
        )
        serialized = json.dumps(session.to_dict())
        self.assertEqual([turn.role for turn in session.turns], ["user", "assistant", "tool"])
        self.assertNotIn("secret reasoning", serialized)
        self.assertNotIn("secret-signature", serialized)

    def test_s_cla_05_broken_chain_warns_without_inventing_parent(self) -> None:
        session_id = str(uuid.uuid4())
        record = self.turn(
            "user", str(uuid.uuid4()), str(uuid.uuid4()), "surviving child", -1, sessionId=session_id
        )
        self.session([record], identifier=session_id)
        summary = claude.ADAPTER.list(self.query(), ReadBudget())[0]
        session = claude.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        self.assertIn("W_BROKEN_CHAIN", session.warnings)
        self.assertEqual([turn.content for turn in session.turns], ["surviving child"])

    def test_s_cla_06_partial_tail_warns_but_interior_corruption_fails(self) -> None:
        session_id = str(uuid.uuid4())
        record = self.turn("user", str(uuid.uuid4()), None, "valid", -1, sessionId=session_id)
        self.session([record], identifier=session_id, trailing=b'{"type":')
        summary = claude.ADAPTER.list(self.query(), ReadBudget())[0]
        session = claude.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        self.assertIn("W_PARTIAL_TAIL", session.warnings)

        other_id = str(uuid.uuid4())
        _, path = self.session([record], identifier=other_id, project="corrupt")
        path.write_bytes(path.read_bytes() + b"{broken}\n" + path.read_bytes())
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_s_cla_07_slug_collision_uses_canonical_recorded_cwd(self) -> None:
        wanted = str(uuid.uuid4())
        other = str(uuid.uuid4())
        self.session(
            [self.turn("user", str(uuid.uuid4()), None, "wanted", -1, sessionId=wanted)],
            identifier=wanted,
            project="same-slug-a",
        )
        wrong_cwd = self.root / "other"
        wrong_cwd.mkdir()
        record = self.turn("user", str(uuid.uuid4()), None, "wrong", -1, sessionId=other)
        record["cwd"] = str(wrong_cwd)
        self.session([record], identifier=other, project="same-slug-b")
        values = claude.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual([value.session_id for value in values], [wanted])

    def test_common_selection_ambiguity_path_injection_bounds_and_busy(self) -> None:
        for index in range(2):
            identifier = str(uuid.uuid4())
            record = self.turn("user", str(uuid.uuid4()), None, "same needle", -index, sessionId=identifier)
            self.session([record], identifier=identifier, project=f"p{index}")
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(
            ["claude", "show", "needle", "--cwd", str(self.cwd), "--source-root", str(self.root), "--json"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "E_AMBIGUOUS")
        marker = self.root / "PWNED"
        stdout, stderr = io.StringIO(), io.StringIO()
        run(
            [
                "claude",
                "show",
                f"$(touch {marker})",
                "--cwd",
                str(self.cwd),
                "--source-root",
                str(self.root),
                "--json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertFalse(marker.exists())
        with self.assertRaises(DiagnosticError) as bounded:
            claude.ADAPTER.list(self.query(), ReadBudget(Bounds(scanned_records=1)))
        self.assertEqual(bounded.exception.code, "E_LIMIT_EXCEEDED")
        with mock.patch.object(claude, "stable_read_bytes", side_effect=DiagnosticError.source_busy()):
            with self.assertRaises(DiagnosticError) as busy:
                claude.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(busy.exception.code, "E_SOURCE_BUSY")


class CodexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()

    def query(self, ref: str | None = None) -> Query:
        return Query("codex", ref=ref, cwd=str(self.cwd), source_root=str(self.root))

    def rollout(
        self,
        identifier: str | None = None,
        *,
        archived: bool = False,
        records: list[dict] | None = None,
        suffix: str = ".jsonl",
    ) -> tuple[str, Path]:
        identifier = identifier or str(uuid.uuid4())
        base = self.root / ("archived_sessions" if archived else "sessions") / "2026" / "07" / "20"
        path = base / f"rollout-2026-07-20T00-00-00-{identifier}.jsonl"
        if suffix == ".jsonl.zst":
            path = Path(str(path) + ".zst")
        values = records or [
            {"type": "session_meta", "timestamp": stamp(-3), "payload": {"id": identifier, "cwd": str(self.cwd), "source": "cli", "git": {"branch": "main"}}},
            {"type": "response_item", "timestamp": stamp(-2), "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Build feature"}]}},
            {"type": "response_item", "timestamp": stamp(-1), "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Implemented"}]}},
        ]
        write_jsonl(path, values)
        return identifier, path

    def database(self, generation: int, rows: list[tuple], *, unknown: bool = False) -> Path:
        path = self.root / f"state_{generation}.sqlite"
        connection = sqlite3.connect(path)
        if unknown:
            connection.execute("CREATE TABLE unknown(value TEXT)")
        else:
            connection.executescript(
                """
                CREATE TABLE threads (
                    id TEXT,
                    rollout_path TEXT,
                    updated_at_ms INTEGER,
                    source TEXT,
                    cwd TEXT,
                    title TEXT,
                    first_user_message TEXT,
                    archived INTEGER,
                    git_branch TEXT
                );
                """
            )
            connection.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)", rows)
        connection.commit()
        connection.close()
        return path

    def db_row(self, identifier: str, path: Path, *, archived: int = 0, source: str = "cli", title: str = "DB title") -> tuple:
        return (
            identifier,
            str(path.relative_to(self.root)),
            int(datetime.now(timezone.utc).timestamp() * 1000),
            source,
            str(self.cwd),
            title,
            "First prompt",
            archived,
            "feature/db",
        )

    def test_s_cod_01_02_highest_supported_db_and_cli_vscode_rows(self) -> None:
        first, first_path = self.rollout()
        second, second_path = self.rollout()
        self.database(10, [], unknown=True)
        self.database(9, [self.db_row(first, first_path), self.db_row(second, second_path, source="vscode")])
        before = tree_snapshot(self.root)
        values = codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual({value.session_id for value in values}, {first, second})
        self.assertTrue(all(value.provider == codex.SQLITE_FORMAT for value in values))
        session = codex.ADAPTER.show(ResolvedRef.from_summary(values[0]), self.query(), ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["Build feature", "Implemented"])
        self.assertEqual(before, tree_snapshot(self.root))

    def test_s_cod_03_archive_hidden_by_default_exact_id_selectable(self) -> None:
        active, active_path = self.rollout()
        archived, archived_path = self.rollout(archived=True)
        self.database(9, [self.db_row(active, active_path), self.db_row(archived, archived_path, archived=1)])
        self.assertEqual([item.session_id for item in codex.ADAPTER.list(self.query(), ReadBudget())], [active])
        exact = codex.ADAPTER.list(self.query(archived), ReadBudget())
        self.assertEqual([item.session_id for item in exact], [archived])
        shown = codex.ADAPTER.show(ResolvedRef.from_summary(exact[0]), self.query(archived), ReadBudget())
        self.assertEqual(shown.session_id, archived)

    def test_s_cod_04_05_12_private_sqlite_family_source_immutable(self) -> None:
        identifier, rollout = self.rollout()
        database = self.database(9, [self.db_row(identifier, rollout)])
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("UPDATE threads SET title=title")
        connection.commit()
        before = tree_snapshot(self.root)
        values = codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(values[0].session_id, identifier)
        self.assertEqual(before, tree_snapshot(self.root))
        connection.close()

    def test_busy_snapshot_probe_falls_back_to_query_only_path_used_by_list(self) -> None:
        identifier, rollout = self.rollout()
        database = self.database(9, [self.db_row(identifier, rollout)])
        before = tree_snapshot(self.root)
        with mock.patch.object(
            codex_sqlite.os.path,
            "getsize",
            return_value=codex_sqlite.DEFAULT_BOUNDS.sqlite_snapshot_bytes,
        ), mock.patch.object(
            codex_sqlite,
            "private_sqlite_connection",
            side_effect=DiagnosticError.source_busy(provider=codex.SQLITE_FORMAT),
        ):
            capability = codex.ADAPTER.probe(self.query())
            values = codex.ADAPTER.list(self.query(), ReadBudget())

        self.assertEqual(capability.state, "supported")
        self.assertEqual(capability.format_id, codex.SQLITE_FORMAT)
        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertEqual(before, tree_snapshot(self.root))

    def test_s_cod_06_09_rollout_fallback_omits_reasoning_encrypted_and_control(self) -> None:
        identifier = str(uuid.uuid4())
        records = [
            {"type": "session_meta", "timestamp": stamp(-5), "payload": {"id": identifier, "cwd": str(self.cwd), "source": "cli"}},
            {"type": "turn_context", "timestamp": stamp(-4), "payload": {"developer": "hidden"}},
            {"type": "response_item", "timestamp": stamp(-3), "payload": {"type": "reasoning", "summary": "secret reasoning", "encrypted_content": "cipher"}},
            {"type": "response_item", "timestamp": stamp(-2), "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Visible request"}]}},
            {"type": "response_item", "timestamp": stamp(-1), "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Visible reply"}]}},
        ]
        self.rollout(identifier, records=records)
        summary = codex.ADAPTER.list(self.query(), ReadBudget())[0]
        session = codex.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        serialized = json.dumps(session.to_dict())
        self.assertEqual([turn.content for turn in session.turns], ["Visible request", "Visible reply"])
        self.assertNotIn("secret reasoning", serialized)
        self.assertNotIn("cipher", serialized)
        self.assertNotIn("hidden", serialized)

    def test_s_cod_07_08_zstd_absence_and_malicious_path_degrade_only_provider(self) -> None:
        compressed, _ = self.rollout(suffix=".jsonl.zst")
        marker = self.root / "called"
        fake = self.root / "zstd"
        fake.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        fake.chmod(0o755)
        with mock.patch.object(codex, "TRUSTED_ZSTD_PATHS", ()), mock.patch.dict(os.environ, {"PATH": str(self.root)}):
            capability = codex.ADAPTER.probe(self.query())
            listed_absent = codex.ADAPTER.list(self.query(compressed), ReadBudget())
        self.assertEqual(capability.state, "partial")
        self.assertIn("W_OPTIONAL_ZSTD_UNAVAILABLE", capability.warnings)
        self.assertFalse(marker.exists())
        self.assertEqual(listed_absent, [])
        # When a trusted decoder exists, corrupt/malicious compressed payloads still
        # degrade only this session (empty list), not fail the whole provider list.
        listed_corrupt = codex.ADAPTER.list(self.query(compressed), ReadBudget())
        self.assertEqual(listed_corrupt, [])

    def test_s_cod_08_decoder_uses_fixed_argv_no_shell_timeout_surface(self) -> None:
        with mock.patch.object(codex, "_trusted_zstd", return_value="/trusted/zstd"), mock.patch.object(
            codex.subprocess, "Popen", side_effect=OSError("unavailable")
        ) as launched:
            with self.assertRaises(DiagnosticError) as caught:
                codex._decompress_zstd(b"synthetic")
        self.assertEqual(caught.exception.code, "E_CAPABILITY_UNAVAILABLE")
        args, kwargs = launched.call_args
        self.assertEqual(args[0], ["/trusted/zstd", "-d", "-q", "-c"])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["env"]["PATH"], "")

    def test_s_cod_10_unknown_schema_fails_reader_closed(self) -> None:
        self.database(10, [], unknown=True)
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(
            ["codex", "show", "latest", "--cwd", str(self.cwd), "--source-root", str(self.root), "--json"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 5)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "E_UNSUPPORTED_FORMAT")

    def test_s_cod_11_hot_journal_fails_closed(self) -> None:
        identifier, rollout = self.rollout()
        database = self.database(9, [self.db_row(identifier, rollout)])
        Path(str(database) + "-journal").write_bytes(b"synthetic hot journal")
        with self.assertRaises(DiagnosticError) as caught:
            codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_SQLITE_HOT_JOURNAL")

    def test_common_corrupt_bounds_busy_and_injection(self) -> None:
        identifier, path = self.rollout()
        path.write_bytes(path.read_bytes() + b"{broken}\n")
        with self.assertRaises(DiagnosticError) as corrupt:
            codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(corrupt.exception.code, "E_CORRUPT_RECORD")
        with self.assertRaises(DiagnosticError) as bounded:
            codex.ADAPTER.list(self.query(), ReadBudget(Bounds(scanned_records=1)))
        self.assertEqual(bounded.exception.code, "E_LIMIT_EXCEEDED")
        marker = self.root / "owned"
        stdout, stderr = io.StringIO(), io.StringIO()
        run(
            ["codex", "show", f"$(touch {marker})", "--cwd", str(self.cwd), "--source-root", str(self.root), "--json"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertFalse(marker.exists())
        with mock.patch.object(codex, "stable_read_bytes", side_effect=DiagnosticError.source_busy()):
            with self.assertRaises(DiagnosticError) as busy:
                codex.ADAPTER.list(self.query(identifier), ReadBudget())
        self.assertEqual(busy.exception.code, "E_SOURCE_BUSY")


class CursorAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()

    def query(self, ref: str | None = None) -> Query:
        return Query("cursor", ref=ref, cwd=str(self.cwd), source_root=str(self.root))

    def chat(
        self,
        *,
        identifier: str | None = None,
        archived: bool = False,
        kind: str = "project",
        title: str | None = "Cursor chat",
        links: list[str] | None = None,
        records: dict[str, list[dict]] | None = None,
    ) -> tuple[str, Path]:
        identifier = identifier or str(uuid.uuid4())
        cwd_hash = cursor._cwd_hash(str(self.cwd))
        session = self.root / "chats" / cwd_hash / identifier
        links = links if links is not None else ["transcripts/0001.jsonl"]
        metadata = {
            "format": cursor.CLI_FORMAT,
            "id": identifier,
            "cwd": str(self.cwd),
            "cwd_hash": cwd_hash,
            "title": title,
            "created_at": stamp(-20),
            "updated_at": stamp(30),
            "archived": archived,
            "composer_kind": kind,
            "git_branch": "feature/cursor",
            "transcripts": links,
        }
        session.mkdir(parents=True, exist_ok=True)
        (session / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        records = records or {
            "transcripts/0001.jsonl": [
                {"type": "message", "role": "user", "content": "Cursor request", "timestamp": stamp(-2)},
                {"type": "message", "role": "assistant", "content": "Cursor reply", "timestamp": stamp(-1)},
            ]
        }
        for relative, values in records.items():
            write_jsonl(session / relative, values)
        return identifier, session / "metadata.json"

    def desktop(self, rows: list[tuple], links: list[tuple], blobs: list[tuple], *, unknown: bool = False) -> Path:
        path = self.root / "state.vscdb"
        connection = sqlite3.connect(path)
        if unknown:
            connection.execute("CREATE TABLE ItemTable(key TEXT, value BLOB)")
        else:
            connection.executescript(
                """
                CREATE TABLE cursor_composers (
                    id TEXT,
                    cwd TEXT,
                    cwd_hash TEXT,
                    title TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    archived INTEGER,
                    composer_kind TEXT,
                    git_branch TEXT
                );
                CREATE TABLE cursor_transcript_links (
                    composer_id TEXT,
                    ordinal INTEGER,
                    blob_key TEXT
                );
                CREATE TABLE cursor_blobs (
                    blob_key TEXT,
                    payload_json TEXT
                );
                """
            )
            connection.executemany("INSERT INTO cursor_composers VALUES (?,?,?,?,?,?,?,?,?)", rows)
            connection.executemany("INSERT INTO cursor_transcript_links VALUES (?,?,?)", links)
            connection.executemany("INSERT INTO cursor_blobs VALUES (?,?)", blobs)
        connection.commit()
        connection.close()
        return path

    def desktop_row(self, identifier: str, *, archived: int = 0, kind: str = "project") -> tuple:
        return (
            identifier,
            str(self.cwd),
            cursor._cwd_hash(str(self.cwd)),
            "Desktop chat",
            stamp(-20),
            stamp(20),
            archived,
            kind,
            "main",
        )

    def test_s_cur_01_02_cli_hash_exact_and_links_preserve_order(self) -> None:
        identifier, metadata = self.chat(
            links=["transcripts/0002.jsonl", "transcripts/0001.jsonl"],
            records={
                "transcripts/0002.jsonl": [{"type": "message", "role": "user", "content": "first linked"}],
                "transcripts/0001.jsonl": [{"type": "message", "role": "assistant", "content": "second linked"}],
            },
        )
        before = tree_snapshot(self.root)
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        session = cursor.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        self.assertEqual(summary.session_id, identifier)
        self.assertEqual(Path(summary.source_path), metadata)
        self.assertEqual([turn.content for turn in session.turns], ["first linked", "second linked"])
        self.assertEqual(before, tree_snapshot(self.root))

    def test_s_cur_03_archived_and_subagent_default_excluded_exact_id_allowed(self) -> None:
        active, _ = self.chat()
        archived, _ = self.chat(archived=True)
        subagent, _ = self.chat(kind="subagent")
        self.assertEqual([item.session_id for item in cursor.ADAPTER.list(self.query(), ReadBudget())], [active])
        self.assertEqual([item.session_id for item in cursor.ADAPTER.list(self.query(archived), ReadBudget())], [archived])
        self.assertEqual([item.session_id for item in cursor.ADAPTER.list(self.query(subagent), ReadBudget())], [subagent])

    def test_s_cur_04_desktop_snapshot_and_stable_blob_order(self) -> None:
        identifier = str(uuid.uuid4())
        path = self.desktop(
            [self.desktop_row(identifier)],
            [(identifier, 0, "b0"), (identifier, 1, "b1")],
            [
                ("b0", json.dumps({"type": "message", "role": "user", "content": "desktop request"})),
                ("b1", json.dumps({"type": "message", "role": "assistant", "content": "desktop reply"})),
            ],
        )
        before = tree_snapshot(self.root)
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        session = cursor.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        self.assertEqual(summary.provider, cursor.DESKTOP_FORMAT)
        self.assertEqual(Path(summary.source_path), path)
        self.assertEqual([turn.content for turn in session.turns], ["desktop request", "desktop reply"])
        self.assertEqual(before, tree_snapshot(self.root))

    def test_s_cur_05_missing_cli_and_desktop_blobs_warn_without_fabrication(self) -> None:
        identifier, _ = self.chat(
            records={
                "transcripts/0001.jsonl": [
                    {"type": "message", "role": "user", "content": "visible"},
                    {"type": "message", "role": "assistant", "content_blob": "blobs/missing.txt"},
                ]
            }
        )
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        session = cursor.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(identifier), ReadBudget())
        self.assertIn("W_MISSING_BLOB", session.warnings)
        self.assertEqual([turn.content for turn in session.turns], ["visible"])

        self.root.joinpath("chats").rename(self.root / "chats-hidden")
        desktop_id = str(uuid.uuid4())
        self.desktop([self.desktop_row(desktop_id)], [(desktop_id, 0, "absent")], [])
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        session = cursor.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        self.assertIn("W_MISSING_BLOB", session.warnings)
        self.assertEqual(session.turns, ())

    def test_s_cur_06_stale_index_discovers_only_safe_transcript_and_warns(self) -> None:
        identifier, _ = self.chat(
            links=["transcripts/missing.jsonl"],
            records={"transcripts/actual.jsonl": [{"type": "message", "role": "user", "content": "safe evidence"}]},
        )
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        self.assertIn("W_STALE_INDEX", summary.warnings)
        session = cursor.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(identifier), ReadBudget())
        self.assertIn("W_STALE_INDEX", session.warnings)
        self.assertEqual([turn.content for turn in session.turns], ["safe evidence"])

    def test_s_cur_07_capability_names_parser_not_native_picker_parity(self) -> None:
        self.chat()
        capability = cursor.ADAPTER.probe(self.query())
        self.assertEqual(capability.format_id, cursor.CLI_FORMAT)
        self.assertNotIn("picker", " ".join(capability.evidence).casefold())

    def test_s_cur_08_unknown_and_hot_desktop_fail_closed(self) -> None:
        self.desktop([], [], [], unknown=True)
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(
            ["cursor", "show", "latest", "--cwd", str(self.cwd), "--source-root", str(self.root), "--json"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 5)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "E_UNSUPPORTED_FORMAT")
        (self.root / "state.vscdb").unlink()
        identifier = str(uuid.uuid4())
        path = self.desktop([self.desktop_row(identifier)], [], [])
        Path(str(path) + "-journal").write_bytes(b"hot")
        with self.assertRaises(DiagnosticError) as caught:
            cursor.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_SQLITE_HOT_JOURNAL")

    def test_common_cwd_signature_path_traversal_bounds_busy_and_injection(self) -> None:
        identifier, metadata = self.chat()
        value = json.loads(metadata.read_text())
        value["cwd_hash"] = "0" * 32
        metadata.write_text(json.dumps(value))
        self.assertEqual(cursor.ADAPTER.probe(self.query()).state, "unsupported")

        value["cwd_hash"] = cursor._cwd_hash(str(self.cwd))
        value["transcripts"] = ["../outside.jsonl"]
        metadata.write_text(json.dumps(value))
        with self.assertRaises(DiagnosticError) as unsafe:
            cursor.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(unsafe.exception.code, "E_UNSAFE_PATH")

        value["transcripts"] = ["transcripts/0001.jsonl"]
        metadata.write_text(json.dumps(value))
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        with self.assertRaises(DiagnosticError) as bounded:
            cursor.ADAPTER.show(
                ResolvedRef.from_summary(summary), self.query(), ReadBudget(Bounds(scanned_records=1))
            )
        self.assertEqual(bounded.exception.code, "E_LIMIT_EXCEEDED")

        marker = self.root / "owned"
        stdout, stderr = io.StringIO(), io.StringIO()
        run(
            ["cursor", "show", f";touch {marker}", "--cwd", str(self.cwd), "--source-root", str(self.root), "--json"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertFalse(marker.exists())
        with mock.patch.object(cursor, "stable_read_bytes", side_effect=DiagnosticError.source_busy()):
            with self.assertRaises(DiagnosticError) as busy:
                cursor.ADAPTER.list(self.query(identifier), ReadBudget())
        self.assertEqual(busy.exception.code, "E_SOURCE_BUSY")


if __name__ == "__main__":
    unittest.main()
