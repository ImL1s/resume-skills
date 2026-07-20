from __future__ import annotations

import os
import tempfile
import unittest
import unicodedata
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import SessionSummary
from portable_resume.paths import canonicalize_cwd, same_cwd
from portable_resume.select import AmbiguousSelection, bounded_candidates, select_session


class SelectionAndPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.other = self.root / "other"
        self.other.mkdir()

    def summary(self, session_id: str, *, updated: str | None, title: str | None = None, cwd: Path | None = None, source_path: Path | None = None, source: str = "claude") -> SessionSummary:
        return SessionSummary(
            source=source,
            session_id=session_id,
            updated_at=updated,
            title=title,
            cwd=str(cwd or self.cwd),
            source_path=str(source_path) if source_path else None,
        )

    def test_u006_latest_empty_and_none_choose_newest_exact_cwd(self) -> None:
        values = [
            self.summary("old", updated="2026-01-01T00:00:00Z"),
            self.summary("new", updated="2026-02-01T00:00:00Z"),
            self.summary("foreign", updated="2027-01-01T00:00:00Z", cwd=self.other),
        ]
        for ref in (None, "", "latest"):
            with self.subTest(ref=ref):
                self.assertEqual(select_session(values, ref=ref, cwd=str(self.cwd)).selected.session_id, "new")

    def test_u007_exact_id(self) -> None:
        selected = select_session([self.summary("native-42", updated=None)], ref="native-42", cwd=str(self.cwd))
        self.assertEqual(selected.selected.session_id, "native-42")

    def test_u008_exact_safe_path(self) -> None:
        record = self.root / "session.jsonl"
        record.write_text("{}")
        selected = select_session(
            [self.summary("s", updated=None, source_path=record)],
            ref=str(record),
            cwd=str(self.cwd),
            approved_roots=(str(self.root),),
        )
        self.assertEqual(selected.selected.session_id, "s")

    def test_u009_unique_bounded_text(self) -> None:
        values = [self.summary("one", title="Feature alpha", updated=None), self.summary("two", title="Other", updated=None)]
        self.assertEqual(select_session(values, ref="alpha", cwd=str(self.cwd)).selected.session_id, "one")

    def test_u010_ambiguous_text_is_stable(self) -> None:
        values = [
            self.summary("b", title="same", updated="2026-01-01T00:00:00Z"),
            self.summary("a", title="same", updated="2026-02-01T00:00:00Z"),
        ]
        with self.assertRaises(AmbiguousSelection) as caught:
            select_session(values, ref="same", cwd=str(self.cwd))
        self.assertEqual(caught.exception.code, "E_AMBIGUOUS")
        self.assertEqual([item.session_id for item in caught.exception.candidates], ["a", "b"])

    def test_u011_no_match(self) -> None:
        with self.assertRaises(DiagnosticError) as caught:
            select_session([], ref="missing", cwd=str(self.cwd))
        self.assertEqual(caught.exception.code, "E_NO_MATCH")

    def test_u012_equal_time_uses_source_id_provider_tie_break(self) -> None:
        values = [
            self.summary("z", updated="2026-01-01T00:00:00Z", source="codex"),
            self.summary("a", updated="2026-01-01T00:00:00Z", source="claude"),
        ]
        self.assertEqual(select_session(values, ref="latest", cwd=str(self.cwd)).selected.session_id, "a")

    def test_u013_relative_parent_and_unicode_normalize(self) -> None:
        nested = self.cwd / "nested"
        nested.mkdir()
        self.assertEqual(canonicalize_cwd("..", base=str(nested)), canonicalize_cwd(self.cwd))
        composed = self.root / "caf\u00e9"
        decomposed = self.root / "cafe\u0301"
        self.assertEqual(unicodedata.normalize("NFC", str(decomposed)), str(composed))
        self.assertTrue(same_cwd(str(composed), str(decomposed)))

    def test_u014_path_outside_approved_root(self) -> None:
        approved = self.cwd
        record = self.other / "outside"
        record.write_text("x")
        with self.assertRaises(DiagnosticError) as caught:
            select_session([], ref=str(record), cwd=str(self.cwd), approved_roots=(str(approved),))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_u027_candidates_capped_null_last_and_closed(self) -> None:
        values = [self.summary(str(index), updated=None if index == 0 else f"2026-01-{(index % 28) + 1:02d}T00:00:00Z") for index in range(75)]
        candidates = bounded_candidates(values)
        self.assertEqual(len(candidates), 50)
        self.assertTrue(all(set(item.to_dict()) == {"source", "session_id", "title", "cwd", "branch", "updated_at", "inert", "untrusted_content"} for item in candidates))
        self.assertNotIn("0", [item.session_id for item in candidates])


if __name__ == "__main__":
    unittest.main()
