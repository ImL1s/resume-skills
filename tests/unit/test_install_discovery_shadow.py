"""#34: discovery roots + duplicate/shadow Skill scan."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.cli import run as install_cli_run
from portable_resume.install.discovery import (
    POLICY_ALLOW,
    POLICY_BLOCK,
    POLICY_WARN,
    STATUS_DUP_DIFFERENT,
    STATUS_DUP_FOREIGN,
    STATUS_DUP_IDENTICAL,
    STATUS_HIGHER_SHADOW,
    STATUS_PRECEDENCE_UNKNOWN,
    STATUS_SAME_PHYSICAL,
    STATUS_UNSAFE,
    discovery_roots_for_host,
    require_no_blocking_shadow,
    scan_skill_duplicates,
)
from portable_resume.install.transaction import execute_install, plan_install, verify_root


def _write_skill(root: Path, skill: str, body: bytes = b"---\nname: x\n---\nold\n") -> None:
    skill_dir = root / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_bytes(body)
    scripts = skill_dir / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "run_reader.py").write_bytes(b"# foreign runner\n")


class DiscoveryPolicyTests(unittest.TestCase):
    def test_every_host_has_primary_project_and_user_roots(self) -> None:
        from portable_resume.install.catalog import HOST_KEYS

        for host in HOST_KEYS:
            roots = discovery_roots_for_host(host)
            ids = {r.root_id for r in roots}
            self.assertIn(f"{host}.project.primary", ids)
            self.assertIn(f"{host}.user.primary", ids)
            project = next(r for r in roots if r.root_id.endswith(".project.primary"))
            user = next(r for r in roots if r.root_id.endswith(".user.primary"))
            self.assertEqual(project.precedence, 5)
            self.assertEqual(user.precedence, 10)

    def test_cursor_includes_agents_and_compat_roots(self) -> None:
        roots = discovery_roots_for_host("cursor")
        rels = {(r.base, r.rel) for r in roots}
        self.assertIn(("project", ".cursor/skills"), rels)
        self.assertIn(("project", ".agents/skills"), rels)
        self.assertIn(("project", ".claude/skills"), rels)
        self.assertIn(("home", ".codex/skills"), rels)


class DuplicateScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.project = Path(self._tmp.name) / "project"
        self.home.mkdir()
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unique_when_only_selected_empty(self) -> None:
        selected = self.project / ".cursor" / "skills"
        selected.mkdir(parents=True)
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=("resume-codex",),
        )
        self.assertEqual(report["aggregate_status"], "unique")
        self.assertEqual(report["aggregate_policy"], POLICY_ALLOW)
        self.assertTrue(report["ok"])

    def test_equal_precedence_divergent_agents_warns(self) -> None:
        selected = self.project / ".cursor" / "skills"
        agents = self.project / ".agents" / "skills"
        selected.mkdir(parents=True)
        _write_skill(agents, "resume-codex", b"---\nname: resume-codex\n---\nOLD AGENTS\n")
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=("resume-codex",),
        )
        self.assertEqual(report["aggregate_policy"], POLICY_WARN)
        statuses = {f["status"] for f in report["findings"] if not f.get("is_selected")}
        self.assertTrue(
            statuses & {STATUS_DUP_FOREIGN, STATUS_DUP_DIFFERENT, STATUS_PRECEDENCE_UNKNOWN}
        )

    def test_higher_precedence_project_blocks_global_install(self) -> None:
        """Divergent project copy blocks user-global install (project outranks user)."""
        project_root = self.project / ".cursor" / "skills"
        global_root = self.home / ".cursor" / "skills"
        global_root.mkdir(parents=True)
        _write_skill(project_root, "resume-codex", b"---\nname: resume-codex\n---\nSTALE PROJECT\n")
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(global_root),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="global",
            skill_names=("resume-codex",),
        )
        self.assertEqual(report["aggregate_policy"], POLICY_BLOCK)
        self.assertEqual(report["aggregate_status"], STATUS_HIGHER_SHADOW)
        self.assertFalse(report["ok"])
        with self.assertRaises(DiagnosticError) as ctx:
            require_no_blocking_shadow(
                host="cursor",
                selected_root=str(global_root),
                project_dir=str(self.project),
                home_dir=str(self.home),
                selected_scope="global",
            )
        self.assertEqual(ctx.exception.code, "E_INSTALL_SHADOW")

    def test_identical_full_package_allows(self) -> None:
        from portable_resume.install.render import materialize_plan

        selected = self.project / ".cursor" / "skills"
        agents = self.project / ".agents" / "skills"
        selected.mkdir(parents=True)
        files = materialize_plan("cursor")
        for rel, data in files.items():
            dest = agents / Path(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        skill = "resume-codex"
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=(skill,),
        )
        non_selected = [f for f in report["findings"] if not f.get("is_selected")]
        self.assertTrue(non_selected)
        self.assertTrue(all(f["status"] == STATUS_DUP_IDENTICAL for f in non_selected))
        self.assertEqual(report["aggregate_policy"], POLICY_ALLOW)

    def test_skill_pair_only_not_identical(self) -> None:
        """SKILL.md + runner match without runtime must not count as identical."""
        from portable_resume.install.render import materialize_plan

        selected = self.project / ".cursor" / "skills"
        agents = self.project / ".agents" / "skills"
        selected.mkdir(parents=True)
        files = materialize_plan("cursor")
        skill = "resume-codex"
        skill_dir = agents / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_bytes(files[f"{skill}/SKILL.md"])
        (skill_dir / "scripts").mkdir()
        (skill_dir / "scripts" / "run_reader.py").write_bytes(
            files[f"{skill}/scripts/run_reader.py"]
        )
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=(skill,),
        )
        non_selected = [f for f in report["findings"] if not f.get("is_selected")]
        self.assertTrue(non_selected)
        self.assertFalse(any(f["status"] == STATUS_DUP_IDENTICAL for f in non_selected))
        # Equal-tier divergent → warn (not allow-identical).
        self.assertEqual(report["aggregate_policy"], POLICY_WARN)

    def test_unsafe_higher_precedence_blocks(self) -> None:
        """Symlinked skill at project root blocks global install."""
        project_root = self.project / ".cursor" / "skills"
        global_root = self.home / ".cursor" / "skills"
        global_root.mkdir(parents=True)
        project_root.mkdir(parents=True)
        real = self.project / "elsewhere" / "resume-codex"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_bytes(b"x")
        os.symlink(real, project_root / "resume-codex")
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(global_root),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="global",
            skill_names=("resume-codex",),
        )
        self.assertEqual(report["aggregate_policy"], POLICY_BLOCK)
        self.assertEqual(report["aggregate_status"], STATUS_HIGHER_SHADOW)

    def test_same_physical_shared_root_not_duplicate(self) -> None:
        # Codex + Antigravity share project .agents/skills — same path is not shadow.
        shared = self.project / ".agents" / "skills"
        shared.mkdir(parents=True)
        _write_skill(shared, "resume-codex")
        report = scan_skill_duplicates(
            host="codex",
            selected_root=str(shared),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=("resume-codex",),
        )
        # Selected findings only / unique aggregate.
        self.assertIn(report["aggregate_status"], ("unique", STATUS_SAME_PHYSICAL, "selected_present"))
        self.assertEqual(report["aggregate_policy"], POLICY_ALLOW)
        self.assertEqual(report["blocking_count"], 0)

    def test_symlink_skill_dir_reported_unsafe(self) -> None:
        selected = self.project / ".cursor" / "skills"
        agents = self.project / ".agents" / "skills"
        selected.mkdir(parents=True)
        agents.mkdir(parents=True)
        real = self.project / "elsewhere" / "resume-codex"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_bytes(b"x")
        os.symlink(real, agents / "resume-codex")
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=("resume-codex",),
        )
        unsafe = [f for f in report["findings"] if f["status"] == STATUS_UNSAFE]
        self.assertTrue(unsafe)

    def test_scan_is_read_only(self) -> None:
        selected = self.project / ".claude" / "skills"
        selected.mkdir(parents=True)
        alt = self.home / ".claude" / "skills"
        _write_skill(alt, "resume-claude")
        before = list(self.home.rglob("*"))
        scan_skill_duplicates(
            host="claude",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=("resume-claude",),
        )
        after = list(self.home.rglob("*"))
        self.assertEqual(sorted(p.as_posix() for p in before), sorted(p.as_posix() for p in after))

    def test_unknown_precedence_compat_warns(self) -> None:
        selected = self.project / ".cursor" / "skills"
        compat = self.project / ".claude" / "skills"
        selected.mkdir(parents=True)
        _write_skill(compat, "resume-codex")
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=("resume-codex",),
        )
        self.assertEqual(report["aggregate_policy"], POLICY_WARN)
        self.assertEqual(report["aggregate_status"], STATUS_PRECEDENCE_UNKNOWN)


class CliAuditAndInstallGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.project = Path(self._tmp.name) / "project"
        self.home.mkdir()
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_audit_host_json(self) -> None:
        selected = self.project / ".cursor" / "skills"
        selected.mkdir(parents=True)
        import io
        import sys

        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            code = install_cli_run(
                [
                    "audit-host",
                    "--host",
                    "cursor",
                    "--scope",
                    "project",
                    "--project",
                    str(self.project),
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )
        finally:
            sys.stdout = old
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["schema_version"], "portable-resume/discovery-scan-v1")
        self.assertEqual(data["host"], "cursor")
        self.assertIn("discovery_policy", data)

    def test_install_blocked_by_shadow(self) -> None:
        project_root = self.project / ".cursor" / "skills"
        _write_skill(project_root, "resume-codex", b"STALE\n")
        import io
        import sys

        err = io.StringIO()
        old_err = sys.stderr
        sys.stderr = err
        try:
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "cursor",
                    "--scope",
                    "global",
                    "--project",
                    str(self.project),
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )
        finally:
            sys.stderr = old_err
        self.assertEqual(code, 6)
        self.assertIn("E_INSTALL_SHADOW", err.getvalue())

    def test_install_succeeds_without_shadow(self) -> None:
        plan = plan_install(
            host="cursor",
            scope="project",
            root=str(self.project / ".cursor" / "skills"),
            dry_run=False,
        )
        # Use CLI path for discovery gate.
        import io
        import sys

        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "cursor",
                    "--scope",
                    "project",
                    "--project",
                    str(self.project),
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )
        finally:
            sys.stdout = old
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertTrue(data.get("ok"))
        self.assertIn("discovery", data)
        self.assertEqual(data["discovery"]["aggregate_policy"], POLICY_ALLOW)
        verify_root(str(self.project / ".cursor" / "skills"))


if __name__ == "__main__":
    unittest.main()
