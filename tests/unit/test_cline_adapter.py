from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import ResolvedRef
from portable_resume.adapters.cline import ADAPTER, FORMAT_ID
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query
from tests.helpers.core import tree_snapshot

FIXTURES = Path("tests/fixtures/cline")
CWD = "/tmp/project"
BASIC_ID = "cl000101-0101-4101-8101-010101010101"
CHILD_ID = "cl000102-0202-4202-8202-020202020202"


def fixture_root(case: str) -> Path:
    return (FIXTURES / case).resolve()


def query(root: Path, ref: str | None = None, **kwargs: object) -> Query:
    return Query(
        source="cline",
        ref=ref,
        cwd=CWD,
        source_root=str(root),
        within_min=0,
        **kwargs,
    )


class ClineAdapterTests(unittest.TestCase):
    def _assert_soft_listing_diagnostic(
        self,
        error: DiagnosticError,
        *,
        propagates: bool,
    ) -> None:
        import tempfile

        from portable_resume.adapters import cline as cline_mod
        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            sessions_dir = Path(temporary) / "sessions"
            messages_path = bf._write_session_files(
                sessions_dir,
                session_id=BASIC_ID,
                messages=[{"id": "u", "role": "user", "content": "placeholder"}],
            )
            messages_path.write_bytes(b"x" * (cline_mod._LIST_ELIGIBILITY_BYTES + 1))
            current = Query(
                source="cline",
                cwd=None,
                source_root=str(sessions_dir),
                within_min=0,
            )

            with mock.patch(
                "portable_resume.adapters.cline.stable_read_windows",
                side_effect=error,
            ):
                if propagates:
                    with self.assertRaises(DiagnosticError) as caught:
                        ADAPTER.list(current, ReadBudget())
                    self.assertEqual(caught.exception.code, error.code)
                else:
                    self.assertEqual(ADAPTER.list(current, ReadBudget()), [])

    def test_soft_listing_propagates_unsafe_path(self) -> None:
        self._assert_soft_listing_diagnostic(
            DiagnosticError.unsafe_path(), propagates=True
        )

    def test_soft_listing_propagates_source_busy(self) -> None:
        self._assert_soft_listing_diagnostic(
            DiagnosticError.source_busy(), propagates=True
        )

    def test_soft_listing_propagates_budget_exhaustion(self) -> None:
        self._assert_soft_listing_diagnostic(
            DiagnosticError.limit_exceeded(), propagates=True
        )

    def test_soft_listing_propagates_unknown_diagnostic(self) -> None:
        self._assert_soft_listing_diagnostic(
            DiagnosticError("E_INVARIANT"), propagates=True
        )

    def test_soft_listing_skips_corrupt_candidate(self) -> None:
        self._assert_soft_listing_diagnostic(
            DiagnosticError("E_CORRUPT_RECORD"), propagates=False
        )

    def test_exact_indexless_selection_propagates_unsafe_messages_read(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        sessions_only = root / "data" / "sessions"
        current = Query(
            source="cline",
            ref=BASIC_ID,
            cwd=CWD,
            source_root=str(sessions_only),
            within_min=0,
        )

        with mock.patch(
            "portable_resume.adapters.cline._load_messages_payload",
            side_effect=DiagnosticError.unsafe_path(),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(current, ReadBudget())

        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_indexless_listing_propagates_busy_messages_read(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        sessions_only = root / "data" / "sessions"
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(sessions_only),
            within_min=0,
        )

        with mock.patch(
            "portable_resume.adapters.cline._load_messages_payload",
            side_effect=DiagnosticError.source_busy(),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(current, ReadBudget())

        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_indexless_listing_propagates_unknown_messages_diagnostic(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        sessions_only = root / "data" / "sessions"
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(sessions_only),
            within_min=0,
        )

        with mock.patch(
            "portable_resume.adapters.cline._load_messages_payload",
            side_effect=DiagnosticError("E_INVARIANT"),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.list(current, ReadBudget())

        self.assertEqual(caught.exception.code, "E_INVARIANT")

    def test_indexless_listing_propagates_manifest_budget_exhaustion(self) -> None:
        from portable_resume.bounds import Bounds

        root = fixture_root("s-cl-01-user-basic")
        sessions_only = root / "data" / "sessions"
        messages_path = sessions_only / BASIC_ID / f"{BASIC_ID}.messages.json"
        budget = ReadBudget(
            limits=Bounds(source_read_bytes=messages_path.stat().st_size)
        )
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(sessions_only),
            within_min=0,
        )

        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.list(current, budget)

        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_indexless_listing_keeps_session_with_corrupt_manifest(self) -> None:
        import tempfile

        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            sessions_dir = Path(temporary) / "sessions"
            bf._write_session_files(
                sessions_dir,
                session_id=BASIC_ID,
                messages=[
                    {"id": "u", "role": "user", "content": "kept user"},
                    {"id": "a", "role": "assistant", "content": "kept reply"},
                ],
            )
            manifest_path = sessions_dir / BASIC_ID / f"{BASIC_ID}.json"
            manifest_path.write_text("{not-json", encoding="utf-8")
            current = Query(
                source="cline",
                cwd=None,
                source_root=str(sessions_dir),
                within_min=0,
            )

            summaries = ADAPTER.list(current, ReadBudget())

        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
        self.assertIsNone(summaries[0].title)

    def test_show_propagates_busy_manifest_read(self) -> None:
        from portable_resume.adapters import cline as cline_mod

        root = fixture_root("s-cl-01-user-basic")
        sessions_only = root / "data" / "sessions"
        current = Query(
            source="cline",
            ref=BASIC_ID,
            cwd=CWD,
            source_root=str(sessions_only),
            within_min=0,
        )
        original_read = cline_mod.stable_read_bytes

        def busy_manifest(path: str, **kwargs: object) -> object:
            if path.endswith(f"/{BASIC_ID}.json"):
                raise DiagnosticError.source_busy()
            return original_read(path, **kwargs)

        with mock.patch(
            "portable_resume.adapters.cline.stable_read_bytes",
            side_effect=busy_manifest,
        ):
            with self.assertRaises(DiagnosticError) as caught:
                ADAPTER.show(
                    ResolvedRef(session_id=BASIC_ID, source_path=""),
                    current,
                    ReadBudget(),
                )

        self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_show_keeps_session_with_corrupt_manifest(self) -> None:
        import tempfile

        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            sessions_dir = Path(temporary) / "sessions"
            messages_path = bf._write_session_files(
                sessions_dir,
                session_id=BASIC_ID,
                messages=[
                    {"id": "u", "role": "user", "content": "kept user"},
                    {"id": "a", "role": "assistant", "content": "kept reply"},
                ],
            )
            manifest_path = sessions_dir / BASIC_ID / f"{BASIC_ID}.json"
            manifest_path.write_text("{not-json", encoding="utf-8")
            current = Query(
                source="cline",
                ref=BASIC_ID,
                cwd=None,
                source_root=str(sessions_dir),
                within_min=0,
            )

            session = ADAPTER.show(
                ResolvedRef(session_id=BASIC_ID, source_path=str(messages_path)),
                current,
                ReadBudget(),
            )

        self.assertEqual(session.session_id, BASIC_ID)
        self.assertEqual([turn.content for turn in session.turns], ["kept user", "kept reply"])

    def test_list_and_show_basic(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        before = tree_snapshot(root)
        current = query(root)
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].session_id, BASIC_ID)
        self.assertEqual(summaries[0].provider, FORMAT_ID)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic cline user prompt", "synthetic cline assistant reply"],
        )
        self.assertEqual(tree_snapshot(root), before)

    def test_probe_supported(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        report = ADAPTER.probe(query(root))
        self.assertEqual(report.state, "supported")
        self.assertEqual(report.format_id, FORMAT_ID)

    def test_default_list_hides_subagent(self) -> None:
        root = fixture_root("s-cl-02-parent-subagent")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
        child = ADAPTER.show(
            ResolvedRef(session_id=CHILD_ID, source_path=""),
            query(root, ref=CHILD_ID),
            ReadBudget(),
        )
        self.assertEqual(child.session_id, CHILD_ID)
        self.assertIn("child should hide", child.turns[0].content)

    def test_unsupported_messages_version(self) -> None:
        root = fixture_root("s-cl-03-unsupported-messages")
        with self.assertRaises(DiagnosticError) as caught:
            ADAPTER.show(
                ResolvedRef(session_id=BASIC_ID, source_path=""),
                query(root, ref=BASIC_ID),
                ReadBudget(),
            )
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED_FORMAT")

    def test_cwd_mismatch_filtered(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        other = Query(
            source="cline",
            cwd="/tmp/other",
            source_root=str(root),
            within_min=0,
        )
        self.assertEqual(ADAPTER.list(other, ReadBudget()), [])

    def test_sessions_dir_only_lists_without_index(self) -> None:
        root = fixture_root("s-cl-01-user-basic")
        sessions_only = root / "data" / "sessions"
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(sessions_only),
            within_min=0,
        )
        report = ADAPTER.probe(current)
        self.assertIn(report.state, {"partial", "supported"})
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(session.session_id, BASIC_ID)
        self.assertTrue(session.turns)

    def test_prompt_only_without_messages_not_listed(self) -> None:
        import tempfile
        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            db_path = data / "db" / "sessions.db"
            sessions_dir = data / "sessions"
            conn = bf._connect(db_path)
            # Index has prompt but no messages file on disk.
            bf._insert_session(
                conn,
                session_id=BASIC_ID,
                prompt="stale prompt only",
                messages_path="",
                updated_at="2024-06-01T12:00:00.000000Z",
            )
            # Older valid session should win latest.
            other = "cl000199-0101-4101-8101-010101010199"
            bf._write_session_files(
                sessions_dir,
                session_id=other,
                messages=[
                    {"id": "u", "role": "user", "content": "older valid user"},
                    {"id": "a", "role": "assistant", "content": "older valid asst"},
                ],
            )
            bf._insert_session(
                conn,
                session_id=other,
                prompt="older valid user",
                messages_path="",
                updated_at="2024-01-01T12:00:00.000000Z",
            )
            conn.commit()
            conn.close()
            current = Query(
                source="cline",
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            )
            summaries = ADAPTER.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [other])

    def test_exact_sessions_db_source_root_can_show(self) -> None:
        """Direct sessions.db path must still reach sibling messages JSON (Codex P2)."""
        root = fixture_root("s-cl-01-user-basic")
        db_path = root / "data" / "db" / "sessions.db"
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(db_path),
            within_min=0,
        )
        report = ADAPTER.probe(current)
        self.assertEqual(report.state, "supported")
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(
            [turn.content for turn in session.turns],
            ["synthetic cline user prompt", "synthetic cline assistant reply"],
        )

    def test_data_db_directory_source_root_can_show(self) -> None:
        """source_root=.../data/db must contain under data so sessions/ is readable (Codex P1)."""
        root = fixture_root("s-cl-01-user-basic")
        db_dir = root / "data" / "db"
        current = Query(
            source="cline",
            cwd=CWD,
            source_root=str(db_dir),
            within_min=0,
        )
        report = ADAPTER.probe(current)
        self.assertEqual(report.state, "supported")
        summaries = ADAPTER.list(current, ReadBudget())
        self.assertEqual(len(summaries), 1)
        session = ADAPTER.show(ResolvedRef.from_summary(summaries[0]), current, ReadBudget())
        self.assertEqual(session.session_id, BASIC_ID)
        self.assertTrue(session.turns)

    def test_list_skips_corrupt_newer_and_keeps_older_valid(self) -> None:
        """Default list must skip corrupt/unsupported candidates for latest (Codex P1)."""
        import tempfile
        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            db_path = data / "db" / "sessions.db"
            sessions_dir = data / "sessions"
            conn = bf._connect(db_path)
            corrupt_id = "cl000188-0101-4101-8101-010101010188"
            good_id = "cl000177-0101-4101-8101-010101010177"
            corrupt_dir = sessions_dir / corrupt_id
            corrupt_dir.mkdir(parents=True)
            (corrupt_dir / f"{corrupt_id}.messages.json").write_text(
                "{not-json",
                encoding="utf-8",
            )
            bf._insert_session(
                conn,
                session_id=corrupt_id,
                prompt="newer corrupt",
                messages_path="",
                updated_at="2024-06-02T12:00:00.000000Z",
            )
            bf._write_session_files(
                sessions_dir,
                session_id=good_id,
                messages=[
                    {"id": "u", "role": "user", "content": "older good user"},
                    {"id": "a", "role": "assistant", "content": "older good asst"},
                ],
            )
            bf._insert_session(
                conn,
                session_id=good_id,
                prompt="older good user",
                messages_path="",
                updated_at="2024-06-01T12:00:00.000000Z",
            )
            conn.commit()
            conn.close()
            current = Query(
                source="cline",
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            )
            summaries = ADAPTER.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [good_id])
            session = ADAPTER.show(
                ResolvedRef.from_summary(summaries[0]), current, ReadBudget()
            )
            self.assertEqual(session.session_id, good_id)

    def test_list_summaries_use_messages_source_path(self) -> None:
        """Indexed list should expose messages path for exact-path selection (Codex P2)."""
        root = fixture_root("s-cl-01-user-basic")
        summaries = ADAPTER.list(query(root), ReadBudget())
        self.assertEqual(len(summaries), 1)
        self.assertTrue(
            summaries[0].source_path.endswith(f"{BASIC_ID}.messages.json"),
            summaries[0].source_path,
        )

    def test_exact_id_missing_from_stale_index_recovers_json(self) -> None:
        """Exact id not in sessions.db still recovers sessions/<id> messages (Codex P1)."""
        import tempfile
        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            db_path = data / "db" / "sessions.db"
            sessions_dir = data / "sessions"
            conn = bf._connect(db_path)
            # Index has an unrelated session only.
            other = "cl000155-0101-4101-8101-010101010155"
            bf._write_session_files(
                sessions_dir,
                session_id=other,
                messages=[
                    {"id": "u", "role": "user", "content": "indexed only"},
                    {"id": "a", "role": "assistant", "content": "indexed reply"},
                ],
            )
            bf._insert_session(
                conn,
                session_id=other,
                prompt="indexed only",
                messages_path="",
            )
            # Target exists only as messages JSON (stale index gap).
            missing = "cl000166-0101-4101-8101-010101010166"
            bf._write_session_files(
                sessions_dir,
                session_id=missing,
                messages=[
                    {"id": "u", "role": "user", "content": "json-only exact"},
                    {"id": "a", "role": "assistant", "content": "json-only reply"},
                ],
            )
            conn.commit()
            conn.close()
            current = Query(
                source="cline",
                cwd=CWD,
                source_root=str(root),
                ref=missing,
                within_min=0,
            )
            summaries = ADAPTER.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [missing])
            session = ADAPTER.show(
                ResolvedRef.from_summary(summaries[0]), current, ReadBudget()
            )
            self.assertEqual(session.session_id, missing)
            self.assertIn("json-only exact", session.turns[0].content)

    def test_corrupt_index_falls_back_to_sessions_json(self) -> None:
        """Unsupported/corrupt sessions.db must not block JSON recovery (Codex P1)."""
        import sqlite3
        import tempfile
        from tests.fixtures.cline import build_fixtures as bf

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            db_path = data / "db" / "sessions.db"
            sessions_dir = data / "sessions"
            db_path.parent.mkdir(parents=True)
            # Valid JSON sessions.
            bf._write_session_files(
                sessions_dir,
                session_id=BASIC_ID,
                messages=[
                    {"id": "u", "role": "user", "content": "from json only"},
                    {"id": "a", "role": "assistant", "content": "json reply"},
                ],
            )
            # Corrupt/unsupported index (empty DB, no sessions table).
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE other (id INTEGER)")
            conn.commit()
            conn.close()
            current = Query(
                source="cline",
                cwd=CWD,
                source_root=str(root),
                within_min=0,
            )
            report = ADAPTER.probe(current)
            self.assertIn(report.state, {"partial", "supported"})
            summaries = ADAPTER.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [BASIC_ID])
            session = ADAPTER.show(
                ResolvedRef.from_summary(summaries[0]), current, ReadBudget()
            )
            self.assertIn("from json only", session.turns[0].content)

    def test_large_messages_list_uses_tail_for_envelope(self) -> None:
        """Oversized sort_keys JSON keeps sessionId/version in the tail (Codex P1)."""
        import json
        import tempfile
        from portable_resume.adapters import cline as cline_mod

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions_dir = root / "data" / "sessions"
            session_id = BASIC_ID
            session_dir = sessions_dir / session_id
            session_dir.mkdir(parents=True)
            # Build a payload larger than list eligibility with sort_keys so
            # version/sessionId sit after the messages array.
            filler = "x" * (cline_mod._LIST_ELIGIBILITY_BYTES + 8_000)
            payload = {
                "agent": "lead",
                "messages": [
                    {"id": "u", "role": "user", "content": filler},
                    {"id": "a", "role": "assistant", "content": "large reply"},
                ],
                "sessionId": session_id,
                "updated_at": "2024-01-01T12:00:00.000000Z",
                "version": 1,
            }
            (session_dir / f"{session_id}.messages.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest = {
                "version": 1,
                "session_id": session_id,
                "cwd": CWD,
                "workspace_root": CWD,
                "prompt": "large",
                "started_at": "2024-01-01T12:00:00.000000Z",
                "updated_at": "2024-01-01T12:00:00.000000Z",
            }
            (session_dir / f"{session_id}.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            current = Query(
                source="cline",
                cwd=CWD,
                source_root=str(sessions_dir),
                within_min=0,
            )
            summaries = ADAPTER.list(current, ReadBudget())
            self.assertEqual([item.session_id for item in summaries], [session_id])

    def test_indexless_scan_does_not_prefer_early_id_over_newer(self) -> None:
        """Indexless list must not truncate alphabetically before recency sort (Codex P1)."""
        import tempfile
        from tests.fixtures.cline import build_fixtures as bf
        from portable_resume.bounds import Bounds, ReadBudget

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions_dir = root / "data" / "sessions"
            # Early ID (alphabetically first), older stamp.
            early = "cl000001-0101-4101-8101-010101010001"
            late = "cl000999-0101-4101-8101-010101010999"
            for session_id, stamp, prompt in (
                (early, "2024-01-01T12:00:00.000000Z", "older early id"),
                (late, "2024-06-01T12:00:00.000000Z", "newer late id"),
            ):
                bf._write_session_files(
                    sessions_dir,
                    session_id=session_id,
                    messages=[
                        {"id": "u", "role": "user", "content": prompt},
                        {"id": "a", "role": "assistant", "content": "reply"},
                    ],
                )
                # Patch manifest timestamps for recency.
                manifest = sessions_dir / session_id / f"{session_id}.json"
                import json

                data = json.loads(manifest.read_text(encoding="utf-8"))
                data["started_at"] = stamp
                data["updated_at"] = stamp
                manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            current = Query(
                source="cline",
                cwd=CWD,
                source_root=str(sessions_dir),
                within_min=0,
            )
            # listed_sessions=1 would wrongly pick early id if truncated pre-sort.
            budget = ReadBudget(limits=Bounds(listed_sessions=1))
            summaries = ADAPTER.list(current, budget)
            self.assertEqual([item.session_id for item in summaries], [late])


if __name__ == "__main__":
    unittest.main()
