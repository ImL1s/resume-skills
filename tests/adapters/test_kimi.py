from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.kimi import FORMAT_ID, LEGACY_FORMAT_ID, KimiAdapter
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot
from tests.helpers.fixture_manifest import validate_fixture_tree


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "kimi"
CWD = "/workspace/project"
CURRENT_ID = "11111111-1111-4111-8111-111111111111"
LEGACY_ID = "22222222-2222-4222-8222-222222222222"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case / "root").resolve()


def materialize_current(destination: Path) -> Path:
    shutil.copytree(fixture_root("s-kim-01"), destination)
    session_dir = next((destination / "sessions").glob("*/*"))
    (destination / "session_index.jsonl").write_text(
        json.dumps(
            {
                "sessionId": CURRENT_ID,
                "sessionDir": str(session_dir.resolve()),
                "workDir": CWD,
                "synthetic": True,
            }
        )
        + "\n"
    )
    return destination


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(source="kimi", ref=ref, cwd=CWD, source_root=str(root), **kwargs)


def resolved(items, session_id: str) -> ResolvedRef:
    return ResolvedRef.from_summary(next(item for item in items if item.session_id == session_id))


class KimiFixtureTests(unittest.TestCase):
    def test_fixture_manifests_are_synthetic_and_generation_specific(self) -> None:
        manifests = validate_fixture_tree(FIXTURES)
        self.assertEqual({item.case for item in manifests}, {"s-kim-01", "s-kim-02"})
        self.assertEqual({item.format_id for item in manifests}, {FORMAT_ID, LEGACY_FORMAT_ID})
        self.assertTrue(all(item.synthetic for item in manifests))


