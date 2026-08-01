"""Installer argument validation and shadow-family regression tests."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.cli import run as install_cli_run
from portable_resume.install.discovery import POLICY_BLOCK, require_no_blocking_shadow


class InstallCliValidationTests(unittest.TestCase):
    def test_project_scope_without_project_is_invalid_input(self) -> None:
        for command in ("install", "verify", "uninstall"):
            with self.subTest(command=command):
                stderr = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = install_cli_run(
                        [command, "--host", "claude", "--scope", "project"]
                    )

                self.assertEqual(code, 2)
                payload = json.loads(stderr.getvalue().strip().splitlines()[-1])
                self.assertEqual(payload["code"], "E_INVALID_INPUT")

    def test_host_choices_reject_typos_and_all_for_audit(self) -> None:
        cases = (
            ("install", "clade"),
            ("verify", "clade"),
            ("uninstall", "clade"),
            ("audit-host", "all"),
        )
        for command, host in cases:
            with self.subTest(command=command):
                stderr = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = install_cli_run(
                        [command, "--host", host, "--scope", "global"]
                    )

                self.assertEqual(code, 2)
                error_text = stderr.getvalue()
                self.assertIn("invalid choice", error_text)
                self.assertIn("claude", error_text)
                payload = json.loads(error_text.strip().splitlines()[-1])
                self.assertEqual(payload["code"], "E_INVALID_INPUT")


class ShadowFamilyValidationTests(unittest.TestCase):
    def test_blocking_shadow_family_is_deduplicated_before_cap(self) -> None:
        findings = [
            {
                "root_id": "grok.project.primary",
                "policy": POLICY_BLOCK,
                "is_selected": False,
            }
            for _ in range(8)
        ]
        findings.append(
            {
                "root_id": "grok.project.secondary",
                "policy": POLICY_BLOCK,
                "is_selected": False,
            }
        )
        report = {"aggregate_policy": POLICY_BLOCK, "findings": findings}

        with (
            mock.patch(
                "portable_resume.install.discovery.scan_skill_duplicates",
                return_value=report,
            ),
            self.assertRaises(DiagnosticError) as caught,
        ):
            require_no_blocking_shadow(
                host="grok",
                selected_root="/synthetic/selected",
                project_dir="/synthetic/project",
                home_dir="/synthetic/home",
                selected_scope="global",
            )

        self.assertEqual(
            caught.exception.family,
            ("grok.project.primary", "grok.project.secondary"),
        )


if __name__ == "__main__":
    unittest.main()
