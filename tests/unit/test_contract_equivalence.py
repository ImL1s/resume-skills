from __future__ import annotations

import json
import unittest
from pathlib import Path

from portable_resume.bounds import Bounds, DEFAULT_BOUNDS
from portable_resume.contracts import validate_envelope
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Envelope, Query, Session, Turn
from portable_resume.sanitize import sanitize_session
from tests.helpers.json_schema import SchemaReject, validate_schema


class ContractEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(Path("schemas/portable-resume-v1.schema.json").read_text())

    def minimal(self) -> dict:
        return Envelope.create(
            operation="show",
            query=Query("claude", cwd="/tmp/project"),
            sessions=(Session("claude", "s1", cwd="/tmp/project"),),
            generated_at="2026-07-20T00:00:00Z",
        ).to_dict()

    def shared_corpus(self):
        yield "valid-minimal", self.minimal(), True
        generated_null = self.minimal()
        generated_null["generated_at"] = None
        yield "generated-null", generated_null, False
        false_marker = self.minimal()
        false_marker["sessions"][0]["inert"] = False
        yield "false-marker", false_marker, False
        unknown_source = self.minimal()
        unknown_source["query"]["source"] = "unknown"
        yield "unknown-source", unknown_source, False
        extra = self.minimal()
        extra["extra"] = 1
        yield "extra-key", extra, False
        over = self.minimal()
        over["sessions"][0]["last_user_request"] = "x" * (DEFAULT_BOUNDS.normalized_content_bytes + 1)
        yield "individual-content-over", over, False

        half = DEFAULT_BOUNDS.normalized_content_bytes // 2
        aggregate_exact = self.minimal()
        aggregate_exact["sessions"][0]["last_user_request"] = "u" * half
        aggregate_exact["sessions"][0]["last_assistant_action"] = "a" * half
        yield "aggregate-content-exact-ascii", aggregate_exact, True

        aggregate_over = self.minimal()
        aggregate_over["sessions"][0]["last_user_request"] = "u" * half
        aggregate_over["sessions"][0]["last_assistant_action"] = "a" * half
        aggregate_over["sessions"][0]["turns"] = [Turn(0, "user", "x").to_dict()]
        yield "aggregate-content-over-ascii", aggregate_over, False

        multibyte_exact = self.minimal()
        multibyte_exact["sessions"][0]["last_user_request"] = "é" * half
        yield "aggregate-content-exact-multibyte", multibyte_exact, True

        multibyte_over = self.minimal()
        multibyte_over["sessions"][0]["last_user_request"] = "é" * half
        multibyte_over["sessions"][0]["turns"] = [Turn(0, "user", "é").to_dict()]
        yield "aggregate-content-over-multibyte", multibyte_over, False

    def test_runtime_and_json_schema_share_accept_reject_corpus(self) -> None:
        for name, value, expected in self.shared_corpus():
            with self.subTest(name=name):
                runtime = True
                schema = True
                try:
                    validate_envelope(value)
                except DiagnosticError:
                    runtime = False
                try:
                    validate_schema(value, self.schema)
                except SchemaReject:
                    schema = False
                self.assertEqual(runtime, expected)
                self.assertEqual(schema, expected)

    def test_sanitizer_enforces_same_aggregate_with_small_budget(self) -> None:
        bounds = Bounds(normalized_content_bytes=10, normalized_turns=10, tool_output_chars=10)
        result = sanitize_session(
            Session(
                "claude",
                "s",
                last_user_request="123456",
                last_assistant_action="abcdef",
                turns=(Turn(0, "user", "turn"),),
            ),
            bounds=bounds,
        )
        total = sum(
            len(value.encode())
            for value in (result.last_user_request, result.last_assistant_action)
            if value is not None
        ) + sum(len(turn.content.encode()) for turn in result.turns)
        self.assertLessEqual(total, 10)
        self.assertIn("W_TRUNCATED", result.warnings)

    def test_schema_bounds_last_activity_strings(self) -> None:
        session = self.schema["$defs"]["session"]["properties"]
        self.assertEqual(session["last_user_request"]["maxLength"], DEFAULT_BOUNDS.normalized_content_bytes)
        self.assertEqual(session["last_assistant_action"]["maxLength"], DEFAULT_BOUNDS.normalized_content_bytes)
        self.assertEqual(self.schema["properties"]["generated_at"]["type"], "string")

    def test_schema_declares_aggregate_utf8_extension(self) -> None:
        extension = self.schema["$defs"]["session"]["x-portable-resume-max-total-utf8-bytes"]
        self.assertEqual(extension["limit"], DEFAULT_BOUNDS.normalized_content_bytes)
        self.assertEqual(extension["stringFields"], ["last_user_request", "last_assistant_action"])
        self.assertEqual(extension["arrayField"], "turns")
        self.assertEqual(extension["arrayStringField"], "content")


if __name__ == "__main__":
    unittest.main()
