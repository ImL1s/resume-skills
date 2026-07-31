from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.gemini import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/gemini")
CWD = "/tmp/project"
OTHER_CWD = "/tmp/other"
BASIC_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
SUB_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OTHER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="gemini",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


def _project_hash(cwd: str) -> str:
    return hashlib.sha256(cwd.encode("utf-8")).hexdigest()


class GeminiAdapterTests(unittest.TestCase):
    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-gm-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        session = ADAPTER.show(
            ResolvedRef.from_summary(summaries[0]), current, ReadBudget()
        )
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic gemini user prompt", "synthetic gemini assistant reply"],
        )
        joined = " ".join(turn.content for turn in session.turns)
        self.assertNotIn("secret", joined)
        self.assertNotIn("must omit", joined)
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported(self) -> None:
        report = ADAPTER.probe(query(fixture_root("s-gm-01-user-basic")))
        self.assertEqual(report.state, "supported")

    def test_default_list_hides_subagent(self) -> None:
        root = fixture_root("s-gm-02-main-and-subagent")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
        child = ADAPTER.show(
            ResolvedRef(session_id=SUB_ID, source_path=""),
            query(root, ref=SUB_ID),
            ReadBudget(),
        )
        self.assertEqual(child.session_id, SUB_ID)
        self.assertIn("subagent should hide", child.turns[0].content)

    def test_corrupt_session_fails_closed(self) -> None:
        root = fixture_root("s-gm-03-corrupt")
        # list skips corrupt; exact show may raise
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(summaries, [])
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(
                ResolvedRef(session_id=BASIC_ID, source_path=""),
                query(root, ref=BASIC_ID),
                ReadBudget(),
            )
        self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_NO_MATCH"})

    def test_not_antigravity_key(self) -> None:
        self.assertEqual(ADAPTER.key, "gemini")
        self.assertNotEqual(FORMAT_ID, "antigravity-transcript-jsonl-v1")

    def _write_two_project_store(self, root: Path) -> tuple[str, str]:
        project_hash = _project_hash(CWD)
        other_hash = _project_hash(OTHER_CWD)
        self.assertNotEqual(project_hash, other_hash)
        for project, session_id, stamp, prompt in (
            (
                project_hash,
                BASIC_ID,
                "2024-01-01T12:00:00.000Z",
                "project user prompt",
            ),
            (
                other_hash,
                OTHER_ID,
                "2024-01-02T12:00:00.000Z",
                "other project newer session",
            ),
        ):
            chats = root / "tmp" / project / "chats"
            chats.mkdir(parents=True)
            path = chats / f"session-2024-01-01T12-00-{session_id[:8]}.jsonl"
            lines = [
                {
                    "sessionId": session_id,
                    "projectHash": project,
                    "startTime": stamp,
                    "lastUpdated": stamp,
                    "kind": "main",
                },
                {
                    "id": "msg-u1",
                    "timestamp": stamp,
                    "type": "user",
                    "content": [{"text": prompt}],
                },
                {
                    "id": "msg-a1",
                    "timestamp": stamp,
                    "type": "gemini",
                    "content": [{"text": "reply"}],
                },
            ]
            path.write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
        return project_hash, other_hash

    def test_cwd_filters_to_matching_project_hash(self) -> None:
        """latest must not return a newer session from another projectHash."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_two_project_store(root)

            listed = ADAPTER.list(query(root), ReadBudget())
            self.assertEqual([item.session_id for item in listed], [BASIC_ID])
            self.assertEqual(listed[0].cwd, CWD)

            other_listed = ADAPTER.list(
                Query(
                    source="gemini",
                    ref=None,
                    cwd=OTHER_CWD,
                    source_root=str(root),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual([item.session_id for item in other_listed], [OTHER_ID])

            # Unscoped list may see both projects (no cwd filter).
            unscoped = ADAPTER.list(
                Query(
                    source="gemini",
                    ref=None,
                    cwd=None,
                    source_root=str(root),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual(
                sorted(item.session_id for item in unscoped),
                sorted([BASIC_ID, OTHER_ID]),
            )

    def test_source_root_project_hash_stays_contained(self) -> None:
        """--source-root on tmp/<hash> must not widen to sibling projects."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_hash, _other = self._write_two_project_store(root)
            scoped = root / "tmp" / project_hash
            listed = ADAPTER.list(
                Query(
                    source="gemini",
                    ref=None,
                    cwd=None,
                    source_root=str(scoped),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual([item.session_id for item in listed], [BASIC_ID])

    def test_text_ref_is_not_treated_as_exact_session_id(self) -> None:
        root = fixture_root("s-gm-01-user-basic")
        listed = ADAPTER.list(
            Query(
                source="gemini",
                ref="authentication",
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            ),
            ReadBudget(),
        )
        # Text refs fall through to normal list (not empty prefilter by id).
        self.assertEqual([item.session_id for item in listed], [BASIC_ID])

    def test_exact_ref_case_insensitive_uuid(self) -> None:
        root = fixture_root("s-gm-01-user-basic")
        upper = BASIC_ID.upper()
        listed = ADAPTER.list(query(root, ref=upper), ReadBudget())
        self.assertEqual([item.session_id for item in listed], [BASIC_ID])

    def test_exact_short_id_case_fold_prefix(self) -> None:
        root = fixture_root("s-gm-01-user-basic")
        # Filename short id is a1b2c3d4; uppercase must still match full UUID.
        listed = ADAPTER.list(query(root, ref="A1B2C3D4"), ReadBudget())
        self.assertEqual([item.session_id for item in listed], [BASIC_ID])

    def test_exact_file_source_root_stays_on_that_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_hash, _other = self._write_two_project_store(root)
            other_session = (
                root
                / "tmp"
                / _project_hash(OTHER_CWD)
                / "chats"
                / f"session-2024-01-01T12-00-{OTHER_ID[:8]}.jsonl"
            )
            # Point source-root at the older project file; must not pick the newer other project.
            project_file = (
                root
                / "tmp"
                / project_hash
                / "chats"
                / f"session-2024-01-01T12-00-{BASIC_ID[:8]}.jsonl"
            )
            listed = ADAPTER.list(
                Query(
                    source="gemini",
                    ref=None,
                    cwd=None,
                    source_root=str(project_file),
                    within_min=0,
                ),
                ReadBudget(),
            )
            self.assertEqual([item.session_id for item in listed], [BASIC_ID])
            self.assertTrue(other_session.is_file())

    def test_show_rejects_unknown_content_bearing_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _project_hash(CWD)
            chats = root / "tmp" / project / "chats"
            chats.mkdir(parents=True)
            path = chats / "session-2024-01-01T12-00-a1b2c3d4.jsonl"
            lines = [
                {
                    "sessionId": BASIC_ID,
                    "projectHash": project,
                    "startTime": "2024-01-01T12:00:00.000Z",
                    "lastUpdated": "2024-01-01T12:00:00.000Z",
                    "kind": "main",
                },
                {
                    "id": "msg-u1",
                    "timestamp": "2024-01-01T12:00:00.000Z",
                    "type": "user",
                    "content": [{"text": "hello"}],
                },
                {
                    "id": "msg-x1",
                    "timestamp": "2024-01-01T12:00:01.000Z",
                    "type": "model_reply",
                    "content": [{"text": "unknown type with content"}],
                },
            ]
            path.write_text(
                "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
            )
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.show(
                    ResolvedRef(session_id=BASIC_ID, source_path=str(path)),
                    query(root, ref=BASIC_ID),
                    ReadBudget(),
                )
            self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")


if __name__ == "__main__":
    unittest.main()
