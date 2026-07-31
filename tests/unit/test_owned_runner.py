"""Owned skill runner: hard-bound source, argv lanes, no free-text shell splice."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.render import materialize_plan, render_skill_markdown
from portable_resume.model import SOURCE_KEYS


def _load_force(source: str = "codex") -> types.ModuleType:
    """Load rendered run_reader as a module without executing __main__."""

    body = materialize_plan("claude")
    key = f"resume-{source}/scripts/run_reader.py"
    text = body[key].decode("utf-8")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / f"resume-{source}" / "scripts" / "run_reader.py"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
        package = root / ".portable-resume" / "runtime" / "portable_resume"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "reader.py").write_text(
            "def main(argv=None):\n    return 0\n", encoding="utf-8"
        )
        (package / "model.py").write_text(
            f"SOURCE_KEYS = {tuple(SOURCE_KEYS)!r}\n", encoding="utf-8"
        )
        spec = importlib.util.spec_from_file_location(f"owned_runner_{source}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class OwnedRunnerArgvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_force("codex")
        self.force = self.module._force_expected_source

    def test_bound_source_constant(self) -> None:
        self.assertEqual(self.module._BOUND_SOURCE, "codex")
        self.assertEqual(self.module._KNOWN_SOURCES, frozenset(SOURCE_KEYS))

    def test_strips_hostile_expected_source_spellings(self) -> None:
        out = self.force(
            ["show", "latest", "--expected-source", "claude", "--expected-source=qwen"]
        )
        self.assertEqual(out[0], "codex")
        self.assertEqual(out.count("--expected-source"), 1)
        self.assertEqual(out[-2:], ["--expected-source", "codex"])
        self.assertNotIn("claude", out)
        self.assertNotIn("qwen", out)

    def test_expected_source_does_not_swallow_next_option(self) -> None:
        out = self.force(
            ["--expected-source", "--request-file", "/tmp/r.json", "--format", "handoff"]
        )
        self.assertIn("--request-file", out)
        self.assertIn("/tmp/r.json", out)
        self.assertEqual(out[-2:], ["--expected-source", "codex"])
        # Still request-file lane, not bare show of the path.
        self.assertNotEqual(out[0], "codex")

    def test_show_and_list_inject_bound_source(self) -> None:
        self.assertEqual(
            self.force(["show", "latest"]),
            ["codex", "show", "latest", "--expected-source", "codex"],
        )
        self.assertEqual(
            self.force(["list", "--json"]),
            ["codex", "list", "--json", "--expected-source", "codex"],
        )

    def test_hostile_leading_source_is_replaced(self) -> None:
        out = self.force(["claude", "show", "latest"])
        self.assertEqual(out[0], "codex")
        self.assertEqual(out[1], "show")
        self.assertNotIn("claude", out)

    def test_bare_ref_becomes_show_ref(self) -> None:
        out = self.force(["sess-abc"])
        self.assertEqual(out, ["codex", "show", "sess-abc", "--expected-source", "codex"])

    def test_empty_argv_defaults_to_list(self) -> None:
        out = self.force([])
        self.assertEqual(out, ["codex", "list", "--expected-source", "codex"])

    def test_request_file_lane_no_positional_source_injection(self) -> None:
        out = self.force(["--request-file", "/tmp/r.json", "--format", "handoff"])
        self.assertEqual(
            out,
            [
                "--request-file",
                "/tmp/r.json",
                "--format",
                "handoff",
                "--expected-source",
                "codex",
            ],
        )
        out2 = self.force(["--request-file=/tmp/r.json"])
        self.assertEqual(out2[0], "--request-file=/tmp/r.json")
        self.assertEqual(out2[-2:], ["--expected-source", "codex"])

    def test_request_file_drops_hostile_leading_source(self) -> None:
        out = self.force(
            ["claude", "--request-file", "/tmp/r.json", "--expected-source", "qwen"]
        )
        self.assertNotIn("claude", out)
        self.assertNotIn("qwen", out)
        self.assertIn("--request-file", out)
        self.assertEqual(out[-2:], ["--expected-source", "codex"])

    def test_help_keeps_help_flag(self) -> None:
        out = self.force(["--help"])
        self.assertEqual(out[0], "--help")
        self.assertEqual(out[-2:], ["--expected-source", "codex"])

    def test_realpath_package_resolution_in_template(self) -> None:
        body = materialize_plan("grok")
        runner = body["resume-claude/scripts/run_reader.py"].decode("utf-8")
        self.assertIn("os.path.realpath(__file__)", runner)
        self.assertIn("_SKILL_PACKAGE", runner)
        self.assertIn('".portable-resume"', runner)
        self.assertIn("_force_expected_source", runner)
        self.assertIn("_strip_expected_source", runner)
        self.assertIn("SOURCE_KEYS", runner)
        self.assertIn('_BOUND_SOURCE = "claude"', runner)


class OwnedRunnerRuntimeFailureTests(unittest.TestCase):
    def _write_runner(self, root: Path) -> Path:
        runner = root / "resume-claude" / "scripts" / "run_reader.py"
        runner.parent.mkdir(parents=True)
        rendered = materialize_plan("claude")[
            "resume-claude/scripts/run_reader.py"
        ]
        runner.write_bytes(rendered)
        return runner

    def _run(
        self, runner: Path, *, pythonpath: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if pythonpath is None:
            env.pop("PYTHONPATH", None)
        else:
            env["PYTHONPATH"] = str(pythonpath)
        return subprocess.run(
            [sys.executable, str(runner), "list", "--cwd", "/tmp"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(runner.parents[2]),
        )

    def _write_hostile_package(self, root: Path, marker: Path) -> Path:
        package = root / "portable_resume"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
            encoding="utf-8",
        )
        (package / "reader.py").write_text(
            "def main(argv=None):\n    return 0\n", encoding="utf-8"
        )
        (package / "model.py").write_text("SOURCE_KEYS = ('claude',)\n", encoding="utf-8")
        return package

    def _assert_missing_runtime_diagnostic(
        self, completed: subprocess.CompletedProcess[str]
    ) -> None:
        self.assertEqual(completed.returncode, 5)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(
            completed.stderr,
            DiagnosticError("E_CAPABILITY_UNAVAILABLE").to_json() + "\n",
        )

    def test_missing_runtime_emits_stable_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = self._run(self._write_runner(Path(temporary)))

        self._assert_missing_runtime_diagnostic(completed)
        payload = json.loads(completed.stderr)
        self.assertEqual(payload["schema_version"], "portable-resume/diagnostic-v1")
        self.assertEqual(payload["code"], "E_CAPABILITY_UNAVAILABLE")
        self.assertEqual(payload["exit_code"], 5)
        self.assertNotIn("Traceback", completed.stderr)

    def test_missing_owned_package_rejects_later_pythonpath_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self._write_runner(root)
            marker = root / "foreign-imported"
            foreign = root / "foreign"
            self._write_hostile_package(foreign, marker)
            completed = self._run(runner, pythonpath=foreign)
            self.assertFalse(marker.exists())

        self._assert_missing_runtime_diagnostic(completed)

    def test_namespace_owned_package_rejects_later_pythonpath_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self._write_runner(root)
            owned_package = root / ".portable-resume" / "runtime" / "portable_resume"
            owned_package.mkdir(parents=True)
            marker = root / "foreign-imported"
            foreign = root / "foreign"
            self._write_hostile_package(foreign, marker)
            completed = self._run(runner, pythonpath=foreign)
            self.assertFalse(marker.exists())

        self._assert_missing_runtime_diagnostic(completed)

    def test_owned_package_symlink_outside_runtime_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self._write_runner(root)
            marker = root / "foreign-imported"
            foreign_package = self._write_hostile_package(root / "foreign", marker)
            owned_package = root / ".portable-resume" / "runtime" / "portable_resume"
            owned_package.parent.mkdir(parents=True)
            owned_package.symlink_to(foreign_package, target_is_directory=True)
            completed = self._run(runner)
            self.assertFalse(marker.exists())

        self._assert_missing_runtime_diagnostic(completed)

    def test_present_runtime_missing_reader_is_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self._write_runner(root)
            package = root / ".portable-resume" / "runtime" / "portable_resume"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            completed = self._run(runner)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("No module named 'portable_resume.reader'", completed.stderr)
        self.assertIn("Traceback", completed.stderr)
        self.assertNotIn("E_CAPABILITY_UNAVAILABLE", completed.stderr)

    def test_present_runtime_missing_internal_module_is_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self._write_runner(root)
            package = root / ".portable-resume" / "runtime" / "portable_resume"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "reader.py").write_text(
                "import portable_resume.does_not_exist\n", encoding="utf-8"
            )
            completed = self._run(runner)

        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "No module named 'portable_resume.does_not_exist'", completed.stderr
        )
        self.assertIn("Traceback", completed.stderr)
        self.assertNotIn("E_CAPABILITY_UNAVAILABLE", completed.stderr)


class OwnedSkillMarkdownTests(unittest.TestCase):
    def test_owned_path_and_two_lanes(self) -> None:
        text = render_skill_markdown(host="claude", source="codex")
        self.assertIn("owned skill package root", text)
        self.assertIn("scripts/run_reader.py", text)
        self.assertIn("/abs/path/to/owned-skill-package/scripts/run_reader.py", text)
        self.assertIn("Request lanes", text)
        self.assertIn("Simple direct ref", text)
        self.assertIn("Typed request-file", text)
        self.assertIn("portable-resume/request-v1", text)
        self.assertIn("--request-file", text)
        self.assertIn("resume_ref", text)
        self.assertIn("schema_version", text)
        self.assertIn('must be `"show"` only', text)
        # No conceptual placeholders that expand empty or invite path guessing.
        self.assertNotIn("<this-skill>", text)
        self.assertNotIn("$OWNED_SKILL_DIR", text)
        self.assertNotIn("OWNED_SKILL_DIR", text)
        self.assertNotIn("ref, cwd, options", text)
        self.assertNotIn('"show" or "list"', text)
        self.assertIn("Never splice untrusted free text into shell source", text)
        self.assertIn("hard-binds `source=codex`", text)
        self.assertIn("Host skill metadata", text)

    def test_every_source_binds_own_key(self) -> None:
        for source in sorted(SOURCE_KEYS):
            text = render_skill_markdown(host="cursor", source=source)
            self.assertIn(f"source={source}", text)
            self.assertIn("owned skill package root", text)
            runner = materialize_plan("cursor")[f"resume-{source}/scripts/run_reader.py"].decode(
                "utf-8"
            )
            self.assertIn(f'_BOUND_SOURCE = "{source}"', runner)


if __name__ == "__main__":
    unittest.main()
