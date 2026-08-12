"""Windows install documentation honesty for issue #247."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class WindowsInstallDocsTests(unittest.TestCase):
    def test_user_install_uses_interpreter_derived_scripts_directory(self) -> None:
        for relative in ("README.md", "docs/install-hosts.md"):
            with self.subTest(path=relative):
                text = (REPO / relative).read_text(encoding="utf-8")
                self.assertIn("sysconfig.get_path('scripts', 'nt_user')", text)
                self.assertIn("Open a **new** PowerShell", text)
                self.assertIn("[Environment]::SetEnvironmentVariable", text)

    def test_shared_root_and_windows_evidence_boundaries_are_explicit(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        guide = (REPO / "docs/install-hosts.md").read_text(encoding="utf-8")
        for text in (readme, guide):
            self.assertIn("quick-install all", text)
            self.assertIn("shared", text.lower())
            self.assertIn("physical root", text.lower())
            self.assertRegex(text, r"(?s)(?:\*\*not\*\*|not)\s+(?:a\s+)?(?:full\s+)?306/306")
        self.assertIn("Verify each intended host separately", guide)
        self.assertIn("focused Claude/Cursor/Codex", guide)
        self.assertIn("WINDOWS_PRODUCTIZATION.md", guide)
        self.assertNotIn("publishes one final manifest per root", guide)
        self.assertIn("older-version coordinated upgrade", guide)

        match = re.search(r"\[Windows user install and shared Skill roots\]\(([^)]+)\)", readme)
        if match is None:
            self.fail("README Windows install guide link is missing")
        target, anchor = match.group(1).split("#", 1)
        target_path = REPO / target
        self.assertTrue(target_path.is_file())
        heading = "## " + anchor.replace("-", " ")
        self.assertIn(heading.casefold(), target_path.read_text(encoding="utf-8").casefold())


if __name__ == "__main__":
    unittest.main()
