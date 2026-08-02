"""CLI --output atomic no-clobber wiring for list/sources."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import CapabilityReport
from portable_resume.model import SessionSummary
from portable_resume.reader import run


class ReaderOutputCliTests(unittest.TestCase):
    def test_list_output_no_clobber_and_matches_stdout(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return [
                        SessionSummary(
                            source=source,
                            session_id="s1",
                            title="hello",
                            cwd=query.cwd,
                            updated_at="2026-08-01T12:00:00Z",
                        )
                    ]

            return _Adapter()

        with tempfile.TemporaryDirectory() as temporary:
            out_path = Path(temporary) / "list.json"
            with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
                stdout = io.StringIO()
                code = run(
                    [
                        "claude",
                        "list",
                        "--format",
                        "json",
                        "--cwd",
                        temporary,
                        "--output",
                        str(out_path),
                    ],
                    stdout=stdout,
                    stderr=io.StringIO(),
                )
                self.assertEqual(code, 0)
                self.assertEqual(stdout.getvalue(), "")
                file_bytes = out_path.read_text(encoding="utf-8")

                stdout2 = io.StringIO()
                code2 = run(
                    ["claude", "list", "--format", "json", "--cwd", temporary],
                    stdout=stdout2,
                    stderr=io.StringIO(),
                )
                self.assertEqual(code2, 0)
                self.assertEqual(file_bytes, stdout2.getvalue())

                # Second write without --force must fail and preserve content.
                stderr = io.StringIO()
                code3 = run(
                    [
                        "claude",
                        "list",
                        "--format",
                        "json",
                        "--cwd",
                        temporary,
                        "--output",
                        str(out_path),
                    ],
                    stdout=io.StringIO(),
                    stderr=stderr,
                )
                self.assertEqual(code3, 2)
                self.assertIn("E_INVALID_INPUT", stderr.getvalue())
                self.assertEqual(out_path.read_text(encoding="utf-8"), file_bytes)

                # --force replaces.
                code4 = run(
                    [
                        "claude",
                        "list",
                        "--format",
                        "json",
                        "--cwd",
                        temporary,
                        "--output",
                        str(out_path),
                        "--force",
                    ],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
                self.assertEqual(code4, 0)
                self.assertEqual(out_path.read_text(encoding="utf-8"), file_bytes)

    def test_output_dash_writes_stdout(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "supported")

                def list(self, query, budget):  # noqa: ANN001
                    return []

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            stdout = io.StringIO()
            code = run(
                ["claude", "list", "--format", "json", "--output", "-"],
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["operation"], "list")

    def test_force_without_output_is_invalid(self) -> None:
        code = run(
            ["claude", "list", "--force"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        self.assertEqual(code, 2)

    def test_sources_output_file(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    return CapabilityReport(source, "fixture", "unavailable")

            return _Adapter()

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sources.json"
            with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
                code = run(
                    ["sources", "--json", "--output", str(path)],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            self.assertEqual(code, 0)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "portable-resume/sources-v1")


if __name__ == "__main__":
    unittest.main()
