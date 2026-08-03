"""Structural contract: Windows productization plan pack is complete and honest.

These tests assert the durable handoff docs for #125/#209 residuals exist and
that pre-final slices forbid early Policy B lift / fake dual-OS mutating claims.
They do not implement Windows install.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_DIR = REPO_ROOT / "docs" / "plans" / "windows-productization"

REQUIRED_FILES = (
    "INDEX.md",
    "00-baseline-and-global-rules.md",
    "03-rootlock-wire.md",
    "04-relative-mutations.md",
    "05-parent-chain-reparse.md",
    "06-adversarial-product-path.md",
    "07-policy-b-enablement.md",
    "209-platform-honesty.md",
)

# Pre-final slices (must keep Policy B fail-closed).
PRE_FINAL_SLICES = (
    "03-rootlock-wire.md",
    "04-relative-mutations.md",
    "05-parent-chain-reparse.md",
    "06-adversarial-product-path.md",
)

FAIL_CLOSED_MARKERS = (
    "MUST keep fail-closed",
    "MUST STILL fail closed",
    "fail closed",
    "Policy B",
    "E_INSTALL_UNSUPPORTED_PLATFORM",
    "require_mutating_install_platform",
)

WINDOWS_VERIFY_MARKERS = (
    "windows-latest",
    'os.name=="nt"',
    "os.name == \"nt\"",
    "assert os.name",
    "real Windows",
    "real `nt`",
    "real nt",
)


class WindowsProductizationPlanPackTests(unittest.TestCase):
    def test_required_plan_files_exist(self) -> None:
        self.assertTrue(PLAN_DIR.is_dir(), f"missing plan dir: {PLAN_DIR}")
        for name in REQUIRED_FILES:
            path = PLAN_DIR / name
            self.assertTrue(path.is_file(), f"missing plan file: {path}")
            self.assertGreater(path.stat().st_size, 200, f"plan file too small: {path}")

    def test_index_reflects_phase7_and_dual_os_v1_closed(self) -> None:
        """After #125 Phase 7, INDEX must not send agents back to Phase 4."""
        text = (PLAN_DIR / "INDEX.md").read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r"#125.*CLOSED|CLOSED.*#125", re.I | re.S))
        self.assertRegex(text, re.compile(r"Phase 7|Policy B lift", re.I))
        self.assertIn("smoke_windows_product_install.py", text)
        self.assertRegex(text, re.compile(r"306/306|Ubuntu only|Ubuntu-only", re.I))
        self.assertRegex(
            text,
            re.compile(r"#209.*CLOSED|V1 desktop dual-OS", re.I | re.S),
        )
        self.assertNotRegex(
            text,
            re.compile(r"1 \(start here\).*04-relative-mutations", re.I | re.S),
        )
        self.assertNotRegex(
            text,
            re.compile(
                r"Product `install`.*still raise.*E_INSTALL_UNSUPPORTED_PLATFORM",
                re.I | re.S,
            ),
        )

    def test_pre_final_slices_forbid_early_policy_b_lift(self) -> None:
        for name in PRE_FINAL_SLICES:
            text = (PLAN_DIR / name).read_text(encoding="utf-8")
            lowered = text.lower()
            # Must mention keep-fail-closed / must not lift product gate.
            has_fail_closed = any(m.lower() in lowered for m in FAIL_CLOSED_MARKERS)
            self.assertTrue(has_fail_closed, f"{name} missing Policy B fail-closed language")
            # Must not instruct closing #125 as done in pre-final.
            self.assertNotRegex(
                text,
                re.compile(r"close\s+#125\s+now|close\s+#125\s+immediately", re.I),
            )
            # Explicit must-not lift patterns
            self.assertRegex(
                text,
                re.compile(
                    r"do not.*(lift|remove|weaken).*(policy b|require_mutating)|"
                    r"must not.*(lift|remove).*(policy b|gate)|"
                    r"MUST STILL fail closed|"
                    r"MUST keep fail-closed",
                    re.I | re.S,
                ),
                f"{name} must forbid early Policy B lift",
            )

    def test_only_phase_7_may_enable_product_gate(self) -> None:
        text = (PLAN_DIR / "07-policy-b-enablement.md").read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r"ONLY slice allowed to lift|lift Policy B", re.I))
        self.assertIn("Phase 6", text)
        # Checklist gates
        self.assertIn("windows-latest", text)

    def test_slices_include_windows_runnable_verification(self) -> None:
        for name in REQUIRED_FILES:
            if name in {"INDEX.md", "00-baseline-and-global-rules.md", "209-platform-honesty.md"}:
                continue
            text = (PLAN_DIR / name).read_text(encoding="utf-8")
            self.assertTrue(
                any(m in text for m in WINDOWS_VERIFY_MARKERS),
                f"{name} missing Windows-runnable verification markers",
            )
            self.assertIn("pytest", text.lower())

    def test_index_forbids_fake_wsl_musl_bsd_verified(self) -> None:
        text = (PLAN_DIR / "INDEX.md").read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r"not-run", re.I))
        self.assertRegex(text, re.compile(r"WSL2|musl|FreeBSD|BSD", re.I))
        honesty = (PLAN_DIR / "209-platform-honesty.md").read_text(encoding="utf-8")
        self.assertRegex(honesty, re.compile(r"Never mark WSL2|not-run", re.I))
        self.assertNotRegex(
            honesty,
            re.compile(r"mark WSL2.*verified from ordinary Linux", re.I),
        )

    def test_anti_theater_no_ubuntu_as_windows(self) -> None:
        text = (PLAN_DIR / "00-baseline-and-global-rules.md").read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r"mock|Ubuntu|monkeypatch", re.I))
        self.assertRegex(text, re.compile(r"Anti-theater|anti-theater", re.I))

    def test_index_records_post_phase7_autoclose_policy(self) -> None:
        """Post-#125 INDEX: no early Phase-4 start; keep residual family honesty."""
        text = (PLAN_DIR / "INDEX.md").read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r"CLOSED", re.I))
        self.assertRegex(
            text,
            re.compile(r"Do not claim Windows installed-runner \*\*306/306\*\*|not\*\* 306/306", re.I),
        )
        self.assertRegex(text, re.compile(r"WSL2|musl|FreeBSD|BSD", re.I))

    def test_plans_readme_pointer_post_phase7(self) -> None:
        """Top-level plans/README must not send agents back to incomplete Phase 4."""
        path = REPO_ROOT / "plans" / "README.md"
        self.assertTrue(path.is_file(), f"missing {path}")
        text = path.read_text(encoding="utf-8")
        self.assertIn("windows-productization", text)
        self.assertRegex(text, re.compile(r"#125.*COMPLETE|Phases 1–7 COMPLETE", re.I | re.S))
        self.assertRegex(text, re.compile(r"#209.*CLOSED|dual-OS", re.I | re.S))
        self.assertNotRegex(
            text,
            re.compile(r"Next incomplete slice.*04-relative-mutations", re.I | re.S),
        )
        self.assertIn("smoke_windows_product_install.py", text)

    def test_status_residual_tracker_marks_125_closed(self) -> None:
        """STATUS residual row must record #125 CLOSED, not open Phase 4 work."""
        path = REPO_ROOT / "docs" / "STATUS.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn("#125 CLOSED", text)
        self.assertRegex(
            text,
            re.compile(r"Phase 7 \(landed\)|Policy B gate lifted", re.I | re.S),
        )
        self.assertNotRegex(
            text,
            re.compile(
                r"productization still OPEN\*\* \(RootLock wire \+ relative mutations",
                re.I,
            ),
        )
        self.assertNotRegex(
            text,
            re.compile(r"next incomplete\s*=\s*\*\*Phase 4\*\*|next incomplete.*Phase 4", re.I),
        )


if __name__ == "__main__":
    unittest.main()
