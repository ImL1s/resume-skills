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
        self.assertEqual(metadata["license"]["text"], "Apache-2.0")


if __name__ == "__main__":
    unittest.main()
