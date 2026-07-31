from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import check_docs


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

    def test_docs_check_rejects_broken_root_onboarding_and_count_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(REPO / "README.md", root / "README.md")
            shutil.copy2(REPO / "CHANGELOG.md", root / "CHANGELOG.md")
            shutil.copytree(REPO / "docs", root / "docs")

            readme_path = root / "README.md"
            readme = readme_path.read_text(encoding="utf-8")
            readme = readme.replace(
                'alt="Local coding-agent session stores flow into a sealed context '
                'archive, then into fresh destination sessions"',
                'alt="Nine coding-agent sources flow into nine destination sessions"',
            )
            readme = readme.replace("Installed (pipx/pip):", "Lower-level commands:")
            readme = readme.replace(
                "\nportable-resume --version",
                "\nPYTHONPATH=src python3 scripts/portable-resume --version",
            )
            readme_path.write_text(readme, encoding="utf-8")

            install_hosts_path = root / "docs" / "install-hosts.md"
            install_hosts = install_hosts_path.read_text(encoding="utf-8").replace(
                "# all user-global profiles (count derives from the registry)",
                "# all thirteen user-global profiles",
            )
            install_hosts_path.write_text(install_hosts, encoding="utf-8")

            changelog_path = root / "CHANGELOG.md"
            changelog_path.write_text(
                "## Unreleased\n\n- misplaced entry\n\n"
                + changelog_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            with mock.patch.object(check_docs, "REPO", root):
                report = check_docs.check()

        failures = report["failures"]
        self.assertIn("README.md: hero alt text must be count-free", failures)
        self.assertIn("README.md: missing installed (pipx/pip) command section", failures)
        self.assertIn(
            "docs/install-hosts.md: quick-install all comment must be registry-derived",
            failures,
        )
        self.assertIn(
            "CHANGELOG.md: expected one H1 followed by one Unreleased section",
            failures,
        )

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
