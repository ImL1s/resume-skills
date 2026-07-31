from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
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

    def test_metadata_only_release_check_rejects_current_development_version(self) -> None:
        result = self.run_check(f"v{portable_resume.__version__}")
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["version"], portable_resume.__version__)
        self.assertFalse(payload["git"]["checked"])
        self.assertIn("development versions cannot be released", payload["errors"])
        self.assertEqual(
            payload["build_identity"]["base_version"],
            portable_resume.__version__,
        )

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
        self.assertIn("python scripts/write_release_checksums.py", release)
        self.assertIn("sha256sum --check SHA256SUMS", release)
        self.assertIn("shasum -a 256 --check SHA256SUMS", release)
        self.assertIn("from portable_resume.registry import matrix_dimensions", release)
        self.assertIn('"packaging_cells": dimensions["cells"]', release)
        self.assertIn('"installed_runner_cells": dimensions["cells"]', release)
        self.assertIn("python scripts/prepare_build_identity.py", release)
        self.assertIn("PORTABLE_RESUME_BUILD_IDENTITY_FILE", release)
        self.assertIn("PORTABLE_RESUME_BUILD_IDENTITY_SHA256", release)
        self.assertIn("python scripts/verify_artifact_identities.py", release)
        self.assertIn("python scripts/smoke_distribution.py", release)
        self.assertIn(
            "--host-report release-assets/host-packages-build.json \\\n"
            "            --output release-assets/artifact-identities.json \\\n"
            "            dist/* release-assets/hosts/*.zip",
            release,
        )
        for dependency in (
            "needs: [validate, verify]",
            "needs: [validate, build]",
            "needs: [build, distribution-smoke]",
            "needs: [validate, build, attest]",
            "needs: [validate, draft-release]",
            "needs: [validate, draft-release, publish-pypi]",
        ):
            self.assertIn(dependency, release)
        self.assertIn("identity = load_identity_file(", release)
        self.assertIn("current_identity = git_build_identity()", release)
        self.assertIn("if current_identity != identity:", release)
        self.assertIn("artifact build mutated the source package", release)
        self.assertIn("poison-build-identity.json", release)
        self.assertIn('"build_identity": identity', release)
        self.assertIn("commit: ${{ steps.metadata.outputs.commit }}", release)
        self.assertEqual(
            release.count("ref: ${{ needs.validate.outputs.commit }}"),
            3,
        )
        self.assertEqual(release.count("release tag moved after validation"), 3)
        self.assertEqual(release.count("ref: ${{ env.RELEASE_TAG }}"), 1)
        self.assertIn('identity.get("commit_sha") != expected_commit', release)
        self.assertIn('host_report.get("build_identity") != identity', release)
        self.assertLess(
            release.index("python scripts/prepare_build_identity.py"),
            release.index("python -m build"),
        )
        self.assertLess(
            release.index("python scripts/verify_artifact_identities.py"),
            release.index("Generate release evidence"),
        )
        for asset in (
            "release-assets/build-identity.json",
            "release-assets/artifact-identities.json",
        ):
            self.assertGreaterEqual(release.count(asset), 5)
        self.assertNotIn('"packaging_cells": 64', release)
        self.assertNotIn('"installed_runner_cells": 64', release)

        ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("fetch-depth: 0", ci)
        self.assertIn("python scripts/self_verify.py --profile ci-quality", ci)
        self.assertIn("python scripts/prepare_build_identity.py", ci)
        self.assertIn("python scripts/verify_artifact_identities.py", ci)
        self.assertIn("python scripts/smoke_distribution.py", ci)
        self.assertIn(
            "--host-report host-packages/host-packages.json \\\n"
            "            --output package-evidence/artifact-identities.json \\\n"
            "            dist/* host-packages/*.zip",
            ci,
        )
        self.assertIn("python -m build --outdir dist-repro", ci)
        self.assertIn(
            '[[ "$(find dist -maxdepth 1 -type f | wc -l)" == "2" ]]',
            ci,
        )
        self.assertIn('cmp "$artifact" "dist-repro/${artifact#dist/}"', ci)
        self.assertIn("package-source-status.before", ci)
        self.assertIn("package-source-status.after", ci)
        self.assertIn("poison-build-identity.json", ci)
        self.assertLess(
            ci.index("python scripts/prepare_build_identity.py"),
            ci.index("python -m build"),
        )

    def test_release_checksum_manifest_uses_flat_asset_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "dist" / "portable_resume-9.9.9-py3-none-any.whl"
            plugin = root / "release-assets" / "hosts" / "plugin.zip"
            wheel.parent.mkdir(parents=True)
            plugin.parent.mkdir(parents=True)
            wheel.write_bytes(b"wheel")
            plugin.write_bytes(b"plugin")
            manifest = root / "release-assets" / "SHA256SUMS"

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts" / "write_release_checksums.py"),
                    "--output",
                    str(manifest),
                    str(plugin),
                    str(wheel),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            lines = manifest.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [line.split("  ", 1)[1] for line in lines],
                sorted((plugin.name, wheel.name)),
            )
            self.assertTrue(all("/" not in line.split("  ", 1)[1] for line in lines))

            downloaded = root / "downloaded"
            downloaded.mkdir()
            shutil.copy2(wheel, downloaded / wheel.name)
            shutil.copy2(plugin, downloaded / plugin.name)
            for line in lines:
                digest, name = line.split("  ", 1)
                self.assertEqual(
                    sha256((downloaded / name).read_bytes()).hexdigest(),
                    digest,
                )

    def test_release_checksum_manifest_rejects_duplicate_asset_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "one" / "artifact.zip"
            second = root / "two" / "artifact.zip"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"one")
            second.write_bytes(b"two")

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts" / "write_release_checksums.py"),
                    "--output",
                    str(root / "SHA256SUMS"),
                    str(first),
                    str(second),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate release asset basename", result.stderr)


if __name__ == "__main__":
    unittest.main()
