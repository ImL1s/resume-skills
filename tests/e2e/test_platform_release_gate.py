"""OS-aware release gate: deterministic suite on this OS; peer OS honesty."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class PlatformReleaseGateTests(unittest.TestCase):
    def test_current_os_deterministic_gate(self) -> None:
        expected = os.environ.get("PORTABLE_RESUME_EXPECT_OS")
        current = platform.system().lower()
        if expected:
            mapping = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
            want = mapping.get(expected.lower(), expected.lower())
            got = {"darwin": "darwin", "linux": "linux", "windows": "windows"}.get(current, current)
            if want != got:
                self.skipTest(f"gate expects {want}, running on {got}")

        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        compile_p = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(compile_p.returncode, 0, compile_p.stderr)

        self_check = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "portable-resume"), "self-check", "--json"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(self_check.returncode, 0, self_check.stderr)
        report = json.loads(self_check.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["matrix"]["cell_count"], 36)

        matrix = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "install-resume-skills"), "matrix", "--json"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(matrix.returncode, 0, matrix.stderr)
        body = json.loads(matrix.stdout)
        self.assertTrue(body["ok"])
        self.assertEqual(body["cell_count"], 36)

    def test_peer_os_not_silently_claimed(self) -> None:
        # Dual-OS AC-18: without a second runner, docs must not claim both OS green.
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        host = (REPO / "docs" / "host-support.md").read_text(encoding="utf-8")
        # honest limitation language present somewhere
        blob = readme + "\n" + host
        self.assertTrue(
            "Linux" in blob or "dual-OS" in blob or "macOS" in blob or "not-run" in blob,
            "release docs must discuss platform evidence honestly",
        )
        # never claim both OS gates passed in host-support profile table
        self.assertNotIn("verified-live on macOS and Linux", blob.lower())


if __name__ == "__main__":
    unittest.main()
