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


if __name__ == "__main__":
    unittest.main()
