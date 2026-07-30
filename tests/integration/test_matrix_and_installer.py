"""Destination-host × source packaging and installer transaction tests."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError, SOURCE_KEYS
import portable_resume.install.cli as install_cli_module
from portable_resume.install.cli import run as install_cli_run
from portable_resume.install.catalog import HOST_KEYS, HOST_PROFILES, matrix_cells, resolve_skill_root
from portable_resume.install.manifest import claim_key
from portable_resume.install.render import (
    frontmatter_keys,
    materialize_plan,
    package_identity,
    render_skill_markdown,
)
import portable_resume.install.transaction as transaction_module
from portable_resume.install.transaction import (
    execute_install,
    load_manifest,
    matrix_report,
    plan_install,
    uninstall_claim,
    verify_root,
    _tree_snapshot,
)
from portable_resume.registry import matrix_dimensions


class MatrixTests(unittest.TestCase):
    def test_all_hosts_share_one_package_identity(self) -> None:
        identities = {package_identity(materialize_plan(host)) for host in HOST_KEYS}
        self.assertEqual(len(identities), 1)

    def test_all_cells_and_strict_frontmatter(self) -> None:
        cells = matrix_cells()
        expected = matrix_dimensions()["cells"]
        self.assertEqual(len(cells), expected)
        self.assertEqual(len(set(cells)), expected)
        report = matrix_report()
        self.assertTrue(report["ok"])
        self.assertEqual(report["cell_count"], expected)
        self.assertEqual(report["expected"], expected)
        for host, source in cells:
            text = render_skill_markdown(host=host, source=source)
            self.assertEqual(frontmatter_keys(text), ["name", "description"])
            self.assertIn(f"name: resume-{source}", text)
            self.assertIn("portable-resume/request-v1", text)
            self.assertIn("run_reader.py", text)
            self.assertIn("--format handoff", text)
            self.assertNotIn("Context7", text)
            self.assertNotIn("web search", text.lower())
            self.assertNotIn("URL-fetch", text)
            self.assertIn("owned reader must remain offline", text)
            # #25: host profile IDs stay in the catalog, not the portable Skill body.
            self.assertNotIn(HOST_PROFILES[host].profile_id, text)
            self.assertIn("host-neutral", text)
            body = materialize_plan(host)
            skill_md = body[f"resume-{source}/SKILL.md"].decode("utf-8")
            self.assertEqual(skill_md, text)
            runner = body[f"resume-{source}/scripts/run_reader.py"].decode("utf-8")
            self.assertIn(f'"{source}"', runner)
            self.assertIn(".portable-resume", runner)
            self.assertIn("portable_resume.reader", runner)
            self.assertIn("os.path.realpath(__file__)", runner)
            self.assertIn("_force_expected_source", runner)
            self.assertIn("owned skill package root", text)
            self.assertNotIn("<this-skill>", text)
            self.assertNotIn("$OWNED_SKILL_DIR", text)

    def test_shared_runtime_present_for_every_host(self) -> None:
        for host in sorted(HOST_KEYS):
            files = materialize_plan(host)
            self.assertIn(".portable-resume/resources/handoff-policy.md", files)
            self.assertTrue(any(path.startswith(".portable-resume/runtime/portable_resume/") for path in files))
            self.assertIn(".portable-resume/runtime/portable_resume/reader.py", files)
            # Plan 025: installer package must not ship into skill runtime trees.
            install_runtime = [
                path
                for path in files
                if path.startswith(".portable-resume/runtime/portable_resume/install/")
            ]
            self.assertEqual(install_runtime, [])
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

    @staticmethod
    def _file_bytes(root: Path) -> dict[str, bytes]:
        if not root.exists():
            return {}
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

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

    def test_pi_install_verify_uninstall(self) -> None:
        root = self._root("pi")
        plan = plan_install(host="pi", scope="project", root=root)
        result = execute_install(plan)
        self.assertTrue(result["ok"])
        verified = verify_root(root)
        self.assertTrue(verified["ok"])
        skill = Path(root) / "resume-claude" / "SKILL.md"
        self.assertTrue(skill.is_file())
        removed = uninstall_claim(host="pi", scope="project", root=root)
        self.assertTrue(removed["ok"])
        self.assertFalse(skill.exists())

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

    def test_force_backup_ids_are_unique_within_one_second(self) -> None:
        root = self.project / "backup-root"
        results = []
        with mock.patch.object(transaction_module.time, "strftime", return_value="20260724T010203Z"):
            for index in range(2):
                conflict = root / "resume-cursor" / "SKILL.md"
                conflict.parent.mkdir(parents=True, exist_ok=True)
                conflict.write_text(f"foreign-{index}\n", encoding="utf-8")
                plan = plan_install(
                    host="cursor",
                    scope="project",
                    root=str(root),
                    force_with_backup=True,
                )
                results.append(execute_install(plan, force_with_backup=True))
                uninstall_claim(host="cursor", scope="project", root=str(root))

        backup_roots = [Path(result["backup_root"]) for result in results]
        self.assertNotEqual(backup_roots[0].name, backup_roots[1].name)
        self.assertTrue(all(path.is_dir() for path in backup_roots))
        for index, backup_root in enumerate(backup_roots):
            backup = backup_root / "resume-cursor" / "SKILL.md"
            self.assertEqual(backup.read_text(encoding="utf-8"), f"foreign-{index}\n")

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
        # Host-neutral Skill payloads (#25): natural shared roots (e.g. codex +
        # antigravity `.agents/skills`) are byte-identical. Distinct roots still
        # exercise every host profile's install path.
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

    def test_codex_antigravity_share_natural_project_root(self) -> None:
        """#25: compatible hosts claim one physical `.agents/skills` tree."""
        root = self._root("codex")  # .agents/skills
        execute_install(plan_install(host="codex", scope="project", root=root))
        execute_install(plan_install(host="antigravity", scope="project", root=root))
        manifest = load_manifest(root)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        claims = list(manifest.claims)
        self.assertEqual(len(claims), 2)
        skill = Path(root) / "resume-codex" / "SKILL.md"
        body = skill.read_text(encoding="utf-8")
        self.assertNotIn("Host activation (codex-v1)", body)
        self.assertNotIn("Host activation (antigravity-v1)", body)
        self.assertIn("host-neutral", body)
        verify_root(root, claim=claim_key(host="codex", scope="project", root=root))
        verify_root(root, claim=claim_key(host="antigravity", scope="project", root=root))
        un = uninstall_claim(host="codex", scope="project", root=root)
        self.assertTrue(un["ok"])
        # Shared files remain for the surviving claim.
        self.assertTrue(skill.is_file())
        verify_root(root, claim=claim_key(host="antigravity", scope="project", root=root))

    def test_all_host_install_shared_realpath_with_identical_payloads(self) -> None:
        """Symlinked global roots succeed when payload bytes match (#25)."""
        shared = self.home / ".claude" / "skills"
        shared.mkdir(parents=True)
        antigravity_parent = self.home / ".gemini" / "config"
        antigravity_parent.mkdir(parents=True)
        os.symlink(shared, antigravity_parent / "skills")

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "all",
                    "--scope",
                    "global",
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertTrue((shared / ".portable-resume" / "manifest.json").is_file())
        self.assertTrue(any(shared.glob("resume-*")))
        verify_root(str(shared))

    def test_quick_install_defaults_to_safe_global_roots(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = install_cli_run(
                [
                    "quick-install",
                    "qwen",
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["plan"]["host"], "qwen")
        self.assertEqual(payload["plan"]["scope"], "global")
        root = Path(self._root("qwen", scope="global"))
        self.assertTrue((root / "resume-qwen" / "SKILL.md").is_file())
        verify_root(
            str(root),
            claim=claim_key(host="qwen", scope="global", root=str(root)),
        )

    def test_all_host_install_preflights_later_root_conflict_before_mutation(self) -> None:
        grok_root = Path(self._root("grok", scope="global"))
        conflict = grok_root / "resume-grok" / "SKILL.md"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("user owned\n", encoding="utf-8")

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "all",
                    "--scope",
                    "global",
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )

        self.assertEqual(code, 6)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "E_INSTALL_CONFLICT")
        antigravity_root = Path(self._root("antigravity", scope="global"))
        self.assertFalse((antigravity_root / ".portable-resume").exists())
        self.assertEqual(conflict.read_text(encoding="utf-8"), "user owned\n")

    def test_all_host_later_execution_failure_restores_earlier_root_bytes(self) -> None:
        earlier_root = Path(self._root("claude", scope="global"))
        execute_install(plan_install(host="claude", scope="global", root=str(earlier_root)))
        before = self._file_bytes(earlier_root)
        original_execute = transaction_module.execute_install
        calls = 0

        def fail_later_root(plan, *, force_with_backup=False, lock=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected later-root failure")
            return original_execute(plan, force_with_backup=force_with_backup, lock=lock)

        stdout = StringIO()
        stderr = StringIO()
        with (
            mock.patch.object(install_cli_module, "_hosts", return_value=["claude", "grok"]),
            mock.patch.object(transaction_module, "execute_install", side_effect=fail_later_root),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "all",
                    "--scope",
                    "global",
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )

        self.assertEqual(code, 8)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "E_INVARIANT")
        # Installer lock metadata is process-owned and may be rewritten while
        # multi-root holds exclusive locks (#23); compare payload+manifest only.
        def without_lock(tree: dict[str, bytes]) -> dict[str, bytes]:
            return {
                path: data
                for path, data in tree.items()
                if not path.endswith("/install.lock") and path != ".portable-resume/install.lock"
            }

        self.assertEqual(without_lock(self._file_bytes(earlier_root)), without_lock(before))
        verify_root(str(earlier_root))

    def test_all_host_later_failure_removes_earlier_fresh_install(self) -> None:
        earlier_root = Path(self._root("claude", scope="global"))
        self.assertEqual(self._file_bytes(earlier_root), {})
        original_execute = transaction_module.execute_install
        calls = 0

        def fail_later_root(plan, *, force_with_backup=False, lock=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected later-root failure")
            return original_execute(plan, force_with_backup=force_with_backup, lock=lock)

        with (
            mock.patch.object(install_cli_module, "_hosts", return_value=["claude", "grok"]),
            mock.patch.object(transaction_module, "execute_install", side_effect=fail_later_root),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "all",
                    "--scope",
                    "global",
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )

        self.assertEqual(code, 8)
        # Exclusive install.lock may remain while multi-root releases locks
        # after compensation (#23); payload/manifest must be gone.
        remaining = {
            path: data
            for path, data in self._file_bytes(earlier_root).items()
            if not path.endswith("install.lock")
        }
        self.assertEqual(remaining, {})

    def test_all_host_reports_partial_state_when_compensation_fails(self) -> None:
        original_execute = transaction_module.execute_install
        calls = 0

        def fail_later_root(plan, *, force_with_backup=False, lock=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected later-root failure")
            return original_execute(plan, force_with_backup=force_with_backup, lock=lock)

        stderr = StringIO()
        with (
            mock.patch.object(install_cli_module, "_hosts", return_value=["claude", "grok"]),
            mock.patch.object(transaction_module, "execute_install", side_effect=fail_later_root),
            mock.patch.object(
                transaction_module,
                "restore_install_checkpoint",
                side_effect=DiagnosticError("E_RECOVERY_REQUIRED"),
            ),
            redirect_stdout(StringIO()),
            redirect_stderr(stderr),
        ):
            code = install_cli_run(
                [
                    "install",
                    "--host",
                    "all",
                    "--scope",
                    "global",
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )

        diagnostic = json.loads(stderr.getvalue())
        self.assertEqual(code, 6)
        self.assertEqual(diagnostic["code"], "E_RECOVERY_REQUIRED")
        self.assertEqual(diagnostic["family"], ["claude"])

    def test_cli_verify_requires_the_requested_host_claim(self) -> None:
        root = self._root("claude", scope="global")
        execute_install(plan_install(host="antigravity", scope="global", root=root))
        requested_claim = claim_key(host="claude", scope="global", root=root)
        with self.assertRaises(DiagnosticError) as ctx:
            verify_root(root, claim=requested_claim)
        self.assertEqual(ctx.exception.code, "E_VERIFY_MISMATCH")

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = install_cli_run(
                [
                    "verify",
                    "--host",
                    "claude",
                    "--scope",
                    "global",
                    "--home",
                    str(self.home),
                    "--json",
                ]
            )
        self.assertEqual(code, 7)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "E_VERIFY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
