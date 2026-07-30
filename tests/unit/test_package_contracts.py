"""#27: versioned package contracts and offline validation."""

from __future__ import annotations

import io
import json
import zipfile
import unittest

from portable_resume import __version__
from portable_resume.install.package_contracts import (
    PACKAGE_CONTRACTS,
    PACKAGE_CONTRACTS_SCHEMA,
    contract_for_package_type,
    contracts_report,
    validate_archive_bytes,
    validate_member_paths,
    validate_skills_layout,
)


class PackageContractRegistryTests(unittest.TestCase):
    def test_contracts_cover_all_builder_surfaces(self) -> None:
        expected = {
            "direct-skills",
            "antigravity-plugin",
            "claude-marketplace",
            "codex-marketplace",
            "cursor-marketplace",
            "grok-plugin",
            "qwen-extension",
            "kimi-plugin",
        }
        self.assertEqual(set(PACKAGE_CONTRACTS), expected)
        report = contracts_report()
        self.assertEqual(report["schema_version"], PACKAGE_CONTRACTS_SCHEMA)
        self.assertEqual(report["bundle_version"], __version__)

    def test_each_contract_has_stable_id(self) -> None:
        for key, contract in PACKAGE_CONTRACTS.items():
            self.assertTrue(contract.contract_id.endswith("-v1"))
            self.assertEqual(contract.package_type, key)
            self.assertIn(contract.native_evidence_status, {"not-run", "pass", "historical"})


class OfflineValidationTests(unittest.TestCase):
    def test_rejects_parent_escape_and_install_runtime(self) -> None:
        failures = validate_member_paths(
            ["ok/SKILL.md", "../escape", "x/portable_resume/install/cli.py"]
        )
        self.assertTrue(any("unsafe" in f for f in failures))
        self.assertTrue(any("forbidden" in f for f in failures))

    def test_skills_layout_requires_all_sources(self) -> None:
        failures = validate_skills_layout(
            ["skills/resume-claude/SKILL.md"],
            skills_prefix="skills/",
        )
        self.assertTrue(any("missing skill" in f for f in failures))

    def test_validate_bad_zip(self) -> None:
        report = validate_archive_bytes(b"not-a-zip", package_type="direct-skills")
        self.assertFalse(report["ok"])
        self.assertEqual(report["native_evidence_status"], "not-run")
        self.assertTrue(report["failures"])

    def test_minimal_direct_skills_contract_shape(self) -> None:
        # Empty archive fails skills layout — proves contract is enforced.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("readme.txt", b"x")
        report = validate_archive_bytes(buf.getvalue(), package_type="direct-skills")
        self.assertFalse(report["ok"])
        self.assertEqual(report["contract_id"], "direct-skills-v1")

    def test_contract_for_unknown_raises(self) -> None:
        with self.assertRaises(KeyError):
            contract_for_package_type("nope")


if __name__ == "__main__":
    unittest.main()
