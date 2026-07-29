"""Owned skill runner: hard-bound source, argv lanes, no free-text shell splice."""

from __future__ import annotations

import importlib.util
import tempfile
import types
import unittest
from pathlib import Path

from portable_resume.install.render import materialize_plan, render_skill_markdown
from portable_resume.model import SOURCE_KEYS


def _load_force(source: str = "codex") -> types.ModuleType:
    """Load rendered run_reader as a module without executing __main__."""

    body = materialize_plan("claude")
    key = f"resume-{source}/scripts/run_reader.py"
    text = body[key].decode("utf-8")
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "run_reader.py"
        path.write_text(text, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(f"owned_runner_{source}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Runtime import needs portable_resume on path; use checkout via PYTHONPATH in tests.
        # Stub reader.main so import succeeds without executing CLI.
        import portable_resume.reader as reader_mod

        original_main = reader_mod.main
        reader_mod.main = lambda argv=None: 0  # type: ignore[assignment]
        try:
            spec.loader.exec_module(module)
        finally:
            reader_mod.main = original_main
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

    def test_empty_argv_defaults_show_latest(self) -> None:
        out = self.force([])
        self.assertEqual(out, ["codex", "show", "latest", "--expected-source", "codex"])

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
        # Equals form
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
        # Bound source literal after render
        self.assertIn('_BOUND_SOURCE = "claude"', runner)


class OwnedSkillMarkdownTests(unittest.TestCase):
    def test_owned_path_and_two_lanes(self) -> None:
        text = render_skill_markdown(host="claude", source="codex")
        self.assertIn("OWNED_SKILL_DIR", text)
        self.assertIn("$OWNED_SKILL_DIR/scripts/run_reader.py", text)
        self.assertIn("Request lanes", text)
        self.assertIn("Simple direct ref", text)
        self.assertIn("Typed request-file", text)
        self.assertIn("portable-resume/request-v1", text)
        self.assertIn("--request-file", text)
        self.assertIn("resume_ref", text)
        self.assertIn("schema_version", text)
        self.assertIn('must be `"show"` only', text)
        # Must not document wrong request keys that load_request rejects.
        self.assertNotIn("ref, cwd, options", text)
        self.assertNotIn("containing selection fields only (source, action, ref", text)
        self.assertNotIn('"show" or "list"', text)
        # Conceptual placeholder must not remain
        self.assertNotIn("<this-skill>", text)
        # Free-text shell splice forbidden
        self.assertIn("Never splice untrusted free text into shell source", text)
        self.assertIn("Do **not** guess another", text)
        self.assertIn("hard-binds `source=codex`", text)

    def test_every_source_binds_own_key(self) -> None:
        for source in sorted(SOURCE_KEYS):
            text = render_skill_markdown(host="cursor", source=source)
            self.assertIn(f"source={source}", text)
            self.assertIn("OWNED_SKILL_DIR", text)
            runner = materialize_plan("cursor")[f"resume-{source}/scripts/run_reader.py"].decode(
                "utf-8"
            )
            self.assertIn(f'_BOUND_SOURCE = "{source}"', runner)


if __name__ == "__main__":
    unittest.main()
