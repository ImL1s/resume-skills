from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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
        env["HOME"] = "relative-host-home"
        env["USERPROFILE"] = "relative-user-profile"
        env["XDG_CONFIG_HOME"] = "relative-xdg-config"
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

    def test_check_reports_mutated_self_check_contract(self) -> None:
        from scripts import render_docs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "docs", root / "docs")
            path = root / "docs" / "diagnostics.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace("`W_SCHEMA_MISSING`", "`W_SCHEMA_CHANGED`", 1)
            path.write_text(text, encoding="utf-8")

            failures = render_docs.check(root)

        self.assertEqual(len(failures), 1)
        self.assertIn("docs/diagnostics.md", failures[0])
        self.assertIn("W_SCHEMA_MISSING", failures[0])

    def test_check_reports_missing_registered_document(self) -> None:
        from scripts import render_docs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "docs", root / "docs")
            (root / "docs" / "diagnostics.md").unlink()

            failures = render_docs.check(root)

        self.assertEqual(len(failures), 1)
        self.assertIn("docs/diagnostics.md", failures[0])
        self.assertIn("missing", failures[0].lower())

    def test_diagnostic_surface_mapping_is_exact_and_fails_closed(self) -> None:
        from scripts import render_docs
        from portable_resume.diagnostics import ERROR_EXIT_CODES, ExitCode

        self.assertEqual(
            set(render_docs.DIAGNOSTIC_SURFACES),
            set(ERROR_EXIT_CODES),
        )
        with mock.patch.dict(
            ERROR_EXIT_CODES,
            {"E_FUTURE_CODE": ExitCode.INVARIANT},
        ):
            with self.assertRaisesRegex(ValueError, "diagnostic surfaces"):
                render_docs.rendered_regions()

    def test_exit_code_reference_is_generated_and_fails_closed(self) -> None:
        from scripts import render_docs
        from portable_resume.diagnostics import ExitCode

        regions = render_docs.rendered_regions()
        self.assertEqual(set(render_docs.EXIT_CODE_REFERENCE), set(ExitCode))
        for exit_code in ExitCode:
            self.assertIn(
                f"| {int(exit_code)} | `{exit_code.name}` |",
                regions["exit-codes-table"],
            )

        with mock.patch.dict(render_docs.EXIT_CODE_REFERENCE, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "exit-code reference"):
                render_docs.rendered_regions()

    def test_self_check_result_warning_contract_is_separate(self) -> None:
        from scripts import render_docs
        from portable_resume.diagnostics import ExitCode

        region = render_docs.rendered_regions()["self-check-result-contract"]
        self.assertIn("`W_REGISTRY_INVALID:<ExceptionType>`", region)
        self.assertIn("`W_SCHEMA_MISSING`", region)
        self.assertIn(f"exit {int(ExitCode.CORRUPT_OR_LIMIT)}", region)

        with mock.patch.dict(
            render_docs.SELF_CHECK_RESULT_WARNINGS,
            {"W_FUTURE_SELF_CHECK": "Future warning."},
        ):
            with self.assertRaisesRegex(ValueError, "self-check result warnings"):
                render_docs.rendered_regions()

    def test_self_check_contract_rejects_wrong_failure_return(self) -> None:
        from scripts import render_docs

        source = (
            REPO / "src" / "portable_resume" / "reader.py"
        ).read_text(encoding="utf-8")
        expected = 'return 0 if report["ok"] else ExitCode.CORRUPT_OR_LIMIT'
        replacement = (
            "incidental = ExitCode.CORRUPT_OR_LIMIT\n"
            "    return 0 if report[\"ok\"] else ExitCode.UNSAFE_OR_BUSY"
        )
        self.assertIn(expected, source)
        mutated = source.replace(expected, replacement, 1)

        with self.assertRaisesRegex(ValueError, "CORRUPT_OR_LIMIT"):
            render_docs._self_check_source_contract(mutated)

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
                "matrix-counts-table",
                "host-support-table",
                "install-hosts-table",
                "exit-codes-table",
                "error-codes-table",
                "warning-codes-list",
                "self-check-result-contract",
            },
        )
        dims = matrix_dimensions()
        self.assertIn(
            f"**{dims['sources']}×{dims['destinations']}={dims['cells']}**",
            regions["matrix-summary"],
        )
        self.assertIn(
            f"cells={dims['cells']}",
            regions["matrix-counts-table"],
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
