from __future__ import annotations

import unittest
from pathlib import Path


class PublicPolicyFilesTests(unittest.TestCase):
    def test_security_and_contributing_exist(self) -> None:
        for name in ("SECURITY.md", "CONTRIBUTING.md"):
            text = Path(name).read_text(encoding="utf-8")
            self.assertGreater(len(text), 400)
        sec = Path("SECURITY.md").read_text(encoding="utf-8")
        self.assertRegex(sec, r"(?i)threat|session|report|vulnerab")
        con = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("synthetic", con)
        self.assertIn("~/.grok/bundled/skills", con)
