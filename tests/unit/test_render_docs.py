from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class RenderDocsTests(unittest.TestCase):
    def test_committed_generated_regions_match_registry(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "render_docs.py"), "--check"],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_check_ignores_host_runtime_environment(self) -> None:
        env = os.environ.copy()
        env["KIMI_CODE_HOME"] = "relative-host-home"

        completed = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "render_docs.py"), "--check"],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_check_reports_a_mutated_generated_row(self) -> None:
        from scripts import render_docs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "docs", root / "docs")
            path = root / "docs" / "host-support.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace("| Antigravity / agy |", "| Mutated host |", 1)
            path.write_text(text, encoding="utf-8")

            failures = render_docs.check(root)

        self.assertEqual(len(failures), 1)
        self.assertIn("docs/host-support.md", failures[0])
        self.assertIn("-| Mutated host |", failures[0])
        self.assertIn("+| Antigravity / agy |", failures[0])

    def test_generated_regions_contain_structure_not_evidence_claims(self) -> None:
        from scripts import render_docs
        from portable_resume.diagnostics import (
            DiagnosticError,
            ERROR_EXIT_CODES,
            WARNING_CODES,
        )
        from portable_resume.registry import matrix_dimensions

        regions = render_docs.rendered_regions()

        self.assertEqual(render_docs.counts(), matrix_dimensions())
        self.assertEqual(
            set(regions),
            {
                "matrix-summary",
                "host-support-table",
                "install-hosts-table",
                "error-codes-table",
                "warning-codes-list",
            },
        )
        for code, exit_code in ERROR_EXIT_CODES.items():
            self.assertIn(f"`{code}`", regions["error-codes-table"])
            self.assertIn(f"| {int(exit_code)} |", regions["error-codes-table"])
            self.assertIn(DiagnosticError(code).message, regions["error-codes-table"])
        for code in WARNING_CODES:
            self.assertIn(f"`{code}`", regions["warning-codes-list"])
        generated = "\n".join(regions.values()).lower()
        for evidence_word in ("not-run", "pass", "verified", "evidence"):
            self.assertNotIn(evidence_word, generated)


if __name__ == "__main__":
    unittest.main()
