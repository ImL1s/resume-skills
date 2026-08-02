"""self_verify profiles and CI workflow must not double-run expensive stages (#67)."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def _load_self_verify():
    path = REPO / "scripts" / "self_verify.py"
    spec = importlib.util.spec_from_file_location("portable_resume_self_verify", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


self_verify_module = _load_self_verify()


class SelfVerifyProfileTests(unittest.TestCase):
    def test_profiles_are_closed_and_disjoint_for_ci(self) -> None:
        self.assertIn("local", self_verify_module.PROFILES)
        self.assertIn("ci-compat", self_verify_module.PROFILES)
        self.assertIn("ci-quality", self_verify_module.PROFILES)
        compat = set(self_verify_module.PROFILES["ci-compat"])
        quality = set(self_verify_module.PROFILES["ci-quality"])
        # Docs/secrets are not re-run in every matrix cell.
        self.assertNotIn("docs", compat)
        self.assertNotIn("secrets", compat)
        self.assertEqual(quality, {"version_state", "docs", "secrets"})
        # Compat still carries the expensive suite exactly once per cell.
        self.assertIn("unit", compat)
        self.assertIn("compile", compat)
        self.assertNotIn("packaging", compat)
        self.assertIn("packaging", self_verify_module.STAGE_NAMES)
        # Local remains the full set.
        self.assertEqual(
            tuple(self_verify_module.PROFILES["local"]),
            self_verify_module.STAGE_NAMES,
        )
        completed = mock.Mock(returncode=0, stderr="", stdout="")
        with mock.patch.object(self_verify_module, "run", return_value=completed) as run:
            code, _ = self_verify_module._stage_unit()
        self.assertEqual(code, 0)
        self.assertEqual(
            [call.args[0][5] for call in run.call_args_list],
            [
                "tests/adapters",
                "tests/e2e",
                "tests/integration",
                "tests/security",
                "tests/unit",
            ],
        )

    def test_resolve_stages_rejects_unknown_names(self) -> None:
        with self.assertRaises(SystemExit):
            self_verify_module.resolve_stages(profile=None, only=["not-a-stage"])
        with self.assertRaises(SystemExit):
            self_verify_module.resolve_stages(profile="nope", only=None)

    def test_resolve_only_preserves_canonical_order(self) -> None:
        stages = self_verify_module.resolve_stages(
            profile=None,
            only=["unit", "compile", "unit"],
        )
        self.assertEqual(stages, ["compile", "unit"])


class CiWorkflowDedupeTests(unittest.TestCase):
    def test_matrix_job_does_not_re_run_docs_or_full_suite_after_self_verify(self) -> None:
        text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        # Quality job owns docs/secrets once.
        self.assertIn("ci-quality", text)
        self.assertIn("ci-compat", text)
        # Matrix must not invoke bare check_docs / second unittest discover.
        matrix_block = text.split("name: test (")[1].split("package:")[0]
        self.assertNotIn("check_docs.py", matrix_block)
        self.assertNotIn("unittest discover", matrix_block)
        self.assertIn("ci-compat", matrix_block)
        self.assertIn("smoke_installed_matrix.py", matrix_block)
        # Package waits on POSIX matrix, Windows nt job, and quality.
        self.assertRegex(
            text,
            re.compile(r"needs:\s*\[test,\s*test-windows,\s*quality\]"),
        )
        self.assertIn("windows-latest", text)
        self.assertIn("test-windows:", text)
        packaging_command = "python scripts/self_verify.py --only packaging"
        package_block = text.split("\n  package:", 1)[1]
        self.assertNotIn(packaging_command, matrix_block)
        self.assertEqual(package_block.count(packaging_command), 1)


if __name__ == "__main__":
    unittest.main()
