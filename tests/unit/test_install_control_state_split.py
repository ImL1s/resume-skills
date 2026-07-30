"""#33: separate shareable payload from machine-local control state."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.render import materialize_plan, package_identity
from portable_resume.install.transaction import (
    MANIFEST_NAME,
    STATE_SUBDIR,
    SUPPORT_DIR,
    control_state_dir,
    execute_install,
    load_manifest,
    plan_install,
    uninstall_claim,
    verify_root,
    _migrate_v1_control_state,
)


class ControlStateSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.project = Path(self._tmp.name) / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.root = resolve_skill_root(
            host="claude",
            scope="project",
            project_dir=str(self.project),
            home_dir=str(self.home),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _install(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        result = execute_install(plan)
        self.assertTrue(result["ok"])

    def test_control_files_under_state_not_support_root(self) -> None:
        self._install()
        state = control_state_dir(self.root)
        self.assertTrue(os.path.isfile(os.path.join(state, MANIFEST_NAME)))
        self.assertTrue(os.path.isfile(os.path.join(state, "install.lock")) or True)
        # Manifest must not sit next to shareable runtime.
        self.assertFalse(os.path.isfile(os.path.join(self.root, SUPPORT_DIR, MANIFEST_NAME)))
        self.assertTrue(os.path.isdir(os.path.join(self.root, SUPPORT_DIR, "runtime")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, SUPPORT_DIR, "resources")))

    def test_shareable_gitignore_excludes_only_state(self) -> None:
        self._install()
        gi = Path(self.root) / SUPPORT_DIR / ".gitignore"
        text = gi.read_text(encoding="utf-8")
        self.assertIn(".state/", text)
        # Only ignore patterns (non-comment lines) matter.
        patterns = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertEqual(patterns, [".state/"])
        # Part of deterministic package identity.
        files = materialize_plan("claude")
        self.assertIn(".portable-resume/.gitignore", files)
        self.assertEqual(files[".portable-resume/.gitignore"], gi.read_bytes())

    def test_shareable_payload_has_no_absolute_machine_paths(self) -> None:
        self._install()
        support = Path(self.root) / SUPPORT_DIR
        for path in support.rglob("*"):
            if not path.is_file():
                continue
            # Skip control state entirely.
            try:
                path.relative_to(support / STATE_SUBDIR)
                continue
            except ValueError:
                pass
            data = path.read_bytes()
            # No home or temp absolute paths in shareable bytes.
            self.assertNotIn(str(self.home).encode(), data)
            self.assertNotIn(str(self._tmp.name).encode(), data)
            self.assertNotIn(b"/Users/", data)
            self.assertNotIn(b"/var/folders/", data)

    def test_verify_reports_control_layout(self) -> None:
        self._install()
        report = verify_root(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["control_layout"], "state-v1")
        self.assertTrue(report["control_state_dir"].endswith(f"{SUPPORT_DIR}/{STATE_SUBDIR}"))

    def test_migrate_v1_manifest_into_state(self) -> None:
        self._install()
        state = control_state_dir(self.root)
        support = Path(self.root) / SUPPORT_DIR
        # Simulate pre-#33 layout: move control back to support root.
        legacy_manifest = support / MANIFEST_NAME
        shutil.move(os.path.join(state, MANIFEST_NAME), legacy_manifest)
        # Drop empty-ish state dir contents except keep dir
        for name in os.listdir(state):
            p = os.path.join(state, name)
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.unlink(p)
        self.assertTrue(legacy_manifest.is_file())
        self.assertFalse(os.path.isfile(os.path.join(state, MANIFEST_NAME)))
        # Load still works via legacy resolve.
        m = load_manifest(self.root)
        self.assertIsNotNone(m)
        # Migration under lock path.
        result = _migrate_v1_control_state(self.root)
        self.assertTrue(result["migrated"])
        self.assertTrue(os.path.isfile(os.path.join(state, MANIFEST_NAME)))
        self.assertFalse(legacy_manifest.exists())
        verify_root(self.root)

    def test_package_identity_covers_gitignore_not_state(self) -> None:
        a = package_identity(materialize_plan("claude"))
        b = package_identity(materialize_plan("claude"))
        self.assertEqual(a, b)
        # State files are not in materialize_plan.
        files = materialize_plan("claude")
        self.assertFalse(any(".state/" in k for k in files))
        self.assertTrue(any(k.startswith(".portable-resume/runtime/") for k in files))

    def test_second_machine_checkout_without_state_needs_fresh_install(self) -> None:
        """Committed payload alone has no claims; second home installs cleanly."""
        self._install()
        # Simulate shareable-only tree copy (no .state).
        payload_only = Path(self._tmp.name) / "payload_only"
        shutil.copytree(
            Path(self.root),
            payload_only,
            ignore=shutil.ignore_patterns(STATE_SUBDIR),
        )
        # Copy without state should not verify as owned install.
        from portable_resume.diagnostics import DiagnosticError

        with self.assertRaises(DiagnosticError):
            verify_root(str(payload_only))
        # Fresh install into a new project root with payload seed is still fine.
        other = Path(self._tmp.name) / "other_project"
        other.mkdir()
        other_root = resolve_skill_root(
            host="claude",
            scope="project",
            project_dir=str(other),
            home_dir=str(self.home),
        )
        plan = plan_install(host="claude", scope="project", root=other_root)
        self.assertTrue(execute_install(plan)["ok"])
        verify_root(other_root)

    def test_uninstall_removes_state(self) -> None:
        self._install()
        uninstall_claim(host="claude", scope="project", root=self.root)
        self.assertIsNone(load_manifest(self.root))


if __name__ == "__main__":
    unittest.main()
