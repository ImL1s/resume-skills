"""PATH-shim and process isolation for all six source CLIs (shipped reader path)."""

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

from portable_resume.diagnostics import SOURCE_KEYS
from portable_resume.reader import run


class NoSourceCliExecTests(unittest.TestCase):
    def test_path_shim_binaries_never_run_during_list_show(self) -> None:
        fixture = Path("tests/fixtures/claude/s-cla-01-ordered-parent-chain/root")
        self.assertTrue(fixture.is_dir())
        with tempfile.TemporaryDirectory() as temporary:
            bin_dir = Path(temporary) / "bin"
            bin_dir.mkdir()
            marker = Path(temporary) / "CALLED"
            for name in sorted(SOURCE_KEYS):
                path = bin_dir / name
                path.write_text(f"#!/bin/sh\necho {name} >> '{marker}'\nexit 99\n", encoding="utf-8")
                path.chmod(0o755)
            # also common launcher names
            for name in ("claude", "codex", "cursor", "opencode", "agy", "grok"):
                path = bin_dir / name
                if not path.exists():
                    path.write_text(f"#!/bin/sh\necho {name} >> '{marker}'\nexit 99\n", encoding="utf-8")
                    path.chmod(0o755)
            env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False):
                code = run(
                    [
                        "claude",
                        "list",
                        "--cwd",
                        "/workspace/project",
                        "--source-root",
                        str(fixture.resolve()),
                        "--json",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertFalse(marker.exists(), "source CLI shim was executed")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["schema_version"], "portable-resume/v1")
            self.assertTrue(payload["inert"])

    def test_reader_show_blocks_process_and_network_apis(self) -> None:
        fixture = Path("tests/fixtures/claude/s-cla-01-ordered-parent-chain/root")
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")),
            mock.patch.object(subprocess, "run", side_effect=AssertionError("process forbidden")),
            mock.patch.object(os, "system", side_effect=AssertionError("shell forbidden")),
            mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden")),
        ):
            code = run(
                [
                    "claude",
                    "show",
                    "latest",
                    "--cwd",
                    "/workspace/project",
                    "--source-root",
                    str(fixture.resolve()),
                    "--format",
                    "handoff",
                ],
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        text = stdout.getvalue().lower()
        self.assertIn("untrusted", text)
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
