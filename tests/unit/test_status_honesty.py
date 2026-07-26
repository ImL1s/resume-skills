from __future__ import annotations

import unittest
from pathlib import Path


class StatusHonestyTests(unittest.TestCase):
    def test_status_does_not_claim_next_wave_supported(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        self.assertNotIn("OpenClaw: supported", text)
        self.assertNotIn("pi destination: supported", text.lower())
        self.assertNotIn("goose source: supported", text.lower())
        self.assertNotRegex(
            text,
            r"(?i)\b(pi|openclaw|goose)\b[^.\n]{0,40}\bsupported\b",
        )

    def test_status_describes_registry_derived_matrix(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("derived from registries", lowered)
        self.assertRegex(text, r"8\s*[×x]\s*8\s*=\s*64|8×8=64|currently 8×8")

    def test_status_open_work_links_next_wave_roadmap(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"github\.com/ImL1s/resume-skills/issues/36")
        self.assertRegex(text, r"github\.com/ImL1s/resume-skills/issues/48")

    def test_agents_md_uses_registry_derived_matrix_language(self) -> None:
        text = Path("AGENTS.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertNotIn("six coding-agent sources", lowered)
        self.assertNotIn("36 cells", lowered)
        self.assertIn("derived from registries", lowered)
        self.assertRegex(text, r"8\s*[×x]\s*8|enabled_source|enabled_destination|registry")

    def test_readme_and_host_support_note_registry_derived_matrix(self) -> None:
        for path in (Path("README.md"), Path("docs/host-support.md")):
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "derived from registries",
                text.lower(),
                msg=f"{path} missing registry-derived matrix note",
            )


if __name__ == "__main__":
    unittest.main()
