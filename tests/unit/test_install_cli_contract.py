"""#32: installer CLI flags and install-result-v1 contract."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from portable_resume.install.cli import (
    RESULT_SCHEMA,
    _root_for,
    build_parser,
    run as install_cli_run,
)


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

    @staticmethod
    def _tree_entries(root: Path) -> list[tuple[str, str, bytes | None]]:
        entries = []
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append((rel, "symlink", os.readlink(path).encode()))
            elif path.is_dir():
                entries.append((rel, "dir", None))
            else:
                entries.append((rel, "file", path.read_bytes()))
        return entries

    def test_explicit_root_intermediate_symlink_is_rejected_without_outside_mutation(self) -> None:
        outside = Path(self._tmp.name) / "outside"
        skills = outside / "skills"
        skills.mkdir(parents=True)
        (skills / "sentinel.txt").write_bytes(b"keep")
        layout = Path(self._tmp.name) / "layout"
        layout.mkdir()
        (layout / "link").symlink_to(outside, target_is_directory=True)
        before = self._tree_entries(outside)

        for dry_run in (True, False):
            argv = [
                "install", "--host", "claude", "--scope", "global",
                "--root", str(layout / "link" / "skills"), "--home", str(self.home),
            ]
            if dry_run:
                argv.append("--dry-run")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = install_cli_run(argv)
            self.assertEqual(code, 6)
            self.assertEqual(self._tree_entries(outside), before)

    def test_explicit_root_missing_child_under_intermediate_symlink_is_rejected(self) -> None:
        outside = Path(self._tmp.name) / "outside-missing"
        outside.mkdir()
        layout = Path(self._tmp.name) / "layout-missing"
        layout.mkdir()
        (layout / "link").symlink_to(outside, target_is_directory=True)
        before = self._tree_entries(outside)
        for dry_run in (True, False):
            argv = [
                "install", "--host", "claude", "--scope", "global",
                "--root", str(layout / "link" / "missing"), "--home", str(self.home),
            ]
            if dry_run:
                argv.append("--dry-run")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = install_cli_run(argv)
            self.assertEqual(code, 6)
            self.assertEqual(self._tree_entries(outside), before)

    def test_explicit_leaf_alias_dry_and_live_succeed(self) -> None:
        physical = Path(self._tmp.name) / "physical"
        physical.mkdir()
        leaf = Path(self._tmp.name) / "leaf"
        leaf.symlink_to(physical, target_is_directory=True)
        before = self._tree_entries(physical)
        for dry_run in (True, False):
            argv = [
                "install", "--host", "claude", "--scope", "global",
                "--root", str(leaf), "--home", str(self.home),
            ]
            if dry_run:
                argv.append("--dry-run")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                code = install_cli_run(argv)
            self.assertEqual(code, 0, err.getvalue())
            if dry_run:
                self.assertEqual(self._tree_entries(physical), before)

    def test_explicit_root_preserves_override_precedence_and_normalizes_spelling(self) -> None:
        explicit = Path("relative-root")
        self.assertEqual(
            _root_for("claude", "project", str(self.project), str(self.home), str(explicit)),
            os.path.abspath(str(explicit)),
        )
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(
                _root_for("claude", "global", None, str(self.home), "~/custom-skills"),
                os.path.abspath(str(self.home / "custom-skills")),
            )

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
