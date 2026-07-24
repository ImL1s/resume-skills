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
        self.assertIn("python scripts/write_release_checksums.py", release)
        self.assertIn("sha256sum --check SHA256SUMS", release)
        self.assertIn("shasum -a 256 --check SHA256SUMS", release)

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
