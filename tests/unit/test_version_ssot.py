from __future__ import annotations

import unittest

import portable_resume
from portable_resume.install.catalog import BUNDLE_VERSION


class VersionSsotTests(unittest.TestCase):
    def test_bundle_version_matches_package(self) -> None:
        self.assertEqual(BUNDLE_VERSION, portable_resume.__version__)


if __name__ == "__main__":
    unittest.main()
