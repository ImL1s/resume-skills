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

    def test_index_next_incomplete_is_phase4_not_phase3(self) -> None:
        """After Phase 3 landed on main, handoff must start low models at Phase 4."""
        text = (PLAN_DIR / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("03-rootlock-wire.md", text)
        self.assertIn("04-relative-mutations.md", text)
        # Phase 3 is baseline landed, not the next start-here work
        self.assertRegex(
            text,
            re.compile(r"Phase 3.*LANDED|LANDED on main", re.I | re.S),
        )
        self.assertRegex(
            text,
            re.compile(r"1 \(start here\).*04-relative-mutations", re.I | re.S),
        )
        self.assertRegex(
            text,
            re.compile(
                r"First PR for a low model on Windows.*04-relative-mutations\.md",
                re.I | re.S,
            ),
        )
        # Incomplete slices still before enablement in document order
        i_phase4 = text.find("04-relative-mutations")
        i_enable = text.find("07-policy-b-enablement")
        self.assertGreater(i_phase4, 0)
        self.assertGreater(i_enable, i_phase4)

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

    def test_index_forbids_github_autoclose_before_phase7(self) -> None:
        text = (PLAN_DIR / "INDEX.md").read_text(encoding="utf-8")
        self.assertRegex(
            text,
            re.compile(r"MUST NOT use:.*Closes|auto-close|GitHub auto-close", re.I | re.S),
        )
        self.assertRegex(
            text,
            re.compile(r"Only Phase 7.*Closes #125|Closes #125", re.I | re.S),
        )
        # Pre-final guidance must keep #125 open language in index global rules
        self.assertRegex(
            text,
            re.compile(r"Do not\*\* close \*\*#125|do not\*\* close \*\*#125|Do not.*close \*\*#125", re.I),
        )

    def test_plans_readme_pointer_starts_at_phase4(self) -> None:
        """Top-level plans/README must not send low models back to Phase 3 RootLock."""
        path = REPO_ROOT / "plans" / "README.md"
        self.assertTrue(path.is_file(), f"missing {path}")
        text = path.read_text(encoding="utf-8")
        self.assertIn("windows-productization", text)
        self.assertIn("04-relative-mutations.md", text)
        self.assertRegex(
            text,
            re.compile(
                r"Phase 4|04-relative-mutations|start here|Next incomplete",
                re.I,
            ),
        )
        # Must not present Phase 3 as the first remaining order without landed note
        self.assertNotRegex(
            text,
            re.compile(
                r"Order:\s*Phase 3 RootLock\s*→\s*4 relative",
                re.I,
            ),
            "plans/README still lists Phase 3 as first remaining work",
        )
        self.assertRegex(
            text,
            re.compile(r"1–3 landed|Phase 3.*landed|Do not re-implement Phase 3", re.I),
        )

    def test_status_residual_tracker_does_not_list_rootlock_wire_as_remaining(self) -> None:
        """STATUS residual row must not advertise RootLock wire as still-to-do foundation."""
        path = REPO_ROOT / "docs" / "STATUS.md"
        text = path.read_text(encoding="utf-8")
        # Locate the #125 residual tracker cell content
        self.assertIn("#125", text)
        # Must acknowledge Phase 3 / RootLock landed and point next at Phase 4
        self.assertRegex(
            text,
            re.compile(
                r"Phase 1–3 \(landed\)|RootLock.*wire.*landed|RootLock wire is not remaining",
                re.I | re.S,
            ),
        )
        self.assertRegex(
            text,
            re.compile(r"next incomplete.*Phase 4|Phase 4.*relative mutations", re.I | re.S),
        )
        # Forbidden stale phrasing that lists RootLock wire as open remaining work
        self.assertNotRegex(
            text,
            re.compile(
                r"productization still OPEN\*\* \(RootLock wire \+ relative mutations",
                re.I,
            ),
        )


if __name__ == "__main__":
    unittest.main()
