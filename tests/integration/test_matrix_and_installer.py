"""Thirty-six cell packaging and installer transaction tests."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError, SOURCE_KEYS
from portable_resume.install.catalog import HOST_KEYS, HOST_PROFILES, matrix_cells, resolve_skill_root
from portable_resume.install.render import frontmatter_keys, materialize_plan, render_skill_markdown
from portable_resume.install.transaction import (
    execute_install,
    load_manifest,
    matrix_report,
    plan_install,
    uninstall_claim,
    verify_root,
    _tree_snapshot,
)


class MatrixTests(unittest.TestCase):
    def test_thirty_six_cells_and_strict_frontmatter(self) -> None:
        cells = matrix_cells()
        self.assertEqual(len(cells), 36)
        self.assertEqual(len(set(cells)), 36)
        report = matrix_report()
        self.assertTrue(report["ok"])
        self.assertEqual(report["cell_count"], 36)
        self.assertEqual(report["expected"], 36)
        for host, source in cells:
            text = render_skill_markdown(host=host, source=source)
            self.assertEqual(frontmatter_keys(text), ["name", "description"])
            self.assertIn(f"name: resume-{source}", text)
            self.assertIn("portable-resume/request-v1", text)
            self.assertIn("run_reader.py", text)
            self.assertIn("--format handoff", text)
            self.assertIn(HOST_PROFILES[host].profile_id, text)
            body = materialize_plan(host)
            skill_md = body[f"resume-{source}/SKILL.md"].decode("utf-8")
            self.assertEqual(skill_md, text)
            runner = body[f"resume-{source}/scripts/run_reader.py"].decode("utf-8")
            self.assertIn(f'"{source}"', runner)
            self.assertIn(".portable-resume", runner)
            self.assertIn("portable_resume.reader", runner)

    def test_shared_runtime_present_for_every_host(self) -> None:
        for host in sorted(HOST_KEYS):
            files = materialize_plan(host)
            self.assertIn(".portable-resume/resources/handoff-policy.md", files)
            self.assertTrue(any(path.startswith(".portable-resume/runtime/portable_resume/") for path in files))
            self.assertIn(".portable-resume/runtime/portable_resume/reader.py", files)
            for source in sorted(SOURCE_KEYS):
                self.assertIn(f"resume-{source}/SKILL.md", files)
                self.assertIn(f"resume-{source}/scripts/run_reader.py", files)


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name) / "home"
        self.project = Path(self._tmpdir.name) / "project"
        self.home.mkdir()
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _root(self, host: str, scope: str = "project") -> str:
        return resolve_skill_root(
            host=host,
            scope=scope,
            project_dir=str(self.project),
            home_dir=str(self.home),
        )

    def test_dry_run_is_observationally_pure(self) -> None:
        root = self._root("claude")
        before = _tree_snapshot(root)
        plan = plan_install(host="claude", scope="project", root=root, dry_run=True)
        result = execute_install(plan)
        self.assertTrue(result["dry_run"])
        self.assertEqual(_tree_snapshot(root), before)
        self.assertGreater(len(plan.creates), 10)

    def test_install_verify_reinstall_uninstall(self) -> None:
        root = self._root("claude")
        plan = plan_install(host="claude", scope="project", root=root)
        result = execute_install(plan)
        self.assertTrue(result["ok"])
        self.assertFalse(result["dry_run"])
        verified = verify_root(root)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["generation"], 1)
        # idempotent reinstall
        plan2 = plan_install(host="claude", scope="project", root=root)
        result2 = execute_install(plan2)
        self.assertTrue(result2["ok"])
        self.assertEqual(result2["generation"], 2)
        # skills exist with safe modes
        skill = Path(root) / "resume-codex" / "SKILL.md"
        self.assertTrue(skill.is_file())
        runner = Path(root) / "resume-codex" / "scripts" / "run_reader.py"
        self.assertTrue(runner.is_file())
        self.assertTrue(os.stat(runner).st_mode & stat.S_IXUSR)
        # uninstall
        removed = uninstall_claim(host="claude", scope="project", root=root)
        self.assertTrue(removed["ok"])
        self.assertIn("resume-codex/SKILL.md", removed["removed_files"])
        self.assertFalse(skill.exists())
        self.assertIsNone(load_manifest(root))

    def test_non_owned_conflict_refuses_without_force(self) -> None:
        root = self._root("grok")
        target = Path(root) / "resume-grok" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("user owned skill\n", encoding="utf-8")
        with self.assertRaises(DiagnosticError) as ctx:
            plan_install(host="grok", scope="project", root=root)
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        self.assertEqual(target.read_text(encoding="utf-8"), "user owned skill\n")

    def test_force_with_backup_replaces_and_records_backup(self) -> None:
        root = self._root("cursor")
        target = Path(root) / "resume-cursor" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("user owned skill\n", encoding="utf-8")
        plan = plan_install(host="cursor", scope="project", root=root, force_with_backup=True)
        self.assertIn("resume-cursor/SKILL.md", plan.backups)
        result = execute_install(plan, force_with_backup=True)
        self.assertTrue(result["ok"])
        self.assertNotEqual(target.read_text(encoding="utf-8"), "user owned skill\n")
        backups = list((Path(root) / ".portable-resume" / "backups").rglob("SKILL.md"))
        self.assertTrue(backups)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "user owned skill\n")
        verify_root(root)

    def test_verify_detects_drift(self) -> None:
        root = self._root("opencode")
        plan = plan_install(host="opencode", scope="project", root=root)
        execute_install(plan)
        skill = Path(root) / "resume-opencode" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
        with self.assertRaises(DiagnosticError) as ctx:
            verify_root(root)
        self.assertEqual(ctx.exception.code, "E_VERIFY_MISMATCH")

    def test_all_hosts_project_install_matrix(self) -> None:
        # Use distinct explicit roots: codex and antigravity share the natural
        # project path `.agents/skills` but host-specific bodies are not byte-identical.
        for host in sorted(HOST_KEYS):
            root = str(self.project / "skills-roots" / host)
            plan = plan_install(host=host, scope="project", root=root)
            execute_install(plan)
            report = verify_root(root)
            self.assertTrue(report["ok"], host)
            for source in sorted(SOURCE_KEYS):
                path = Path(root) / f"resume-{source}" / "SKILL.md"
                self.assertTrue(path.is_file(), f"{host}/{source}")
                self.assertEqual(frontmatter_keys(path.read_text(encoding="utf-8")), ["name", "description"])

    def test_shared_natural_root_with_divergent_hosts_conflicts(self) -> None:
        root = self._root("codex")  # .agents/skills
        execute_install(plan_install(host="codex", scope="project", root=root))
        with self.assertRaises(DiagnosticError) as ctx:
            plan_install(host="antigravity", scope="project", root=root)
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")


if __name__ == "__main__":
    unittest.main()
