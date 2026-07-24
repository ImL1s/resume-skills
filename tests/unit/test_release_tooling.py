from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import portable_resume

REPO = Path(__file__).resolve().parents[2]


class ReleaseToolingTests(unittest.TestCase):
    def run_check(self, tag: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / "check_release.py"),
                "--tag",
                tag,
                "--json",
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_metadata_only_release_check_matches_current_version(self) -> None:
        result = self.run_check(f"v{portable_resume.__version__}")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], portable_resume.__version__)
        self.assertFalse(payload["git"]["checked"])

    def test_release_check_rejects_mismatched_or_non_semver_tag(self) -> None:
        for tag in ("v999.0.0", "latest", "v01.2.3"):
            with self.subTest(tag=tag):
                result = self.run_check(tag)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(result.stdout)["ok"])

    def test_workflows_pin_actions_and_release_never_clobbers_published_assets(self) -> None:
        for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            text = (REPO / relative).read_text(encoding="utf-8")
            uses = re.findall(r"^\s*uses:\s*([^\s#]+)", text, re.MULTILINE)
            self.assertTrue(uses)
            for value in uses:
                with self.subTest(workflow=relative, uses=value):
                    self.assertRegex(value, r"^[^@]+@[0-9a-f]{40}$")

        release = (REPO / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("refusing to replace assets on an already-published release", release)
        self.assertIn("environment:\n      name: pypi", release)
        self.assertIn("attestations: write", release)
        self.assertIn("subject-path:", release)


if __name__ == "__main__":
    unittest.main()
