"""P0 regressions for Cursor large-session bounds (#11 step 1: CLI JSONL)."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from portable_resume.adapters import cursor
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query


def _stamp(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class CursorLargeSessionCliJsonlTests(unittest.TestCase):
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
        title: str | None = "Cursor chat",
        records: dict[str, list[dict]] | None = None,
        raw_transcript: bytes | None = None,
    ) -> tuple[str, Path]:
        identifier = identifier or str(uuid.uuid4())
        cwd_hash = cursor._cwd_hash(str(self.cwd))
        session = self.root / "chats" / cwd_hash / identifier
        links = ["transcripts/0001.jsonl"]
        metadata = {
            "format": cursor.CLI_FORMAT,
            "id": identifier,
            "cwd": str(self.cwd),
            "cwd_hash": cwd_hash,
            "title": title,
            "created_at": _stamp(-20),
            "updated_at": _stamp(30),
            "archived": False,
            "composer_kind": "project",
            "git_branch": "feature/cursor",
            "transcripts": links,
        }
        session.mkdir(parents=True, exist_ok=True)
        (session / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        transcript = session / "transcripts" / "0001.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        if raw_transcript is not None:
            transcript.write_bytes(raw_transcript)
        else:
            records = records or {
                "transcripts/0001.jsonl": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": "Cursor request",
                        "timestamp": _stamp(-2),
                    },
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": "Cursor reply",
                        "timestamp": _stamp(-1),
                    },
                ]
            }
            for relative, values in records.items():
                path = session / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    b"".join(
                        json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n" for record in values
                    )
                )
        return identifier, session / "metadata.json"

    def test_show_file_between_record_and_source_read_bytes_succeeds(self) -> None:
        """Whole-file size may exceed record_bytes when each line is small."""
        user = {
            "type": "message",
            "role": "user",
            "content": "hello large session",
            "timestamp": _stamp(-2),
        }
        assistant = {
            "type": "message",
            "role": "assistant",
            "content": "reply large session",
            "timestamp": _stamp(-1),
        }
        # Filler is a valid non-message transcript type so turns stay few.
        filler_line = (
            json.dumps(
                {"type": "system", "note": "x" * 400, "synthetic": True},
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        header = (
            json.dumps(user, separators=(",", ":")).encode("utf-8")
            + b"\n"
            + json.dumps(assistant, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        target = 17 * 1024 * 1024
        repeats = max(1, (target - len(header)) // len(filler_line) + 1)
        payload = header + filler_line * repeats
        self.assertGreater(len(payload), 16 * 1024 * 1024)
        self.assertLess(len(payload), 256 * 1024 * 1024)

        identifier, _ = self.chat(raw_transcript=payload)
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        session = cursor.ADAPTER.show(
            ResolvedRef.from_summary(summary),
            self.query(identifier),
            ReadBudget(),
        )
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["hello large session", "reply large session"],
        )

    def test_show_over_transcript_records_raises_limit_exceeded(self) -> None:
        """Line count above transcript_records fails closed — no partial Session."""
        lines = [
            {
                "type": "message",
                "role": "user",
                "content": f"line-{index}",
                "timestamp": _stamp(index),
            }
            for index in range(5)
        ]
        identifier, _ = self.chat(
            records={"transcripts/0001.jsonl": lines},
        )
        summary = cursor.ADAPTER.list(self.query(), ReadBudget())[0]
        tight = Bounds(transcript_records=3, scanned_records=100)
        budget = ReadBudget(limits=tight)
        with self.assertRaises(DiagnosticError) as caught:
            cursor.ADAPTER.show(
                ResolvedRef.from_summary(summary),
                self.query(identifier),
                budget,
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_list_with_metadata_title_does_not_open_transcript(self) -> None:
        """List title comes from metadata; transcript must not be full-parsed."""
        identifier, _ = self.chat(title="Metadata title only")
        with mock.patch.object(
            cursor,
            "_parse_transcript",
            side_effect=AssertionError("list must not full-parse transcript when title is set"),
        ):
            summaries = cursor.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, identifier)
        self.assertEqual(summaries[0].title, "Metadata title only")




class CursorLargeSessionLiveCliTests(unittest.TestCase):
    """Live CLI store.db silent truncation (issue #11 step 2)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / ".cursor"
        self.root.mkdir()
        self.cwd = "/workspace/project"
        h = cursor._cwd_hash(self.cwd)
        self.session_id = str(uuid.uuid4())
        session_dir = self.root / "chats" / h / self.session_id
        session_dir.mkdir(parents=True)
        self.store = session_dir / "store.db"
        conn = __import__("sqlite3").connect(self.store)
        conn.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
        # 5 blobs: with transcript_records=4 must fail closed (LIMIT 5 probe).
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            payload = json.dumps({"role": role, "content": f"blob-{i}"}).encode("utf-8")
            conn.execute("INSERT INTO blobs(id, data) VALUES (?, ?)", (f"b{i}", payload))
        conn.commit()
        conn.close()
        (session_dir / "meta.json").write_text(
            json.dumps(
                {
                    "cwd": self.cwd,
                    "title": "live-large",
                    "createdAtMs": 1_700_000_000_000,
                    "updatedAtMs": 1_700_000_100_000,
                }
            ),
            encoding="utf-8",
        )

    def test_show_more_blobs_than_transcript_records_fails_closed(self) -> None:
        query = Query(source="cursor", cwd=self.cwd, source_root=str(self.root), within_min=0)
        summaries = cursor.ADAPTER.list(query, ReadBudget())
        hit = next(s for s in summaries if s.session_id == self.session_id)
        tight = ReadBudget(limits=Bounds(transcript_records=4, scanned_records=100))
        with self.assertRaises(DiagnosticError) as caught:
            cursor.ADAPTER.show(ResolvedRef.from_summary(hit), query, tight)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


class CursorLargeSessionDesktopFilterTests(unittest.TestCase):
    """Synthetic Desktop filter-before-LIMIT (issue #11 step 3)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()

    def _desktop(self, rows: list[tuple]) -> Path:
        import sqlite3

        path = self.root / "state.vscdb"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE cursor_composers (
                id TEXT, cwd TEXT, cwd_hash TEXT, title TEXT,
                created_at TEXT, updated_at TEXT, archived INTEGER,
                composer_kind TEXT, git_branch TEXT
            );
            CREATE TABLE cursor_transcript_links (
                composer_id TEXT, ordinal INTEGER, blob_key TEXT
            );
            CREATE TABLE cursor_blobs (blob_key TEXT, payload_json TEXT);
            """
        )
        conn.executemany("INSERT INTO cursor_composers VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()
        return path

    def test_archived_and_subagent_do_not_crowd_out_eligible_parent(self) -> None:
        eligible = str(uuid.uuid4())
        rows = []
        # Enough newer archived/subagent rows to exceed the SQL discovery window
        # (min(scanned_records, listed_sessions*4)+1 ≈ 201) if filters ran after LIMIT.
        noise_ids = []
        for i in range(250):
            sid = str(uuid.uuid4())
            noise_ids.append(sid)
            kind = "subagent" if i % 2 == 0 else "project"
            archived = 0 if kind == "subagent" else 1
            rows.append(
                (
                    sid,
                    str(self.cwd),
                    cursor._cwd_hash(str(self.cwd)),
                    f"noise-{i}",
                    _stamp(-100 + i),
                    _stamp(100 + i),
                    archived,
                    kind,
                    "main",
                )
            )
        # Older eligible project composer — outside an unfiltered crowded window
        rows.append(
            (
                eligible,
                str(self.cwd),
                cursor._cwd_hash(str(self.cwd)),
                "eligible-parent",
                _stamp(-200),
                _stamp(-50),
                0,
                "project",
                "main",
            )
        )
        self._desktop(rows)
        query = Query("cursor", cwd=str(self.cwd), source_root=str(self.root), within_min=0)
        listed = cursor.ADAPTER.list(query, ReadBudget())
        ids = {item.session_id for item in listed}
        self.assertIn(eligible, ids)
        self.assertTrue(ids.isdisjoint(set(noise_ids)))
        # exact archived still reachable
        archived_id = noise_ids[1]  # archived project row (i=1 -> project archived=1)
        exact = cursor.ADAPTER.list(
            Query("cursor", ref=archived_id, cwd=str(self.cwd), source_root=str(self.root), within_min=0),
            ReadBudget(),
        )
        self.assertTrue(any(item.session_id == archived_id for item in exact))


class CursorLargeSessionComposerDataTests(unittest.TestCase):
    """Live Desktop composerData length gate (issue #11 step 4)."""

    def test_oversized_composer_data_fails_before_decode_success(self) -> None:
        from portable_resume.adapters.cursor_live import _show_live_desktop
        import sqlite3

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Path(tmp.name)
        db = storage / "state.vscdb"
        sid = str(uuid.uuid4())
        huge = "x" * (16 * 1024 * 1024 + 100)
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE composerHeaders (composerId TEXT, createdAt INTEGER, lastUpdatedAt INTEGER, value TEXT)"
        )
        conn.execute(
            "CREATE TABLE cursorDiskKV (key TEXT, value BLOB)"
        )
        conn.execute(
            "INSERT INTO composerHeaders VALUES (?,?,?,?)",
            (sid, 1, 2, json.dumps({"name": "t"})),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES (?,?)",
            (f"composerData:{sid}", huge.encode("utf-8")),
        )
        conn.commit()
        conn.close()
        with self.assertRaises(DiagnosticError) as caught:
            _show_live_desktop(str(db), sid, ReadBudget(), max_tool_chars=4000)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()


