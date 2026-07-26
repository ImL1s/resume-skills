from __future__ import annotations

import unittest
from pathlib import Path


class StatusHonestyTests(unittest.TestCase):
    def test_status_does_not_claim_next_wave_supported(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        self.assertNotIn("OpenClaw: supported", text)
        self.assertNotIn("goose source: supported", text.lower())
        self.assertNotRegex(
            text,
            r"(?i)\b(openclaw|goose)\b[^.\n]{0,40}\bsupported\b",
        )
        self.assertNotRegex(
            text,
            r"(?i)pi[^.\n]{0,40}(picker|native activation).{0,20}pass",
        )

    def test_status_describes_registry_derived_matrix(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("derived from registries", lowered)
        self.assertRegex(text, r"9\s*[×x]\s*9\s*=\s*81|9×9=81|currently 9×9")

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
        self.assertRegex(
            text,
            r"9\s*[×x]\s*9|9\s*[×x]\s*8|enabled_source|enabled_destination|registry",
        )

    def test_readme_and_host_support_note_registry_derived_matrix(self) -> None:
        for path in (Path("README.md"), Path("docs/host-support.md")):
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "derived from registries",
                text.lower(),
                msg=f"{path} missing registry-derived matrix note",
            )


    def test_status_notes_stable_scan_lines_adoption_is_partial(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("stable_scan_lines", lowered)
        self.assertTrue("adopted by pi" in lowered or "remaining adapters still pending" in lowered)

    def test_status_marks_issue_20_closed_via_pr_49(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"Installer recover containment \(#20\)")
        self.assertRegex(text, r"\*\*Closed\*\* via \[PR #49\]")
        self.assertIn("test_install_recover_containment.py", text)

    def test_status_reflects_pi_merge_honesty(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertRegex(text, r"\*\*\d+ pass locally\*\*")
        self.assertIn("d9152cd", text)
        self.assertIn("340", text)  # archived PR #51 merge count
        self.assertRegex(text, r"(?i)pi.*destination.*(supported|pass)")
        self.assertRegex(text, r"(?i)(native|picker|host.?ui).*(not-run|not claimed)")
        self.assertTrue(
            "pi" in lowered
            and "source" in lowered
            and "supported" in lowered
        )
        # Published 0.3.3 must not silently absorb unreleased 81-cell claims.
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertIn("Unreleased `main`", readme)
        self.assertRegex(readme, r"0\.3\.3[^\n]*64/64|64/64[^\n]*0\.3\.3")


if __name__ == "__main__":
    unittest.main()
