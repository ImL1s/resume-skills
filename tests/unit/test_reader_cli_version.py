from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import portable_resume
from portable_resume.build_identity import build_identity


REPO = Path(__file__).resolve().parents[2]


class ReaderCliVersionTests(unittest.TestCase):
    def test_source_clis_report_package_version(self) -> None:
        for command in ("portable-resume", "install-resume-skills"):
            with self.subTest(command=command):
                completed = subprocess.run(
                    [sys.executable, str(REPO / "scripts" / command), "--version"],
                    cwd=REPO,
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(
                    completed.stdout.strip(),
                    f"{command} {build_identity()['version']}",
                )
                self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
