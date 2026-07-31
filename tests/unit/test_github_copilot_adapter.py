from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.github_copilot import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from portable_resume.reader import run
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/github-copilot")
CWD = "/tmp/project"
OTHER_CWD = "/tmp/other"
BASIC_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CORRUPT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="github-copilot",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class GitHubCopilotAdapterTests(unittest.TestCase):
    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-gcp-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        self.assertEqual(summaries[0].cwd, CWD)
        session = ADAPTER.show(
            ResolvedRef.from_summary(summaries[0]), current, ReadBudget()
        )
        contents = [turn.content for turn in session.turns]
        self.assertEqual(
            contents,
            [
                "synthetic copilot user prompt",
                "synthetic copilot assistant reply",
                "bash",
            ],
        )
        joined = " ".join(contents)
        self.assertNotIn("must omit", joined)
        self.assertNotIn("secret cmd", joined)
        self.assertNotIn("secret out", joined)
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported(self) -> None:
        report = ADAPTER.probe(query(fixture_root("s-gcp-01-user-basic")))
        self.assertEqual(report.state, "supported")

    def test_cwd_filters_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # two projects under one store
            for sid, cwd, stamp, prompt in (
                (BASIC_ID, CWD, "2024-01-01T12:00:00.000Z", "project prompt"),
                (OTHER_ID, OTHER_CWD, "2024-01-02T12:00:00.000Z", "other newer"),
            ):
                chats = root / "session-state" / sid
                chats.mkdir(parents=True)
                lines = [
                    {
                        "type": "session.start",
                        "id": "e1",
                        "parentId": None,
                        "timestamp": stamp,
                        "data": {
                            "sessionId": sid,
                            "startTime": stamp,
                            "context": {"cwd": cwd},
                        },
                    },
                    {
                        "type": "user.message",
                        "id": "e2",
                        "parentId": "e1",
                        "timestamp": stamp,
                        "data": {"content": prompt},
                    },
                    {
                        "type": "assistant.message",
                        "id": "e3",
                        "parentId": "e2",
                        "timestamp": stamp,
                        "data": {"content": "reply"},
                    },
                ]
                (chats / "events.jsonl").write_text(
                    "".join(json.dumps(line) + "\n" for line in lines),
                    encoding="utf-8",
                )
            listed = ADAPTER.list(query(root), ReadBudget())
            self.assertEqual([item.session_id for item in listed], [BASIC_ID])
            other = ADAPTER.list(
                Query(
                    source="github-copilot",
                    ref=None,
                    cwd=OTHER_CWD,
                    source_root=str(root),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual([item.session_id for item in other], [OTHER_ID])

    def test_corrupt_fails_closed_on_show(self) -> None:
        root = fixture_root("s-gcp-03-corrupt")
        self.assertEqual(ADAPTER.list(query(root), ReadBudget()), [])
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(
                ResolvedRef(session_id=CORRUPT_ID, source_path=""),
                query(root, ref=CORRUPT_ID),
                ReadBudget(),
            )
        self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_NO_MATCH"})

    def test_exact_file_source_root(self) -> None:
        root = fixture_root("s-gcp-01-user-basic")
        events = (
            root
            / "session-state"
            / BASIC_ID
            / "events.jsonl"
        )
        listed = ADAPTER.list(
            Query(
                source="github-copilot",
                ref=None,
                cwd=CWD,
                source_root=str(events),
                within_min=0,
            ),
            ReadBudget(),
        )
        self.assertEqual([item.session_id for item in listed], [BASIC_ID])

    def test_exact_file_source_root_does_not_list_siblings(self) -> None:
        """exact events.jsonl must not widen to sibling session-state entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for sid, cwd, stamp, prompt in (
                (BASIC_ID, CWD, "2024-01-01T12:00:00.000Z", "older session"),
                (OTHER_ID, CWD, "2024-01-02T12:00:00.000Z", "newer sibling same cwd"),
            ):
                sess = root / "session-state" / sid
                sess.mkdir(parents=True)
                lines = [
                    {
                        "type": "session.start",
                        "id": "e1",
                        "parentId": None,
                        "timestamp": stamp,
                        "data": {
                            "sessionId": sid,
                            "startTime": stamp,
                            "context": {"cwd": cwd},
                        },
                    },
                    {
                        "type": "user.message",
                        "id": "e2",
                        "parentId": "e1",
                        "timestamp": stamp,
                        "data": {"content": prompt},
                    },
                    {
                        "type": "assistant.message",
                        "id": "e3",
                        "parentId": "e2",
                        "timestamp": stamp,
                        "data": {"content": "reply"},
                    },
                ]
                (sess / "events.jsonl").write_text(
                    "".join(json.dumps(line) + "\n" for line in lines),
                    encoding="utf-8",
                )
            exact = root / "session-state" / BASIC_ID / "events.jsonl"
            listed = ADAPTER.list(
                Query(
                    source="github-copilot",
                    ref=None,
                    cwd=CWD,
                    source_root=str(exact),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual([item.session_id for item in listed], [BASIC_ID])

    def test_cli_exact_file_source_root(self) -> None:
        """Public CLI must accept --source-root=events.jsonl (reader file-or-dir)."""
        root = fixture_root("s-gcp-01-user-basic")
        events = root / "session-state" / BASIC_ID / "events.jsonl"
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            [
                "github-copilot",
                "list",
                "--cwd",
                CWD,
                "--source-root",
                str(events),
                "--within-min",
                "0",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        ids = [item["session_id"] for item in payload["sessions"]]
        self.assertEqual(ids, [BASIC_ID])

    def test_list_uses_bounded_metadata_not_full_transcript(self) -> None:
        """List must not full-scan every transcript (Codex P1 budget)."""
        from portable_resume.bounds import Bounds

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sid = BASIC_ID
            sess = root / "session-state" / sid
            sess.mkdir(parents=True)
            lines = [
                {
                    "type": "session.start",
                    "id": "e1",
                    "parentId": None,
                    "timestamp": "2024-01-01T12:00:00.000Z",
                    "data": {
                        "sessionId": sid,
                        "startTime": "2024-01-01T12:00:00.000Z",
                        "context": {"cwd": CWD},
                    },
                },
                {
                    "type": "user.message",
                    "id": "e2",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:01.000Z",
                    "data": {"content": "title from early user"},
                },
            ]
            # Pad with many assistant rows after the public user turn.
            for index in range(200):
                lines.append(
                    {
                        "type": "assistant.message",
                        "id": f"a{index}",
                        "parentId": "e2",
                        "timestamp": f"2024-01-01T12:00:{index % 60:02d}.000Z",
                        "data": {"content": f"pad {index}"},
                    }
                )
            (sess / "events.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            # Budget would fail a full multi-thousand-line scan; list only charges
            # scanned_records for the head window (not transcript_records).
            listed = ADAPTER.list(
                query(root),
                ReadBudget(Bounds(transcript_records=8, scanned_records=128)),
            )
            self.assertEqual([item.session_id for item in listed], [sid])
            self.assertEqual(listed[0].title, "title from early user")

    def test_show_uses_active_parent_lineage(self) -> None:
        """Abandoned rewind branch must not appear in show handoff (Codex P1)."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sid = BASIC_ID
            sess = root / "session-state" / sid
            sess.mkdir(parents=True)
            lines = [
                {
                    "type": "session.start",
                    "id": "e1",
                    "parentId": None,
                    "timestamp": "2024-01-01T12:00:00.000Z",
                    "data": {
                        "sessionId": sid,
                        "startTime": "2024-01-01T12:00:00.000Z",
                        "context": {"cwd": CWD},
                    },
                },
                {
                    "type": "user.message",
                    "id": "e2",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:01.000Z",
                    "data": {"content": "first user (abandoned after rewind)"},
                },
                {
                    "type": "assistant.message",
                    "id": "e3",
                    "parentId": "e2",
                    "timestamp": "2024-01-01T12:00:02.000Z",
                    "data": {"content": "first assistant (abandoned)"},
                },
                # Rewind: new user re-parents to session root (sibling of e2).
                {
                    "type": "user.message",
                    "id": "e4",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:03.000Z",
                    "data": {"content": "rewound user prompt"},
                },
                {
                    "type": "assistant.message",
                    "id": "e5",
                    "parentId": "e4",
                    "timestamp": "2024-01-01T12:00:04.000Z",
                    "data": {"content": "rewound assistant reply"},
                },
                {
                    "type": "session.shutdown",
                    "id": "e6",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:05.000Z",
                    "data": {},
                },
            ]
            (sess / "events.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            current = query(root, ref=sid)
            listed = ADAPTER.list(current, ReadBudget())
            self.assertEqual(len(listed), 1)
            session = ADAPTER.show(
                ResolvedRef.from_summary(listed[0]), current, ReadBudget()
            )
            texts = [turn.content for turn in session.turns]
            self.assertEqual(texts, ["rewound user prompt", "rewound assistant reply"])
            self.assertNotIn("first user (abandoned after rewind)", texts)
            self.assertNotIn("first assistant (abandoned)", texts)

    def test_list_respects_late_context_changed(self) -> None:
        """list cwd must match show after session.context_changed in head."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sid = BASIC_ID
            sess = root / "session-state" / sid
            sess.mkdir(parents=True)
            lines = [
                {
                    "type": "session.start",
                    "id": "e1",
                    "parentId": None,
                    "timestamp": "2024-01-01T12:00:00.000Z",
                    "data": {
                        "sessionId": sid,
                        "startTime": "2024-01-01T12:00:00.000Z",
                        "context": {"cwd": "/tmp/old-project"},
                    },
                },
                {
                    "type": "user.message",
                    "id": "e2",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:01.000Z",
                    "data": {"content": "started in old cwd"},
                },
                {
                    "type": "session.context_changed",
                    "id": "e3",
                    "parentId": "e2",
                    "timestamp": "2024-01-01T12:00:02.000Z",
                    "data": {"cwd": CWD},
                },
                {
                    "type": "user.message",
                    "id": "e4",
                    "parentId": "e3",
                    "timestamp": "2024-01-01T12:00:03.000Z",
                    "data": {"content": "continued in new cwd"},
                },
            ]
            (sess / "events.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            current = query(root)
            listed = ADAPTER.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in listed], [sid])
            self.assertEqual(listed[0].cwd, CWD)
            session = ADAPTER.show(
                ResolvedRef.from_summary(listed[0]), current, ReadBudget()
            )
            self.assertEqual(session.cwd, CWD)

    def test_list_and_show_latest_match_start_cwd_after_context_change(self) -> None:
        """Querying the start cwd must survive select_session after context_changed."""
        import io

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sid = BASIC_ID
            sess = root / "session-state" / sid
            sess.mkdir(parents=True)
            old = "/tmp/old-project"
            lines = [
                {
                    "type": "session.start",
                    "id": "e1",
                    "parentId": None,
                    "timestamp": "2024-01-01T12:00:00.000Z",
                    "data": {
                        "sessionId": sid,
                        "startTime": "2024-01-01T12:00:00.000Z",
                        "context": {"cwd": old},
                    },
                },
                {
                    "type": "user.message",
                    "id": "e2",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:01.000Z",
                    "data": {"content": "in old cwd"},
                },
                {
                    "type": "session.context_changed",
                    "id": "e3",
                    "parentId": "e2",
                    "timestamp": "2024-01-01T12:00:02.000Z",
                    "data": {"cwd": CWD},
                },
                {
                    "type": "assistant.message",
                    "id": "e4",
                    "parentId": "e3",
                    "timestamp": "2024-01-01T12:00:03.000Z",
                    "data": {"content": "now in new cwd"},
                },
            ]
            (sess / "events.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            listed = ADAPTER.list(
                Query(
                    source="github-copilot",
                    cwd=old,
                    source_root=str(root),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual([item.session_id for item in listed], [sid])
            self.assertEqual(listed[0].cwd, old)
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = run(
                [
                    "github-copilot",
                    "show",
                    "latest",
                    "--cwd",
                    old,
                    "--source-root",
                    str(root),
                    "--within-min",
                    "0",
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 0, stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["sessions"][0]["session_id"], sid)

    def test_exact_path_ref_bypasses_age_and_list_cap(self) -> None:
        root = fixture_root("s-gcp-01-user-basic")
        events = root / "session-state" / BASIC_ID / "events.jsonl"
        listed = ADAPTER.list(
            Query(
                source="github-copilot",
                ref=str(events),
                cwd=CWD,
                source_root=str(root),
                within_min=1,  # would exclude 2024 fixtures without exact bypass
            ),
            ReadBudget(),
        )
        self.assertEqual([item.session_id for item in listed], [BASIC_ID])

    def test_assistant_reasoning_is_omitted_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sid = BASIC_ID
            sess = root / "session-state" / sid
            sess.mkdir(parents=True)
            lines = [
                {
                    "type": "session.start",
                    "id": "e1",
                    "parentId": None,
                    "timestamp": "2024-01-01T12:00:00.000Z",
                    "data": {
                        "sessionId": sid,
                        "startTime": "2024-01-01T12:00:00.000Z",
                        "context": {"cwd": CWD},
                    },
                },
                {
                    "type": "user.message",
                    "id": "e2",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:01.000Z",
                    "data": {"content": "ask"},
                },
                {
                    "type": "assistant.reasoning",
                    "id": "e3",
                    "parentId": "e2",
                    "timestamp": "2024-01-01T12:00:02.000Z",
                    "data": {"content": "private chain of thought"},
                },
                {
                    "type": "assistant.message",
                    "id": "e4",
                    "parentId": "e3",
                    "timestamp": "2024-01-01T12:00:03.000Z",
                    "data": {"content": "public reply"},
                },
            ]
            (sess / "events.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            current = query(root, ref=sid)
            session = ADAPTER.show(
                ResolvedRef.from_summary(ADAPTER.list(current, ReadBudget())[0]),
                current,
                ReadBudget(),
            )
            texts = [turn.content for turn in session.turns]
            self.assertEqual(texts, ["ask", "public reply"])
            self.assertNotIn("private chain of thought", texts)

    def test_probe_handles_many_session_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "session-state"
            state.mkdir()
            for index in range(80):
                sid = f"aaaaaaaa-bbbb-4ccc-8ddd-{index:012d}"
                sess = state / sid
                sess.mkdir()
                (sess / "events.jsonl").write_text(
                    json.dumps(
                        {
                            "type": "session.start",
                            "id": "e1",
                            "parentId": None,
                            "timestamp": "2024-01-01T12:00:00.000Z",
                            "data": {
                                "sessionId": sid,
                                "startTime": "2024-01-01T12:00:00.000Z",
                                "context": {"cwd": CWD},
                            },
                        }
                    )
                    + "\n"
                    + json.dumps(
                        {
                            "type": "user.message",
                            "id": "e2",
                            "parentId": "e1",
                            "timestamp": "2024-01-01T12:00:01.000Z",
                            "data": {"content": "hi"},
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            report = ADAPTER.probe(query(root))
            self.assertEqual(report.state, "supported")

    def test_list_sees_context_changed_after_line_64_when_file_fits_head(self) -> None:
        """Full-file head must not stop at 64 lines before a late context_changed."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sid = BASIC_ID
            sess = root / "session-state" / sid
            sess.mkdir(parents=True)
            old = "/tmp/old-project"
            lines: list[dict[str, object]] = [
                {
                    "type": "session.start",
                    "id": "e1",
                    "parentId": None,
                    "timestamp": "2024-01-01T12:00:00.000Z",
                    "data": {
                        "sessionId": sid,
                        "startTime": "2024-01-01T12:00:00.000Z",
                        "context": {"cwd": old},
                    },
                },
                {
                    "type": "user.message",
                    "id": "e2",
                    "parentId": "e1",
                    "timestamp": "2024-01-01T12:00:01.000Z",
                    "data": {"content": "start"},
                },
            ]
            parent = "e2"
            for index in range(63):
                eid = f"p{index}"
                lines.append(
                    {
                        "type": "assistant.message",
                        "id": eid,
                        "parentId": parent,
                        "timestamp": "2024-01-01T12:00:02.000Z",
                        "data": {"content": f"pad {index}"},
                    }
                )
                parent = eid
            lines.append(
                {
                    "type": "session.context_changed",
                    "id": "ecx",
                    "parentId": parent,
                    "timestamp": "2024-01-01T12:00:03.000Z",
                    "data": {"cwd": CWD},
                }
            )
            (sess / "events.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            listed = ADAPTER.list(query(root), ReadBudget())
            self.assertEqual([item.session_id for item in listed], [sid])
            self.assertEqual(listed[0].cwd, CWD)

    def test_exact_file_source_root_rejects_sibling_path_ref(self) -> None:
        """Pinned events.jsonl containment must not accept sibling path refs."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for sid, prompt in (
                (BASIC_ID, "pinned"),
                (OTHER_ID, "sibling"),
            ):
                sess = root / "session-state" / sid
                sess.mkdir(parents=True)
                (sess / "events.jsonl").write_text(
                    "".join(
                        json.dumps(line) + "\n"
                        for line in (
                            {
                                "type": "session.start",
                                "id": "e1",
                                "parentId": None,
                                "timestamp": "2024-01-01T12:00:00.000Z",
                                "data": {
                                    "sessionId": sid,
                                    "startTime": "2024-01-01T12:00:00.000Z",
                                    "context": {"cwd": CWD},
                                },
                            },
                            {
                                "type": "user.message",
                                "id": "e2",
                                "parentId": "e1",
                                "timestamp": "2024-01-01T12:00:01.000Z",
                                "data": {"content": prompt},
                            },
                        )
                    ),
                    encoding="utf-8",
                )
            pinned = root / "session-state" / BASIC_ID / "events.jsonl"
            sibling = root / "session-state" / OTHER_ID / "events.jsonl"
            listed = ADAPTER.list(
                Query(
                    source="github-copilot",
                    ref=str(sibling),
                    cwd=CWD,
                    source_root=str(pinned),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual(listed, [])

    def test_list_truncates_when_aggregate_metadata_budget_exhausted(self) -> None:
        """Many sessions must not raise E_LIMIT_EXCEEDED on shared scanned budget."""
        from portable_resume.bounds import Bounds

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "session-state"
            state.mkdir()
            for index in range(40):
                sid = f"aaaaaaaa-bbbb-4ccc-8ddd-{index:012d}"
                sess = state / sid
                sess.mkdir()
                lines = [
                    {
                        "type": "session.start",
                        "id": "e1",
                        "parentId": None,
                        "timestamp": "2024-01-01T12:00:00.000Z",
                        "data": {
                            "sessionId": sid,
                            "startTime": "2024-01-01T12:00:00.000Z",
                            "context": {"cwd": CWD},
                        },
                    },
                    {
                        "type": "user.message",
                        "id": "e2",
                        "parentId": "e1",
                        "timestamp": "2024-01-01T12:00:01.000Z",
                        "data": {"content": f"session {index}"},
                    },
                ]
                # Pad each file so metadata hits the per-file head cap.
                for pad in range(62):
                    lines.append(
                        {
                            "type": "assistant.message",
                            "id": f"a{pad}",
                            "parentId": "e2",
                            "timestamp": "2024-01-01T12:00:02.000Z",
                            "data": {"content": f"pad {pad}"},
                        }
                    )
                (sess / "events.jsonl").write_text(
                    "".join(json.dumps(line) + "\n" for line in lines),
                    encoding="utf-8",
                )
            # 40 * 64 would exceed scanned_records=200; list must truncate, not raise.
            listed = ADAPTER.list(
                query(root),
                ReadBudget(Bounds(scanned_records=200, listed_sessions=50)),
            )
            self.assertGreater(len(listed), 0)
            self.assertLessEqual(len(listed), 50)


if __name__ == "__main__":
    unittest.main()
