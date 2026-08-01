from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

from portable_resume import __version__
from portable_resume.diagnostics import SOURCE_KEYS
from portable_resume.install.catalog import HOST_KEYS
from portable_resume.registry import enabled_package_keys

REPO = Path(__file__).resolve().parents[2]


class HostPackageBuilderTests(unittest.TestCase):
    def build(self, output: Path) -> dict:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / "build_host_packages.py"),
                "--output-dir",
                str(output),
                "--json",
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_builds_safe_complete_deterministic_host_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            report = self.build(first)
            repeated = self.build(second)
            self.assertEqual(report["host_count"], len(HOST_KEYS))
            self.assertEqual(report["direct_package_count"], len(HOST_KEYS))
            self.assertEqual(report["plugin_package_count"], len(enabled_package_keys()))
            expected_artifact_count = len(HOST_KEYS) + len(enabled_package_keys())
            self.assertEqual(len(report["artifacts"]), expected_artifact_count)
            artifact_files = [item["file"] for item in report["artifacts"]]
            self.assertEqual(len(artifact_files), len(set(artifact_files)))
            self.assertEqual(
                {path.name for path in first.glob("*.zip")},
                set(artifact_files),
            )
            self.assertEqual(
                set(report["package_surfaces"]),
                set(enabled_package_keys()),
            )
            self.assertEqual(report["schema_version"], "portable-resume/host-packages-v2")
            self.assertEqual(report["version"], __version__)
            self.assertEqual(
                report["build_identity"]["base_version"],
                __version__,
            )
            self.assertEqual(
                report["artifact_version"],
                report["build_identity"]["version"],
            )
            self.assertEqual(report["live_host_installation"], "not-run")
            self.assertEqual(report["native_package_activation"], "not-run")
            self.assertIn("package_contracts_schema", report)
            self.assertIn("contracts", report)
            self.assertEqual(
                {item["file"]: item["sha256"] for item in report["artifacts"]},
                {item["file"]: item["sha256"] for item in repeated["artifacts"]},
            )
            for item in report["artifacts"]:
                self.assertIn(report["artifact_version"], item["file"])
                self.assertIn("contract_id", item)
                self.assertEqual(item["offline_validation"], "pass")
                self.assertEqual(item["native_evidence_status"], "not-run")
                archive = first / item["file"]
                self.assertEqual(
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                    item["sha256"],
                )
                with zipfile.ZipFile(archive) as zipped:
                    names = zipped.namelist()
                    self.assertTrue(names)
                    self.assertTrue(
                        all(
                            not PurePosixPath(name).is_absolute()
                            and ".." not in PurePosixPath(name).parts
                            and "\\" not in name
                            for name in names
                        )
                    )
                    self.assertEqual(
                        len([name for name in names if name.endswith("/SKILL.md")]),
                        len(SOURCE_KEYS),
                    )
                    self.assertTrue(
                        any(
                            name.endswith(
                                "resources/portable-resume-v1.schema.json"
                            )
                            for name in names
                        )
                    )
                    self.assertFalse(
                        any("/portable_resume/install/" in name for name in names)
                    )
                    identity_members = [
                        name
                        for name in names
                        if name.endswith(
                            "/portable_resume/resources/build-identity.json"
                        )
                    ]
                    self.assertEqual(len(identity_members), 1)
                    self.assertEqual(
                        json.loads(zipped.read(identity_members[0]).decode("utf-8")),
                        report["build_identity"],
                    )

    def test_plugin_archives_have_required_root_manifests(self) -> None:
        expected = {
            "antigravity-plugin": "plugin.json",
            "claude-marketplace": ".claude-plugin/marketplace.json",
            "codex-marketplace": ".agents/plugins/marketplace.json",
            "cursor-marketplace": ".cursor-plugin/marketplace.json",
            "grok-plugin": "plugin.json",
            "qwen-extension": "qwen-extension.json",
            "kimi-plugin": "kimi.plugin.json",
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "packages"
            report = self.build(output)
            for item in report["artifacts"]:
                if item["type"] not in expected:
                    continue
                with zipfile.ZipFile(output / item["file"]) as zipped:
                    manifest = json.loads(
                        zipped.read(expected[item["type"]]).decode("utf-8")
                    )
                if item["type"] not in {
                    "antigravity-plugin",
                    "claude-marketplace",
                    "codex-marketplace",
                    "cursor-marketplace",
                }:
                    self.assertEqual(manifest["name"], "portable-resume")
                    self.assertEqual(manifest["version"], __version__)

    def test_plugin_layouts_match_public_specs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "packages"
            report = self.build(output)
            artifacts = {item["type"]: item for item in report["artifacts"]}

            codex = output / artifacts["codex-marketplace"]["file"]
            with zipfile.ZipFile(codex) as zipped:
                marketplace = json.loads(
                    zipped.read(".agents/plugins/marketplace.json").decode("utf-8")
                )
                entry = marketplace["plugins"][0]
                self.assertEqual(
                    entry["source"],
                    {
                        "source": "local",
                        "path": "./plugins/portable-resume",
                    },
                )
                self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
                self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
                plugin = json.loads(
                    zipped.read(
                        "plugins/portable-resume/.codex-plugin/plugin.json"
                    ).decode("utf-8")
                )
                self.assertEqual(plugin["skills"], "./skills/")
                self.assertEqual(plugin["version"], __version__)

            cursor = output / artifacts["cursor-marketplace"]["file"]
            with zipfile.ZipFile(cursor) as zipped:
                marketplace = json.loads(
                    zipped.read(".cursor-plugin/marketplace.json").decode("utf-8")
                )
                source = marketplace["plugins"][0]["source"]
                plugin = json.loads(
                    zipped.read(
                        f"{source}/.cursor-plugin/plugin.json"
                    ).decode("utf-8")
                )
                self.assertEqual(plugin["skills"], "./skills/")
                self.assertEqual(plugin["version"], __version__)
                self.assertTrue(
                    any(
                        name.startswith(f"{source}/skills/")
                        and name.endswith("/SKILL.md")
                        for name in zipped.namelist()
                    )
                )

            antigravity = output / artifacts["antigravity-plugin"]["file"]
            with zipfile.ZipFile(antigravity) as zipped:
                self.assertEqual(
                    json.loads(zipped.read("plugin.json").decode("utf-8")),
                    {"name": "portable-resume"},
                )
                self.assertTrue(
                    any(
                        name.startswith("skills/")
                        and name.endswith("/SKILL.md")
                        for name in zipped.namelist()
                    )
                )

            qwen = output / artifacts["qwen-extension"]["file"]
            with zipfile.ZipFile(qwen) as zipped:
                manifest = json.loads(
                    zipped.read("qwen-extension.json").decode("utf-8")
                )
                self.assertEqual(manifest["skills"], "skills")
                self.assertEqual(manifest["version"], __version__)
                self.assertTrue(
                    any(
                        name.startswith("skills/")
                        and name.endswith("/SKILL.md")
                        for name in zipped.namelist()
                    )
                )

            kimi = output / artifacts["kimi-plugin"]["file"]
            with zipfile.ZipFile(kimi) as zipped:
                manifest = json.loads(
                    zipped.read("kimi.plugin.json").decode("utf-8")
                )
                self.assertEqual(manifest["skills"], "./skills/")
                self.assertEqual(manifest["version"], __version__)
                self.assertTrue(
                    any(
                        name.startswith("skills/")
                        and name.endswith("/SKILL.md")
                        for name in zipped.namelist()
                    )
                )

    def test_offline_contract_rejects_archive_missing_manifest(self) -> None:
        from portable_resume.install.package_contracts import validate_archive_bytes
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("skills/resume-claude/SKILL.md", b"---\nname: x\n---\n")
        report = validate_archive_bytes(buf.getvalue(), package_type="grok-plugin")
        self.assertFalse(report["ok"])
        self.assertTrue(any("missing required member" in f for f in report["failures"]))


if __name__ == "__main__":
    unittest.main()
