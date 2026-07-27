from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.kimi import FORMAT_ID, LEGACY_FORMAT_ID, KimiAdapter
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from portable_resume.reader import run
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

    def test_show_preserves_current_summary_metadata_if_state_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            adapter = KimiAdapter(root=str(root))
            current = query(root, CURRENT_ID)
            summaries = adapter.list(current, ReadBudget())
            expected = summaries[0]
            transcript = next(root.rglob("wire.jsonl"))
            next(root.rglob("state.json")).unlink()
            shown = adapter.show(resolved(summaries, CURRENT_ID), current, ReadBudget())
            self.assertEqual(shown.cwd, expected.cwd)
            self.assertEqual(shown.title, expected.title)
            self.assertIn("W_MISSING_BLOB", shown.warnings)

            stdout, stderr = io.StringIO(), io.StringIO()
            code = run(
                [
                    "kimi",
                    "show",
                    str(transcript),
                    "--cwd",
                    CWD,
                    "--source-root",
                    str(root),
                    "--json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())["sessions"][0]["cwd"], CWD)

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
        self.assertEqual(session.cwd, CWD)
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

            letter_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            session_dir = next((root / "sessions").glob("*/*"))
            renamed = session_dir.with_name(letter_id)
            session_dir.rename(renamed)
            (root / "session_index.jsonl").write_text(
                json.dumps(
                    {
                        "sessionId": letter_id,
                        "sessionDir": str(renamed.resolve()),
                        "workDir": CWD,
                        "synthetic": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            uppercase = Query(
                source="kimi",
                ref=letter_id.upper(),
                cwd="/different",
                source_root=str(root),
                within_min=0,
            )
            values = KimiAdapter(root=str(root)).list(uppercase, ReadBudget())
            self.assertEqual([item.session_id for item in values], [letter_id])

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

            stdout, stderr = io.StringIO(), io.StringIO()
            code = run(
                ["kimi", "show", LEGACY_ID, "--cwd", CWD, "--json"],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())["sessions"][0]["session_id"], LEGACY_ID)

    def test_partial_tail_only_is_warned_but_interior_and_duplicate_corruption_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            transcript.write_bytes(transcript.read_bytes() + b'{"message":')
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, CURRENT_ID), ReadBudget())
            # list is metadata-only and must not fail on a partial terminal wire line
            self.assertEqual([item.session_id for item in values], [CURRENT_ID])
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
                adapter = KimiAdapter(root=str(root))
                values = adapter.list(query(root, CURRENT_ID), ReadBudget())
                with self.assertRaises(DiagnosticError) as caught:
                    adapter.show(resolved(values, CURRENT_ID), query(root, CURRENT_ID), ReadBudget())
                self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_truncated_multibyte_utf8_tail_is_warned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            transcript.write_bytes(transcript.read_bytes() + b'{"message":"\xe4\xb8')
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, CURRENT_ID), ReadBudget())
            shown = adapter.show(resolved(values, CURRENT_ID), query(root, CURRENT_ID), ReadBudget())
            self.assertIn("W_PARTIAL_TAIL", shown.warnings)

        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            transcript.write_bytes(transcript.read_bytes() + b'{"message":"\xff')
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, CURRENT_ID), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolved(values, CURRENT_ID), query(root, CURRENT_ID), ReadBudget())
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_nonfinite_depth_and_container_overflow_fail_closed(self) -> None:
        nested = b'{"role":"user","content":' + (b"[" * 34) + b'"deep"' + (b"]" * 34) + b"}\n"
        oversized = json.dumps(
            {
                "role": "user",
                "content": "wide",
                "metadata": {str(index): index for index in range(513)},
            }
        ).encode("utf-8") + b"\n"
        corruptions = (b'{"role":"user","content":"bad","value":NaN}\n', nested, oversized)
        for corruption in corruptions:
            with self.subTest(corruption=corruption[:64]), tempfile.TemporaryDirectory() as temporary:
                root = materialize_current(Path(temporary) / "current")
                transcript = next(root.rglob("wire.jsonl"))
                transcript.write_bytes(corruption + transcript.read_bytes())
                adapter = KimiAdapter(root=str(root))
                values = adapter.list(query(root, CURRENT_ID), ReadBudget())
                with self.assertRaises(DiagnosticError) as caught:
                    adapter.show(resolved(values, CURRENT_ID), query(root, CURRENT_ID), ReadBudget())
                self.assertIn(caught.exception.code, {"E_CORRUPT_RECORD", "E_LIMIT_EXCEEDED"})

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
                # Discovery skips unsafe index/FS candidates rather than aborting the store.
                values = KimiAdapter(root=str(root)).list(query(root, CURRENT_ID), ReadBudget())
            self.assertEqual(values, [])
            run.assert_not_called()
            # Exact show still hard-rejects a symlink path (do not resolve through it).
            with self.assertRaises(DiagnosticError) as show_caught:
                KimiAdapter(root=str(root)).show(
                    ResolvedRef(
                        session_id=CURRENT_ID,
                        source_path=str(transcript),
                        provider=FORMAT_ID,
                    ),
                    query(root, CURRENT_ID),
                    ReadBudget(),
                )
            self.assertEqual(show_caught.exception.code, "E_UNSAFE_PATH")

    def test_changing_source_exhausts_stable_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")

            def race(phase: str, _attempt: int, path: str) -> None:
                if phase == "after-read" and path.endswith("wire.jsonl"):
                    with open(path, "ab") as handle:
                        handle.write(b" ")

            adapter = KimiAdapter(root=str(root), read_hook=race)
            values = adapter.list(query(root, CURRENT_ID), ReadBudget())
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(resolved(values, CURRENT_ID), query(root, CURRENT_ID), ReadBudget())
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_append_only_index_reducer_survives_many_updates_and_delete_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            session_dir = next((root / "sessions").glob("*/*"))
            index = root / "session_index.jsonl"
            lines: list[str] = []
            for i in range(10_000):
                lines.append(
                    json.dumps(
                        {
                            "sessionId": CURRENT_ID,
                            "sessionDir": str(session_dir.resolve()),
                            "workDir": CWD,
                            "seq": i,
                            "synthetic": True,
                        }
                    )
                )
            other = "33333333-3333-4333-8333-333333333333"
            lines.append(
                json.dumps(
                    {
                        "sessionId": other,
                        "sessionDir": str((session_dir.parent / other).resolve()),
                        "workDir": CWD,
                        "synthetic": True,
                    }
                )
            )
            lines.append(json.dumps({"sessionId": other, "deleted": True, "synthetic": True}))
            lines.append(json.dumps({"sessionId": CURRENT_ID, "deleted": True, "synthetic": True}))
            lines.append(
                json.dumps(
                    {
                        "sessionId": CURRENT_ID,
                        "sessionDir": str(session_dir.resolve()),
                        "workDir": CWD,
                        "final": True,
                        "synthetic": True,
                    }
                )
            )
            index.write_text("\n".join(lines) + "\n", encoding="utf-8")
            before = tree_snapshot(root)
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, within_min=0), ReadBudget())
            self.assertEqual([item.session_id for item in values], [CURRENT_ID])
            self.assertEqual(tree_snapshot(root), before)

    def test_large_wire_list_is_metadata_only_and_show_uses_source_read_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            # ~17 MiB of small synthetic lines: under source_read_bytes, over record_bytes.
            filler = (
                json.dumps(
                    {
                        "type": "context.append_loop_event",
                        "event": {
                            "type": "content.part",
                            "uuid": "p",
                            "turnId": "t",
                            "step": 0,
                            "stepUuid": "s",
                            "part": {"type": "text", "text": "x" * 200},
                        },
                        "time": 1784851400,
                        "synthetic": True,
                    }
                )
                + "\n"
            )
            target = 17 * 1024 * 1024
            with transcript.open("ab") as handle:
                written = 0
                while written < target:
                    handle.write(filler.encode("utf-8"))
                    written += len(filler)
            self.assertGreater(transcript.stat().st_size, 16 * 1024 * 1024)
            before = tree_snapshot(root)

            wire_opens = {"count": 0}

            def count_wire(phase: str, _attempt: int, path: str) -> None:
                if phase == "before-read" and path.endswith("wire.jsonl"):
                    wire_opens["count"] += 1

            adapter = KimiAdapter(root=str(root), read_hook=count_wire)
            values = adapter.list(query(root, CURRENT_ID, within_min=0), ReadBudget())
            self.assertEqual([item.session_id for item in values], [CURRENT_ID])
            self.assertEqual(wire_opens["count"], 0, "list must not open wire content")

            shown = adapter.show(resolved(values, CURRENT_ID), query(root, CURRENT_ID), ReadBudget())
            self.assertGreaterEqual(wire_opens["count"], 1)
            self.assertEqual(shown.turns[0].content, "Current Kimi prompt")
            self.assertIn("Current Kimi", " ".join(turn.content for turn in shown.turns if turn.role == "assistant"))
            self.assertEqual(tree_snapshot(root), before)

    def test_exact_path_show_with_missing_index_warns_stale_and_fs_fallback_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            index = root / "session_index.jsonl"
            index.unlink()
            before = tree_snapshot(root)
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, within_min=0), ReadBudget())
            self.assertEqual([item.session_id for item in values], [CURRENT_ID])
            self.assertIn("W_STALE_INDEX", values[0].warnings)
            shown = adapter.show(
                ResolvedRef(
                    session_id=CURRENT_ID,
                    source_path=str(transcript.resolve()),
                    provider=FORMAT_ID,
                ),
                query(root, CURRENT_ID),
                ReadBudget(),
            )
            # Exact show does not re-scan the index; title/cwd come from state.json.
            self.assertEqual(shown.turns[0].content, "Current Kimi prompt")
            self.assertIn("W_STALE_INDEX", shown.warnings)
            self.assertEqual(tree_snapshot(root), before)

            index.write_text("", encoding="utf-8")
            exact = adapter.list(query(root, str(transcript), within_min=0), ReadBudget())
            self.assertIn("W_STALE_INDEX", exact[0].warnings)
            shown = adapter.show(
                resolved(exact, CURRENT_ID),
                query(root, str(transcript), within_min=0),
                ReadBudget(),
            )
            self.assertIn("W_STALE_INDEX", shown.warnings)

    def test_exact_show_rejects_wrong_current_provider_path_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            original = next(root.rglob("wire.jsonl"))
            wrong = root / "elsewhere" / CURRENT_ID / "agents" / "main" / "wire.jsonl"
            wrong.parent.mkdir(parents=True)
            wrong.write_bytes(original.read_bytes())
            adapter = KimiAdapter(root=str(root))
            with self.assertRaises(DiagnosticError) as caught:
                adapter.show(
                    ResolvedRef(
                        session_id=CURRENT_ID,
                        source_path=str(wrong),
                        provider=FORMAT_ID,
                    ),
                    query(root, CURRENT_ID),
                    ReadBudget(),
                )
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "legacy"
            shutil.copytree(fixture_root("s-kim-02"), root)
            original = next(root.rglob("context.jsonl"))
            wrong = root / "sessions" / "not-a-md5-hash" / LEGACY_ID / "context.jsonl"
            wrong.parent.mkdir(parents=True)
            wrong.write_bytes(original.read_bytes())
            with self.assertRaises(DiagnosticError) as caught:
                KimiAdapter(root=str(root)).list(
                    query(root, str(wrong), within_min=0),
                    ReadBudget(),
                )
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            (root / "session_index.jsonl").unlink()
            session_dir = next((root / "sessions").glob("*/*"))
            holding = root / "holding" / CURRENT_ID
            holding.parent.mkdir()
            session_dir.rename(holding)
            session_dir.symlink_to(holding, target_is_directory=True)
            records, warnings = KimiAdapter(root=str(root))._current_exact_id_records(
                str(root.resolve()),
                CURRENT_ID,
                ReadBudget(),
            )
            self.assertEqual(records, [])
            self.assertIn("W_STALE_INDEX", warnings)

    def test_reader_exact_path_bypasses_storewide_filesystem_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl")).resolve()
            (root / "session_index.jsonl").unlink()
            next(root.rglob("state.json")).unlink()
            for ref in (str(transcript), CURRENT_ID):
                with self.subTest(ref=ref):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with mock.patch.object(
                        KimiAdapter,
                        "_fs_fallback_current",
                        side_effect=DiagnosticError.limit_exceeded(),
                    ):
                        code = run(
                            [
                                "kimi",
                                "show",
                                ref,
                                "--cwd",
                                CWD,
                                "--source-root",
                                str(root),
                                "--json",
                            ],
                            stdout=stdout,
                            stderr=stderr,
                        )
                    self.assertEqual(code, 0, stderr.getvalue())
                    payload = json.loads(stdout.getvalue())
                    self.assertEqual(payload["sessions"][0]["session_id"], CURRENT_ID)
                    self.assertIn("W_STALE_INDEX", payload["sessions"][0]["warnings"])

    def test_exact_show_survives_corrupt_index_and_separate_discovery_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            index = root / "session_index.jsonl"
            # Poison index: interior corrupt line would fail reduce if hard-gated.
            index.write_text(
                index.read_text(encoding="utf-8")
                + '{"sessionId":"bad","sessionDir":"/x","workDir":"/y"\n'
                + json.dumps({"not": "a session"})
                + "\n",
                encoding="utf-8",
            )
            # Large-but-valid index history must not share show transcript budget.
            session_dir = next((root / "sessions").glob("*/*"))
            with index.open("a", encoding="utf-8") as handle:
                for i in range(8_000):
                    handle.write(
                        json.dumps(
                            {
                                "sessionId": CURRENT_ID,
                                "sessionDir": str(session_dir.resolve()),
                                "workDir": CWD,
                                "seq": i,
                                "synthetic": True,
                            }
                        )
                        + "\n"
                    )
            filler = json.dumps({"type": "metadata", "synthetic": True, "n": 0}) + "\n"
            with transcript.open("ab") as handle:
                for i in range(3_000):
                    handle.write(filler.replace('"n": 0', f'"n": {i}').encode("utf-8"))
            before = tree_snapshot(root)
            adapter = KimiAdapter(root=str(root))
            shown = adapter.show(
                ResolvedRef(
                    session_id=CURRENT_ID,
                    source_path=str(transcript.resolve()),
                    provider=FORMAT_ID,
                ),
                query(root, CURRENT_ID),
                ReadBudget(),
            )
            # Corrupt/large index must not be consulted on exact-path show.
            self.assertEqual(shown.turns[0].content, "Current Kimi prompt")
            self.assertEqual(tree_snapshot(root), before)

    def test_index_tombstone_is_not_revived_by_fs_union(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            session_dir = next((root / "sessions").glob("*/*"))
            extra_id = "33333333-3333-4333-8333-333333333333"
            extra_dir = session_dir.with_name(extra_id)
            shutil.copytree(session_dir, extra_dir)
            index = root / "session_index.jsonl"
            index.write_text(
                json.dumps(
                    {
                        "sessionId": CURRENT_ID,
                        "sessionDir": str(session_dir.resolve()),
                        "workDir": CWD,
                        "synthetic": True,
                    }
                )
                + "\n"
                + json.dumps({"sessionId": CURRENT_ID, "deleted": True, "synthetic": True})
                + "\n"
                + json.dumps(
                    {
                        "sessionId": extra_id,
                        "sessionDir": str(extra_dir.resolve()),
                        "workDir": CWD,
                        "synthetic": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            # Leftover on-disk session must not reappear after index tombstone.
            values = KimiAdapter(root=str(root)).list(query(root, within_min=0), ReadBudget())
            self.assertEqual([item.session_id for item in values], [extra_id])
            with index.open("a", encoding="utf-8") as handle:
                handle.write('{"corrupt":\n')
            values = KimiAdapter(root=str(root)).list(query(root, within_min=0), ReadBudget())
            self.assertEqual([item.session_id for item in values], [extra_id])

            # Decoded-but-structurally-invalid events fail the authoritative
            # index closed rather than being mistaken for harmless syntax.
            with index.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"not": "a session", "synthetic": True}) + "\n")
            values = KimiAdapter(root=str(root)).list(query(root, within_min=0), ReadBudget())
            self.assertEqual(values, [])

        for kind in ("directory", "dangling-symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = materialize_current(Path(temporary) / "current")
                index = root / "session_index.jsonl"
                index.unlink()
                if kind == "directory":
                    index.mkdir()
                else:
                    index.symlink_to(root / "missing-index")
                stdout, stderr = io.StringIO(), io.StringIO()
                code = run(
                    [
                        "kimi",
                        "show",
                        CURRENT_ID,
                        "--cwd",
                        CWD,
                        "--source-root",
                        str(root),
                        "--json",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )
                self.assertEqual(code, 3)
                self.assertIn("E_NO_MATCH", stderr.getvalue())

    def test_partial_index_merges_unindexed_session_from_fs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            sessions = root / "sessions"
            bucket = next(sessions.iterdir())
            extra_id = "44444444-4444-4444-8444-444444444444"
            extra_dir = bucket / extra_id
            (extra_dir / "agents" / "main").mkdir(parents=True)
            (extra_dir / "agents" / "main" / "wire.jsonl").write_text(
                json.dumps(
                    {
                        "type": "context.append_message",
                        "message": {"role": "user", "content": "extra only on disk"},
                        "time": 1784851600,
                        "synthetic": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (extra_dir / "state.json").write_text(
                json.dumps({"synthetic": True, "workDir": CWD, "customTitle": "extra"}),
                encoding="utf-8",
            )
            # Index still only mentions CURRENT_ID (partial / incomplete index).
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, within_min=0), ReadBudget())
            ids = {item.session_id for item in values}
            self.assertIn(CURRENT_ID, ids)
            self.assertIn(extra_id, ids)
            extra = next(item for item in values if item.session_id == extra_id)
            self.assertIn("W_STALE_INDEX", extra.warnings)

    def test_index_line_limit_is_not_softened_to_filesystem_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            index = root / "session_index.jsonl"
            index.write_text(index.read_text(encoding="utf-8") * 2, encoding="utf-8")
            limits = Bounds(transcript_records=1)
            with self.assertRaises(DiagnosticError) as caught:
                KimiAdapter(root=str(root)).list(
                    query(root, within_min=0),
                    ReadBudget(limits=limits),
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_probe_filesystem_fallback_uses_default_aggregate_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            (root / "session_index.jsonl").unlink()
            source = next(root.rglob("wire.jsonl"))
            extra_id = "55555555-5555-4555-8555-555555555555"
            extra = root / "sessions" / "other-bucket" / extra_id / "agents" / "main" / "wire.jsonl"
            extra.parent.mkdir(parents=True)
            extra.write_bytes(source.read_bytes())
            tight = ReadBudget(limits=Bounds(scanned_records=1))
            with mock.patch("portable_resume.adapters.kimi.ReadBudget", return_value=tight):
                with self.assertRaises(DiagnosticError) as caught:
                    KimiAdapter(root=str(root)).probe(query(root, within_min=0))
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_transcript_line_budget_and_oversize_line_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_current(Path(temporary) / "current")
            transcript = next(root.rglob("wire.jsonl"))
            base = transcript.read_bytes()
            adapter = KimiAdapter(root=str(root))
            values = adapter.list(query(root, CURRENT_ID), ReadBudget())
            ref = resolved(values, CURRENT_ID)

            # 50_001 physical transcript lines → explicit limit (no partial Session).
            line = b'{"type":"metadata","synthetic":true}\n'
            with transcript.open("wb") as handle:
                handle.write(base)
                for _ in range(50_001):
                    handle.write(line)
            with self.assertRaises(DiagnosticError) as too_many:
                adapter.show(ref, query(root, CURRENT_ID), ReadBudget())
            self.assertEqual(too_many.exception.code, "E_LIMIT_EXCEEDED")

            # Single line larger than record_bytes.
            with transcript.open("wb") as handle:
                handle.write(base)
                handle.write(b'{"type":"metadata","blob":"' + (b"a" * (16 * 1024 * 1024 + 8)) + b'"}\n')
            with self.assertRaises(DiagnosticError) as oversize:
                adapter.show(ref, query(root, CURRENT_ID), ReadBudget())
            self.assertEqual(oversize.exception.code, "E_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
