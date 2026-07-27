from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import portable_resume
from portable_resume.install.catalog import BUNDLE_VERSION


class VersionSsotTests(unittest.TestCase):
    def test_bundle_version_matches_package(self) -> None:
        self.assertEqual(BUNDLE_VERSION, portable_resume.__version__)

    def test_project_metadata_matches_package_and_repository_license(self) -> None:
        metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(metadata["version"], portable_resume.__version__)
        self.assertEqual(
            metadata["description"],
            "Offline, local-only context migration across coding agents",
        )
        self.assertEqual(metadata["license"], "Apache-2.0")
        self.assertEqual(metadata["license-files"], ["LICENSE", "NOTICE"])
        self.assertEqual(
            metadata["urls"],
            {
                "Homepage": "https://github.com/ImL1s/resume-skills",
                "Documentation": "https://github.com/ImL1s/resume-skills/tree/main/docs",
                "Repository": "https://github.com/ImL1s/resume-skills",
                "Issues": "https://github.com/ImL1s/resume-skills/issues",
                "Changelog": "https://github.com/ImL1s/resume-skills/blob/main/CHANGELOG.md",
            },
        )

    def test_packaged_schema_matches_repository_schema(self) -> None:
        public = Path("schemas/portable-resume-v1.schema.json").read_bytes()
        packaged = Path(
            "src/portable_resume/resources/portable-resume-v1.schema.json"
        ).read_bytes()
        self.assertEqual(packaged, public)


if __name__ == "__main__":
    unittest.main()
