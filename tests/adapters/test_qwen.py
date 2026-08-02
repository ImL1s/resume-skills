from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.qwen import FORMAT_ID, QwenAdapter
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CWD = "/workspace/project"


def fixture_root() -> Path:
    return (FIXTURES / "qwen" / "s-qwe-01" / "root").resolve()


def query(root: Path, ref: str | None = "qwen-one", **kwargs: object) -> Query:
    return Query(source="qwen", ref=ref, cwd=CWD, source_root=str(root), **kwargs)


def resolved(items, session_id: str = "qwen-one") -> ResolvedRef:
    return ResolvedRef.from_summary(next(item for item in items if item.session_id == session_id))


def write_chat(root: Path, session_id: str, records: list[dict[str, object]], *, project: str = "-workspace-project") -> Path:
    chats = root / "projects" / project / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    path = chats / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records))
    return path


class QwenAdapterTests(unittest.TestCase):
    def test_list_show_selects_last_lineage_filters_internal_and_preserves_source(self) -> None:
        root = fixture_root()
        before = tree_snapshot(root)
        adapter = QwenAdapter(root=str(root))
        current = query(root)

        report = adapter.probe(current)
        self.assertEqual((report.state, report.format_id), ("supported", FORMAT_ID))
        summaries = adapter.list(current, ReadBudget())
        self.assertEqual([item.session_id for item in summaries], ["qwen-one"])
        self.assertEqual(summaries[0].cwd, CWD)
        self.assertNotIn("ignored.runtime", summaries[0].source_path or "")

        session = adapter.show(resolved(summaries), current, ReadBudget())
        self.assertEqual([turn.role for turn in session.turns], ["user", "assistant", "tool"])
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["Inspect the synthetic Qwen store.", "Only public answer text.", "synthetic tool output"],
        )
        combined = " ".join(turn.content for turn in session.turns)
        self.assertNotIn("hidden system", combined)
        self.assertNotIn("private thought", combined)
        self.assertNotIn("abandoned branch", combined)
        self.assertEqual(session.last_user_request, "Inspect the synthetic Qwen store.")
        self.assertEqual(session.last_assistant_action, "Only public answer text.")
        self.assertEqual(tree_snapshot(root), before)

    def test_upstream_genai_content_parts_and_archived_chat(self) -> None:
        root = fixture_root()
        adapter = QwenAdapter(root=str(root))
        current = query(root, ref="archived-one")
        summaries = adapter.list(current, ReadBudget())
        archived = next(item for item in summaries if item.session_id == "archived-one")
        # Path separators are OS-native on Windows (#206/#207).
        source_path = (archived.source_path or "").replace("\\", "/")
        self.assertIn("/chats/archive/", source_path)

        session = adapter.show(ResolvedRef.from_summary(archived), current, ReadBudget())
        self.assertEqual([turn.content for turn in session.turns], ["Archived prompt", "Archived public answer"])
        combined = " ".join(turn.content for turn in session.turns)
        self.assertNotIn("hidden thought", combined)
        self.assertNotIn("private function", combined)
        self.assertNotIn("embedded bytes", combined)
        self.assertIn("W_BINARY_OMITTED", session.warnings)
        self.assertIn("W_MISSING_BLOB", session.warnings)

    def test_root_precedence_runtime_then_home_with_query_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime_root = base / "runtime"
            home_root = base / "home"
            override_root = base / "override"
            for root, session_id in (
                (runtime_root, "runtime-one"),
                (home_root, "home-one"),
                (override_root, "override-one"),
            ):
                write_chat(
                    root,
                    session_id,
                    [
                        {
                            "uuid": f"{session_id}-message",
                            "parentUuid": None,
                            "sessionId": session_id,
                            "timestamp": "2026-07-24T00:00:00Z",
                            "type": "user",
                            "cwd": CWD,
                            "message": session_id,
                        }
                    ],
                )
            environment = {"QWEN_RUNTIME_DIR": str(runtime_root), "QWEN_HOME": str(home_root)}
            with mock.patch.dict(os.environ, environment, clear=False):
                adapter = QwenAdapter()
                runtime = adapter.list(Query(source="qwen", cwd=CWD, within_min=0), ReadBudget())
                self.assertEqual([item.session_id for item in runtime], ["runtime-one"])
                overridden = adapter.list(
                    Query(source="qwen", cwd=CWD, source_root=str(override_root), within_min=0),
                    ReadBudget(),
                )
                self.assertEqual([item.session_id for item in overridden], ["override-one"])
            with mock.patch.dict(os.environ, {"QWEN_HOME": str(home_root)}, clear=True):
                home = QwenAdapter().list(Query(source="qwen", cwd=CWD, within_min=0), ReadBudget())
                self.assertEqual([item.session_id for item in home], ["home-one"])

    def test_ref_cwd_age_runtime_sidecar_and_broken_chain(self) -> None:
        root = fixture_root()
        adapter = QwenAdapter(root=str(root))
        self.assertEqual(adapter.list(Query(source="qwen", cwd="/different", source_root=str(root)), ReadBudget()), [])
        # The fixture is older than the default window, but an exact id bypasses age.
        exact = adapter.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in exact], ["qwen-one"])
        path_ref = adapter.list(query(root, ref=exact[0].source_path), ReadBudget())
        self.assertEqual([item.session_id for item in path_ref], ["qwen-one"])

        with tempfile.TemporaryDirectory() as temporary:
            broken_root = Path(temporary)
            chat = write_chat(
                broken_root,
                "broken-one",
                [
                    {
                        "uuid": "root",
                        "parentUuid": None,
                        "sessionId": "broken-one",
                        "timestamp": "2026-07-24T00:00:00Z",
                        "type": "user",
                        "cwd": CWD,
                        "message": "complete root",
                    },
                    {
                        "uuid": "orphan",
                        "parentUuid": "missing",
                        "sessionId": "broken-one",
                        "timestamp": "2026-07-24T00:01:00Z",
                        "type": "assistant",
                        "cwd": CWD,
                        "message": "orphan answer",
                    },
                ],
            )
            (chat.parent / "broken-one.runtime.json").write_text("{not transcript")
            current = Query(source="qwen", ref="broken-one", cwd=CWD, source_root=str(broken_root))
            values = QwenAdapter().list(current, ReadBudget())
            session = QwenAdapter().show(resolved(values, "broken-one"), current, ReadBudget())
            self.assertIn("W_BROKEN_CHAIN", session.warnings)
            self.assertEqual([turn.content for turn in session.turns], ["complete root"])

    def test_flat_records_without_parent_links_preserve_file_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_chat(
                root,
                "flat-one",
                [
                    {
                        "uuid": "first",
                        "sessionId": "flat-one",
                        "timestamp": "2026-07-24T00:00:00Z",
                        "type": "user",
                        "cwd": CWD,
                        "message": "flat prompt",
                    },
                    {
                        "uuid": "second",
                        "sessionId": "flat-one",
                        "timestamp": "2026-07-24T00:01:00Z",
                        "type": "assistant",
                        "cwd": CWD,
                        "message": "flat response",
                    },
                ],
            )
            current = Query(source="qwen", ref="flat-one", cwd=CWD, source_root=str(root))
            values = QwenAdapter().list(current, ReadBudget())
            session = QwenAdapter().show(resolved(values, "flat-one"), current, ReadBudget())
            self.assertEqual([turn.content for turn in session.turns], ["flat prompt", "flat response"])

    def test_current_duplicate_uuid_fragments_are_aggregated_but_conflicts_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_chat(
                root,
                "fragments-one",
                [
                    {
                        "uuid": "user",
                        "parentUuid": None,
                        "sessionId": "fragments-one",
                        "timestamp": "2026-07-24T00:00:00Z",
                        "type": "user",
                        "cwd": CWD,
                        "message": {"role": "user", "parts": [{"text": "prompt"}]},
                    },
                    {
                        "uuid": "answer",
                        "parentUuid": "user",
                        "sessionId": "fragments-one",
                        "timestamp": "2026-07-24T00:01:00Z",
                        "type": "assistant",
                        "cwd": CWD,
                        "message": {"role": "model", "parts": [{"text": "part one"}]},
                    },
                    {
                        "uuid": "answer",
                        "parentUuid": "user",
                        "sessionId": "fragments-one",
                        "timestamp": "2026-07-24T00:01:01Z",
                        "type": "assistant",
                        "cwd": CWD,
                        "message": {"role": "model", "parts": [{"text": "part two"}]},
                    },
                ],
            )
            current = Query(
                source="qwen",
                ref="fragments-one",
                cwd=CWD,
                source_root=str(root),
            )
            values = QwenAdapter().list(current, ReadBudget())
            session = QwenAdapter().show(
                resolved(values, "fragments-one"),
                current,
                ReadBudget(),
            )
            self.assertEqual(
                [turn.content for turn in session.turns],
                ["prompt", "part one\npart two"],
            )

            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            records[-1]["parentUuid"] = "different"
            path.write_text(
                "".join(
                    json.dumps(record, separators=(",", ":")) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            # List is metadata-only (no UUID lineage graph). Fragment conflicts
            # fail closed on show, which still aggregates and validates lineage.
            list_after = QwenAdapter().list(current, ReadBudget())
            self.assertEqual([item.session_id for item in list_after], ["fragments-one"])
            with self.assertRaises(DiagnosticError) as caught:
                QwenAdapter().show(resolved(list_after, "fragments-one"), current, ReadBudget())
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_partial_tail_is_skipped_but_interior_and_duplicate_key_corruption_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_chat(
                root,
                "tail-one",
                [
                    {
                        "uuid": "root",
                        "parentUuid": None,
                        "sessionId": "tail-one",
                        "timestamp": "2026-07-24T00:00:00Z",
                        "type": "user",
                        "cwd": CWD,
                        "message": "safe",
                    }
                ],
            )
            path.write_bytes(path.read_bytes() + b'{"uuid":')
            current = Query(source="qwen", ref="tail-one", cwd=CWD, source_root=str(root))
            values = QwenAdapter().list(current, ReadBudget())
            session = QwenAdapter().show(resolved(values, "tail-one"), current, ReadBudget())
            self.assertIn("W_PARTIAL_TAIL", session.warnings)

        for corrupt in (
            b'{"uuid":\n',
            b'{"uuid":"a","uuid":"b","type":"user","message":"bad"}\n',
        ):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = write_chat(
                    root,
                    "bad-one",
                    [
                        {
                            "uuid": "root",
                            "parentUuid": None,
                            "sessionId": "bad-one",
                            "timestamp": "2026-07-24T00:00:00Z",
                            "type": "user",
                            "cwd": CWD,
                            "message": "safe",
                        }
                    ],
                )
                path.write_bytes(corrupt + path.read_bytes())
                with self.assertRaises(DiagnosticError) as caught:
                    QwenAdapter().list(
                        Query(source="qwen", ref="bad-one", cwd=CWD, source_root=str(root)),
                        ReadBudget(),
                    )
                self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_symlinked_transcript_is_rejected_and_changing_source_is_busy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.jsonl"
            outside.write_text('{"type":"user","message":"outside"}\n')
            chats = root / "projects" / "project" / "chats"
            chats.mkdir(parents=True)
            (chats / "linked.jsonl").symlink_to(outside)
            with self.assertRaises(DiagnosticError) as caught:
                QwenAdapter().list(
                    Query(source="qwen", ref="linked", cwd=CWD, source_root=str(root)),
                    ReadBudget(),
                )
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_chat(
                root,
                "race-one",
                [
                    {
                        "uuid": "root",
                        "parentUuid": None,
                        "sessionId": "race-one",
                        "timestamp": "2026-07-24T00:00:00Z",
                        "type": "user",
                        "cwd": CWD,
                        "message": "race",
                    }
                ],
            )

            def race(phase: str, _attempt: int, path: str) -> None:
                if phase == "after-read":
                    with open(path, "ab") as handle:
                        handle.write(b" ")

            with self.assertRaises(DiagnosticError) as caught:
                QwenAdapter(read_hook=race).list(
                    Query(source="qwen", ref="race-one", cwd=CWD, source_root=str(root)),
                    ReadBudget(),
                )
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_issue12_list_uses_scanned_budget_show_uses_transcript(self) -> None:
        """Large multi-line chats: list charges scanned_records; show uses transcript."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "large-lines"
            records = [
                {
                    "uuid": "root",
                    "parentUuid": None,
                    "sessionId": session_id,
                    "timestamp": "2026-07-24T00:00:00Z",
                    "type": "user",
                    "cwd": CWD,
                    "message": "large chat prompt",
                }
            ]
            # > default discovery-oriented ceilings for show when mis-charged, but
            # under normalized_turns so a correct full show still succeeds.
            for index in range(1, 1_500):
                records.append(
                    {
                        "uuid": f"a{index}",
                        "parentUuid": "root" if index == 1 else f"a{index - 1}",
                        "sessionId": session_id,
                        "timestamp": f"2026-07-24T00:00:{index % 60:02d}Z",
                        "type": "assistant",
                        "cwd": CWD,
                        "message": f"line {index}",
                    }
                )
            write_chat(root, session_id, records)
            current = Query(
                source="qwen",
                ref=session_id,
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            )
            # List must not charge transcript_records even when that ceiling is tiny.
            list_budget = ReadBudget(
                Bounds(scanned_records=2_000, transcript_records=10)
            )
            summaries = QwenAdapter().list(current, list_budget)
            self.assertEqual([item.session_id for item in summaries], [session_id])
            self.assertEqual(summaries[0].title, "large chat prompt")
            self.assertEqual(list_budget.transcript_records_read, 0)
            self.assertGreater(list_budget.records, 0)

            # Show charges transcript_records via stable_scan_lines; low ceiling fails.
            with self.assertRaises(DiagnosticError) as caught:
                QwenAdapter().show(
                    ResolvedRef.from_summary(summaries[0]),
                    current,
                    ReadBudget(Bounds(transcript_records=50)),
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

            shown = QwenAdapter().show(
                ResolvedRef.from_summary(summaries[0]),
                current,
                ReadBudget(),
            )
            self.assertEqual(shown.turns[0].content, "large chat prompt")
            self.assertGreater(len(shown.turns), 100)

    def test_issue12_file_over_record_bytes_streams_under_source_read(self) -> None:
        """Whole-file > record_bytes but under source_read_bytes still lists/shows."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "oversize-file"
            path = write_chat(
                root,
                session_id,
                [
                    {
                        "uuid": "root",
                        "parentUuid": None,
                        "sessionId": session_id,
                        "timestamp": "2026-07-24T00:00:00Z",
                        "type": "user",
                        "cwd": CWD,
                        "message": "oversize prompt",
                    }
                ],
            )
            # ~17 MiB via fewer large pad lines so show stays under transcript_records.
            # Pads share one uuid so fragment aggregation collapses them; the final
            # answer is written last so lineage selects it as the current leaf.
            filler = (
                json.dumps(
                    {
                        "uuid": "pad",
                        "parentUuid": "root",
                        "sessionId": session_id,
                        "timestamp": "2026-07-24T00:00:30Z",
                        "type": "assistant",
                        "cwd": CWD,
                        "message": "x" * 8_000,
                        "synthetic": True,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            target = 17 * 1024 * 1024
            with path.open("ab") as handle:
                written = 0
                while written < target:
                    handle.write(filler.encode("utf-8"))
                    written += len(filler)
                handle.write(
                    (
                        json.dumps(
                            {
                                "uuid": "answer",
                                "parentUuid": "root",
                                "sessionId": session_id,
                                "timestamp": "2026-07-24T00:01:00Z",
                                "type": "assistant",
                                "cwd": CWD,
                                "message": "oversize answer",
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                )
            self.assertGreater(path.stat().st_size, 16 * 1024 * 1024)

            current = Query(
                source="qwen",
                ref=session_id,
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            )
            # List uses head/tail windows (not whole-file record_bytes).
            summaries = QwenAdapter().list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [session_id])
            self.assertEqual(summaries[0].title, "oversize prompt")

            # Show streams via stable_scan_lines under source_read_bytes.
            shown = QwenAdapter().show(
                ResolvedRef.from_summary(summaries[0]),
                current,
                ReadBudget(),
            )
            self.assertEqual(shown.turns[0].content, "oversize prompt")
            self.assertIn("oversize answer", [turn.content for turn in shown.turns])

    def test_issue12_exact_path_ref_skips_directory_enumeration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_chat(
                root,
                "exact-one",
                [
                    {
                        "uuid": "root",
                        "parentUuid": None,
                        "sessionId": "exact-one",
                        "timestamp": "2026-07-24T00:00:00Z",
                        "type": "user",
                        "cwd": CWD,
                        "message": "exact path",
                    }
                ],
            )
            adapter = QwenAdapter(root=str(root))
            current = Query(
                source="qwen",
                ref=str(path.resolve()),
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            )
            with mock.patch.object(
                adapter,
                "_session_paths",
                side_effect=AssertionError("_session_paths must not run for exact path"),
            ):
                summaries = adapter.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], ["exact-one"])
            self.assertTrue(
                summaries[0].source_path is not None
                and summaries[0].source_path.endswith("exact-one.jsonl")
            )

    def test_issue12_directory_enumeration_fails_before_unbounded_sort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "projects").mkdir(parents=True)
            scan_limit = Bounds().scanned_records

            class _FakeEntry:
                def __init__(self, name: str, path: str) -> None:
                    self.name = name
                    self.path = path

                def is_symlink(self) -> bool:
                    return False

                def stat(self, follow_symlinks: bool = True):  # noqa: ARG002
                    import stat as stat_mod

                    class _S:
                        st_mode = stat_mod.S_IFDIR

                    return _S()

            def fake_scandir(path: str | os.PathLike[str]):
                path_str = os.fspath(path)
                # Only the projects root is over-populated; fail closed while admitting.
                if os.path.basename(path_str.rstrip(os.sep)) == "projects":

                    class _CM:
                        def __iter__(self):
                            for index in range(scan_limit + 5):
                                name = f"proj-{index:05d}"
                                yield _FakeEntry(name, os.path.join(path_str, name))

                        def __enter__(self):
                            return self

                        def __exit__(self, *args: object) -> None:
                            return None

                    return _CM()
                raise AssertionError(f"unexpected scandir after bound: {path_str}")

            adapter = QwenAdapter(root=str(root))
            with mock.patch("portable_resume.adapters.qwen.os.scandir", side_effect=fake_scandir):
                with self.assertRaises(DiagnosticError) as caught:
                    adapter.list(
                        Query(source="qwen", cwd=CWD, source_root=str(root), within_min=0),
                        ReadBudget(),
                    )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
