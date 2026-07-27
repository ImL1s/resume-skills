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

    def test_release_summary_scopes_historical_host_evidence(self) -> None:
        readme_opening = "\n".join(
            Path("README.md").read_text(encoding="utf-8").splitlines()[:30]
        )
        self.assertIn("v0.3.2", readme_opening)
        compact_readme = " ".join(readme_opening.replace("**", "").split())
        self.assertRegex(compact_readme, r"(?i)fresh v0\.3\.4.*not-run")

        host = Path("docs/host-support.md").read_text(encoding="utf-8")
        for label in (
            "Native local plugin/extension installs",
            "Public marketplace installation",
            "Visual marketplace picker",
        ):
            row = next(line for line in host.splitlines() if f"| {label} |" in line)
            self.assertIn("v0.3.2", row, label)
        latest = next(
            line
            for line in host.splitlines()
            if "| Latest archived remote CI/release |" in line
        )
        self.assertIn("v0.3.4", latest)

        status = Path("docs/STATUS.md").read_text(encoding="utf-8")
        headless = next(
            line
            for line in status.splitlines()
            if "| Host-native headless Skill activation |" in line
        )
        self.assertIn("v0.3.2", headless)
        self.assertIn("v0.3.4", headless)
        self.assertIn("not-run", headless)

    def test_historical_evidence_heading_is_version_scoped(self) -> None:
        evidence = Path("docs/evidence-summary.md").read_text(encoding="utf-8")
        self.assertNotIn("## Fresh local verification", evidence)
        self.assertIn("## Historical local verification: v0.3.2-era", evidence)


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
        self.assertRegex(text, r"81/81")
        self.assertIn("359", text)  # current local suite after Pi destination PR C
        self.assertIn("d9152cd", text)  # archived PR #51 merge tip
        self.assertIn("340", text)  # archived PR #51 merge count
        self.assertRegex(text, r"(?i)pi.*destination.*(supported|pass)")
        self.assertRegex(text, r"(?i)(native|picker|host.?ui).*(not-run|not claimed)")
        self.assertTrue(
            "pi" in lowered
            and "source" in lowered
            and "supported" in lowered
        )
        # Published 0.3.4 claims the 81-cell matrix; keep Pi native UI unclaimed.
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r"0\.3\.4")
        self.assertRegex(readme, r"81/81")
        self.assertRegex(readme, r"(?i)pi native UI|Pi native UI")
        self.assertRegex(readme, r"not-run")


if __name__ == "__main__":
    unittest.main()
