"""Content-free command contract for the real issue #263 APFS proof."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import runpy
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

        proof_job = workflow.split("  issue263-apfs-proof:\n", 1)[1].split(
            "\n  package:\n", 1
        )[0]
        self.assertIn('name: "issue #263 real APFS COW proof"', proof_job)
        exact_sha = "${{ github.event.pull_request.head.sha || github.sha }}"
        self.assertIn(f"ref: {exact_sha}", proof_job)
        self.assertIn(f"ISSUE263_EXPECTED_SHA: {exact_sha}", proof_job)
        self.assertIn(f"name: issue263-apfs-proof-{exact_sha}", proof_job)
        self.assertIn("issue263-apfs-proof.json.sha256", proof_job)

    def test_output_and_stdout_are_identical_canonical_json_with_exact_sidecar(self) -> None:
        namespace = runpy.run_path(
            str(ROOT / "scripts" / "prove_issue263_macos_apfs.py"),
            run_name="issue263_proof_contract",
        )
        write_output = namespace["_write_output"]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                write_output(output, {"z": 2, "a": "value"})

            emitted = output.read_bytes()
            self.assertEqual(stdout.getvalue().encode("ascii"), emitted)
            expected = hashlib.sha256(emitted).hexdigest()
            self.assertEqual(
                output.with_name(output.name + ".sha256").read_text(encoding="ascii"),
                f"{expected}  {output.name}\n",
            )
            self.assertNotIn("raw_output_sha256", json.loads(emitted))

    def test_expected_head_mismatch_fails_before_capability_or_artifact_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof.json"
            environment = dict(os.environ)
            environment["ISSUE263_EXPECTED_SHA"] = "0" * 40
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prove_issue263_macos_apfs.py",
                    "--iterations",
                    "200",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "")
            self.assertFalse(output.exists())
            self.assertFalse(output.with_name(output.name + ".sha256").exists())
            self.assertEqual(
                json.loads(completed.stderr)["reason"],
                "proof HEAD does not match expected SHA",
            )

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
            self.assertFalse(output.with_name(output.name + ".sha256").exists())
            self.assertEqual(
                json.loads(completed.stderr),
                {
                    "ok": False,
                    "reason": "iterations below proof minimum",
                    "schema": "portable-resume/issue-263-apfs-proof-v2",
                },
            )


if __name__ == "__main__":
    unittest.main()
