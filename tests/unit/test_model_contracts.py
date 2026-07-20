from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.contracts import validate_diagnostic, validate_envelope
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Candidate, Envelope, Query, Session, Turn


FIXED = "2026-07-20T00:00:00Z"


class ModelContractTests(unittest.TestCase):
    def minimal(self) -> dict:
        envelope = Envelope.create(
            operation="list",
            query=Query("claude", cwd="/tmp/project"),
            sessions=(Session(source="claude", session_id="s1", cwd="/tmp/project"),),
            generated_at=FIXED,
        )
        return envelope.to_dict()

    def test_u001_valid_minimal_list_is_inert(self) -> None:
        value = self.minimal()
        validate_envelope(value)
        self.assertIs(value["inert"], True)
        self.assertIs(value["sessions"][0]["untrusted_content"], True)

    def test_u002_show_turn_ordinals_and_markers(self) -> None:
        value = Envelope.create(
            operation="show",
            query=Query("codex", ref="x", cwd="/tmp/project"),
            sessions=(
                Session(
                    source="codex",
                    session_id="x",
                    turns=(
                        Turn(0, "user", "request"),
                        Turn(1, "assistant", "answer"),
                        Turn(2, "tool", "output", tool_name="read"),
                    ),
                ),
            ),
            generated_at=FIXED,
        ).to_dict()
        validate_envelope(value)
        self.assertEqual([item["ordinal"] for item in value["sessions"][0]["turns"]], [0, 1, 2])
        self.assertTrue(all(item["inert"] and item["untrusted_content"] for item in value["sessions"][0]["turns"]))

    def test_u003_missing_or_false_markers_fail(self) -> None:
        cases = []
        root = self.minimal()
        root["inert"] = False
        cases.append(root)
        session = self.minimal()
        del session["sessions"][0]["untrusted_content"]
        cases.append(session)
        turns = self.minimal()
        turns["sessions"][0]["turns"] = [Turn(0, "user", "x").to_dict()]
        turns["sessions"][0]["turns"][0]["inert"] = False
        cases.append(turns)
        for value in cases:
            with self.subTest(value=value), self.assertRaisesRegex(DiagnosticError, "invariant"):
                validate_envelope(value)

    def test_u004_closed_schema_source_role_and_version(self) -> None:
        cases = []
        version = self.minimal()
        version["schema_version"] = "portable-resume/v2"
        cases.append(version)
        source = self.minimal()
        source["query"]["source"] = "other"
        cases.append(source)
        role = self.minimal()
        role["sessions"][0]["turns"] = [Turn(0, "user", "x").to_dict()]
        role["sessions"][0]["turns"][0]["role"] = "system"
        cases.append(role)
        extra = self.minimal()
        extra["secret"] = "no"
        cases.append(extra)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(DiagnosticError) as caught:
                validate_envelope(value)
            self.assertEqual(caught.exception.code, "E_INVARIANT")

    def test_u005_optional_values_are_explicit_null(self) -> None:
        value = self.minimal()["sessions"][0]
        for key in ("source_path", "title", "branch", "created_at", "updated_at", "source_repo_root", "last_user_request", "last_assistant_action"):
            self.assertIn(key, value)
            self.assertIsNone(value[key])

    def test_u017_exact_bounds_accepted(self) -> None:
        custom = Bounds(scanned_records=1, source_read_bytes=1, normalized_turns=1)
        budget = ReadBudget(custom)
        budget.consume_records(1)
        budget.consume_bytes(1)
        budget.consume_turns(1)
        self.assertEqual((budget.records, budget.bytes_read, budget.turns), (1, 1, 1))

    def test_u018_one_over_each_budget_fails(self) -> None:
        for method in ("consume_records", "consume_bytes", "consume_turns"):
            budget = ReadBudget(Bounds(scanned_records=0, source_read_bytes=0, normalized_turns=0))
            with self.subTest(method=method), self.assertRaises(DiagnosticError) as caught:
                getattr(budget, method)(1)
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_u024_diagnostic_is_closed_bounded_and_content_free(self) -> None:
        secret = "transcript secret sk-abcdefghijklmnopqrstuvwxyz"
        error = DiagnosticError("E_CORRUPT_RECORD", secret, source="claude", provider="fmt/../../bad", family=("/x/db-wal",))
        value = error.to_dict()
        validate_diagnostic(value)
        self.assertNotIn("secret", json.dumps(value))
        self.assertNotIn("sk-", json.dumps(value))
        self.assertEqual(value["provider"], "fmt....bad")
        self.assertEqual(value["family"], ["db-wal"])

    def test_schema_file_declares_closed_nested_objects(self) -> None:
        schema = json.loads(Path("schemas/portable-resume-v1.schema.json").read_text())
        self.assertFalse(schema["additionalProperties"])
        for name in ("query", "turn", "session", "candidate"):
            self.assertFalse(schema["$defs"][name]["additionalProperties"])
        self.assertEqual(schema["properties"]["schema_version"]["const"], "portable-resume/v1")


if __name__ == "__main__":
    unittest.main()
