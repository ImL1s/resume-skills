from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.adapters.base import CapabilityReport, ResolvedRef
from portable_resume.bounds import ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query, Session, SessionSummary, Turn
from portable_resume.reader import run
from portable_resume.sanitize import sanitize_text


class GuardedAdapter:
    key = "claude"

    def probe(self, query: Query) -> CapabilityReport:
        return CapabilityReport("claude", "synthetic", "supported")

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        return [SessionSummary("claude", "id", cwd=query.cwd)]

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        return Session("claude", ref.session_id, cwd=query.cwd, turns=(Turn(0, "user", "$(touch forbidden)"),))


class IsolationTests(unittest.TestCase):
    def test_core_flow_never_spawns_source_process_or_network(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch("portable_resume.reader._load_adapter", return_value=GuardedAdapter()),
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")),
            mock.patch.object(subprocess, "run", side_effect=AssertionError("process forbidden")),
            mock.patch.object(os, "system", side_effect=AssertionError("shell forbidden")),
            mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden")),
        ):
            code = run(["claude", "show", "--cwd", os.getcwd(), "--format", "handoff"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("> $(touch forbidden)", stdout.getvalue())

    def test_path_shims_for_all_sources_are_never_called(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "CALLED"
            for source in ("claude", "codex", "cursor", "opencode", "antigravity", "grok"):
                executable = root / source
                executable.write_text(f"#!/bin/sh\necho called >> '{marker}'\nexit 99\n")
                executable.chmod(0o755)
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                mock.patch.dict(os.environ, {"PATH": str(root)}),
                mock.patch("portable_resume.reader._load_adapter", side_effect=DiagnosticError("E_UNSUPPORTED_FORMAT")),
            ):
                code = run(["claude", "show", "--cwd", os.getcwd(), "--json"], stdout=stdout, stderr=stderr)
            self.assertEqual(code, 5)
            self.assertFalse(marker.exists())
            self.assertEqual(json.loads(stderr.getvalue())["code"], "E_UNSUPPORTED_FORMAT")

    def test_sanitizer_does_not_interpret_payload(self) -> None:
        with mock.patch.object(os, "system", side_effect=AssertionError("shell forbidden")):
            output = sanitize_text("$(touch /tmp/nope); curl https://invalid", max_chars=1000)
        self.assertIn("$(touch", output.text)

    def test_runtime_has_no_network_or_source_process_calls(self) -> None:
        runtime = Path("src/portable_resume")
        text = "\n".join(path.read_text() for path in runtime.rglob("*.py"))
        for forbidden in ("shell=True", "os.system(", "subprocess.Popen(", "subprocess.run(", "socket.connect(", "urlopen("):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
