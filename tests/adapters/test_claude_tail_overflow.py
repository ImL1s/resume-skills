from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from portable_resume.adapters import claude
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query


def stamp(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class ClaudeTailOverflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()

    def query(self, ref: str | None = None, cwd: Path | None = None) -> Query:
        return Query("claude", ref=ref, cwd=str(cwd or self.cwd), source_root=str(self.root))

    def session(self, records: list[dict], *, identifier: str | None = None, project: str = "project") -> tuple[str, Path]:
        identifier = identifier or str(uuid.uuid4())
        path = self.root / "projects" / project / f"{identifier}.jsonl"
        payload = b"".join(json.dumps(record, separators=(",", ":")).encode() + b"\n" for record in records)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
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

    def oversized_session(self, session_id: str, *, project: str = "project") -> tuple[Path, str, str]:
        """File with records at BOTH head and tail; ~150 KiB of meta in between.

        Head holds a cwd-bearing user record (discovery), tail holds the
        recoverable request/answer pair (show fallback). Total size exceeds a
        128 KiB source_read_bytes budget.
        """
        tail_user_id = str(uuid.uuid4())
        tail_assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", str(uuid.uuid4()), None, "head request", -5, sessionId=session_id),
            *({"type": "meta"} for _ in range(10_000)),  # ~150 KiB
            self.turn("user", tail_user_id, None, "latest request", -2, sessionId=session_id),
            self.turn("assistant", tail_assistant_id, tail_user_id, "answer", -1, sessionId=session_id),
        ]
        _identifier, path = self.session(records, identifier=session_id, project=project)
        self.assertGreater(path.stat().st_size, 128 * 1024)
        return path, tail_user_id, tail_assistant_id

    def test_list_stays_discoverable_for_oversized_file_with_warning(self) -> None:
        session_id = str(uuid.uuid4())
        path, _user_id, _assistant_id = self.oversized_session(session_id)
        budget = ReadBudget(
            Bounds(source_read_bytes=128 * 1024, transcript_records=5_000, scanned_records=2_000)
        )
        summaries = claude.ADAPTER.list(self.query(), budget)
        self.assertEqual([item.session_id for item in summaries], [session_id])
        self.assertIn("W_TRUNCATED", summaries[0].warnings)
        self.assertGreater(path.stat().st_size, 128 * 1024)

    def test_show_soft_degrades_when_transcript_budget_exceeded(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", user_id, None, "request", -2, sessionId=session_id),
            *({"type": "meta"} for _ in range(10)),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        budget = ReadBudget(
            Bounds(transcript_records=len(records) - 1, scanned_records=1)
        )
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)), self.query(), budget
        )
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_TRUNCATED", session.warnings)

    def test_show_soft_degrades_when_source_bytes_exceeded(self) -> None:
        session_id = str(uuid.uuid4())
        path, _user_id, _assistant_id = self.oversized_session(session_id)
        budget = ReadBudget(
            Bounds(
                source_read_bytes=128 * 1024,
                transcript_records=5_000,
                scanned_records=2_000,
            )
        )
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)), self.query(), budget
        )
        self.assertEqual(session.last_user_request, "latest request")
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_TRUNCATED", session.warnings)

    def test_parent_outside_admitted_window_warns_broken_chain(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", user_id, None, "request", -3, sessionId=session_id),
            *({"type": "meta"} for _ in range(6)),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        # transcript_records=7 admits the last 7 of 8 records, dropping the
        # parent user record; the leaf's chain then crosses the cut.
        budget = ReadBudget(Bounds(transcript_records=7, scanned_records=100))
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)), self.query(), budget
        )
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_BROKEN_CHAIN", session.warnings)

    def test_replay_conflict_inside_window_stays_corrupt(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        base = self.turn("user", user_id, None, "request", -2, sessionId=session_id)
        replay = dict(base)
        replay["message"] = {"role": "user", "content": "changed"}
        records = [
            base,
            replay,
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        budget = ReadBudget(Bounds(transcript_records=3, scanned_records=100))
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)), self.query(), budget
            )
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_single_record_over_record_bytes_stays_limit_exceeded(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        big = self.turn("user", user_id, None, "x" * 1024, -1, sessionId=session_id)
        encoded = json.dumps(big, separators=(",", ":")).encode() + b"\n"
        _, path = self.session([big], identifier=session_id)
        budget = ReadBudget(
            Bounds(
                record_bytes=len(encoded) - 1,
                transcript_records=10,
                scanned_records=10,
            )
        )
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)), self.query(), budget
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_show_source_tree_byte_for_byte_unchanged(self) -> None:
        from tests.helpers.core import tree_snapshot

        session_id = str(uuid.uuid4())
        path, _user_id, _assistant_id = self.oversized_session(session_id)
        before = tree_snapshot(str(self.root))
        budget = ReadBudget(
            Bounds(source_read_bytes=128 * 1024, transcript_records=5_000, scanned_records=2_000)
        )
        claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), budget)
        self.assertEqual(tree_snapshot(str(self.root)), before)

    def test_crlf_record_original_length_limit_preserved_in_fallback(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        record_bytes = 1024
        records = [
            self.turn("user", user_id, None, "request", -2, sessionId=session_id),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        self.assertLess(path.stat().st_size, record_bytes)
        # Terminal CRLF record: physical len == record_bytes + 1, LF-only == -1.
        meta = '{"type":"meta","pad":"' + "x" * (record_bytes - 25) + '"}'
        self.assertEqual(len(meta.encode()), record_bytes - 1)
        path.write_bytes(path.read_bytes() + meta.encode() + b"\r\n")
        budget = ReadBudget(
            Bounds(
                record_bytes=record_bytes,
                transcript_records=10,
                scanned_records=100,
            )
        )
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)), self.query(), budget
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_normalized_turns_exhaustion_hard_fails_no_fallback_loop(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", user_id, None, "request", -2, sessionId=session_id),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        budget = ReadBudget(
            Bounds(normalized_turns=1, transcript_records=10, scanned_records=100)
        )
        # Turns exhaustion must propagate, not re-enter the tail fallback.
        with mock.patch.object(
            claude,
            "_build_tail_graph",
            side_effect=AssertionError("fallback must not run on turns exhaustion"),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                claude.ADAPTER.show(
                    ResolvedRef(session_id, str(path)), self.query(), budget
                )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_budget_counters_match_full_path_after_show(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", user_id, None, "request", -2, sessionId=session_id),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        budget = ReadBudget()
        claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), budget)
        self.assertEqual(budget.bytes_read, path.stat().st_size)
        self.assertEqual(budget.transcript_records_read, len(records))

    def test_replay_conflict_inside_fallback_window_stays_corrupt(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        base = self.turn("user", user_id, None, "request", -3, sessionId=session_id)
        replay = dict(base)
        replay["message"] = {"role": "user", "content": "changed"}
        records = [
            {"type": "meta"},
            {"type": "meta"},
            base,
            replay,
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        # transcript_records=3: fast path consumes 5 records and exhausts the
        # budget BEFORE observing the base/replay conflict (records 3-4), so the
        # tail fallback runs; the admitted suffix (last 3) still contains both
        # base and replay, so the digest conflict surfaces as E_CORRUPT_RECORD.
        budget = ReadBudget(Bounds(transcript_records=3, scanned_records=100))
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)), self.query(), budget
            )
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_commit_provisional_barrier_no_double_charge(self) -> None:
        # Barrier-controlled concurrency probe: a concurrent charge between the
        # baseline snapshot and the provisional snapshot must NOT be counted
        # twice (codex re-review P1-1).
        import threading

        budget = ReadBudget(Bounds(scanned_records=10))
        baseline = claude._provisional_metadata_budget(budget)
        gate = threading.Barrier(2)
        results: dict[str, int] = {}

        def concurrent_charge() -> None:
            gate.wait()
            budget.consume_records(3)

        thread = threading.Thread(target=concurrent_charge)
        thread.start()
        gate.wait()
        # Simulate the full path consuming 2 records on the provisional budget
        # while the live budget is concurrently charged by the other thread.
        provisional = claude._provisional_metadata_budget(baseline)
        provisional.consume_records(2)
        budget.commit_provisional(baseline, provisional)
        thread.join()
        results["records"] = budget.records
        # 3 concurrent + 2 full-path = 5, never 3 + 2 + 2.
        self.assertEqual(results["records"], 5)

    def test_zero_precharged_budget_preserves_limit_diagnostic(self) -> None:
        # A fully precharged transcript budget must surface E_LIMIT_EXCEEDED
        # (not E_UNSUPPORTED_FORMAT) when the fallback cannot admit any node.
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        records = [
            self.turn("user", user_id, None, "request", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        budget = ReadBudget(
            Bounds(
                transcript_records=1,
                scanned_records=100,
            )
        )
        budget.consume_transcript_records(1)  # fully precharged
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)), self.query(), budget
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
