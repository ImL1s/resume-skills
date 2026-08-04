"""#34: discovery roots + duplicate/shadow Skill scan."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
    _read_regular_capped,
    discovery_roots_for_host,
    inspect_skill_copy,
    require_no_blocking_shadow,
    scan_skill_duplicates,
)
from portable_resume.install.render import materialize_plan, package_identity
from portable_resume.install.transaction import (
    execute_install,
    manifest_path,
    plan_install,
    verify_root,
)


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

    def test_selected_partial_install_discovery_uses_recorded_source_plan(self) -> None:
        root = self.project / ".claude" / "skills"
        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=str(root),
                sources=("codex", "grok"),
            )
        )
        report = scan_skill_duplicates(
            host="claude",
            selected_root=str(root),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
        )
        expected = package_identity(
            materialize_plan("claude", sources=("codex", "grok"))
        )
        self.assertEqual(report["expected_package_identity"], expected)
        self.assertEqual(report["skills_scanned"], ["resume-codex", "resume-grok"])
        selected = [row for row in report["findings"] if row["detail"] == "selected_root"]
        self.assertEqual({row["skill"] for row in selected}, {"resume-codex", "resume-grok"})

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
        self.assertIsNotNone(ctx.exception.hint)
        self.assertIn("audit-host", ctx.exception.hint or "")
        self.assertEqual(
            ctx.exception.to_dict()["hint"],
            DiagnosticError("E_INSTALL_SHADOW").to_dict()["hint"],
        )

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

    def test_explicit_sources_expand_shadow_scan_beyond_partial_claim(self) -> None:
        """Install --sources expansion must scan newly requested skills (#242 P1)."""
        from portable_resume.install.transaction import execute_install, plan_install

        selected = self.project / ".claude" / "skills"
        selected.mkdir(parents=True)
        # Existing partial claim: codex only.
        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=str(selected),
                sources=("codex",),
            )
        )
        report_old = scan_skill_duplicates(
            host="claude",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
        )
        self.assertEqual(report_old["skills_scanned"], ["resume-codex"])
        report_new = scan_skill_duplicates(
            host="claude",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            sources=("codex", "grok"),
        )
        self.assertEqual(report_new["skills_scanned"], ["resume-codex", "resume-grok"])
        # Higher-precedence divergent project skill for the newly requested name
        # must block when the expanded set is scanned (global install target).
        global_root = self.home / ".claude" / "skills"
        global_root.mkdir(parents=True)
        _write_skill(
            self.project / ".claude" / "skills",
            "resume-grok",
            b"---\nname: resume-grok\n---\nSTALE PROJECT GROK\n",
        )
        with self.assertRaises(DiagnosticError) as ctx:
            require_no_blocking_shadow(
                host="claude",
                selected_root=str(global_root),
                project_dir=str(self.project),
                home_dir=str(self.home),
                selected_scope="global",
                sources=("codex", "grok"),
            )
        self.assertEqual(ctx.exception.code, "E_INSTALL_SHADOW")

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


class DiscoveryReaderSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "skills"
        plan = plan_install(host="cursor", scope="project", root=str(self.root))
        execute_install(plan)
        self.expected_identity = package_identity(materialize_plan("cursor"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def inspect(self, *, expected: str | None = None) -> dict[str, object]:
        return inspect_skill_copy(
            str(self.root),
            "resume-codex",
            host="cursor",
            expected_payload_digest=self.expected_identity if expected is None else expected,
        )

    def test_failed_nofollow_open_is_not_retried(self) -> None:
        skill_md = self.root / "resume-codex" / "SKILL.md"
        real_open = os.open
        calls: list[int] = []

        def fail_first_open(
            path: str | bytes,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            calls.append(flags)
            if len(calls) == 1:
                raise OSError("simulated no-follow race")
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch("portable_resume.install.discovery.os.open", side_effect=fail_first_open):
            self.assertIsNone(_read_regular_capped(str(skill_md), max_bytes=256 * 1024))
        self.assertEqual(len(calls), 1)

    def test_symlinked_skill_markdown_is_unsafe_and_never_verified(self) -> None:
        skill_md = self.root / "resume-codex" / "SKILL.md"
        target = self.root / "same-skill-markdown"
        target.write_bytes(skill_md.read_bytes())
        skill_md.unlink()
        skill_md.symlink_to(target)

        result = self.inspect()

        self.assertTrue(result["unsafe"])
        self.assertFalse(result["payload_verified"])
        self.assertIsNone(result["skill_md_sha256"])

    def test_matches_expected_uses_payload_bytes_not_manifest_metadata(self) -> None:
        manifest = Path(manifest_path(str(self.root)))
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["package_identity"] = "0" * 64
        manifest.write_text(json.dumps(document), encoding="utf-8")

        result = self.inspect()

        self.assertTrue(result["payload_verified"])
        self.assertTrue(result["matches_expected"])
        self.assertEqual(result["package_identity"], "0" * 64)

    def test_matches_expected_is_independent_from_payload_verified(self) -> None:
        result = self.inspect(expected="f" * 64)

        self.assertTrue(result["payload_verified"])
        self.assertFalse(result["matches_expected"])

        runner = self.root / "resume-codex" / "scripts" / "run_reader.py"
        runner.write_bytes(runner.read_bytes() + b"\n# modified\n")
        modified = self.inspect()
        self.assertFalse(modified["payload_verified"])
        self.assertFalse(modified["matches_expected"])

    def test_matches_expected_uses_actual_identity_for_same_size_mismatch(self) -> None:
        rel = "resume-codex/scripts/run_reader.py"
        runner = self.root / rel
        original = runner.read_bytes()
        replacement = bytes([original[0] ^ 1]) + original[1:]
        self.assertEqual(len(replacement), len(original))
        runner.write_bytes(replacement)
        actual = materialize_plan("cursor")
        actual[rel] = replacement

        result = self.inspect(expected=package_identity(actual))

        self.assertFalse(result["payload_verified"])
        self.assertTrue(result["matches_expected"])

    def test_capped_read_fails_closed_when_file_grows_during_read(self) -> None:
        path = self.root / "growing"
        original = b"bounded"
        path.write_bytes(original)
        real_read = os.read
        grew = False

        def grow_after_first_read(fd: int, size: int) -> bytes:
            nonlocal grew
            chunk = real_read(fd, size)
            if not grew:
                grew = True
                with path.open("ab") as stream:
                    stream.write(b"!")
            return chunk

        with mock.patch("portable_resume.install.discovery.os.read", side_effect=grow_after_first_read):
            self.assertIsNone(_read_regular_capped(str(path), max_bytes=len(original)))

    def test_capped_read_fails_closed_when_file_mutates_during_read(self) -> None:
        path = self.root / "mutating"
        original = b"stable"
        path.write_bytes(original)
        real_read = os.read
        mutated = False

        def mutate_after_first_read(fd: int, size: int) -> bytes:
            nonlocal mutated
            chunk = real_read(fd, size)
            if not mutated:
                mutated = True
                path.write_bytes(b"change")
            return chunk

        with mock.patch("portable_resume.install.discovery.os.read", side_effect=mutate_after_first_read):
            self.assertIsNone(_read_regular_capped(str(path), max_bytes=len(original)))

    def test_unreadable_manifest_does_not_hide_matching_payload(self) -> None:
        Path(manifest_path(str(self.root))).write_text("{not-json", encoding="utf-8")

        result = self.inspect()

        self.assertTrue(result["manifest_unreadable"])
        self.assertFalse(result["payload_verified"])
        self.assertTrue(result["matches_expected"])


class CodexFollowupTests(unittest.TestCase):
    """Follow-ups from PR #102 Codex review on #34 HEAD."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.project = Path(self._tmp.name) / "project"
        self.home.mkdir()
        self.project.mkdir()
        self._old_cwd = os.getcwd()
        os.chdir(self.project)

    def tearDown(self) -> None:
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_global_install_without_project_scans_cwd(self) -> None:
        """Global install without --project must still see project-tier shadows."""
        project_root = self.project / ".cursor" / "skills"
        _write_skill(project_root, "resume-codex", b"STALE PROJECT\n")
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
                    "--home",
                    str(self.home),
                ]
            )
        finally:
            sys.stderr = old_err
        self.assertEqual(code, 6)
        self.assertIn("E_INSTALL_SHADOW", err.getvalue())

    def test_malformed_alternate_manifest_does_not_abort(self) -> None:
        selected = self.project / ".cursor" / "skills"
        agents = self.project / ".agents" / "skills"
        selected.mkdir(parents=True)
        _write_skill(agents, "resume-codex")
        support = agents / ".portable-resume"
        support.mkdir()
        (support / "manifest.json").write_text("{not-json", encoding="utf-8")
        report = scan_skill_duplicates(
            host="cursor",
            selected_root=str(selected),
            project_dir=str(self.project),
            home_dir=str(self.home),
            selected_scope="project",
            skill_names=("resume-codex",),
        )
        self.assertTrue(report["ok"] or report["aggregate_policy"] == POLICY_WARN)
        # Must not raise; findings still present for the foreign skill.
        self.assertTrue(any(not f.get("is_selected") for f in report["findings"]))

    def test_kimi_env_home_primary_user_root(self) -> None:
        from portable_resume.install.discovery import discovery_roots_for_host, resolve_discovery_path

        env_home = self.home / "kimi-custom"
        env_home.mkdir()
        entry = next(
            r for r in discovery_roots_for_host("kimi") if r.root_id == "kimi.user.primary"
        )
        path = resolve_discovery_path(
            entry,
            project_dir=str(self.project),
            home_dir=str(self.home),
            host="kimi",
            environ={"KIMI_CODE_HOME": str(env_home)},
            isolation=False,
        )
        self.assertEqual(os.path.realpath(path), os.path.realpath(env_home / "skills"))

    def test_kilo_config_dir_singular_skill_root(self) -> None:
        """#46: singular skill/ must track KILO_CONFIG_DIR, not only $HOME."""
        from portable_resume.install.discovery import discovery_roots_for_host, resolve_discovery_path

        env_home = self.home / "kilo-custom"
        env_home.mkdir()
        entry = next(
            r
            for r in discovery_roots_for_host("kilo")
            if r.root_id == "kilo.user.config.skill"
        )
        path = resolve_discovery_path(
            entry,
            project_dir=str(self.project),
            home_dir=str(self.home),
            host="kilo",
            environ={"KILO_CONFIG_DIR": str(env_home)},
            isolation=False,
        )
        self.assertEqual(os.path.realpath(path), os.path.realpath(env_home / "skill"))
        # Isolation must ignore host env override.
        iso = resolve_discovery_path(
            entry,
            project_dir=str(self.project),
            home_dir=str(self.home),
            host="kilo",
            environ={"KILO_CONFIG_DIR": str(env_home)},
            isolation=True,
        )
        self.assertEqual(
            os.path.realpath(iso),
            os.path.realpath(self.home / ".config" / "kilo" / "skill"),
        )


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
                ]
            )
        finally:
            sys.stdout = old
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["schema_version"], "portable-resume/install-result-v1")
        self.assertEqual(data["command"], "audit-host")
        self.assertTrue(data["ok"])
        result = data["results"][0]
        self.assertEqual(result["schema_version"], "portable-resume/discovery-scan-v1")
        self.assertEqual(result["host"], "cursor")
        self.assertIn("discovery_policy", result)

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
                ]
            )
        finally:
            sys.stderr = old_err
        self.assertEqual(code, 6)
        stderr = err.getvalue()
        self.assertIn("E_INSTALL_SHADOW", stderr)
        payload = json.loads(stderr.strip().splitlines()[-1])
        self.assertEqual(payload["code"], "E_INSTALL_SHADOW")
        self.assertEqual(
            payload["hint"],
            DiagnosticError("E_INSTALL_SHADOW").to_dict()["hint"],
        )
        self.assertIn("audit-host", payload["hint"])

    def test_install_succeeds_without_shadow(self) -> None:
        plan_install(
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
                ]
            )
        finally:
            sys.stdout = old
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["schema_version"], "portable-resume/install-result-v1")
        self.assertEqual(data["command"], "install")
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data["results"]), 1)
        result = data["results"][0]
        self.assertIn("discovery", result)
        self.assertEqual(result["discovery"]["aggregate_policy"], POLICY_ALLOW)
        verify_root(str(self.project / ".cursor" / "skills"))


if __name__ == "__main__":
    unittest.main()
