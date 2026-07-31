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
                lines = completed.stdout.strip().splitlines()
                self.assertEqual(lines[0], f"{command} {build_identity()['version']}")
                if command == "portable-resume":
                    self.assertEqual(
                        [line.split(":", 1)[0] for line in lines[1:]],
                        [
                            "runtime-root",
                            "recorded-root",
                            "recorded-root-match",
                            "package-identity",
                        ],
                    )
                else:
                    self.assertEqual(len(lines), 1)
                self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