class KimiAdapterTests(unittest.TestCase):
    def test_current_index_list_show_filters_internal_and_preserves_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            before = tree_snapshot(root)
            adapter = KimiAdapter(root=str(root))
            current = query(root, CURRENT_ID)
            self.assertEqual(adapter.probe(current).format_id, FORMAT_ID)
            summaries = adapter.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [CURRENT_ID])
            self.assertEqual(summaries[0].cwd, CWD)
            session = adapter.show(resolved(summaries, CURRENT_ID), current, ReadBudget())
            self.assertEqual([turn.role for turn in session.turns], ["user", "assistant"])
            self.assertEqual([turn.content for turn in session.turns], ["Current Kimi prompt", "Current Kimi answer"])
            self.assertNotIn("hidden", " ".join(turn.content for turn in session.turns))
            self.assertEqual(tree_snapshot(root), before)

    def test_legacy_metadata_context_and_wire_fallback(self) -> None:
        root = fixture_root("s-kim-02")
        before = tree_snapshot(root)
        adapter = KimiAdapter(root=str(root))
        current = query(root, LEGACY_ID)
        summaries = adapter.list(current, ReadBudget())
        self.assertEqual(summaries[0].provider, LEGACY_FORMAT_ID)
        self.assertEqual(summaries[0].cwd, CWD)
        session = adapter.show(resolved(summaries, LEGACY_ID), current, ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["Legacy Kimi prompt", "Legacy Kimi answer"])
        self.assertEqual(tree_snapshot(root), before)

        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "legacy"
            shutil.copytree(root, copy)
            context = next(copy.rglob("context.jsonl"))
            context.rename(context.with_name("wire.jsonl"))
            fallback = KimiAdapter(root=str(copy))
            values = fallback.list(query(copy, LEGACY_ID), ReadBudget())
            shown = fallback.show(resolved(values, LEGACY_ID), query(copy, LEGACY_ID), ReadBudget())
            self.assertEqual(shown.last_assistant_action, "Legacy Kimi answer")

        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "legacy-flat"
            shutil.copytree(root, copy)
            context = next(copy.rglob("context.jsonl"))
            flat = context.parent.parent / f"{LEGACY_ID}.jsonl"
            context.rename(flat)
            shutil.rmtree(context.parent)
            adapter = KimiAdapter(root=str(copy))
            values = adapter.list(query(copy, LEGACY_ID), ReadBudget())
            self.assertEqual(values[0].source_path, str(flat.resolve()))
            shown = adapter.show(resolved(values, LEGACY_ID), query(copy, LEGACY_ID), ReadBudget())
            self.assertEqual(shown.last_user_request, "Legacy Kimi prompt")

    def test_cwd_exact_id_exact_path_and_age_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            adapter = KimiAdapter(root=str(root))
            exact = adapter.list(query(root, CURRENT_ID, within_min=1), ReadBudget())
            self.assertEqual([item.session_id for item in exact], [CURRENT_ID])
            transcript = next(root.rglob("wire.jsonl"))
            by_path = adapter.list(query(root, str(transcript), within_min=1), ReadBudget())
            self.assertEqual([item.session_id for item in by_path], [CURRENT_ID])
            other = Query(source="kimi", cwd="/different", source_root=str(root), within_min=0)
            self.assertEqual(adapter.list(other, ReadBudget()), [])

    def test_current_index_requires_absolute_contained_session_dir_and_replays_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            index = root / "session_index.jsonl"
            valid = index.read_text()
            # A malformed relative update is skipped and cannot redirect the
            # previously valid index entry.
            index.write_text(
                valid
                + json.dumps(
                    {
                        "sessionId": CURRENT_ID,
                        "sessionDir": f"sessions/project-key/{CURRENT_ID}",
                        "workDir": CWD,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "sessionId": "33333333-3333-4333-8333-333333333333",
                        "sessionDir": str((root.parent / "outside" / "33333333-3333-4333-8333-333333333333").resolve()),
                        "workDir": CWD,
                    }
                )
                + "\n"
            )
            values = KimiAdapter(root=str(root)).list(query(root, CURRENT_ID), ReadBudget())
            self.assertEqual([item.session_id for item in values], [CURRENT_ID])

    def test_default_current_precedence_and_legacy_fallback(self) -> None:
        legacy = fixture_root("s-kim-02")
        with tempfile.TemporaryDirectory() as current_temporary:
            current = materialize_current(Path(current_temporary) / "current")
            with mock.patch.dict(
                os.environ,
                {"KIMI_CODE_HOME": str(current), "KIMI_SHARE_DIR": str(legacy)},
                clear=False,
            ):
                adapter = KimiAdapter()
                values = adapter.list(Query(source="kimi", cwd=CWD, within_min=0), ReadBudget())
                self.assertEqual(values[0].provider, FORMAT_ID)

        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ,
            {"KIMI_CODE_HOME": temporary, "KIMI_SHARE_DIR": str(legacy)},
            clear=False,
        ):
            adapter = KimiAdapter()
            values = adapter.list(Query(source="kimi", cwd=CWD, within_min=0), ReadBudget())
            self.assertEqual(values[0].provider, LEGACY_FORMAT_ID)

    def test_partial_tail_only_is_warned_but_interior_and_duplicate_corruption_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            transcript.write_bytes(transcript.read_bytes() + b'{"message":')
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, CURRENT_ID), ReadBudget())
            shown = adapter.show(resolved(values, CURRENT_ID), query(root, CURRENT_ID), ReadBudget())
            self.assertIn("W_PARTIAL_TAIL", shown.warnings)

        corruptions = (
            b'{"message":\\n',
            b'{"role":"user","role":"assistant","content":"duplicate"}\\n',
        )
        for corruption in corruptions:
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                root = materialize_current(Path(temporary) / "current")
                transcript = next(root.rglob("wire.jsonl"))
                transcript.write_bytes(corruption + transcript.read_bytes())
                with self.assertRaises(DiagnosticError) as caught:
                    KimiAdapter(root=str(root)).list(query(root, CURRENT_ID), ReadBudget())
                self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_current_tool_result_is_recovered_without_tool_call_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "type": "context.append_loop_event",
                            "event": {
                                "type": "tool.result",
                                "toolCallId": "call-1",
                                "result": {
                                    "output": "synthetic tool result",
                                    "isError": False,
                                },
                            },
                            "time": 1784851350,
                        }
                    )
                    + "\n"
                )
            adapter = KimiAdapter(root=str(root))
            current = query(root, CURRENT_ID)
            values = adapter.list(current, ReadBudget())
            shown = adapter.show(
                resolved(values, CURRENT_ID),
                current,
                ReadBudget(),
            )
            self.assertEqual(shown.turns[-1].role, "tool")
            self.assertEqual(shown.turns[-1].content, "synthetic tool result")

    def test_unknown_current_record_and_loop_event_are_warned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"type": "context.future_record", "time": 1784851350})
                    + "\n"
                )
                handle.write(
                    json.dumps(
                        {
                            "type": "context.append_loop_event",
                            "event": {"type": "future.event"},
                            "time": 1784851351,
                        }
                    )
                    + "\n"
                )
            adapter = KimiAdapter(root=str(root))
            current = query(root, CURRENT_ID)
            values = adapter.list(current, ReadBudget())
            shown = adapter.show(resolved(values, CURRENT_ID), current, ReadBudget())
            self.assertIn("W_UNKNOWN_RECORD_SKIPPED", shown.warnings)
            self.assertEqual(
                [turn.content for turn in shown.turns],
                ["Current Kimi prompt", "Current Kimi answer"],
            )

    def test_symlinked_transcript_is_rejected_and_source_is_never_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            target = Path(temporary) / "outside.jsonl"
            target.write_text(json.dumps({"role": "user", "content": "outside"}) + "\n")
            transcript.unlink()
            transcript.symlink_to(target)
            with mock.patch("subprocess.run") as run:
                with self.assertRaises(DiagnosticError) as caught:
                    KimiAdapter(root=str(root)).list(query(root, CURRENT_ID), ReadBudget())
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")
            run.assert_not_called()

    def test_changing_source_exhausts_stable_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")

            def race(phase: str, _attempt: int, path: str) -> None:
                if phase == "after-read" and path.endswith("wire.jsonl"):
                    with open(path, "ab") as handle:
                        handle.write(b" ")

            adapter = KimiAdapter(root=str(root), read_hook=race)
            with self.assertRaises(DiagnosticError) as caught:
                adapter.list(query(root, CURRENT_ID), ReadBudget())
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")


if __name__ == "__main__":
    unittest.main()
