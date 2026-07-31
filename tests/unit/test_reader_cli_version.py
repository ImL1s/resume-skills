from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from portable_resume.build_identity import build_identity
from portable_resume.reader import _runtime_version_report


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

    def test_runtime_version_paths_are_json_escaped(self) -> None:
        report = _runtime_version_report(
            {
                "actual_root": "/tmp/runtime\nroot",
                "recorded_root": "/tmp/recorded\troot",
                "recorded_root_matches_actual": False,
                "package_identity": None,
            },
            prog="portable-resume",
        )

        self.assertNotIn("runtime\nroot", report)
        self.assertNotIn("recorded\troot", report)
        lines = report.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[1], 'runtime-root: "/tmp/runtime\\nroot"')
        self.assertEqual(lines[2], 'recorded-root: "/tmp/recorded\\troot"')


if __name__ == "__main__":
    unittest.main()
