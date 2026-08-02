from __future__ import annotations

import unittest
from pathlib import Path


class StatusHonestyTests(unittest.TestCase):
    def test_status_does_not_claim_next_wave_supported(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        # Product-path agents may claim filesystem support; native UI must stay not-run.
        self.assertNotRegex(
            text,
            r"(?i)pi[^.\n]{0,40}(picker|native activation).{0,20}pass",
        )
        self.assertNotRegex(
            text,
            r"(?i)openclaw[^.\n]{0,60}(picker|native).{0,20}pass",
        )
        self.assertNotRegex(
            text,
            r"(?i)goose[^.\n]{0,60}(picker|native).{0,20}pass",
        )
        self.assertNotRegex(
            text,
            r"(?i)crush[^.\n]{0,60}(picker|native).{0,20}pass",
        )
        self.assertNotRegex(
            text,
            r"(?i)(cline|openhands|hermes|copilot|gemini|kilo)[^.\n]{0,60}(picker|native).{0,20}pass",
        )

    def test_status_describes_registry_derived_matrix(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertTrue(
            "derived from registries" in lowered or "registry-derived" in lowered
        )
        self.assertRegex(
            text,
            r"13\s*[×x]\s*13|13×13=169|169/169|12\s*[×x]\s*12|12×12=144|144/144|11\s*[×x]\s*11|11×11=121|121/121|10\s*[×x]\s*10|100/100|9\s*[×x]\s*9\s*=\s*81|9×9=81",
        )

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
            r"13\s*[×x]\s*13|12\s*[×x]\s*12|11\s*[×x]\s*11|10\s*[×x]\s*10|9\s*[×x]\s*9|enabled_source|enabled_destination|registry",
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
        headless_rows = [
            line
            for line in status.splitlines()
            if line.startswith("| Host-native headless")
        ]
        self.assertEqual(len(headless_rows), 2)
        for row in headless_rows:
            self.assertIn("v0.3.2", row)
            self.assertIn("v0.3.4", row)
            self.assertIn("not-run", row)

        host_ui = Path("docs/host-ui-smoke.md").read_text(encoding="utf-8")
        host_ui_headless = next(
            line
            for line in host_ui.splitlines()
            if "| Host-native headless activation |" in line
        )
        self.assertIn("v0.3.2", host_ui_headless)
        self.assertIn("v0.3.4", host_ui_headless)
        self.assertIn("not-run", host_ui_headless)

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
        # Prefer immutable CI evidence for the current suite. Historical local
        # snapshots may remain, but they must be explicitly labeled historical.
        self.assertRegex(text, r"\*\*\d+ pass in current [^*]+ CI\*\*")
        self.assertRegex(
            text,
            r"(?i)prior \*\*\d+ local\*\* snapshot[^.]{0,160}historical",
        )
        # Current main is registry-derived; published 0.3.4 historical 81 remains noted.
        self.assertRegex(text, r"169/169|144/144|121/121|100/100|81/81")
        self.assertIn("359", text)  # archived local suite after Pi destination PR C
        self.assertIn("d9152cd", text)  # archived PR #51 merge tip
        self.assertIn("340", text)  # archived PR #51 merge count
        self.assertRegex(text, r"(?i)pi.*destination.*(supported|pass)")
        self.assertRegex(text, r"(?i)(native|picker|host.?ui).*(not-run|not claimed)")
        self.assertTrue(
            "pi" in lowered
            and "source" in lowered
            and "supported" in lowered
        )
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r"0\.3\.4")
        self.assertRegex(readme, r"169/169|144/144|121/121|100/100|81/81|historical 81")
        self.assertRegex(readme, r"(?i)pi.*native|Pi/OpenClaw|goose|crush|cline|openhands|hermes|github-copilot|copilot|gemini|kilo|not-run")
        self.assertRegex(readme, r"not-run")


if __name__ == "__main__":
    unittest.main()
