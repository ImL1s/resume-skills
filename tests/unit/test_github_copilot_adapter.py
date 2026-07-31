from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.github_copilot import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
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


if __name__ == "__main__":
    unittest.main()
