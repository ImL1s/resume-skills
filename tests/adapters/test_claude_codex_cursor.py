from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from portable_resume.adapters import claude, codex, codex_sqlite, cursor
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import DEFAULT_BOUNDS, Bounds, ReadBudget
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
    def test_lane_manifests_are_strict_synthetic(self) -> None:
        lane_sources = {"claude", "codex", "cursor"}
        values = [
            value
            for value in validate_fixture_tree("tests/fixtures")
            if value.source in lane_sources
        ]
        fixture_sources = Counter(
            path.parents[1].name
            for path in Path("tests/fixtures").rglob("fixture.json")
            if path.parents[1].name in lane_sources
        )

        self.assertEqual(Counter(value.source for value in values), fixture_sources)
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

    def issue167_query(self, cwd: str) -> Query:
        root = Path(
            "tests/fixtures/claude/s-cla-09-unmatched-cwd-bounds/root"
        ).resolve()
        return Query("claude", cwd=cwd, source_root=str(root))

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

    def render_handoff(
        self,
        records: list[dict],
        *,
        max_tool_chars: int = DEFAULT_BOUNDS.tool_output_chars,
    ) -> str:
        raw_session_id = records[0].get("sessionId")
        self.assertIsInstance(raw_session_id, str)
        session_id = str(raw_session_id)
        self.session(records, identifier=session_id)
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(
            [
                "claude",
                "show",
                session_id,
                "--cwd",
                str(self.cwd),
                "--source-root",
                str(self.root),
                "--max-tool-chars",
                str(max_tool_chars),
                "--format",
                "handoff",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 0, stderr.getvalue())
        return stdout.getvalue()

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
                    {
                        "type": "tool_use",
                        "id": "toolu_synthetic_read_001",
                        "name": "Read",
                        "input": {"file_path": "/workspace/project/app.py"},
                        "caller": {"type": "direct"},
                    },
                ],
                -2,
                sessionId=session_id,
            ),
            self.turn(
                "user",
                tool_id,
                assistant_id,
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_synthetic_read_001",
                        "content": "tool output",
                    }
                ],
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

    def test_s_cla_08_tool_use_input_and_name_render_with_result(self) -> None:
        fixture_root = (
            Path(__file__).parents[1]
            / "fixtures"
            / "claude"
            / "s-cla-08-tool-use-result"
            / "root"
        )
        stdout, stderr = io.StringIO(), io.StringIO()

        code = run(
            [
                "claude",
                "show",
                "latest",
                "--cwd",
                "/workspace/project",
                "--source-root",
                str(fixture_root),
                "--format",
                "handoff",
            ],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        handoff = stdout.getvalue()
        self.assertIn("synthetic file contents", handoff)
        self.assertIn("[2 tool/Read]", handoff)
        self.assertIn("[3 tool/Bash]", handoff)
        self.assertIn("/workspace/project/app.py", handoff)
        self.assertIn("pytest -x", handoff)
        self.assertIn("missing tool result", handoff)

        message_start = handoff.index("### Latest assistant message")
        action_start = handoff.index("### Latest recorded action")
        warnings_start = handoff.index("## Warnings")
        message_section = handoff[message_start:action_start]
        action_section = handoff[action_start:warnings_start]
        self.assertIn("I will inspect the synthetic file first.", message_section)
        self.assertNotIn("pytest -x", message_section)
        self.assertIn("[3 tool/Bash]", action_section)
        self.assertIn("pytest -x", action_section)
        self.assertIn("missing tool result", action_section)
        self.assertNotIn("I will inspect the synthetic file first.", action_section)

    def test_tool_input_is_bounded_without_evicting_correlated_result(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, call_id, result_id = (str(uuid.uuid4()) for _ in range(3))
        handoff = self.render_handoff(
            [
                self.turn("user", user_id, None, "question", -3, sessionId=session_id),
                self.turn(
                    "assistant",
                    call_id,
                    user_id,
                    [
                        {
                            "type": "tool_use",
                            "id": "toolu_large_input",
                            "name": "Read",
                            "input": {"file_path": "/workspace/project/" + "x" * 500},
                        }
                    ],
                    -2,
                    sessionId=session_id,
                ),
                self.turn(
                    "user",
                    result_id,
                    call_id,
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_large_input",
                            "content": "RESULT_STILL_VISIBLE",
                        }
                    ],
                    -1,
                    sessionId=session_id,
                ),
            ],
            max_tool_chars=120,
        )

        self.assertIn("[1 tool/Read]", handoff)
        self.assertIn("RESULT_STILL_VISIBLE", handoff)
        self.assertIn("W_TRUNCATED", handoff)
        self.assertNotIn("x" * 100, handoff)

    def test_tool_input_is_redacted_before_its_sub_budget_truncates(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, call_id, result_id = (str(uuid.uuid4()) for _ in range(3))
        secret = "gh" + "p_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        handoff = self.render_handoff(
            [
                self.turn("user", user_id, None, "question", -3, sessionId=session_id),
                self.turn(
                    "assistant",
                    call_id,
                    user_id,
                    [
                        {
                            "type": "tool_use",
                            "id": "toolu_secret_input",
                            "name": "Bash",
                            "input": {"command": "x " + secret, "note": "\x00unsafe"},
                        }
                    ],
                    -2,
                    sessionId=session_id,
                ),
                self.turn(
                    "user",
                    result_id,
                    call_id,
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_secret_input",
                            "content": "safe result",
                        }
                    ],
                    -1,
                    sessionId=session_id,
                ),
            ],
            max_tool_chars=96,
        )

        self.assertIn("[REDACTED]", handoff)
        self.assertIn("safe result", handoff)
        self.assertNotIn(secret, handoff)
        self.assertNotIn(secret[:18], handoff)
        self.assertNotIn("\x00", handoff)

    def test_unmatched_tool_result_remains_anonymous(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, result_id = (str(uuid.uuid4()) for _ in range(2))
        handoff = self.render_handoff(
            [
                self.turn("user", user_id, None, "question", -2, sessionId=session_id),
                self.turn(
                    "user",
                    result_id,
                    user_id,
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_unknown",
                            "tool_name": "FabricatedName",
                            "content": "orphan result",
                        }
                    ],
                    -1,
                    sessionId=session_id,
                ),
            ]
        )

        self.assertIn("[1 tool]", handoff)
        self.assertNotIn("[1 tool/", handoff)
        self.assertNotIn("FabricatedName", handoff)
        self.assertIn("orphan result", handoff)

    def test_interrupted_tool_call_renders_missing_result(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, call_id = (str(uuid.uuid4()) for _ in range(2))
        handoff = self.render_handoff(
            [
                self.turn("user", user_id, None, "question", -2, sessionId=session_id),
                self.turn(
                    "assistant",
                    call_id,
                    user_id,
                    [
                        {
                            "type": "tool_use",
                            "id": "toolu_interrupted",
                            "name": "Read",
                            "input": {"file_path": "/workspace/project/pending.py"},
                        }
                    ],
                    -1,
                    sessionId=session_id,
                ),
            ]
        )

        self.assertIn("[1 tool/Read]", handoff)
        self.assertIn("/workspace/project/pending.py", handoff)
        self.assertIn("missing tool result", handoff)

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

    def test_primary_cwd_ignores_later_worktree_cwds(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, assistant_id = (str(uuid.uuid4()) for _ in range(2))
        worktree = self.root / "worktree"
        worktree.mkdir()
        first = self.turn("user", user_id, None, "main request", -2, sessionId=session_id)
        second = self.turn(
            "assistant",
            assistant_id,
            user_id,
            "worktree answer",
            -1,
            sessionId=session_id,
        )
        second["cwd"] = str(worktree)
        self.session([first, second], identifier=session_id)

        summaries = claude.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [session_id])
        session = claude.ADAPTER.show(
            ResolvedRef.from_summary(summaries[0]),
            self.query(),
            ReadBudget(),
        )
        self.assertEqual(session.cwd, str(self.cwd))
        self.assertEqual([turn.content for turn in session.turns], ["main request", "worktree answer"])
        self.assertEqual(claude.ADAPTER.list(self.query(cwd=worktree), ReadBudget()), [])

    def test_issue167_unmatched_cwd_completes_with_empty_authoritative_result(self) -> None:
        budget = ReadBudget(Bounds(scanned_records=4))
        query = self.issue167_query("/workspace/unmatched")
        fixture_before = tree_snapshot(Path(query.source_root or ""))

        values = claude.ADAPTER.list(query, budget)

        self.assertEqual(values, [])
        self.assertEqual(budget.records, 4)
        self.assertEqual(fixture_before, tree_snapshot(Path(query.source_root or "")))

        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(
            [
                "claude",
                "list",
                "--cwd",
                query.cwd or "",
                "--source-root",
                query.source_root or "",
                "--json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        envelope = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(envelope["sessions"], [])
        self.assertEqual(envelope["warnings"], [])

    def test_issue167_unmatched_cwd_still_fails_when_prefilter_is_incomplete(self) -> None:
        budget = ReadBudget(Bounds(scanned_records=3))

        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.list(self.issue167_query("/workspace/unmatched"), budget)

        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_issue167_show_latest_unmatched_cwd_renders_no_match_document(self) -> None:
        query = self.issue167_query("/workspace/unmatched")
        stdout, stderr = io.StringIO(), io.StringIO()

        code = run(
            [
                "claude",
                "show",
                "latest",
                "--cwd",
                query.cwd or "",
                "--source-root",
                query.source_root or "",
            ],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 3)
        self.assertIn("# Portable Resume No Match", stdout.getvalue())
        self.assertGreater(len(stdout.getvalue()), 0)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "E_NO_MATCH")

    def test_issue167_relocated_bucket_remains_discoverable(self) -> None:
        values = claude.ADAPTER.list(
            self.issue167_query("/workspace/target"),
            ReadBudget(),
        )

        self.assertEqual(
            [value.session_id for value in values],
            ["00000000-0000-4000-8000-000000000004"],
        )

    def test_issue167_matching_prefilter_payload_is_charged_once(self) -> None:
        session_id = str(uuid.uuid4())
        _, path = self.session(
            [
                self.turn(
                    "user",
                    str(uuid.uuid4()),
                    None,
                    "relocated once",
                    0,
                    sessionId=session_id,
                )
            ],
            identifier=session_id,
            project="relocated-bucket",
        )
        budget = ReadBudget(Bounds(source_read_bytes=path.stat().st_size))

        values = claude.ADAPTER.list(self.query(), budget)

        self.assertEqual([value.session_id for value in values], [session_id])
        self.assertEqual(budget.bytes_read, path.stat().st_size)

    def test_issue167_matched_scan_still_fails_closed_when_oversized(self) -> None:
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.list(
                self.issue167_query("/workspace/target"),
                ReadBudget(Bounds(scanned_records=4)),
            )

        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_semantic_replay_uses_latest_parent_and_conflicts_fail_closed(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, stale_id, attachment_id, leaf_id = (str(uuid.uuid4()) for _ in range(4))
        base_attachment = {
            "type": "attachment",
            "uuid": attachment_id,
            "parentUuid": stale_id,
            "sessionId": session_id,
            "cwd": str(self.cwd),
            "timestamp": stamp(-2),
            "payload": {"kind": "synthetic"},
        }
        replay = dict(base_attachment)
        replay.update({"parentUuid": user_id, "cwd": str(self.root / "bridge-worktree")})
        records = [
            self.turn("user", user_id, None, "start", -4, sessionId=session_id),
            self.turn("assistant", stale_id, user_id, "stale branch", -3, sessionId=session_id),
            base_attachment,
            replay,
            self.turn("user", leaf_id, attachment_id, "selected leaf", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        summary = claude.ADAPTER.list(self.query(), ReadBudget())[0]
        session = claude.ADAPTER.show(ResolvedRef.from_summary(summary), self.query(), ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["start", "selected leaf"])
        self.assertNotIn("W_BROKEN_CHAIN", session.warnings)

        conflicting = dict(replay)
        conflicting["payload"] = {"kind": "changed"}
        write_jsonl(path, [*records, conflicting])
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_cross_type_uuid_replay_fails_closed(self) -> None:
        session_id = str(uuid.uuid4())
        shared_id = str(uuid.uuid4())
        user = self.turn("user", shared_id, None, "request", -2, sessionId=session_id)
        attachment = {
            "type": "attachment",
            "uuid": shared_id,
            "parentUuid": None,
            "sessionId": session_id,
            "cwd": str(self.cwd),
            "timestamp": stamp(-2),
        }
        _, path = self.session([user, attachment], identifier=session_id)
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_replay_usage_reset_is_envelope_but_content_change_is_corrupt(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, assistant_id, leaf_id = (str(uuid.uuid4()) for _ in range(3))
        assistant = self.turn(
            "assistant",
            assistant_id,
            user_id,
            "stable answer",
            -2,
            sessionId=session_id,
        )
        assistant["message"]["usage"] = {
            "input_tokens": 12,
            "output_tokens": 3,
            "cache_creation_input_tokens": 4,
            "cache_read_input_tokens": 5,
        }
        replay = json.loads(json.dumps(assistant))
        replay["message"]["usage"] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        records = [
            self.turn("user", user_id, None, "request", -3, sessionId=session_id),
            assistant,
            replay,
            self.turn("user", leaf_id, assistant_id, "follow-up", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        session = claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["request", "stable answer", "follow-up"],
        )

        conflicting = json.loads(json.dumps(replay))
        conflicting["message"]["content"] = "changed answer"
        write_jsonl(path, [*records, conflicting])
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_large_listing_uses_metadata_windows_not_a_full_snapshot(self) -> None:
        session_id = str(uuid.uuid4())
        record = self.turn("user", str(uuid.uuid4()), None, "large listing", -1, sessionId=session_id)
        _, path = self.session([record], identifier=session_id)
        target_size = 17 * 1024 * 1024
        with path.open("ab") as handle:
            handle.write(b" " * (target_size - path.stat().st_size))
        self.assertGreater(path.stat().st_size, 16 * 1024 * 1024)
        with mock.patch.object(
            claude,
            "snapshot_regular_file",
            side_effect=AssertionError("list must not copy the full transcript"),
        ):
            summaries = claude.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [session_id])

    def test_streaming_show_has_independent_line_and_record_byte_bounds(self) -> None:
        session_id = str(uuid.uuid4())
        user_id, assistant_id = (str(uuid.uuid4()) for _ in range(2))
        records = [
            self.turn("user", user_id, None, "request", -2, sessionId=session_id),
            *({"type": "meta"} for _ in range(2_001)),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        enough = Bounds(transcript_records=len(records), scanned_records=1)
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)),
            self.query(),
            ReadBudget(enough),
        )
        self.assertEqual([turn.content for turn in session.turns], ["request", "answer"])
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)),
            self.query(),
            ReadBudget(Bounds(transcript_records=len(records) - 1, scanned_records=1)),
        )
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_TRUNCATED", session.warnings)

        one_record = self.turn(
            "user",
            str(uuid.uuid4()),
            None,
            "bounded record",
            -1,
            sessionId=session_id,
        )
        encoded = json.dumps(one_record, separators=(",", ":")).encode() + b"\n"
        write_jsonl(path, [one_record])
        exact = Bounds(record_bytes=len(encoded), transcript_records=1, scanned_records=1)
        claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)),
            self.query(),
            ReadBudget(exact),
        )
        with self.assertRaises(DiagnosticError) as record_bytes:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)),
                self.query(),
                ReadBudget(
                    Bounds(
                        record_bytes=len(encoded) - 1,
                        transcript_records=1,
                        scanned_records=1,
                    )
                ),
            )
        self.assertEqual(record_bytes.exception.code, "E_LIMIT_EXCEEDED")

    def test_replay_cycle_fails_closed(self) -> None:
        session_id = str(uuid.uuid4())
        first_id, second_id = (str(uuid.uuid4()) for _ in range(2))
        records = [
            self.turn("user", first_id, second_id, "first", -2, sessionId=session_id),
            self.turn("assistant", second_id, first_id, "second", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_nonfinite_or_pathological_json_numbers_are_corrupt(self) -> None:
        for raw in (
            b'{"type":"user","value":NaN}\n',
            b'{"type":"user","value":1e400}\n',
            b'{"type":"user","value":' + (b"9" * 5_000) + b"}\n",
        ):
            with self.subTest(size=len(raw)), self.assertRaises(DiagnosticError) as caught:
                claude._decode_record(raw, terminal_partial=False)
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_discovery_enumeration_is_bounded_before_sorting(self) -> None:
        directory = self.root / "many"
        directory.mkdir()
        (directory / "a").touch()
        (directory / "b").touch()
        with mock.patch.object(
            claude.os,
            "listdir",
            side_effect=AssertionError("bounded discovery must not use listdir"),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                claude._bounded_names(str(directory), limit=1)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_conversation_record_without_uuid_fails_closed(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        missing = self.turn(
            "assistant",
            str(uuid.uuid4()),
            user_id,
            "must not disappear",
            -1,
            sessionId=session_id,
        )
        missing.pop("uuid")
        records = [
            self.turn("user", user_id, None, "request", -2, sessionId=session_id),
            missing,
        ]
        _, path = self.session(records, identifier=session_id)
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), ReadBudget())
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

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
        with mock.patch.object(claude, "stable_read_windows", side_effect=DiagnosticError.source_busy()):
            with self.assertRaises(DiagnosticError) as busy:
                claude.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(busy.exception.code, "E_SOURCE_BUSY")

    def test_issue19_exact_path_skips_project_enumeration(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        slug = claude._slugify_cwd(str(self.cwd))
        _, path = self.session(
            [self.turn("user", user_id, None, "exact path", 0, sessionId=session_id)],
            identifier=session_id,
            project=slug,
        )
        with mock.patch.object(
            claude,
            "_project_dirs",
            side_effect=AssertionError("_project_dirs must not run for exact path"),
        ):
            values = claude.ADAPTER.list(
                self.query(ref=str(path.resolve())),
                ReadBudget(),
            )
        self.assertEqual([item.session_id for item in values], [session_id])
        self.assertEqual(Path(values[0].source_path), path)

    def test_issue19_missing_under_root_is_no_match_outside_stays_unsafe(self) -> None:
        slug = claude._slugify_cwd(str(self.cwd))
        project = self.root / "projects" / slug
        project.mkdir(parents=True, exist_ok=True)
        for _ in range(2_050):
            (project / f"{uuid.uuid4()}.jsonl").write_text("{}\n", encoding="utf-8")
        missing = project / f"{uuid.uuid4()}.jsonl"
        with self.assertRaises(DiagnosticError) as missing_err:
            claude.ADAPTER.list(self.query(ref=str(missing)), ReadBudget())
        self.assertEqual(missing_err.exception.code, "E_NO_MATCH")
        # probe must not fall through into sibling enumeration after missing path
        report = claude.ADAPTER.probe(self.query(ref=str(missing)))
        self.assertEqual(report.state, "supported")
        outside = Path(tempfile.gettempdir()) / f"portable-resume-outside-{uuid.uuid4()}.jsonl"
        with self.assertRaises(DiagnosticError) as outside_err:
            claude.ADAPTER.list(self.query(ref=str(outside)), ReadBudget())
        self.assertEqual(outside_err.exception.code, "E_UNSAFE_PATH")

    def test_issue19_missing_leaf_under_symlink_parent_stays_unsafe(self) -> None:
        real = self.root / "real-project"
        real.mkdir(parents=True)
        projects = self.root / "projects"
        projects.mkdir(parents=True, exist_ok=True)
        link = projects / "linked-slug"
        link.symlink_to(real, target_is_directory=True)
        missing = link / f"{uuid.uuid4()}.jsonl"
        with self.assertRaises(DiagnosticError) as err:
            claude.ADAPTER.list(self.query(ref=str(missing)), ReadBudget())
        self.assertEqual(err.exception.code, "E_UNSAFE_PATH")

    def test_issue19_missing_non_session_layout_under_root_stays_unsafe(self) -> None:
        # Inside root but not projects/<slug>/<uuid>.jsonl — keep fail-closed unsafe.
        weird = self.root / "not-projects" / "file.jsonl"
        with self.assertRaises(DiagnosticError) as err:
            claude.ADAPTER.list(self.query(ref=str(weird)), ReadBudget())
        self.assertEqual(err.exception.code, "E_UNSAFE_PATH")

    def test_issue19_probe_exact_uuid_survives_large_slug_dir(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        slug = claude._slugify_cwd(str(self.cwd))
        project = self.root / "projects" / slug
        project.mkdir(parents=True, exist_ok=True)
        for _ in range(2_050):
            (project / f"{uuid.uuid4()}.jsonl").write_text("{}\n", encoding="utf-8")
        # UUID lives outside the noisy slug dir.
        _, path = self.session(
            [self.turn("user", user_id, None, "elsewhere", 0, sessionId=session_id)],
            identifier=session_id,
            project="other-bucket",
        )
        report = claude.ADAPTER.probe(self.query(ref=session_id))
        self.assertEqual(report.state, "supported")
        values = claude.ADAPTER.list(self.query(ref=session_id), ReadBudget())
        self.assertEqual([item.session_id for item in values], [session_id])
        self.assertEqual(Path(values[0].source_path), path)

    def test_issue19_exact_uuid_under_cwd_slug_survives_thousands_of_projects(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        slug = claude._slugify_cwd(str(self.cwd))
        projects = self.root / "projects"
        for index in range(2_100):
            (projects / f"noise-{index:04d}").mkdir(parents=True, exist_ok=True)
        _, path = self.session(
            [self.turn("user", user_id, None, "needle", 0, sessionId=session_id)],
            identifier=session_id,
            project=slug,
        )
        # Broad enumeration of 2100 project dirs would raise E_LIMIT_EXCEEDED
        # (_PROJECT_DIR_LIMIT is 1024). Direct slug candidate must win first.
        values = claude.ADAPTER.list(self.query(ref=session_id), ReadBudget())
        self.assertEqual([item.session_id for item in values], [session_id])
        self.assertEqual(Path(values[0].source_path), path)
        session = claude.ADAPTER.show(
            ResolvedRef.from_summary(values[0]),
            self.query(ref=session_id),
            ReadBudget(),
        )
        self.assertEqual([turn.content for turn in session.turns], ["needle"])

    def test_issue19_direct_slug_file_rejects_mismatched_recorded_cwd(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        slug = claude._slugify_cwd(str(self.cwd))
        other_cwd = self.root / "other-repo"
        other_cwd.mkdir()
        # File lives under the query cwd slug, but records a different primary cwd.
        path = self.root / "projects" / slug / f"{session_id}.jsonl"
        write_jsonl(
            path,
            [
                {
                    "type": "user",
                    "uuid": user_id,
                    "parentUuid": None,
                    "sessionId": session_id,
                    "cwd": str(other_cwd),
                    "timestamp": stamp(0),
                    "message": {"role": "user", "content": "wrong bucket"},
                }
            ],
        )
        values = claude.ADAPTER.list(self.query(ref=session_id), ReadBudget())
        self.assertEqual(values, [])

    def test_issue19_cwd_mismatched_direct_still_finds_relocated_eligible_copy(self) -> None:
        """Codex P2: slug-file present but wrong cwd must not hide a good copy."""
        session_id = str(uuid.uuid4())
        user_bad, user_good = str(uuid.uuid4()), str(uuid.uuid4())
        slug = claude._slugify_cwd(str(self.cwd))
        other_cwd = self.root / "other-repo"
        other_cwd.mkdir()
        write_jsonl(
            self.root / "projects" / slug / f"{session_id}.jsonl",
            [
                {
                    "type": "user",
                    "uuid": user_bad,
                    "parentUuid": None,
                    "sessionId": session_id,
                    "cwd": str(other_cwd),
                    "timestamp": stamp(0),
                    "message": {"role": "user", "content": "stale slug hit"},
                }
            ],
        )
        good_path = self.root / "projects" / "relocated-bucket" / f"{session_id}.jsonl"
        write_jsonl(
            good_path,
            [
                {
                    "type": "user",
                    "uuid": user_good,
                    "parentUuid": None,
                    "sessionId": session_id,
                    "cwd": str(self.cwd),
                    "timestamp": stamp(1),
                    "message": {"role": "user", "content": "relocated good"},
                }
            ],
        )
        values = claude.ADAPTER.list(self.query(ref=session_id), ReadBudget())
        self.assertEqual(len(values), 1)
        self.assertEqual(Path(values[0].source_path), good_path)
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, None),
            self.query(ref=session_id),
            ReadBudget(),
        )
        self.assertEqual([turn.content for turn in session.turns], ["relocated good"])
        self.assertEqual(Path(session.source_path), good_path)

    def test_issue19_exact_uuid_falls_back_when_slug_candidate_missing(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        # Stored under a non-slug project dir; cwd slug dir is absent.
        _, path = self.session(
            [self.turn("user", user_id, None, "relocated", 0, sessionId=session_id)],
            identifier=session_id,
            project="foreign-bucket",
        )
        values = claude.ADAPTER.list(self.query(ref=session_id), ReadBudget())
        self.assertEqual([item.session_id for item in values], [session_id])
        self.assertEqual(Path(values[0].source_path), path)

    def test_issue19_duplicate_uuid_across_buckets_does_not_pick_wrong_cwd(self) -> None:
        session_id = str(uuid.uuid4())
        user_a, user_b = str(uuid.uuid4()), str(uuid.uuid4())
        slug = claude._slugify_cwd(str(self.cwd))
        other_cwd = self.root / "other-repo"
        other_cwd.mkdir()
        other_slug = claude._slugify_cwd(str(other_cwd))
        # Same UUID basename in two project buckets; only our cwd is eligible.
        write_jsonl(
            self.root / "projects" / other_slug / f"{session_id}.jsonl",
            [
                {
                    "type": "user",
                    "uuid": user_a,
                    "parentUuid": None,
                    "sessionId": session_id,
                    "cwd": str(other_cwd),
                    "timestamp": stamp(0),
                    "message": {"role": "user", "content": "other"},
                }
            ],
        )
        write_jsonl(
            self.root / "projects" / slug / f"{session_id}.jsonl",
            [
                {
                    "type": "user",
                    "uuid": user_b,
                    "parentUuid": None,
                    "sessionId": session_id,
                    "cwd": str(self.cwd),
                    "timestamp": stamp(1),
                    "message": {"role": "user", "content": "mine"},
                }
            ],
        )
        values = claude.ADAPTER.list(self.query(ref=session_id), ReadBudget())
        self.assertEqual(len(values), 1)
        self.assertEqual(Path(values[0].source_path).parent.name, slug)
        session = claude.ADAPTER.show(ResolvedRef.from_summary(values[0]), self.query(ref=session_id), ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["mine"])

    def test_issue19_exact_path_survives_two_thousand_sibling_jsonl(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        slug = claude._slugify_cwd(str(self.cwd))
        project = self.root / "projects" / slug
        project.mkdir(parents=True, exist_ok=True)
        for index in range(2_050):
            sibling = project / f"{uuid.uuid4()}.jsonl"
            sibling.write_text("{}\n", encoding="utf-8")
            del sibling, index
        _, path = self.session(
            [self.turn("user", user_id, None, "among siblings", 0, sessionId=session_id)],
            identifier=session_id,
            project=slug,
        )
        values = claude.ADAPTER.list(self.query(ref=str(path.resolve())), ReadBudget())
        self.assertEqual([item.session_id for item in values], [session_id])
        # reader.probe runs before list/show — exact path must keep capability supported
        # even when the project dir has > scanned_records siblings.
        report = claude.ADAPTER.probe(self.query(ref=str(path.resolve())))
        self.assertEqual(report.state, "supported")


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

    def test_table_signature_requires_text_column_presence_not_affinity(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute(
            """
            CREATE TABLE threads (
                id BLOB,
                rollout_path REAL,
                updated_at_ms INTEGER,
                source NUMERIC,
                cwd ANY,
                archived INTEGER
            )
            """
        )

        self.assertEqual(
            codex_sqlite._table_signature(connection),
            (True, "updated_at_ms"),
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

    def test_database_filters_parent_rows_before_listing_limit(self) -> None:
        first, first_path = self.rollout()
        second, second_path = self.rollout()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        noise = [
            (
                str(uuid.uuid4()),
                f"sessions/missing-{index}.jsonl",
                now_ms + index + 1,
                "subagent",
                str(self.cwd),
                "noise",
                "noise",
                0,
                None,
            )
            for index in range(DEFAULT_BOUNDS.listed_sessions)
        ]
        first_row = list(self.db_row(first, first_path))
        second_row = list(self.db_row(second, second_path, source="vscode"))
        first_row[2] = now_ms
        second_row[2] = now_ms - 1
        self.database(9, [*noise, tuple(first_row), tuple(second_row)])

        values = codex.ADAPTER.list(self.query(), ReadBudget())

        self.assertEqual({item.session_id for item in values}, {first, second})

    def test_rollout_uses_source_and_transcript_budgets(self) -> None:
        identifier = str(uuid.uuid4())
        records = [
            {
                "type": "session_meta",
                "timestamp": stamp(-4),
                "payload": {
                    "id": identifier,
                    "cwd": str(self.cwd),
                    "source": "cli",
                },
            },
            *(
                {
                    "type": "world_state",
                    "payload": {"padding": "x" * 300, "index": index},
                }
                for index in range(3)
            ),
            {
                "type": "response_item",
                "timestamp": stamp(-1),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": "bounded large rollout",
                },
            },
        ]
        _, path = self.rollout(identifier, records=records)
        self.assertGreater(path.stat().st_size, 1_024)
        self.assertLess(path.stat().st_size, 4_096)
        limits = replace(
            DEFAULT_BOUNDS,
            scanned_records=1,
            transcript_records=len(records),
            record_bytes=1_024,
            source_read_bytes=4_096,
        )
        with mock.patch.object(codex, "DEFAULT_BOUNDS", limits):
            session = codex.ADAPTER.show(
                ResolvedRef(identifier, str(path)),
                self.query(),
                ReadBudget(limits),
            )
        self.assertEqual(session.last_user_request, "bounded large rollout")

        records[1]["payload"]["padding"] = "x" * 1_024
        write_jsonl(path, records)
        with mock.patch.object(codex, "DEFAULT_BOUNDS", limits):
            with self.assertRaises(DiagnosticError) as caught:
                codex.ADAPTER.show(
                    ResolvedRef(identifier, str(path)),
                    self.query(),
                    ReadBudget(limits),
                )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_rollout_stream_honors_remaining_source_budget(self) -> None:
        """Plain show streams via stable_scan_lines; second file still respects remaining budget (#8)."""

        _, first = self.rollout()
        _, second = self.rollout()
        remaining = second.stat().st_size - 1
        limits = replace(
            DEFAULT_BOUNDS,
            source_read_bytes=first.stat().st_size + remaining,
        )
        budget = ReadBudget(limits)
        codex._read_rollout(str(first), str(self.root), budget)

        with mock.patch.object(
            codex,
            "stable_scan_lines",
            wraps=codex.stable_scan_lines,
        ) as scan:
            with self.assertRaises(DiagnosticError) as caught:
                codex._read_rollout(str(second), str(self.root), budget)
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
        self.assertTrue(scan.called)

    def test_plain_show_does_not_whole_file_stable_read(self) -> None:
        identifier, path = self.rollout()
        with mock.patch.object(
            codex,
            "stable_read_bytes",
            side_effect=AssertionError("plain show must not whole-file stable_read_bytes"),
        ):
            session = codex.ADAPTER.show(
                ResolvedRef(identifier, str(path)),
                self.query(),
                ReadBudget(),
            )
        self.assertEqual(session.session_id, identifier)
        self.assertEqual(session.last_user_request, "Build feature")

    def test_large_plain_rollout_show_under_default_bounds(self) -> None:
        """~20 MiB synthetic rollout show succeeds without whole-file buffer (#8)."""

        identifier = str(uuid.uuid4())
        path = (
            self.root
            / "sessions"
            / "2026"
            / "07"
            / "20"
            / f"rollout-2026-07-20T00-00-00-{identifier}.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # ~18 MiB with ~3 KiB lines keeps line count under transcript_records (50k).
        target = 18 * 1024 * 1024
        written = 0
        with path.open("wb") as handle:
            meta = {
                "type": "session_meta",
                "timestamp": stamp(-3),
                "payload": {
                    "id": identifier,
                    "cwd": str(self.cwd),
                    "source": "cli",
                    "git": {"branch": "main"},
                },
            }
            line = (json.dumps(meta, separators=(",", ":")) + "\n").encode("utf-8")
            handle.write(line)
            written += len(line)
            # One real user turn, then bulk skipped world_state lines (no normalized turns).
            seed = {
                "type": "response_item",
                "timestamp": stamp(-2),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "seed request"}],
                },
            }
            line = (json.dumps(seed, separators=(",", ":")) + "\n").encode("utf-8")
            handle.write(line)
            written += len(line)
            pad = "x" * 2800
            index = 0
            while written < target:
                record = {
                    "type": "world_state",
                    "payload": {"padding": pad, "index": index},
                }
                line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
                handle.write(line)
                written += len(line)
                index += 1
            # Final distinctive user turn for assertions.
            final = {
                "type": "response_item",
                "timestamp": stamp(-1),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "large rollout complete"}],
                },
            }
            handle.write((json.dumps(final, separators=(",", ":")) + "\n").encode("utf-8"))
        self.assertGreaterEqual(path.stat().st_size, 17 * 1024 * 1024)
        self.assertLess(index + 3, DEFAULT_BOUNDS.transcript_records)
        with mock.patch.object(
            codex,
            "stable_read_bytes",
            side_effect=AssertionError("large plain show must stream"),
        ):
            session = codex.ADAPTER.show(
                ResolvedRef(identifier, str(path)),
                self.query(),
                ReadBudget(),
            )
        self.assertEqual(session.session_id, identifier)
        self.assertEqual(session.last_user_request, "large rollout complete")
        self.assertEqual([turn.content for turn in session.turns], ["seed request", "large rollout complete"])

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

        self.assertEqual(capability.format_id, codex.SQLITE_FORMAT)
        if codex._trusted_zstd() is None:
            self.assertEqual(capability.state, "partial")
            self.assertIn("W_OPTIONAL_ZSTD_UNAVAILABLE", capability.warnings)
        else:
            self.assertEqual(capability.state, "supported")
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

    def test_s_cod_07_zstd_absence_and_malicious_path_degrade_only_provider(self) -> None:
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

    def test_s_cod_08_zstd_corruption_and_limits_are_not_masked(self) -> None:
        compressed, _ = self.rollout(suffix=".jsonl.zst")
        for error in (
            DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=codex.ZSTD_FORMAT),
            DiagnosticError.limit_exceeded(),
        ):
            with self.subTest(code=error.code):
                with mock.patch.object(
                    codex,
                    "_trusted_zstd",
                    return_value="/trusted/zstd",
                ), mock.patch.object(codex, "_decompress_zstd", side_effect=error):
                    with self.assertRaises(DiagnosticError) as caught:
                        codex.ADAPTER.list(self.query(compressed), ReadBudget())
                self.assertEqual(caught.exception.code, error.code)

    def test_zstd_decompression_uses_remaining_source_budget(self) -> None:
        identifier, compressed = self.rollout(suffix=".jsonl.zst")
        encoded = compressed.read_bytes()
        limits = replace(
            DEFAULT_BOUNDS,
            source_read_bytes=len(encoded) * 2,
        )
        with mock.patch.object(
            codex,
            "_decompress_zstd",
            return_value=encoded,
        ) as decoder:
            session = codex.ADAPTER.show(
                ResolvedRef(identifier, str(compressed)),
                self.query(),
                ReadBudget(limits),
            )
        decoder.assert_called_once_with(encoded, max_bytes=len(encoded))
        self.assertEqual(session.session_id, identifier)

    def test_sparse_database_recovers_sessions_via_fs_head_fallback(self) -> None:
        """Recognized but under-filled SQLite activates read-only FS head scan (#7)."""

        identifier, _path = self.rollout()
        self.database(9, [])
        values = codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertEqual(values[0].provider, codex.ROLLOUT_FORMAT)

    def test_stale_database_path_recovers_via_fs_head_fallback(self) -> None:
        """SQL rows whose rollout path cannot resolve still recover from sessions/ (#7)."""

        identifier, path = self.rollout()
        missing = path.parent / f"rollout-2026-07-20T00-00-00-{identifier}-missing.jsonl"
        self.database(9, [self.db_row(identifier, missing)])
        values = codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertEqual(values[0].source_path, str(path))

    def test_probe_does_not_full_walk_sessions_tree(self) -> None:
        """Probe samples sessions/ with a soft cap; never calls full _rollout_paths (#7)."""

        self.rollout()
        with mock.patch.object(
            codex,
            "_rollout_paths",
            side_effect=AssertionError("probe must not full-walk sessions/"),
        ):
            capability = codex.ADAPTER.probe(self.query())
        self.assertEqual(capability.state, "supported")
        self.assertEqual(capability.format_id, codex.ROLLOUT_FORMAT)

    def test_probe_head_uses_byte_window_not_whole_file_scan(self) -> None:
        """Large plain rollouts are discovered from a head window only (#7)."""

        identifier, path = self.rollout()
        # Append a large body after the metadata head so whole-file scanners would
        # pay multi-MB I/O; head window must still recognize the session.
        with path.open("ab") as handle:
            handle.write(b'{"type":"response_item","payload":{"type":"message","role":"assistant","content":"' + (b"x" * 400_000) + b'"}}\n')
        with mock.patch.object(
            codex,
            "stable_scan_lines",
            side_effect=AssertionError("head discovery must not whole-file scan"),
        ):
            capability = codex.ADAPTER.probe(self.query())
            values = codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(capability.state, "supported")
        self.assertEqual(capability.format_id, codex.ROLLOUT_FORMAT)
        self.assertEqual([item.session_id for item in values], [identifier])

    def test_exact_id_db_hit_survives_large_sessions_tree(self) -> None:
        """Verified exact-ID DB rows must not be lost if FS soft-cap stops (#7)."""

        identifier, path = self.rollout()
        self.database(9, [self.db_row(identifier, path)])
        with mock.patch.object(
            codex,
            "_rollout_paths",
            side_effect=AssertionError("exact-ID verified DB hit must skip underfilled FS"),
        ):
            values = codex.ADAPTER.list(self.query(identifier), ReadBudget())
        self.assertEqual([item.session_id for item in values], [identifier])

    def test_exact_id_absent_from_sqlite_still_fs_falls_back(self) -> None:
        """Exact UUID missing from a recognized DB still recovers from sessions/ (#7)."""

        identifier, _path = self.rollout()
        other, other_path = self.rollout()
        self.database(9, [self.db_row(other, other_path)])
        values = codex.ADAPTER.list(self.query(identifier), ReadBudget())
        self.assertEqual([item.session_id for item in values], [identifier])

    def test_issue260_rejected_heads_do_not_exhaust_matching_head_budget(self) -> None:
        """Cwd-rejected metadata heads are provisional, not aggregate admission."""

        target, target_path = self.rollout()
        child = self.cwd / "child"
        child.mkdir()
        for index in range(8):
            identifier = str(uuid.uuid4())
            self.rollout(
                identifier,
                records=[
                    {
                        "type": "session_meta",
                        "timestamp": stamp(-20 - index),
                        "payload": {
                            "id": identifier,
                            "cwd": str(child / str(index)),
                            "source": "cli",
                        },
                    },
                    {
                        "type": "world_state",
                        "payload": {"synthetic": True, "padding": "x" * 300},
                    },
                ],
            )
        # Deterministically inspect every non-match before the matching rollout
        # without moving the target outside the default listing age window.
        target_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
        os.utime(target_path, ns=(target_ns, target_ns))
        for index, path in enumerate(target_path.parent.glob("*.jsonl"), start=1):
            if path != target_path:
                newer = target_ns + index
                os.utime(path, ns=(newer, newer))
        limits = replace(DEFAULT_BOUNDS, source_read_bytes=1_024)
        budget = ReadBudget(limits)

        values = codex.ADAPTER.list(self.query(), budget)

        self.assertEqual([item.session_id for item in values], [target])
        self.assertLessEqual(budget.bytes_read, target_path.stat().st_size)

    def test_issue260_parent_cwd_miss_is_empty_after_many_leaf_heads(self) -> None:
        child = self.cwd / "child"
        child.mkdir()
        for index in range(8):
            identifier = str(uuid.uuid4())
            self.rollout(
                identifier,
                records=[
                    {
                        "type": "session_meta",
                        "timestamp": stamp(-index),
                        "payload": {
                            "id": identifier,
                            "cwd": str(child / str(index)),
                            "source": "cli",
                        },
                    },
                    {
                        "type": "world_state",
                        "payload": {"synthetic": True, "padding": "x" * 300},
                    },
                ],
            )

        budget = ReadBudget(replace(DEFAULT_BOUNDS, source_read_bytes=1_024))
        self.assertEqual(codex.ADAPTER.list(self.query(), budget), [])
        self.assertEqual(budget.bytes_read, 0)

    def test_issue260_exact_uuid_uses_sparse_exact_discovery(self) -> None:
        identifier, _path = self.rollout()
        with mock.patch.object(
            codex,
            "_rollout_paths",
            side_effect=AssertionError("exact UUID must not build the broad rollout list"),
        ), mock.patch.object(
            codex,
            "_read_rollout_head",
            wraps=codex._read_rollout_head,
        ) as head:
            values = codex.ADAPTER.list(self.query(identifier), ReadBudget())

        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertEqual(head.call_count, 1)

    def test_issue260_exact_uuid_finds_target_beyond_broad_entry_cap(self) -> None:
        identifier = str(uuid.uuid4())
        old_day = self.root / "sessions" / "2026" / "07" / "19"
        target = old_day / f"rollout-2026-07-19T00-00-00-{identifier}.jsonl"
        write_jsonl(
            target,
            [{"type": "session_meta", "timestamp": stamp(), "payload": {"id": identifier, "cwd": str(self.cwd), "source": "cli"}}],
        )
        new_day = self.root / "sessions" / "2026" / "07" / "20"
        new_day.mkdir(parents=True)
        for _index in range(DEFAULT_BOUNDS.scanned_records + 1):
            noise = str(uuid.uuid4())
            (new_day / f"rollout-2026-07-20T00-00-00-{noise}.jsonl").write_bytes(b"{}\n")

        values = codex.ADAPTER.list(self.query(identifier), ReadBudget())

        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertEqual(Path(values[0].source_path), target)

    def test_issue260_exact_uuid_orders_active_archive_collision_by_mtime(self) -> None:
        identifier, active = self.rollout()
        _same, archived = self.rollout(identifier, archived=True)
        active_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
        os.utime(active, ns=(active_ns, active_ns))
        os.utime(archived, ns=(active_ns + 1_000_000_000, active_ns + 1_000_000_000))

        values = codex.ADAPTER.list(self.query(identifier), ReadBudget())

        self.assertEqual(len(values), 1)
        self.assertEqual(Path(values[0].source_path), archived)

    def test_issue260_exact_show_rejects_match_before_incomplete_archive_scan(self) -> None:
        identifier, _active = self.rollout()
        _same, _archived = self.rollout(identifier, archived=True)
        limits = replace(codex.DEFAULT_BOUNDS, transcript_records=8)
        archive_day = self.root / "archived_sessions" / "2026" / "07" / "20"
        for _index in range(8):
            noise = str(uuid.uuid4())
            (archive_day / f"rollout-2026-07-20T00-00-00-{noise}.jsonl").write_bytes(b"{}\n")

        with mock.patch.object(codex, "DEFAULT_BOUNDS", limits):
            with self.assertRaises(DiagnosticError) as caught:
                codex.ADAPTER.show(
                    ResolvedRef(identifier, None),
                    self.query(identifier),
                    ReadBudget(),
                )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_issue260_exact_show_rejects_incomplete_no_match(self) -> None:
        identifier = str(uuid.uuid4())
        day = self.root / "sessions" / "2026" / "07" / "20"
        day.mkdir(parents=True)
        for _index in range(9):
            noise = str(uuid.uuid4())
            (day / f"rollout-2026-07-20T00-00-00-{noise}.jsonl").write_bytes(b"{}\n")

        with mock.patch.object(
            codex,
            "DEFAULT_BOUNDS",
            replace(codex.DEFAULT_BOUNDS, transcript_records=8),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                codex.ADAPTER.show(
                    ResolvedRef(identifier, None),
                    self.query(identifier),
                    ReadBudget(),
                )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_issue260_exact_show_complete_unique_and_collision_are_deterministic(self) -> None:
        unique, _path = self.rollout()
        shown = codex.ADAPTER.show(
            ResolvedRef(unique, None),
            self.query(unique),
            ReadBudget(),
        )
        self.assertEqual(shown.session_id, unique)

        collision, _active = self.rollout()
        _same, _archived = self.rollout(collision, archived=True)
        with self.assertRaises(DiagnosticError) as caught:
            codex.ADAPTER.show(
                ResolvedRef(collision, None),
                self.query(collision),
                ReadBudget(),
            )
        self.assertEqual(caught.exception.code, "E_NO_MATCH")

    def test_issue260_exact_path_short_circuits_broad_discovery(self) -> None:
        identifier, path = self.rollout()
        with mock.patch.object(
            codex,
            "_rollout_paths",
            side_effect=AssertionError("approved exact path must not enumerate rollouts"),
        ):
            values = codex.ADAPTER.list(self.query(str(path)), ReadBudget())

        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertEqual(Path(values[0].source_path), path)

    def test_issue260_exact_path_preserves_archive_and_path_safety(self) -> None:
        archived, archived_path = self.rollout(archived=True)
        self.assertEqual(
            [item.session_id for item in codex.ADAPTER.list(self.query(str(archived_path)), ReadBudget())],
            [archived],
        )

        outside = Path(self.temp.name).parent / f"rollout-2026-07-20T00-00-00-{uuid.uuid4()}.jsonl"
        outside.write_text("{}\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        with self.assertRaises(DiagnosticError) as escaped:
            codex.ADAPTER.list(self.query(str(outside)), ReadBudget())
        self.assertEqual(escaped.exception.code, "E_UNSAFE_PATH")

        link_id = str(uuid.uuid4())
        link = self.root / "sessions" / "2026" / "07" / "20" / (
            f"rollout-2026-07-20T00-00-00-{link_id}.jsonl"
        )
        link.parent.mkdir(parents=True)
        link.symlink_to(archived_path)
        with self.assertRaises(DiagnosticError) as linked:
            codex.ADAPTER.list(self.query(str(link)), ReadBudget())
        self.assertEqual(linked.exception.code, "E_UNSAFE_PATH")

    def test_issue260_broad_zstd_discovery_preserves_matches_provisionally(self) -> None:
        matching, matching_path = self.rollout(suffix=".jsonl.zst")
        child = self.cwd / "child"
        child.mkdir()
        other = str(uuid.uuid4())
        _other, other_path = self.rollout(
            other,
            suffix=".jsonl.zst",
            records=[
                {"type": "session_meta", "timestamp": stamp(), "payload": {"id": other, "cwd": str(child), "source": "cli"}},
            ],
        )
        now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
        os.utime(matching_path, ns=(now_ns, now_ns))
        os.utime(other_path, ns=(now_ns + 1_000_000_000, now_ns + 1_000_000_000))
        budget = ReadBudget(replace(DEFAULT_BOUNDS, source_read_bytes=matching_path.stat().st_size * 2 + 128))
        with mock.patch.object(codex, "_trusted_zstd", return_value="/trusted/zstd"), mock.patch.object(
            codex, "_decompress_zstd", side_effect=lambda data, *, max_bytes: data
        ) as decoder:
            values = codex.ADAPTER.list(self.query(), budget)

        self.assertEqual([item.session_id for item in values], [matching])
        self.assertEqual(decoder.call_count, 2)
        self.assertLessEqual(budget.bytes_read, matching_path.stat().st_size * 2)

    def test_issue260_exact_zstd_keeps_real_decompressed_limit(self) -> None:
        identifier, path = self.rollout(suffix=".jsonl.zst")
        with mock.patch.object(codex, "_trusted_zstd", return_value="/trusted/zstd"), mock.patch.object(
            codex,
            "_decompress_zstd",
            side_effect=DiagnosticError.limit_exceeded(),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                codex.ADAPTER.list(self.query(identifier), ReadBudget())
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
        self.assertEqual(codex._rollout_id(str(path)), identifier)

    def test_list_fs_soft_limit_keeps_db_rows(self) -> None:
        """Soft FS fallback cap must merge, not raise away, verified DB rows (#7)."""

        identifier, path = self.rollout()
        self.database(9, [self.db_row(identifier, path)])
        # Force sparse FS path with soft_limit; hard walk would raise.
        with mock.patch.object(
            codex,
            "_walk_rollouts",
            side_effect=lambda *args, **kwargs: (_ for _ in ()).throw(
                DiagnosticError.limit_exceeded()
            )
            if not kwargs.get("soft_limit")
            else [],
        ):
            # underfilled with no exact ref → FS soft path returns [] and keeps DB.
            values = codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual([item.session_id for item in values], [identifier])

    def test_probe_sample_processes_names_at_visit_cap(self) -> None:
        """Visit-budget exhaustion mid-listing still processes collected names (#7)."""

        day = self.root / "sessions" / "2026" / "07" / "20"
        day.mkdir(parents=True)
        # 129 rollouts in one day directory: more than default visit cap.
        identifiers: list[str] = []
        for index in range(codex._PROBE_VISIT_CAP + 1):
            identifier = str(uuid.uuid4())
            identifiers.append(identifier)
            path = day / f"rollout-2026-07-20T12-00-00-{identifier}.jsonl"
            write_jsonl(
                path,
                [
                    {
                        "type": "session_meta",
                        "timestamp": stamp(-1),
                        "payload": {
                            "id": identifier,
                            "cwd": str(self.cwd),
                            "source": "cli",
                        },
                    }
                ],
            )
        sample = codex._sample_rollout_paths(
            str(self.root),
            max_visits=codex._PROBE_VISIT_CAP,
            max_files=8,
        )
        self.assertGreaterEqual(len(sample), 1)
        self.assertTrue(
            any(codex._rollout_id(path) in identifiers for path in sample),
            "capped day-dir listing must still yield rollouts from collected names",
        )
        capability = codex.ADAPTER.probe(self.query())
        self.assertEqual(capability.state, "supported")

    def test_unknown_database_schema_falls_back_and_retains_rollout_warning(self) -> None:
        identifier = str(uuid.uuid4())
        records = [
            {
                "type": "session_meta",
                "timestamp": stamp(-3),
                "payload": {
                    "id": identifier,
                    "cwd": str(self.cwd),
                    "source": "cli",
                },
            },
            {"type": "future_rollout_step", "payload": {"synthetic": True}},
            {
                "type": "response_item",
                "timestamp": stamp(-1),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "compatible fallback"}],
                },
            },
        ]
        self.rollout(identifier, records=records)
        self.database(10, [], unknown=True)

        capability = codex.ADAPTER.probe(self.query())
        values = codex.ADAPTER.list(self.query(), ReadBudget())

        self.assertEqual(capability.evidence, (codex.ROLLOUT_FORMAT,))
        self.assertIn("W_UNKNOWN_RECORD_SKIPPED", capability.warnings)
        self.assertEqual([value.session_id for value in values], [identifier])
        self.assertEqual(values[0].provider, codex.ROLLOUT_FORMAT)
        self.assertIn("W_UNKNOWN_RECORD_SKIPPED", values[0].warnings)

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

    def test_s_cod_11_hot_journal_degrades_to_fs_rollout(self) -> None:
        # #196: hot journal must not erase plain rollout recovery.
        identifier, rollout = self.rollout()
        database = self.database(9, [self.db_row(identifier, rollout)])
        Path(str(database) + "-journal").write_bytes(b"synthetic hot journal")
        values = codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertIn("W_STALE_INDEX", values[0].warnings or ())
        capability = codex.ADAPTER.probe(self.query())
        self.assertIn(capability.state, {"supported", "partial"})
        self.assertNotEqual(capability.state, "unsafe")

    def test_issue196_busy_sqlite_probe_and_list_use_rollout(self) -> None:
        identifier, rollout = self.rollout()
        self.database(9, [self.db_row(identifier, rollout)])
        before = tree_snapshot(self.root)
        def busy(*_args: object, **_kwargs: object) -> None:
            raise DiagnosticError.source_busy(provider=codex.SQLITE_FORMAT)

        # probe uses codex._database_connection; list uses codex_sqlite via _database_summaries.
        with mock.patch.object(codex, "_database_connection", side_effect=busy), mock.patch.object(
            codex, "_database_summaries", side_effect=busy
        ):
            capability = codex.ADAPTER.probe(self.query())
            values = codex.ADAPTER.list(self.query(), ReadBudget())
            shown = codex.ADAPTER.show(
                ResolvedRef.from_summary(values[0]),
                self.query(),
                ReadBudget(),
            )
        self.assertIn(capability.state, {"supported", "partial"})
        self.assertNotEqual(capability.state, "unsafe")
        self.assertIn("W_STALE_INDEX", capability.warnings)
        self.assertEqual(capability.format_id, codex.ROLLOUT_FORMAT)
        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertIn("W_STALE_INDEX", values[0].warnings or ())
        self.assertEqual(shown.session_id, identifier)
        self.assertEqual(before, tree_snapshot(self.root))

    def test_issue263_live_wal_sqlite_probe_list_show_use_rollout(self) -> None:
        identifier, _rollout = self.rollout()
        database = self.database(9, [])
        Path(str(database) + "-wal").write_bytes(b"synthetic wal")
        Path(str(database) + "-shm").write_bytes(b"synthetic shm")
        before = tree_snapshot(self.root)
        lowered = replace(DEFAULT_BOUNDS, sqlite_snapshot_bytes=1)
        with mock.patch.object(codex_sqlite, "DEFAULT_BOUNDS", lowered):
            capability = codex.ADAPTER.probe(self.query())
            values = codex.ADAPTER.list(self.query(), ReadBudget())
            shown = codex.ADAPTER.show(
                ResolvedRef.from_summary(values[0]),
                self.query(),
                ReadBudget(),
            )
        self.assertEqual(capability.format_id, codex.ROLLOUT_FORMAT)
        self.assertIn("W_STALE_INDEX", capability.warnings)
        self.assertEqual([item.session_id for item in values], [identifier])
        self.assertIn("W_STALE_INDEX", values[0].warnings)
        self.assertIn("W_STALE_INDEX", shown.warnings)
        self.assertEqual(before, tree_snapshot(self.root))

    def test_show_drops_list_only_truncation_but_keeps_stale_index_warning(self) -> None:
        identifier, rollout = self.rollout()
        shown = codex.ADAPTER.show(
            ResolvedRef(
                identifier,
                str(rollout),
                provider=codex.ROLLOUT_FORMAT,
                warnings=("W_TRUNCATED", "W_STALE_INDEX"),
            ),
            self.query(),
            ReadBudget(),
        )
        self.assertNotIn("W_TRUNCATED", shown.warnings)
        self.assertIn("W_STALE_INDEX", shown.warnings)

    def test_issue198_dict_source_subagent_soft_skipped(self) -> None:
        parent_id, _parent = self.rollout()
        sub_id = str(uuid.uuid4())
        sub_records = [
            {
                "type": "session_meta",
                "timestamp": stamp(-2),
                "payload": {
                    "id": sub_id,
                    "cwd": str(self.cwd),
                    "source": {
                        "subagent": {
                            "thread_spawn": {
                                "parent_thread_id": parent_id,
                                "depth": 1,
                            }
                        }
                    },
                },
            },
            {
                "type": "response_item",
                "timestamp": stamp(-1),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "subagent only"}],
                },
            },
        ]
        self.rollout(sub_id, records=sub_records)
        # Must not raise TypeError / E_INVARIANT; parent remains listable.
        values = codex.ADAPTER.list(self.query(), ReadBudget())
        ids = [item.session_id for item in values]
        self.assertIn(parent_id, ids)
        self.assertNotIn(sub_id, ids)
        # Direct meta path raises typed unsupported, never TypeError.
        with self.assertRaises(DiagnosticError) as caught:
            codex._session_meta(sub_records, sub_id, codex.ROLLOUT_FORMAT)
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_common_corrupt_bounds_busy_and_injection(self) -> None:
        identifier, path = self.rollout()
        path.write_bytes(path.read_bytes() + b"{broken}\n")
        with self.assertRaises(DiagnosticError) as corrupt:
            codex.ADAPTER.list(self.query(), ReadBudget())
        self.assertEqual(corrupt.exception.code, "E_CORRUPT_RECORD")
        # Discovery heads charge scanned_records (#7), not full transcript_records.
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
        with mock.patch.object(
            codex, "stable_read_bytes", side_effect=DiagnosticError.source_busy()
        ), mock.patch.object(
            codex, "stable_scan_lines", side_effect=DiagnosticError.source_busy()
        ), mock.patch.object(
            codex, "stable_read_windows", side_effect=DiagnosticError.source_busy()
        ):
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
            # Show charges transcript_records via stable_scan_lines (issue #11), not scanned_records.
            cursor.ADAPTER.show(
                ResolvedRef.from_summary(summary),
                self.query(),
                ReadBudget(Bounds(transcript_records=1)),
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
