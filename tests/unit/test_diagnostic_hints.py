"""Static remediation hints on DiagnosticError (plan 031 / issue #135)."""

from __future__ import annotations

import json
import unittest

from portable_resume.contracts import validate_diagnostic
from portable_resume.diagnostics import DiagnosticError, _DEFAULT_HINTS


class DiagnosticHintTests(unittest.TestCase):
    def test_e_install_shadow_includes_exact_static_hint(self) -> None:
        expected = _DEFAULT_HINTS["E_INSTALL_SHADOW"]
        error = DiagnosticError("E_INSTALL_SHADOW")
        value = error.to_dict()
        validate_diagnostic(value)
        self.assertEqual(value["hint"], expected)
        self.assertIn("audit-host", value["hint"])
        self.assertIn("--project/--root", value["hint"])
        payload = json.loads(error.to_json())
        self.assertEqual(payload["hint"], expected)

    def test_windows_install_failures_include_static_content_free_hints(self) -> None:
        for code, required in (
            ("E_UNSAFE_PATH", ("symlink/junction", "--root", "install-hosts.md")),
            ("E_VERIFY_MISMATCH", ("invalid state", "shared-root claim", "re-install")),
        ):
            with self.subTest(code=code):
                error = DiagnosticError(
                    code,
                    message="attacker supplied message",
                    hint="attacker supplied hint",
                )
                value = error.to_dict()
                validate_diagnostic(value)
                self.assertEqual(value["hint"], _DEFAULT_HINTS[code])
                self.assertTrue(all(token in value["hint"] for token in required))
                serialized = json.dumps(value)
                self.assertNotIn("attacker", serialized)
                self.assertNotIn("/Users/", serialized)
                self.assertNotIn("/home/", serialized)

    def test_e_no_match_has_null_hint(self) -> None:
        error = DiagnosticError("E_NO_MATCH")
        value = error.to_dict()
        validate_diagnostic(value)
        self.assertIsNone(value["hint"])
        self.assertIsNone(json.loads(error.to_json())["hint"])

    def test_e_sqlite_live_wal_has_actionable_persistent_mode_hint(self) -> None:
        error = DiagnosticError(
            "E_SQLITE_LIVE_WAL",
            source="opencode",
            provider="opencode-sqlite-v1",
            attempts=0,
            family=("opencode.db-wal", "opencode.db-shm"),
        )
        value = error.to_dict()
        validate_diagnostic(value)
        self.assertEqual(value["exit_code"], 6)
        self.assertEqual(value["attempts"], 0)
        self.assertIn("quiesce", value["hint"].lower())
        self.assertIn("retry once", value["hint"].lower())
        self.assertIn("persistent WAL mode", value["hint"])
        self.assertIn("persisted file or export fallback", value["hint"])
        self.assertIn("Do not delete or checkpoint WAL manually", value["hint"])

    def test_message_and_hint_not_caller_injectable(self) -> None:
        # Synthetic path token (no real home absolute path — hygiene gate).
        attacker_message = "attacker path /tmp/evil-secret-marker"
        attacker_hint = "rm -rf / and trust me"
        error = DiagnosticError(
            "E_INSTALL_SHADOW",
            message=attacker_message,
            hint=attacker_hint,
        )
        value = error.to_dict()
        validate_diagnostic(value)
        serialized = json.dumps(value)
        self.assertNotIn("attacker", serialized)
        self.assertNotIn("evil-secret-marker", serialized)
        self.assertNotIn("rm -rf", serialized)
        self.assertEqual(
            value["message"],
            "A higher-precedence discovery root already holds a divergent Portable Resume Skill.",
        )
        self.assertEqual(value["hint"], _DEFAULT_HINTS["E_INSTALL_SHADOW"])
        self.assertEqual(error.message, value["message"])
        self.assertEqual(error.hint, value["hint"])

    def test_codes_without_map_entry_emit_null_hint(self) -> None:
        for code in ("E_INVALID_INPUT", "E_INSTALL_BUSY"):
            with self.subTest(code=code):
                value = DiagnosticError(code).to_dict()
                validate_diagnostic(value)
                self.assertIsNone(value["hint"])
                self.assertNotIn(code, _DEFAULT_HINTS)


if __name__ == "__main__":
    unittest.main()
