"""Content-free command contract for the real issue #263 APFS proof."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Issue263APFSProofContractTests(unittest.TestCase):
    def test_ci_exposes_a_specific_proof_check_name(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('name: "issue #263 real APFS COW proof"', workflow)

    def test_below_minimum_fails_before_capability_probe_or_artifact_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prove_issue263_macos_apfs.py",
                    "--iterations",
                    "199",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "")
            self.assertFalse(output.exists())
            self.assertEqual(
                json.loads(completed.stderr),
                {
                    "ok": False,
                    "reason": "iterations below proof minimum",
                    "schema": "portable-resume/issue-263-apfs-proof-v1",
                },
            )


if __name__ == "__main__":
    unittest.main()
