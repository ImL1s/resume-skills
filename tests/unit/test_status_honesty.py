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

    def test_status_separates_closed_platform_slices_from_open_residuals(self) -> None:
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        tracks = [
            line
            for line in text.splitlines()
            if line.startswith("**Cross-platform track")
        ]
        self.assertEqual(len(tracks), 1)
        track = tracks[0]
        self.assertIn("closed read-only/CI slices #205–#208", track)
        self.assertIn("#125 CLOSED", track)
        self.assertIn("949180a", track)
        self.assertIn("30800595796", track)
        # V1 desktop dual-OS (win+mac) closed; residual families stay not-run.
        self.assertIn("#209 V1 desktop dual-OS", track)
        self.assertIn("CLOSED", track)
        self.assertIn("WSL2", track)
        self.assertIn("not-run", track)
        self.assertNotIn("open residual #209", track)
        self.assertNotIn("#209 umbrella remains OPEN", track)
        # After V1 close, no platform-table / residual cell may still say "#209 OPEN".
        self.assertNotIn("#209 OPEN", text)
        self.assertNotIn("#209 remains OPEN", text)
        self.assertNotIn("#205–#209", track)

    def test_windows_installed_runner_not_claimed_as_full_matrix(self) -> None:
        """Windows hard gate is focused product install smoke — never 306/306 on nt."""
        status = Path("docs/STATUS.md").read_text(encoding="utf-8")
        host = Path("docs/host-support.md").read_text(encoding="utf-8")
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        smoke = Path("scripts/smoke_windows_product_install.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("smoke_windows_product_install.py", status)
        self.assertIn("Ubuntu-only", status)
        self.assertIn("smoke_windows_product_install.py", ci)
        self.assertIn("smoke_installed_matrix.py", ci)
        # CI must still hard-gate the focused Windows smoke script.
        self.assertRegex(ci, r"smoke_windows_product_install\.py")
        self.assertIn("full_matrix", smoke)
        self.assertIn("False", smoke)
        # Explicit non-claim of Windows 306/306.
        self.assertRegex(
            host,
            r"(?i)not\*\* claimed 306/306 on Windows|not claimed 306/306 on Windows",
        )
        self.assertRegex(
            status,
            r"(?i)never claim Windows 306/306|not.*306/306 on Windows|focused product-install smoke",
        )
        # Residual families remain not-run in STATUS platform table.
        for family in ("WSL2", "musl-only", "FreeBSD"):
            self.assertIn(family, status)
        self.assertIn("not-run", status)

    def test_smoke_windows_product_install_script_is_partial_gate(self) -> None:
        """Drive the shipped smoke module contract (hosts + honesty report fields)."""
        import importlib.util
        import sys
        from pathlib import Path as P

        path = P("scripts/smoke_windows_product_install.py").resolve()
        spec = importlib.util.spec_from_file_location(
            "smoke_windows_product_install", path
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        hosts = list(mod._SMOKE_HOSTS)
        self.assertEqual(hosts, ["claude", "cursor", "codex"])
        # Non-nt hosts skip with success (no false 306 claim).
        if __import__("os").name != "nt":
            code = mod.main()
            self.assertEqual(code, 0)

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
        """Host UI evidence stays scoped: v0.3.2-era pass only; not-run through current published tip."""
        readme_opening = "\n".join(
            Path("README.md").read_text(encoding="utf-8").splitlines()[:30]
        )
        self.assertIn("v0.3.2", readme_opening)
        compact_readme = " ".join(readme_opening.replace("**", "").split())
        # Current honesty boundary: fresh through last published tip remains not-run.
        self.assertRegex(compact_readme, r"(?i)fresh through 0\.4\.2.*not-run")

        host = Path("docs/host-support.md").read_text(encoding="utf-8")
        for label in (
            "Native local plugin/extension installs",
            "Public marketplace installation",
            "Visual marketplace picker",
        ):
            row = next(line for line in host.splitlines() if f"| {label} |" in line)
            self.assertIn("v0.3.2", row, label)
        marketplace = next(
            line
            for line in host.splitlines()
            if "| Public marketplace installation |" in line
        )
        # Host-support table may still say 0.4.1 or current tip; require not-run honesty.
        self.assertRegex(marketplace, r"0\.4\.[12]")
        self.assertIn("not-run", marketplace)
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
            self.assertIn("0.4.1", row)
            self.assertIn("not-run", row)

        host_ui = Path("docs/host-ui-smoke.md").read_text(encoding="utf-8")
        host_ui_headless = next(
            line
            for line in host_ui.splitlines()
            if "| Host-native headless activation |" in line
        )
        self.assertIn("v0.3.2", host_ui_headless)
        self.assertIn("0.4.1", host_ui_headless)
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
        self.assertRegex(
            text,
            r"\*\*\d+ pass in current [^*]+ CI(?: \(PR #[0-9]+\))?\*\*",
        )
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


    def test_platform_table_marks_209_v1_closed(self) -> None:
        """Windows native mutating cell must not contradict closed #209 V1."""
        text = Path("docs/STATUS.md").read_text(encoding="utf-8")
        win_rows = [
            line
            for line in text.splitlines()
            if line.startswith("| Windows native")
        ]
        self.assertEqual(len(win_rows), 1, msg=win_rows)
        row = win_rows[0]
        self.assertIn("#125 CLOSED", row)
        self.assertIn("#209 V1 desktop dual-OS CLOSED", row)
        self.assertNotIn("#209 OPEN", row)
