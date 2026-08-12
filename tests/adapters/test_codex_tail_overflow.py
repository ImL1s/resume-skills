from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from portable_resume.adapters import codex
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from portable_resume import snapshot
from tests.helpers.core import tree_snapshot


class CodexTailOverflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()
        self.identifier = str(uuid.uuid4())
        self.path = (
            self.root
            / "sessions/2026/08/12"
            / f"rollout-2026-08-12T00-00-00-{self.identifier}.jsonl"
        )
        self.path.parent.mkdir(parents=True)

    def query(self, ref: str | None = None) -> Query:
        return Query("codex", ref=ref, cwd=str(self.cwd), source_root=str(self.root))

    def meta(self, *, cwd: Path | None = None, source: str = "cli") -> dict:
        return {
            "type": "session_meta",
            "timestamp": "2026-08-12T00:00:00Z",
            "payload": {
                "id": self.identifier,
                "cwd": str(cwd or self.cwd),
                "source": source,
                "git": {"branch": "tail"},
            },
        }

    @staticmethod
    def message(role: str, text: str, second: int) -> dict:
        return {
            "type": "response_item",
            "timestamp": f"2026-08-12T00:00:{second:02d}Z",
            "payload": {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
            },
        }

    @staticmethod
    def encoded(record: dict) -> bytes:
        return json.dumps(record, separators=(",", ":")).encode() + b"\n"

    def write(self, records: list[dict], *, suffix: bytes = b"") -> None:
        self.path.write_bytes(b"".join(self.encoded(record) for record in records) + suffix)

    def overflow_records(self) -> list[dict]:
        return [
            self.meta(),
            *({"type": "world_state", "payload": {"pad": "x" * 900}} for _ in range(180)),
            self.message("user", "latest request", 1),
            self.message("assistant", "latest answer", 2),
        ]

    def budget(self, *, source_bytes: int = 64 * 1024, record_bytes: int = 16 * 1024) -> ReadBudget:
        return ReadBudget(
            Bounds(
                source_read_bytes=source_bytes,
                record_bytes=record_bytes,
                transcript_records=500,
                scanned_records=500,
            )
        )

    def show(self, budget: ReadBudget, *, path: Path | None = None):
        return codex.ADAPTER.show(
            ResolvedRef(self.identifier, str(path or self.path)),
            self.query(self.identifier),
            budget,
        )

    def test_oversized_uuid_and_absolute_path_soft_recover_identically_without_full_readers(self) -> None:
        self.write(self.overflow_records())
        before = tree_snapshot(self.root)
        sessions = []
        for resolved in (
            ResolvedRef(self.identifier, str(self.path)),
            ResolvedRef(self.identifier, str(self.path.resolve())),
        ):
            budget = self.budget()
            with mock.patch.object(codex, "stable_scan_lines", side_effect=AssertionError("no full scan")), mock.patch.object(
                codex, "stable_read_bytes", side_effect=AssertionError("no full read")
            ):
                sessions.append(codex.ADAPTER.show(resolved, self.query(self.identifier), budget))
            self.assertEqual(budget.bytes_read, budget.limits.source_read_bytes)
        self.assertEqual(sessions[0].to_dict(), sessions[1].to_dict())
        self.assertEqual(sessions[0].last_user_request, "latest request")
        self.assertEqual(sessions[0].last_assistant_action, "latest answer")
        self.assertIn("W_TRUNCATED", sessions[0].warnings)
        self.assertEqual(tree_snapshot(self.root), before)

    def test_mid_record_fragment_is_discarded_and_terminal_partial_json_warns(self) -> None:
        records = self.overflow_records()
        self.write(records, suffix=b'{"type":"response_item","payload":')
        session = self.show(self.budget(source_bytes=12 * 1024, record_bytes=8 * 1024))
        self.assertEqual(session.last_assistant_action, "latest answer")
        self.assertIn("W_TRUNCATED", session.warnings)
        self.assertIn("W_PARTIAL_TAIL", session.warnings)

    def test_terminal_partial_utf8_warns(self) -> None:
        self.write(self.overflow_records(), suffix=b"\xf0\x9f")
        session = self.show(self.budget())
        self.assertEqual(session.last_assistant_action, "latest answer")
        self.assertIn("W_PARTIAL_TAIL", session.warnings)

    def test_tail_metadata_replay_cannot_override_authoritative_head(self) -> None:
        other = self.root / "other"
        other.mkdir()
        records = self.overflow_records()
        records.insert(-2, self.meta(cwd=other, source="vscode"))
        self.write(records)
        session = self.show(self.budget())
        self.assertEqual(session.cwd, str(self.cwd))
        self.assertEqual(session.branch, "tail")

    def test_compaction_then_rollback_are_applied_in_tail_order(self) -> None:
        compacted = {
            "type": "compacted",
            "timestamp": "2026-08-12T00:00:10Z",
            "payload": {
                "replacement_history": [
                    self.message("user", "compacted request", 3)["payload"],
                    self.message("assistant", "compacted answer", 4)["payload"],
                    self.message("user", "rolled back request", 5)["payload"],
                    self.message("assistant", "rolled back answer", 6)["payload"],
                ]
            },
        }
        rollback = {"type": "event_msg", "payload": {"type": "thread_rolled_back", "num_turns": 1}}
        self.write([self.meta(), *self.overflow_records()[1:-2], compacted, rollback, self.message("assistant", "final", 9)])
        session = self.show(self.budget())
        self.assertEqual([turn.content for turn in session.turns], ["compacted request", "compacted answer", "final"])

    def test_rollback_with_user_boundary_clipped_from_tail_drops_admitted_assistant(self) -> None:
        records = [
            self.meta(),
            *({"type": "world_state", "payload": {"pad": "x" * 900}} for _ in range(7)),
            self.message("user", "rolled back request", 1),
            self.message("assistant", "x" * 1_750, 2),
            {"type": "event_msg", "payload": {"type": "thread_rolled_back", "num_turns": 1}},
        ]
        self.write(records)
        session = self.show(self.budget(source_bytes=4_096, record_bytes=4_096))
        self.assertIsNone(session.last_user_request)
        self.assertIsNone(session.last_assistant_action)
        self.assertEqual(session.turns, ())
        self.assertIn("W_TRUNCATED", session.warnings)
        self.assertIn("W_BROKEN_CHAIN", session.warnings)

    def test_tail_rollback_fully_represented_keeps_prior_turn(self) -> None:
        records = [
            self.meta(),
            *({"type": "world_state", "payload": {"pad": "x" * 900}} for _ in range(7)),
            self.message("user", "kept request", 1),
            self.message("assistant", "kept answer", 2),
            self.message("user", "rolled back request", 3),
            self.message("assistant", "rolled back answer", 4),
            {"type": "event_msg", "payload": {"type": "thread_rolled_back", "num_turns": 1}},
        ]
        self.write(records)
        session = self.show(self.budget(source_bytes=4_096, record_bytes=4_096))
        self.assertEqual([turn.content for turn in session.turns], ["kept request", "kept answer"])

    def test_multi_turn_rollback_partly_beyond_suffix_drops_all_admitted_turns(self) -> None:
        records = [
            self.meta(),
            *({"type": "world_state", "payload": {"pad": "x" * 900}} for _ in range(7)),
            self.message("user", "clipped request", 1),
            self.message("assistant", "x" * 2_500, 2),
            self.message("user", "admitted request", 3),
            self.message("assistant", "admitted answer", 4),
            {"type": "event_msg", "payload": {"type": "thread_rolled_back", "num_turns": 2}},
        ]
        self.write(records)
        session = self.show(self.budget(source_bytes=6_000, record_bytes=4_096))
        self.assertEqual(session.turns, ())
        self.assertIn("W_BROKEN_CHAIN", session.warnings)

    def test_complete_oversized_or_invalid_admitted_record_stays_hard(self) -> None:
        for terminal, expected in (
            (self.message("assistant", "x" * 9_000, 2), "E_LIMIT_EXCEEDED"),
            ({"payload": {"bad": True}}, "E_UNSUPPORTED_FORMAT"),
        ):
            with self.subTest(expected=expected):
                self.write([self.meta(), *self.overflow_records()[1:-2], self.message("user", "latest", 1), terminal])
                with self.assertRaises(DiagnosticError) as caught:
                    self.show(self.budget(source_bytes=32 * 1024, record_bytes=8 * 1024))
                self.assertEqual(caught.exception.code, expected)

    def test_exact_record_ceiling_matches_in_budget_scanner_after_tail_fallback(self) -> None:
        exact = self.message("assistant", "edge" * 64, 2)
        maximum_record = len(self.encoded(exact)) - 1
        records = [
            self.meta(),
            *({"type": "world_state", "payload": {"pad": "x" * 32}} for _ in range(80)),
            self.message("user", "latest request", 1),
            exact,
        ]
        self.write(records)
        self.assertGreater(self.path.stat().st_size, maximum_record * 4)

        session = self.show(
            self.budget(
                source_bytes=maximum_record * 4,
                record_bytes=maximum_record,
            )
        )

        self.assertEqual(session.last_user_request, "latest request")
        self.assertEqual(session.last_assistant_action, "edge" * 64)
        self.assertIn("W_TRUNCATED", session.warnings)

    def test_missing_bounded_head_metadata_is_honest_limit(self) -> None:
        self.write([*({"type": "world_state", "payload": {"pad": "x" * 900}} for _ in range(180)), self.message("user", "tail", 1)])
        with self.assertRaises(DiagnosticError) as caught:
            self.show(self.budget())
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_zero_or_precharged_source_budget_stays_limit(self) -> None:
        self.write(self.overflow_records())
        for budget in (
            self.budget(source_bytes=0),
            self.budget(source_bytes=64 * 1024, record_bytes=0),
            self.budget(source_bytes=64 * 1024),
        ):
            if budget.limits.source_read_bytes:
                if budget.limits.record_bytes:
                    budget.consume_bytes(budget.limits.source_read_bytes)
            with self.subTest(precharged=budget.bytes_read):
                with self.assertRaises(DiagnosticError) as caught:
                    self.show(budget)
                self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_in_budget_plain_show_compatibility(self) -> None:
        self.write([self.meta(), self.message("user", "request", 1), self.message("assistant", "answer", 2)])
        with mock.patch.object(codex, "stable_scan_tail_lines", side_effect=AssertionError("tail path not expected")):
            session = self.show(self.budget())
        self.assertEqual([turn.content for turn in session.turns], ["request", "answer"])
        self.assertNotIn("W_TRUNCATED", session.warnings)

    def test_oversized_resolved_path_does_not_rediscover_db_or_filesystem(self) -> None:
        self.write(self.overflow_records())
        with mock.patch.object(codex, "_exact_rollout_paths", side_effect=AssertionError("no rediscovery")), mock.patch.object(
            codex, "_state_databases", side_effect=AssertionError("no DB discovery")
        ):
            session = self.show(self.budget())
        self.assertEqual(session.session_id, self.identifier)

    def test_oversized_tail_hashes_only_the_admitted_suffix(self) -> None:
        self.write(self.overflow_records())
        starts: list[int] = []
        original = snapshot._hash_descriptor_window

        def observe(descriptor: int, *, start: int, maximum: int):
            starts.append(start)
            return original(descriptor, start=start, maximum=maximum)

        with mock.patch.object(snapshot, "_hash_descriptor_window", side_effect=observe):
            self.show(self.budget())
        self.assertTrue(starts)
        self.assertTrue(all(start > 0 for start in starts), starts)

    def test_oversized_budget_counters_are_exact_and_not_double_charged(self) -> None:
        self.write(self.overflow_records())
        limit = 64 * 1024
        probe = self.budget(source_bytes=limit)
        head_bytes = min(codex._PROBE_HEAD_BYTES, probe.limits.record_bytes, limit // 2)
        admitted = list(
            snapshot.stable_scan_tail_lines(
                self.path,
                root=self.root,
                budget=probe,
                charge_transcript=True,
                max_line_bytes=probe.limits.record_bytes,
                stable_head_bytes=head_bytes,
            )
        )
        budget = self.budget(source_bytes=limit)
        self.show(budget)
        self.assertEqual(budget.bytes_read, limit)
        self.assertEqual(budget.transcript_records_read, len(admitted))

    def test_unsafe_outside_root_and_symlink_stay_hard(self) -> None:
        self.write(self.overflow_records())
        outside_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: outside_dir.rmdir() if outside_dir.exists() and not any(outside_dir.iterdir()) else None)
        outside = outside_dir / self.path.name
        outside.write_bytes(self.path.read_bytes())
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        link_dir = self.root / "linked"
        link_dir.mkdir()
        link = link_dir / self.path.name
        link.symlink_to(self.path)
        for candidate in (outside, link):
            with self.subTest(candidate=str(candidate)):
                with self.assertRaises(DiagnosticError):
                    self.show(self.budget(), path=candidate)

    def test_append_shrink_replacement_tail_and_head_mutation_stay_busy(self) -> None:
        original_scan = codex.stable_scan_tail_lines

        def run_mutation(kind: str) -> None:
            self.write(self.overflow_records())

            def scan(*args, **kwargs):
                def mutate(phase: str, _attempt: int, safe: str) -> None:
                    if phase != "after-read":
                        return
                    target = Path(safe)
                    if kind == "append":
                        with target.open("ab") as handle:
                            handle.write(b" ")
                    elif kind == "shrink":
                        os.truncate(target, target.stat().st_size - 1)
                    elif kind == "replacement":
                        replacement = target.with_suffix(".replacement")
                        replacement.write_bytes(target.read_bytes())
                        os.replace(replacement, target)
                    else:
                        offset = 0 if kind == "head" else target.stat().st_size - 2
                        with target.open("r+b") as handle:
                            handle.seek(offset)
                            old = handle.read(1)
                            handle.seek(offset)
                            handle.write(b" " if old != b" " else b"x")
                return original_scan(*args, **kwargs, hook=mutate)

            with mock.patch.object(codex, "stable_scan_tail_lines", side_effect=scan):
                with self.assertRaises(DiagnosticError) as caught:
                    self.show(self.budget())
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

        for kind in ("append", "shrink", "replacement", "tail", "head"):
            with self.subTest(kind=kind):
                run_mutation(kind)


if __name__ == "__main__":
    unittest.main()
