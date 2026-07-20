from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import CapabilityReport, ResolvedRef
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query, Session, SessionSummary, Turn
from portable_resume.reader import run
from portable_resume.request import load_request


class FakeAdapter:
    key = "claude"

    def probe(self, query: Query) -> CapabilityReport:
        return CapabilityReport("claude", "synthetic-v1", "supported")

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        return [
            SessionSummary(
                source="claude",
                session_id="s1",
                cwd=query.cwd,
                updated_at="2026-07-20T00:00:00Z",
                title="Synthetic",
            )
        ]

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        return Session(
            source="claude",
            session_id=ref.session_id,
            cwd=query.cwd,
            last_user_request="Keep working",
            turns=(Turn(0, "user", "Keep working"),),
        )


class RequestAndCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "project with spaces"
        self.cwd.mkdir()

    def write_request(self, payload: object, *, raw: str | None = None) -> Path:
        path = self.root / "request.json"
        path.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")
        return path

    def valid(self, ref: str = "latest") -> dict[str, str]:
        return {
            "schema_version": "portable-resume/request-v1",
            "source": "claude",
            "action": "show",
            "resume_ref": ref,
            "cwd": str(self.cwd),
        }

    def test_u030_defaults_are_explicit_in_request(self) -> None:
        request = load_request(str(self.write_request(self.valid())), expected_source="claude")
        self.assertEqual(request.resume_ref, "latest")
        self.assertEqual(request.cwd, str(self.cwd))

    def test_u031_metacharacters_unicode_pathlike_and_leading_dash_stay_data(self) -> None:
        for ref in ('-danger "quoted" $(touch nope) `id` \u2603 /tmp/looks-like-path', "semi; amp& pipe|"):
            with self.subTest(ref=ref):
                request = load_request(str(self.write_request(self.valid(ref))), expected_source="claude")
                self.assertEqual(request.resume_ref, ref)
                self.assertNotIn(ref, ["python3", "portable-resume", "--request-file"])

    def test_u032_nul_control_oversize_relative_cwd_extra_and_duplicate_rejected(self) -> None:
        cases: list[tuple[str, Path]] = []
        nul = self.valid("bad\x00ref")
        cases.append(("nul", self.write_request(nul)))
        for name, payload in (
            ("relative", {**self.valid(), "cwd": "relative/path"}),
            ("extra", {**self.valid(), "extra": 1}),
        ):
            path = self.root / f"{name}.json"
            path.write_text(json.dumps(payload))
            cases.append((name, path))
        duplicate = self.root / "duplicate.json"
        duplicate.write_text('{"schema_version":"portable-resume/request-v1","source":"claude","source":"codex","action":"show","resume_ref":"latest","cwd":"' + str(self.cwd) + '"}')
        cases.append(("duplicate", duplicate))
        oversized = self.root / "oversized.json"
        oversized.write_bytes(b"{" + b" " * (16 * 1024) + b"}")
        cases.append(("oversized", oversized))
        for name, path in cases:
            with self.subTest(name=name), self.assertRaises(DiagnosticError):
                load_request(str(path), expected_source="claude")

    def test_u033_schema_source_and_action_mismatch(self) -> None:
        for change in (
            {"schema_version": "portable-resume/request-v2"},
            {"source": "codex"},
            {"action": "list"},
        ):
            with self.subTest(change=change):
                path = self.write_request({**self.valid(), **change})
                with self.assertRaises(DiagnosticError) as caught:
                    load_request(str(path), expected_source="claude")
                self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_u034_symlink_nonregular_and_over_16k_rejected(self) -> None:
        real = self.write_request(self.valid())
        symlink = self.root / "link.json"
        symlink.symlink_to(real)
        directory = self.root / "directory"
        directory.mkdir()
        for path in (symlink, directory):
            with self.subTest(path=path), self.assertRaises(DiagnosticError):
                load_request(str(path), expected_source="claude")
        if hasattr(os, "mkfifo"):
            fifo = self.root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(DiagnosticError):
                load_request(str(fifo), expected_source="claude")

    def test_u035_shell_looking_text_never_causes_side_effect(self) -> None:
        marker = self.root / "owned"
        ref = f"$(touch {marker}) `touch {marker}`; touch {marker}"
        request = load_request(str(self.write_request(self.valid(ref))), expected_source="claude")
        self.assertEqual(request.resume_ref, ref)
        self.assertFalse(marker.exists())
        bad = self.valid("line1\nline2")
        with self.assertRaises(DiagnosticError):
            load_request(str(self.write_request(bad)), expected_source="claude")
        self.assertFalse(marker.exists())

    def test_u028_json_alias_explicit_json_and_default_handoff(self) -> None:
        with mock.patch("portable_resume.reader._load_adapter", return_value=FakeAdapter()):
            outputs = []
            for arguments in (
                ["claude", "show", "--cwd", str(self.cwd), "--json"],
                ["claude", "show", "--cwd", str(self.cwd), "--format", "json"],
            ):
                stdout, stderr = io.StringIO(), io.StringIO()
                self.assertEqual(run(arguments, stdout=stdout, stderr=stderr), 0)
                self.assertEqual(stderr.getvalue(), "")
                payload = json.loads(stdout.getvalue())
                payload["generated_at"] = "CLOCK"
                outputs.append(payload)
            self.assertEqual(outputs[0], outputs[1])
            stdout, stderr = io.StringIO(), io.StringIO()
            self.assertEqual(run(["claude", "show", "--cwd", str(self.cwd)], stdout=stdout, stderr=stderr), 0)
            self.assertIn("# Portable Resume Handoff", stdout.getvalue())
            self.assertNotIn("generated_at", stdout.getvalue())
            stdout, stderr = io.StringIO(), io.StringIO()
            self.assertEqual(run(["claude", "show", "--json", "--format", "handoff"], stdout=stdout, stderr=stderr), 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(json.loads(stderr.getvalue())["code"], "E_INVALID_INPUT")

    def test_valid_request_reaches_honest_unsupported_adapter(self) -> None:
        request = self.write_request(self.valid())
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("portable_resume.reader._load_adapter", side_effect=DiagnosticError("E_UNSUPPORTED_FORMAT")):
            code = run(["--request-file", str(request), "--expected-source", "claude", "--format", "json"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 5)
        self.assertEqual(stdout.getvalue(), "")
        diagnostic = json.loads(stderr.getvalue())
        self.assertEqual(diagnostic["code"], "E_UNSUPPORTED_FORMAT")
        self.assertNotIn(str(self.cwd), stderr.getvalue())

    def test_invalid_request_cli_is_deterministic(self) -> None:
        request = self.write_request({"bad": True})
        outputs = []
        for _ in range(2):
            stdout, stderr = io.StringIO(), io.StringIO()
            self.assertEqual(run(["--request-file", str(request), "--expected-source", "claude"], stdout=stdout, stderr=stderr), 2)
            self.assertEqual(stdout.getvalue(), "")
            outputs.append(stderr.getvalue())
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
