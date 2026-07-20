from __future__ import annotations

import unittest
from pathlib import Path


class ProvenanceHonestyTests(unittest.TestCase):
    def test_notice_does_not_claim_zero_inspection_of_installed_bundle(self) -> None:
        text = Path("NOTICE").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertNotIn("never inspected", lowered)
        self.assertNotIn("was not inspected", lowered)
        self.assertIn("independently authored", lowered)
        self.assertIn("apache", lowered)

    def test_provenance_uses_compatibility_reimplementation_language(self) -> None:
        text = Path("docs/provenance.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)reimplement|compatibility|behavioral")
        self.assertIn("~/.grok/bundled/skills", text)

    def test_attestation_is_scoped_not_universal(self) -> None:
        text = Path("docs/clean-room-attestation.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)(foundation|G001|scope|limited|scoped)")


class PublicDocsLinkTests(unittest.TestCase):
    def test_readme_and_status_do_not_require_omc_research(self) -> None:
        for path in (Path("README.md"), Path("docs/STATUS.md"), Path("docs/host-support.md")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(".omc/research/", text, msg=str(path))
            self.assertNotIn("/Users/", text, msg=str(path))
