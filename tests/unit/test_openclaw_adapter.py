from __future__ import annotations

import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.openclaw import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/openclaw")
CWD = "/tmp/project"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="openclaw",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class OpenClawAdapterTests(unittest.TestCase):
    def test_list_and_show_basic_fixture(self) -> None:
        root = fixture_root("s-oc-01-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, "main:sess-basic-0001")
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        self.assertEqual(summaries[0].title, "Synthetic basic")
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            [
                "Resume context from /tmp/project",
                "Synthetic assistant reply",
            ],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_multi_agent_composite_ids(self) -> None:
        root = fixture_root("s-oc-02-multi-agent")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        ids = sorted(item.session_id for item in summaries)
        self.assertEqual(ids, ["main:sess-main-0001", "worker:sess-worker-0001"])
        worker = next(item for item in summaries if item.session_id.startswith("worker:"))
        session = ADAPTER.show(ResolvedRef.from_summary(worker), current, ReadBudget())
        self.assertEqual(session.session_id, "worker:sess-worker-0001")
        self.assertEqual(
            [turn.content for turn in session.turns],
            [
                "Resume context from /tmp/project",
                "Synthetic assistant reply",
            ],
        )

    def test_compaction_reset_lists_current_window_only(self) -> None:
        root = fixture_root("s-oc-03-compaction-reset")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["main:sess-compact-reset"])
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        contents = [turn.content for turn in session.turns]
        # Compaction summary is inert recovered context on the active window.
        self.assertEqual(
            contents,
            [
                "Long thread before compaction",
                "Synthetic compaction kept first message",
                "Post-reset assistant line",
            ],
        )
        combined = " ".join(contents)
        self.assertNotIn("side-task", combined)

    def test_exact_historical_window_id_is_selectable(self) -> None:
        root = fixture_root("s-oc-03-compaction-reset")
        current = query(root, ref="main:sess-compact-initial")
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["main:sess-compact-initial"])

    def test_internal_and_cron_hidden_unless_exact(self) -> None:
        root = fixture_root("s-oc-04-internal-filter")
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["main:sess-operator-01"])
        exact = ADAPTER.list(query(root, ref="main:sess-cron-01"), ReadBudget())
        self.assertEqual([item.session_id for item in exact], ["main:sess-cron-01"])

    def test_corrupt_meta_is_unsupported(self) -> None:
        root = fixture_root("s-oc-05-corrupt-meta")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "unsupported")
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_probe_supported_on_basic(self) -> None:
        root = fixture_root("s-oc-01-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")
        self.assertEqual(report.format_id, FORMAT_ID)

    def test_nested_message_payload_and_compaction_retention(self) -> None:
        from portable_resume.adapters import openclaw as oc

        nested = {
            "type": "message",
            "id": "n1",
            "parentId": None,
            "message": {"role": "user", "content": "nested user"},
        }
        self.assertEqual(oc._event_role(nested), "user")
        self.assertEqual(oc._message_text(nested), "nested user")

        events = [
            {"type": "message", "id": "a", "parentId": None, "role": "user", "text": "old"},
            {"type": "message", "id": "b", "parentId": "a", "role": "assistant", "text": "replaced"},
            {
                "type": "compaction",
                "id": "c",
                "parentId": "b",
                "firstKeptEntryId": "a",
                "summary": "compacted",
            },
            {"type": "message", "id": "d", "parentId": "c", "role": "user", "text": "after"},
        ]
        path = oc._active_branch_events(events)
        ids = [item.get("id") for item in path]
        # Retains compaction summary and firstKept entry; skips replaced sibling path.
        self.assertEqual(ids, ["a", "c", "d"])
        self.assertNotIn("b", ids)

        with_branch = [
            {"type": "message", "id": "a", "parentId": None, "role": "user", "text": "root"},
            {"type": "branch_summary", "id": "bs", "parentId": "a", "branch": "side"},
            {"type": "message", "id": "z", "parentId": "bs", "role": "assistant", "text": "leaf"},
        ]
        path2 = oc._active_branch_events(with_branch)
        self.assertEqual([item.get("id") for item in path2], ["a", "z"])


if __name__ == "__main__":
    unittest.main()