class CursorSkepticP1RegressionTests(unittest.TestCase):
    """Post-merge skeptic P1s for #11 ship."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()

    def _desktop(self, rows: list[tuple], links=None, blobs=None) -> Path:
        import sqlite3

        path = self.root / "state.vscdb"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE cursor_composers (
                id TEXT, cwd TEXT, cwd_hash TEXT, title TEXT,
                created_at TEXT, updated_at TEXT, archived INTEGER,
                composer_kind TEXT, git_branch TEXT
            );
            CREATE TABLE cursor_transcript_links (
                composer_id TEXT, ordinal INTEGER, blob_key TEXT
            );
            CREATE TABLE cursor_blobs (blob_key TEXT, payload_json TEXT);
            """
        )
        conn.executemany("INSERT INTO cursor_composers VALUES (?,?,?,?,?,?,?,?,?)", rows)
        if links:
            conn.executemany("INSERT INTO cursor_transcript_links VALUES (?,?,?)", links)
        if blobs:
            conn.executemany("INSERT INTO cursor_blobs VALUES (?,?)", blobs)
        conn.commit()
        conn.close()
        return path

    def test_many_eligible_project_composers_list_does_not_fail_at_200(self) -> None:
        """scanned_records window (~2000) must admit 250 project rows (not listed*4=200)."""
        rows = []
        for i in range(250):
            sid = str(uuid.uuid4())
            rows.append(
                (
                    sid,
                    str(self.cwd),
                    cursor._cwd_hash(str(self.cwd)),
                    f"proj-{i}",
                    _stamp(-300 + i),
                    _stamp(i),
                    0,
                    "project",
                    "main",
                )
            )
        self._desktop(rows)
        query = Query("cursor", cwd=str(self.cwd), source_root=str(self.root), within_min=0)
        listed = cursor.ADAPTER.list(query, ReadBudget())
        self.assertGreaterEqual(len(listed), 50)
        self.assertLessEqual(len(listed), 250)

    def test_uppercase_stored_uuid_list_then_show(self) -> None:
        """List normalizes id; show must still resolve case-folded stored UUID."""
        raw_id = str(uuid.uuid4()).upper()
        blob_key = "b0"
        self._desktop(
            [
                (
                    raw_id,
                    str(self.cwd),
                    cursor._cwd_hash(str(self.cwd)),
                    "Upper chat",
                    _stamp(-20),
                    _stamp(20),
                    0,
                    "project",
                    "main",
                )
            ],
            links=[(raw_id, 0, blob_key)],
            blobs=[
                (
                    blob_key,
                    json.dumps({"type": "message", "role": "user", "content": "upper-user"}),
                )
            ],
        )
        query = Query("cursor", cwd=str(self.cwd), source_root=str(self.root), within_min=0)
        listed = cursor.ADAPTER.list(query, ReadBudget())
        self.assertEqual(len(listed), 1)
        # session_id from list is lowercase normalized
        self.assertEqual(listed[0].session_id, raw_id.lower())
        session = cursor.ADAPTER.show(ResolvedRef.from_summary(listed[0]), query, ReadBudget())
        self.assertEqual([t.content for t in session.turns], ["upper-user"])

    def test_live_cli_blob_respects_budget_record_bytes(self) -> None:
        import sqlite3

        root = Path(self.temp.name) / ".cursor"
        root.mkdir()
        cwd = "/workspace/project"
        h = cursor._cwd_hash(cwd)
        sid = str(uuid.uuid4())
        session_dir = root / "chats" / h / sid
        session_dir.mkdir(parents=True)
        store = session_dir / "store.db"
        conn = sqlite3.connect(store)
        conn.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
        # 2 MiB blob; Bounds(record_bytes=1MiB) must reject
        payload = json.dumps({"role": "user", "content": "x" * (2 * 1024 * 1024)}).encode("utf-8")
        self.assertGreater(len(payload), 1024 * 1024)
        conn.execute("INSERT INTO blobs(id, data) VALUES (?, ?)", ("b0", payload))
        conn.commit()
        conn.close()
        (session_dir / "meta.json").write_text(
            json.dumps(
                {
                    "cwd": cwd,
                    "title": "big-blob",
                    "createdAtMs": 1_700_000_000_000,
                    "updatedAtMs": 1_700_000_100_000,
                }
            ),
            encoding="utf-8",
        )
        query = Query(source="cursor", cwd=cwd, source_root=str(root), within_min=0)
        hit = next(s for s in cursor.ADAPTER.list(query, ReadBudget()) if s.session_id == sid)
        tight = ReadBudget(limits=Bounds(record_bytes=1024 * 1024, transcript_records=100, scanned_records=100))
        with self.assertRaises(DiagnosticError) as caught:
            cursor.ADAPTER.show(ResolvedRef.from_summary(hit), query, tight)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
