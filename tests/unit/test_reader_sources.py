"""Plan 044: portable-resume sources presence sweep."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import CapabilityReport
from portable_resume.diagnostics import DiagnosticError, SOURCE_KEYS
from portable_resume.model import SOURCE_KEYS as MODEL_KEYS
from portable_resume.reader import run, sources_report


class SourcesCliTests(unittest.TestCase):
    def test_sources_report_has_all_enabled_keys(self) -> None:
        report = sources_report(cwd=os.getcwd())
        self.assertEqual(report["schema_version"], "portable-resume/sources-v1")
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["sources"]), set(SOURCE_KEYS))
        self.assertEqual(set(SOURCE_KEYS), set(MODEL_KEYS))

    def test_probe_errors_become_rows_not_abort(self) -> None:
        def fake_load(source: str):
            class _Adapter:
                key = source

                def probe(self, query):  # noqa: ANN001
                    if source == "claude":
                        return CapabilityReport(source, "fixture", "supported")
                    if source == "codex":
                        raise DiagnosticError("E_UNSAFE_PATH", source=source)
                    raise RuntimeError("boom")

            return _Adapter()

        with mock.patch("portable_resume.reader._load_adapter", side_effect=fake_load):
            report = sources_report(cwd=os.getcwd())
        self.assertEqual(report["sources"]["claude"]["state"], "supported")
        self.assertEqual(report["sources"]["codex"]["state"], "error")
        self.assertEqual(report["sources"]["codex"].get("code"), "E_UNSAFE_PATH")
        # Some other key should have exception class name.
        self.assertEqual(report["sources"]["grok"]["state"], "error")
        self.assertEqual(report["sources"]["grok"].get("exception"), "RuntimeError")

    def test_run_sources_json_and_table(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(["sources", "--json"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "portable-resume/sources-v1")
        self.assertEqual(set(payload["sources"]), set(SOURCE_KEYS))

        stdout2 = io.StringIO()
        code2 = run(["sources"], stdout=stdout2, stderr=io.StringIO())
        self.assertEqual(code2, 0)
        text = stdout2.getvalue()
        self.assertIn("SOURCE\tSTATE\tFORMAT\tWARNINGS", text)
        self.assertIn("claude\t", text)

    def test_closed_parser_rejects_unknown_flag(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(["sources", "--nope"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 2)
        self.assertIn("E_INVALID_INPUT", stderr.getvalue())

    def test_sources_sweep_does_not_invoke_source_cli_shims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            marker = root / "cli-invoked"
            shim = bin_dir / "claude"
            shim.write_text(
                "#!/bin/sh\n"
                f"printf invoked >> '{marker}'\n"
                "exit 0\n",
                encoding="utf-8",
            )
            shim.chmod(0o755)
            # Common launcher names that must not be needed by probes.
            for name in ("codex", "cursor", "gemini", "agy", "agent"):
                target = bin_dir / name
                target.write_text(shim.read_text(encoding="utf-8"), encoding="utf-8")
                target.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False):
                code = run(["sources", "--json"], stdout=stdout, stderr=stderr)
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertFalse(marker.exists(), "source CLI shim must not run during sources")


if __name__ == "__main__":
    unittest.main()
