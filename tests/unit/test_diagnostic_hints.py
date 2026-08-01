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

    def test_e_no_match_has_null_hint(self) -> None:
        error = DiagnosticError("E_NO_MATCH")
        value = error.to_dict()
        validate_diagnostic(value)
        self.assertIsNone(value["hint"])
        self.assertIsNone(json.loads(error.to_json())["hint"])

    def test_message_and_hint_not_caller_injectable(self) -> None:
        attacker_message = "attacker path /Users/evil/secret"
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
        self.assertNotIn("/Users/evil", serialized)
        self.assertNotIn("rm -rf", serialized)
        self.assertEqual(
            value["message"],
            "A higher-precedence discovery root already holds a divergent Portable Resume Skill.",
        )
        self.assertEqual(value["hint"], _DEFAULT_HINTS["E_INSTALL_SHADOW"])
        self.assertEqual(error.message, value["message"])
        self.assertEqual(error.hint, value["hint"])

    def test_codes_without_map_entry_emit_null_hint(self) -> None:
        for code in ("E_INVALID_INPUT", "E_INSTALL_BUSY", "E_VERIFY_MISMATCH"):
            with self.subTest(code=code):
                value = DiagnosticError(code).to_dict()
                validate_diagnostic(value)
                self.assertIsNone(value["hint"])
                self.assertNotIn(code, _DEFAULT_HINTS)


if __name__ == "__main__":
    unittest.main()
