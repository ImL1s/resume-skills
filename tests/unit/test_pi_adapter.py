from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.pi import ADAPTER, FORMAT_ID_V2, FORMAT_ID_V3
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from portable_resume.reader import run
from tests.helpers.core import tree_snapshot


FIXTURES = Path("tests/fixtures/pi")
CWD = "/tmp/project"


def agent_root(case: str) -> Path:
    return (FIXTURES / case / "agent").resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(source="pi", ref=ref, cwd=CWD, source_root=str(root), within_min=0, **kwargs)


def resolved(items, session_id: str) -> ResolvedRef:
    return ResolvedRef.from_summary(next(item for item in items if item.session_id == session_id))


class PiAdapterTests(unittest.TestCase):
    def test_list_metadata_only_from_fixture(self) -> None:
        root = agent_root("s-pi-01-basic-v3")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertGreaterEqual(len(summaries), 1)
        self.assertEqual(summaries[0].source, "pi")
        self.assertEqual(summaries[0].session_id, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(summaries[0].provider, FORMAT_ID_V3)

    def test_show_basic_v3_fixture(self) -> None:
        root = agent_root("s-pi-01-basic-v3")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        session = ADAPTER.show(resolved(summaries, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            [
                "synthetic user request for basic v3 branch",
                "synthetic assistant reply on the active branch",
            ],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_show_active_branch_skips_compacted_interior(self) -> None:
        root = agent_root("s-pi-02-branch-compaction")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        session = ADAPTER.show(resolved(summaries, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), current, ReadBudget())
        contents = [turn.content for turn in session.turns]
        self.assertEqual(contents[0], "synthetic opening user turn")
        self.assertEqual(contents[1], "synthetic first assistant reply")
        self.assertIn("compaction", contents[2].lower())
        self.assertEqual(contents[3], "synthetic post-compaction user turn")
        self.assertEqual(contents[4], "synthetic active-leaf reply after compaction")
        combined = " ".join(contents)
        self.assertNotIn("alternate-branch", combined)
        self.assertNotIn("summarized", combined)

    def test_show_tool_custom_and_v2_compat(self) -> None:
        root = agent_root("s-pi-03-tool-and-custom")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        session = ADAPTER.show(resolved(summaries, "cccccccc-cccc-cccc-cccc-cccccccccccc"), current, ReadBudget())
        roles = [turn.role for turn in session.turns]
        self.assertEqual(roles, ["user", "tool", "tool", "user", "assistant"])
        self.assertIn("synthetic custom extension context", [turn.content for turn in session.turns])

        v2_root = agent_root("s-pi-05-v2-compat")
        v2_current = query(v2_root)
        v2_summaries = ADAPTER.list(v2_current, ReadBudget())
        self.assertEqual(v2_summaries[0].provider, FORMAT_ID_V2)
        v2_session = ADAPTER.show(
            resolved(v2_summaries, "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
            v2_current,
            ReadBudget(),
        )
        self.assertEqual(
            [turn.content for turn in v2_session.turns],
            [
                "synthetic v2 compatibility user turn",
                "synthetic v2 compatibility assistant reply",
            ],
        )

    def test_handoff_uses_authored_request_and_preserves_custom_message_evidence(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        exit_code = run(
            [
                "pi",
                "show",
                "latest",
                "--cwd",
                CWD,
                "--within-min",
                "0",
                "--source-root",
                str(agent_root("s-pi-03-tool-and-custom")),
                "--format",
                "handoff",
            ],
            stdout=output,
            stderr=error,
        )

        self.assertEqual(exit_code, 0, msg=error.getvalue())
        handoff = output.getvalue()
        request_start = handoff.index("### Latest explicit user request")
        assistant_start = handoff.index("### Latest assistant action")
        transcript_start = handoff.index("### Bounded transcript evidence")
        request_section = handoff[request_start:assistant_start]
        transcript_section = handoff[transcript_start:]
        self.assertIn("> synthetic request needing tools", request_section)
        self.assertNotIn("synthetic custom extension context", request_section)
        self.assertIn("synthetic custom extension context", transcript_section)

    def test_custom_message_only_handoff_has_no_user_request_and_hides_display_false(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            agent = Path(temporary) / "agent"
            session_dir = agent / "sessions" / "--tmp-project--"
            session_dir.mkdir(parents=True)
            session_id = "11111111-2222-4333-8444-555555555555"
            records = (
                {
                    "type": "session",
                    "version": 3,
                    "id": session_id,
                    "timestamp": "2024-01-01T00:00:00.000Z",
                    "cwd": CWD,
                },
                {
                    "type": "custom_message",
                    "id": "custom-visible",
                    "parentId": None,
                    "timestamp": "2024-01-01T00:00:01.000Z",
                    "customType": "synthetic-extension",
                    "content": "visible extension context",
                    "display": True,
                },
                {
                    "type": "custom_message",
                    "id": "custom-hidden",
                    "parentId": "custom-visible",
                    "timestamp": "2024-01-01T00:00:02.000Z",
                    "customType": "synthetic-extension",
                    "content": "hidden extension context",
                    "display": False,
                },
            )
            session_path = session_dir / f"20240101T000000_{session_id}.jsonl"
            session_path.write_text(
                "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            error = io.StringIO()
            exit_code = run(
                [
                    "pi",
                    "show",
                    "latest",
                    "--cwd",
                    CWD,
                    "--within-min",
                    "0",
                    "--source-root",
                    str(agent),
                    "--format",
                    "handoff",
                ],
                stdout=output,
                stderr=error,
            )

        self.assertEqual(exit_code, 0, msg=error.getvalue())
        handoff = output.getvalue()
        request_start = handoff.index("### Latest explicit user request")
        assistant_start = handoff.index("### Latest assistant action")
        transcript_start = handoff.index("### Bounded transcript evidence")
        request_section = handoff[request_start:assistant_start]
        transcript_section = handoff[transcript_start:]
        self.assertIn("> _(not persisted)_", request_section)
        self.assertIn("visible extension context", transcript_section)
        self.assertNotIn("hidden extension context", handoff)

    def test_corrupt_interior_raises_e_corrupt_record(self) -> None:
        root = agent_root("s-pi-04-corrupt-interior")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(resolved(summaries, "dddddddd-dddd-dddd-dddd-dddddddddddd"), current, ReadBudget())
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_list_corrupt_interior_succeeds_with_w_broken_chain(self) -> None:
        root = agent_root("s-pi-04-corrupt-interior")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        match = next(
            item for item in summaries if item.session_id == "dddddddd-dddd-dddd-dddd-dddddddddddd"
        )
        self.assertIn("W_BROKEN_CHAIN", match.warnings)

    def test_exact_path_does_not_scan_sibling_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            agent = base / "agent"
            primary = agent / "sessions" / "--tmp-project--"
            sibling = agent / "sessions" / "--other-project--"
            primary.mkdir(parents=True)
            sibling.mkdir(parents=True)
            target = primary / "20240101T000000_11111111-1111-1111-1111-111111111111.jsonl"
            decoy = sibling / "20240101T000000_22222222-2222-2222-2222-222222222222.jsonl"
            header = {
                "type": "session",
                "version": 3,
                "id": "11111111-1111-1111-1111-111111111111",
                "timestamp": "2024-01-01T00:00:00.000Z",
                "cwd": CWD,
            }
            user = {
                "type": "message",
                "id": "u1",
                "parentId": None,
                "timestamp": "2024-01-01T00:00:01.000Z",
                "message": {"role": "user", "content": "exact path only", "timestamp": 1},
            }
            target.write_text(
                "\n".join(json.dumps(record, separators=(",", ":")) for record in (header, user)) + "\n",
                encoding="utf-8",
            )
            decoy_header = {**header, "id": "22222222-2222-2222-2222-222222222222"}
            decoy_user = {**user, "id": "u2", "message": {"role": "user", "content": "sibling leak", "timestamp": 1}}
            decoy.write_text(
                "\n".join(json.dumps(record, separators=(",", ":")) for record in (decoy_header, decoy_user)) + "\n",
                encoding="utf-8",
            )
            exact = query(agent, ref=str(target.resolve()))
            summaries = ADAPTER.list(exact, ReadBudget())
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].session_id, "11111111-1111-1111-1111-111111111111")

    def test_unsupported_future_version_is_e_unsupported_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            agent = base / "agent" / "sessions" / "--tmp-project--"
            agent.mkdir(parents=True)
            path = agent / "future.jsonl"
            header = {
                "type": "session",
                "version": 99,
                "id": "99999999-9999-9999-9999-999999999999",
                "timestamp": "2024-01-01T00:00:00.000Z",
                "cwd": CWD,
            }
            path.write_text(json.dumps(header) + "\n", encoding="utf-8")
            current = query(base / "agent")
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(current, ReadBudget())
            self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")


    def test_list_uses_tail_window_timestamps_for_large_files(self) -> None:
        """Regression: mid-line tail skip must not discard the whole tail chunk."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            agent = base / "agent" / "sessions" / "--tmp-project--"
            agent.mkdir(parents=True)
            path = agent / "wide.jsonl"
            session_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
            lines = [
                json.dumps(
                    {
                        "type": "session",
                        "version": 3,
                        "id": session_id,
                        "timestamp": "2020-01-01T00:00:00.000Z",
                        "cwd": CWD,
                    },
                    separators=(",", ":"),
                )
            ]
            parent = None
            # Inflate past the 64 KiB metadata head window.
            padding = "p" * 800
            for index in range(120):
                entry_id = f"w{index:04d}"
                stamp = f"2024-06-01T00:{index // 60:02d}:{index % 60:02d}.000Z"
                lines.append(
                    json.dumps(
                        {
                            "type": "message",
                            "id": entry_id,
                            "parentId": parent,
                            "timestamp": stamp,
                            "message": {
                                "role": "user",
                                "content": f"wide {index} {padding}",
                                "timestamp": index,
                            },
                        },
                        separators=(",", ":"),
                    )
                )
                parent = entry_id
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertGreater(path.stat().st_size, 64 * 1024)
            summaries = ADAPTER.list(query(base / "agent"), ReadBudget())
            self.assertEqual(len(summaries), 1)
            self.assertIsNotNone(summaries[0].updated_at)
            self.assertTrue(
                summaries[0].updated_at.startswith("2024-06-01"),
                msg=summaries[0].updated_at,
            )

    def test_show_honors_max_tool_chars(self) -> None:
        root = agent_root("s-pi-03-tool-and-custom")
        current = query(root, max_tool_chars=12)
        summaries = ADAPTER.list(current, ReadBudget())
        session = ADAPTER.show(
            resolved(summaries, "cccccccc-cccc-cccc-cccc-cccccccccccc"),
            current,
            ReadBudget(),
        )
        tool_turns = [turn for turn in session.turns if turn.role == "tool"]
        self.assertTrue(tool_turns)
        for turn in tool_turns:
            self.assertLessEqual(len(turn.content or ""), 12)

    def test_non_utf8_header_returns_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            agent = base / "agent" / "sessions" / "--tmp-project--"
            agent.mkdir(parents=True)
            path = agent / "bad-header.jsonl"
            path.write_bytes(b"\xff\xfe{" + b'"type":"session"}\n')
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(query(base / "agent"), ReadBudget())
            self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"})

    def test_large_synthetic_hits_budget_diagnostics(self) -> None:
        min_bytes = 17 * 1024 * 1024
        max_bytes = 30 * 1024 * 1024
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            agent = base / "agent" / "sessions" / "--tmp-project--"
            agent.mkdir(parents=True)
            path = agent / "large.jsonl"
            session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            header = {
                "type": "session",
                "version": 3,
                "id": session_id,
                "timestamp": "2024-01-01T00:00:00.000Z",
                "cwd": CWD,
            }

            def build_lines(pad_len: int) -> list[str]:
                lines = [json.dumps(header, separators=(",", ":"))]
                parent = None
                padding = "x" * pad_len
                for index in range(50_001):
                    entry_id = f"r{index:06d}"
                    record = {
                        "type": "message",
                        "id": entry_id,
                        "parentId": parent,
                        "timestamp": "2024-01-01T00:00:01.000Z",
                        "message": {
                            "role": "user",
                            "content": f"line {index}{padding}",
                            "timestamp": index,
                        },
                    }
                    lines.append(json.dumps(record, separators=(",", ":")))
                    parent = entry_id
                return lines

            def file_size(lines: list[str]) -> int:
                return sum(len(line.encode("utf-8")) + 1 for line in lines)

            pad_len = 0
            lines = build_lines(pad_len)
            size = file_size(lines)
            if size < min_bytes:
                pad_len = max(1, (min_bytes - size) // 50_001)
                lines = build_lines(pad_len)
                size = file_size(lines)
            while size < min_bytes:
                pad_len += 1
                lines = build_lines(pad_len)
                size = file_size(lines)
            while size > max_bytes and pad_len > 0:
                pad_len -= 1
                lines = build_lines(pad_len)
                size = file_size(lines)
            self.assertGreaterEqual(size, min_bytes, msg=f"fixture size {size} below 17 MiB")
            self.assertLessEqual(size, max_bytes, msg=f"fixture size {size} above 30 MiB")

            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertGreaterEqual(path.stat().st_size, min_bytes)
            self.assertLessEqual(path.stat().st_size, max_bytes)
            current = query(base / "agent")
            summaries = ADAPTER.list(current, ReadBudget())
            ref = resolved(summaries, session_id)
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.show(ref, current, ReadBudget())
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
