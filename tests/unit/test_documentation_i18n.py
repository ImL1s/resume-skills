from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class DocumentationI18nTests(unittest.TestCase):
    def test_multilingual_quickstarts_are_complete_and_current(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "check_docs.py"), "--json"],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["required_locale_count"], 12)
        self.assertEqual(len(report["checked_locales"]), 12)
        self.assertEqual(report["failures"], [])

    def test_context7_is_not_a_product_feature(self) -> None:
        product_docs = [
            REPO / "README.md",
            REPO / "docs" / "STATUS.md",
            REPO / "docs" / "clean-room-attestation.md",
            REPO / "docs" / "i18n" / "README.md",
            REPO / "src" / "portable_resume" / "resources" / "skill" / "SKILL.md.tmpl",
        ]
        product_docs.extend(sorted((REPO / "docs" / "i18n").glob("*.md")))
        for path in product_docs:
            self.assertNotIn("context7", path.read_text(encoding="utf-8").lower(), str(path))
        self.assertFalse((REPO / "docs" / "network-integrations.md").exists())


if __name__ == "__main__":
    unittest.main()
