"""#32: installer CLI flags and install-result-v1 contract."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from portable_resume.install.cli import RESULT_SCHEMA, build_parser, run as install_cli_run


class InstallCliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.project = Path(self._tmp.name) / "project"
        self.home.mkdir()
        self.project.mkdir()
        self._old_cwd = os.getcwd()
        os.chdir(self.project)

    def tearDown(self) -> None:
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_parser_verify_rejects_dry_run(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "verify",
                    "--host",
                    "claude",
                    "--scope",
                    "global",
                    "--dry-run",
                ]
            )

    def test_parser_install_rejects_json_flag(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "install",
                    "--host",
                    "claude",
                    "--scope",
                    "global",
                    "--json",
                ]
            )

    def test_parser_matrix_rejects_json_flag(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["matrix", "--json"])

    def test_parser_hosts_still_accepts_json(self) -> None:
        parser = build_parser()
        ns = parser.parse_args(["hosts", "--json"])
        self.assertTrue(ns.json)

    def test_matrix_emits_result_envelope(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = install_cli_run(["matrix"])
        self.assertEqual(code, 0, err.getvalue())
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["schema_version"], RESULT_SCHEMA)
        self.assertEqual(doc["command"], "matrix")
        self.assertTrue(doc["ok"])
        self.assertEqual(len(doc["results"]), 1)
        self.assertIn("cell_count", doc["results"][0])

    def test_install_dry_run_envelope_single_result_array(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "claude",
                    "--scope",
                    "project",
                    "--project",
                    str(self.project),
                    "--home",
                    str(self.home),
                    "--dry-run",
                ]
            )
        self.assertEqual(code, 0, err.getvalue())
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["schema_version"], RESULT_SCHEMA)
        self.assertEqual(doc["command"], "install")
        self.assertTrue(doc["ok"])
        self.assertTrue(doc["dry_run"])
        self.assertEqual(len(doc["results"]), 1)
        result = doc["results"][0]
        self.assertTrue(result.get("dry_run") or result.get("ok"))
        self.assertIn("plan", result)
        self.assertIn("discovery", result)

    def test_unknown_flag_returns_structured_diagnostic(self) -> None:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = install_cli_run(
                ["install", "--host", "claude", "--scope", "global", "--nope"]
            )
        self.assertEqual(code, 2)
        payload = json.loads(err.getvalue().strip().splitlines()[-1])
        self.assertEqual(payload["code"], "E_INVALID_INPUT")

    def test_removed_json_flag_returns_structured_diagnostic(self) -> None:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "claude",
                    "--scope",
                    "global",
                    "--json",
                ]
            )
        self.assertEqual(code, 2)
        payload = json.loads(err.getvalue().strip().splitlines()[-1])
        self.assertEqual(payload["code"], "E_INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
