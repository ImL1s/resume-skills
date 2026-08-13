"""Installer journal recovery, mutation blocking, and claim lifecycle (shipped APIs)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError, SOURCE_KEYS
import portable_resume.install.cli as install_cli_module
from portable_resume.install.cli import run as install_cli_run
from portable_resume.install.catalog import BUNDLE_VERSION, MANIFEST_SCHEMA, resolve_skill_root
from portable_resume.install.manifest import claim_key, sha256_bytes
from portable_resume.install.render import materialize_plan, package_identity
import portable_resume.install.transaction as transaction_module
from portable_resume.install.transaction import (
    execute_install,
    install_multi_targets,
    journal_path,
    load_manifest,
    plan_install,
    recover_root,
    require_no_pending_journal,
    uninstall_claim,
    verify_root,
    _write_journal,
    manifest_path,
)


class InstallerTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name) / "home"
        self.project = Path(self._tmpdir.name) / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.root = resolve_skill_root(
            host="claude",
            scope="project",
            project_dir=str(self.project),
            home_dir=str(self.home),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @staticmethod
    def _file_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

    def _legacy_shared_root_targets(self) -> tuple[Path, list[tuple[str, str]]]:
        shared = self.home / ".claude" / "skills"
        aliases = [
            ("gemini", self.home / ".gemini" / "skills"),
            ("antigravity", self.home / ".gemini" / "config" / "skills"),
            ("github-copilot", self.home / ".copilot" / "skills"),
        ]
        execute_install(
            plan_install(host="claude", scope="global", root=str(shared))
        )
        manifest_file = Path(manifest_path(str(shared)))
        legacy = json.loads(manifest_file.read_text(encoding="utf-8"))
        legacy["bundle_version"] = "0.3.3"
        for claim in legacy["claims"].values():
            claim["bundle_version"] = "0.3.3"
        manifest_file.write_text(
            json.dumps(legacy, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        for _host, alias in aliases:
            alias.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(shared, alias)
        # Deliberately put the legacy owner last: execution may reorder, results may not.
        return shared, [aliases[0], aliases[1], aliases[2], ("claude", str(shared))]

    def _legacy_multi_claim_targets(self) -> tuple[Path, list[tuple[str, str]]]:
        shared = self.home / ".claude" / "skills"
        gemini = self.home / ".gemini" / "skills"
        gemini.parent.mkdir(parents=True)
        os.symlink(shared, gemini)
        execute_install(plan_install(host="claude", scope="global", root=str(shared)))
        execute_install(plan_install(host="gemini", scope="global", root=str(shared)))
        manifest_file = Path(manifest_path(str(shared)))
        legacy = json.loads(manifest_file.read_text(encoding="utf-8"))
        legacy["bundle_version"] = "0.4.2"
        for claim in legacy["claims"].values():
            claim["bundle_version"] = "0.4.2"
        shared_changes = sorted(
            rel
            for rel, entry in legacy["files"].items()
            if len(entry["claims"]) == 2
        )[:6]
        self.assertEqual(len(shared_changes), 6)
        for index, rel in enumerate(shared_changes):
            old_bytes = f"released-0.4.2-shared-{index}\n".encode()
            (shared / rel).write_bytes(old_bytes)
            legacy["files"][rel]["sha256"] = sha256_bytes(old_bytes)
        manifest_file.write_text(
            json.dumps(legacy, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return shared, [("gemini", str(gemini)), ("claude", str(shared))]

    def _same_version_stale_identity_targets(
        self,
    ) -> tuple[Path, list[tuple[str, str]]]:
        shared = self.home / ".claude" / "skills"
        gemini = self.home / ".gemini" / "skills"
        gemini.parent.mkdir(parents=True)
        os.symlink(shared, gemini)
        execute_install(plan_install(host="claude", scope="global", root=str(shared)))
        execute_install(plan_install(host="gemini", scope="global", root=str(shared)))

        manifest_file = Path(manifest_path(str(shared)))
        stale = json.loads(manifest_file.read_text(encoding="utf-8"))
        shared_rel = next(
            rel
            for rel, entry in sorted(stale["files"].items())
            if len(entry["claims"]) == 2
        )
        old_files = dict(materialize_plan("claude"))
        old_bytes = b"same-version-stale-generated-payload\n"
        old_files[shared_rel] = old_bytes
        old_identity = package_identity(old_files)
        (shared / shared_rel).write_bytes(old_bytes)
        stale["files"][shared_rel]["sha256"] = sha256_bytes(old_bytes)
        stale["package_identity"] = old_identity
        for claim in stale["claims"].values():
            claim["package_identity"] = old_identity
        manifest_file.write_text(
            json.dumps(stale, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return shared, [("gemini", str(gemini)), ("claude", str(shared))]

    def test_multi_target_upgrade_sequences_legacy_owner_before_shared_aliases(self) -> None:
        shared, targets = self._legacy_shared_root_targets()
        before = self._file_bytes(shared)
        payload = shared / "resume-codex" / "SKILL.md"
        payload_mtime = payload.stat().st_mtime_ns

        preview = install_multi_targets(
            targets,
            scope="global",
            dry_run=True,
            force_with_backup=True,
        )

        self.assertEqual(self._file_bytes(shared), before)
        self.assertEqual(
            [result["plan"]["host"] for result in preview],
            [host for host, _root in targets],
        )
        self.assertTrue(all(not result["plan"]["replaces"] for result in preview))

        results = install_multi_targets(
            targets,
            scope="global",
            force_with_backup=True,
        )

        self.assertEqual(
            [result["plan"]["host"] for result in results],
            [host for host, _root in targets],
        )
        self.assertEqual(payload.stat().st_mtime_ns, payload_mtime)
        self.assertTrue(all(not result["plan"]["replaces"] for result in results))
        manifest = load_manifest(str(shared))
        assert manifest is not None
        self.assertEqual(manifest.bundle_version, BUNDLE_VERSION)
        self.assertEqual(len(manifest.claims), len(targets))
        for host, root in targets:
            requested_claim = claim_key(host=host, scope="global", root=root)
            self.assertTrue(verify_root(root, claim=requested_claim)["ok"])

    def test_quick_install_all_dry_run_projects_legacy_owner_upgrade(self) -> None:
        shared, targets = self._legacy_shared_root_targets()
        before = self._file_bytes(shared)

        stdout = StringIO()
        stderr = StringIO()
        with (
            mock.patch.object(
                install_cli_module,
                "_hosts",
                return_value=[host for host, _root in targets],
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = install_cli_run(
                [
                    "quick-install",
                    "all",
                    "--home",
                    str(self.home),
                    "--dry-run",
                    "--force-with-backup",
                ]
            )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(self._file_bytes(shared), before)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "portable-resume/install-result-v1")
        self.assertEqual(
            [result["host"] for result in payload["results"]],
            [host for host, _root in targets],
        )
        self.assertTrue(all(result["dry_run"] for result in payload["results"]))

    def test_multi_claim_released_root_upgrades_with_one_manifest_publish(self) -> None:
        shared, targets = self._legacy_multi_claim_targets()
        before = load_manifest(str(shared))
        assert before is not None

        preview = install_multi_targets(
            targets,
            scope="global",
            dry_run=True,
            force_with_backup=True,
        )
        self.assertEqual([item["plan"]["host"] for item in preview], ["gemini", "claude"])
        self.assertEqual(load_manifest(str(shared)).bundle_version, "0.4.2")

        original_write = transaction_module._atomic_write_support_file_under_fd
        manifest_writes = 0

        def count_manifest_write(root_fd, name, data, **kwargs):
            nonlocal manifest_writes
            if name == transaction_module.MANIFEST_NAME:
                manifest_writes += 1
            return original_write(root_fd, name, data, **kwargs)

        with mock.patch.object(
            transaction_module,
            "_atomic_write_support_file_under_fd",
            side_effect=count_manifest_write,
        ):
            results = install_multi_targets(
                targets,
                scope="global",
                force_with_backup=True,
            )

        self.assertEqual(manifest_writes, 1)
        self.assertEqual([item["plan"]["host"] for item in results], ["gemini", "claude"])
        final = load_manifest(str(shared))
        assert final is not None
        self.assertEqual(final.generation, before.generation + 1)
        self.assertEqual(final.bundle_version, BUNDLE_VERSION)
        self.assertEqual(len(final.claims), 2)

    def test_quick_install_all_upgrades_released_multi_claim_root(self) -> None:
        shared, targets = self._legacy_multi_claim_targets()
        before = self._file_bytes(shared)
        hosts = [host for host, _root in targets]

        for dry_run in (True, False):
            stdout = StringIO()
            stderr = StringIO()
            argv = [
                "quick-install",
                "all",
                "--home",
                str(self.home),
                "--force-with-backup",
            ]
            if dry_run:
                argv.append("--dry-run")
            with (
                mock.patch.object(install_cli_module, "_hosts", return_value=hosts),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = install_cli_run(argv)
            self.assertEqual(code, 0, stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual([item["host"] for item in payload["results"]], hosts)
            if dry_run:
                self.assertEqual(self._file_bytes(shared), before)

        self.assertEqual(load_manifest(str(shared)).bundle_version, BUNDLE_VERSION)

    def test_same_version_identity_upgrade_is_atomic_and_needs_no_force(self) -> None:
        shared, targets = self._same_version_stale_identity_targets()
        before = load_manifest(str(shared))
        assert before is not None
        before_tree = self._file_bytes(shared)

        preview = install_multi_targets(targets, scope="global", dry_run=True)

        self.assertEqual(self._file_bytes(shared), before_tree)
        self.assertTrue(all(item["dry_run"] for item in preview))
        original_write = transaction_module._atomic_write_support_file_under_fd
        manifest_writes = 0

        def count_manifest_write(root_fd, name, data, **kwargs):
            nonlocal manifest_writes
            if name == transaction_module.MANIFEST_NAME:
                manifest_writes += 1
            return original_write(root_fd, name, data, **kwargs)

        with mock.patch.object(
            transaction_module,
            "_atomic_write_support_file_under_fd",
            side_effect=count_manifest_write,
        ):
            results = install_multi_targets(targets, scope="global")

        self.assertEqual(manifest_writes, 1)
        self.assertEqual([item["plan"]["host"] for item in results], ["gemini", "claude"])
        final = load_manifest(str(shared))
        assert final is not None
        self.assertEqual(final.bundle_version, before.bundle_version)
        self.assertEqual(final.generation, before.generation + 1)
        self.assertNotEqual(final.package_identity, before.package_identity)
        for host, root in targets:
            requested_claim = claim_key(host=host, scope="global", root=root)
            self.assertTrue(verify_root(root, claim=requested_claim)["ok"])

    def test_same_version_identity_upgrade_requires_all_existing_claims(self) -> None:
        shared, targets = self._same_version_stale_identity_targets()
        before = self._file_bytes(shared)

        with self.assertRaises(DiagnosticError) as caught:
            install_multi_targets([targets[0]], scope="global", dry_run=True)

        self.assertEqual(caught.exception.code, "E_INSTALL_CONFLICT")
        self.assertEqual(self._file_bytes(shared), before)

    def test_same_version_identity_upgrade_rejects_divergent_alias_payloads(self) -> None:
        shared, targets = self._same_version_stale_identity_targets()
        before = self._file_bytes(shared)
        original_materialize = transaction_module.materialize_plan

        def divergent(host: str, *, sources=None):
            files = dict(original_materialize(host, sources=sources))
            if host == "gemini":
                rel = next(iter(sorted(files)))
                files[rel] = files[rel] + b"divergent"
            return files

        with mock.patch.object(
            transaction_module,
            "materialize_plan",
            side_effect=divergent,
        ):
            with self.assertRaises(DiagnosticError) as caught:
                install_multi_targets(targets, scope="global", dry_run=True)

        self.assertEqual(caught.exception.code, "E_INSTALL_CONFLICT")
        self.assertEqual(self._file_bytes(shared), before)

    def test_same_version_identity_change_with_one_existing_claim_uses_group_path(
        self,
    ) -> None:
        root = Path(self.root)
        execute_install(plan_install(host="claude", scope="project", root=str(root)))
        manifest_file = Path(manifest_path(str(root)))
        stale = json.loads(manifest_file.read_text(encoding="utf-8"))
        rel = next(iter(sorted(stale["files"])))
        old_bytes = b"single-claim-same-version-stale\n"
        (root / rel).write_bytes(old_bytes)
        stale["files"][rel]["sha256"] = sha256_bytes(old_bytes)
        stale["package_identity"] = "a" * 64
        for claim in stale["claims"].values():
            claim["package_identity"] = "a" * 64
        manifest_file.write_text(
            json.dumps(stale, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        result = install_multi_targets(
            [("claude", str(root))],
            scope="project",
        )[0]

        self.assertTrue(result["ok"])
        self.assertTrue(verify_root(str(root))["ok"])

    def test_quick_install_all_upgrades_same_version_identity(self) -> None:
        shared, targets = self._same_version_stale_identity_targets()
        hosts = [host for host, _root in targets]
        stdout = StringIO()
        stderr = StringIO()
        with (
            mock.patch.object(install_cli_module, "_hosts", return_value=hosts),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = install_cli_run(
                ["quick-install", "all", "--home", str(self.home)]
            )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(
            [result["host"] for result in json.loads(stdout.getvalue())["results"]],
            hosts,
        )
        self.assertTrue(verify_root(str(shared))["ok"])

    def test_multi_claim_upgrade_rejects_unrequested_old_claim_without_mutation(self) -> None:
        shared, targets = self._legacy_multi_claim_targets()
        before = self._file_bytes(shared)

        with self.assertRaises(DiagnosticError) as caught:
            install_multi_targets(
                [targets[1]],
                scope="global",
                force_with_backup=True,
            )

        self.assertEqual(caught.exception.code, "E_INSTALL_CONFLICT")
        self.assertEqual(self._file_bytes(shared), before)

    def test_coordinated_upgrade_backs_up_foreign_payload(self) -> None:
        shared, targets = self._legacy_multi_claim_targets()
        rel = "resume-codex/SKILL.md"
        manifest_file = Path(manifest_path(str(shared)))
        legacy = json.loads(manifest_file.read_text(encoding="utf-8"))
        del legacy["files"][rel]
        manifest_file.write_text(json.dumps(legacy, sort_keys=True), encoding="utf-8")
        foreign = shared / rel
        foreign.write_text("foreign\n", encoding="utf-8")

        preview = install_multi_targets(
            targets,
            scope="global",
            dry_run=True,
            force_with_backup=True,
        )
        self.assertIn(rel, preview[0]["plan"]["backups"])

        results = install_multi_targets(
            targets,
            scope="global",
            force_with_backup=True,
        )
        backup_root = Path(results[0]["backup_root"])
        self.assertEqual((backup_root / rel).read_text(encoding="utf-8"), "foreign\n")
        self.assertTrue(verify_root(str(shared))["ok"])

    def test_multi_target_legacy_owner_upgrade_compensates_sibling_failure(self) -> None:
        shared, targets = self._legacy_shared_root_targets()
        targets.append(("grok", str(self.home / ".grok" / "skills")))
        before = self._file_bytes(shared)
        original_execute = transaction_module.execute_install
        calls = 0

        def fail_first_sibling(plan, *, force_with_backup=False, lock=None, locked_root=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected shared-root sibling failure")
            return original_execute(
                plan,
                force_with_backup=force_with_backup,
                lock=lock,
                locked_root=locked_root,
            )

        with mock.patch.object(
            transaction_module,
            "execute_install",
            side_effect=fail_first_sibling,
        ):
            with self.assertRaises(OSError):
                install_multi_targets(
                    targets,
                    scope="global",
                    force_with_backup=True,
                )

        def without_lock(tree: dict[str, bytes]) -> dict[str, bytes]:
            return {
                path: data
                for path, data in tree.items()
                if not path.endswith("install.lock")
            }
        self.assertEqual(without_lock(self._file_bytes(shared)), without_lock(before))
        restored = load_manifest(str(shared))
        assert restored is not None
        self.assertEqual(restored.bundle_version, "0.3.3")
        self.assertEqual(len(restored.claims), 1)

    def test_pending_journal_blocks_mutation_until_recover(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        execute_install(plan)
        verify_root(self.root)
        # simulate crash mid-commit
        os.makedirs(os.path.join(self.root, ".portable-resume"), exist_ok=True)
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "committing",
                "generation": 99,
                "claim": "synthetic",
                "stage_dir": os.path.join(self.root, ".portable-resume", "portable-resume-stage-missing"),
                "backup_root": os.path.join(
                    self.root, ".portable-resume", "backups", "20260726T000000Z-test"
                ),
                "paths": {},
            },
        )
        with self.assertRaises(DiagnosticError) as ctx:
            require_no_pending_journal(self.root)
        self.assertEqual(ctx.exception.code, "E_RECOVERY_REQUIRED")
        with self.assertRaises(DiagnosticError) as ctx2:
            execute_install(plan_install(host="claude", scope="project", root=self.root))
        self.assertEqual(ctx2.exception.code, "E_RECOVERY_REQUIRED")
        with self.assertRaises(DiagnosticError) as ctx3:
            verify_root(self.root)
        self.assertEqual(ctx3.exception.code, "E_RECOVERY_REQUIRED")

        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
        self.assertTrue(recovered["recovered"])
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        # mutations allowed again
        verify_root(self.root)
        plan2 = plan_install(host="claude", scope="project", root=self.root)
        result = execute_install(plan2)
        self.assertTrue(result["ok"])

    def test_complete_stale_journal_is_cleared_by_recover(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        execute_install(plan)
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "complete",
                "generation": 1,
                "claim": "x",
                "stage_dir": None,
                "backup_root": None,
                "paths": {},
            },
        )
        out = recover_root(self.root)
        self.assertEqual(out.get("action"), "cleared_complete_journal")
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        verify_root(self.root)

    def test_journal_path_escape_is_rejected_on_recover(self) -> None:
        # Hostile on-disk journal (bypasses write-time schema self-check): recover
        # must fail closed with E_RECOVERY_REQUIRED rather than act on escapes (#28).
        plan = plan_install(host="claude", scope="project", root=self.root)
        execute_install(plan)
        os.makedirs(os.path.join(self.root, ".portable-resume"), exist_ok=True)
        outside = Path(self._tmpdir.name) / "outside.txt"
        journal = {
            "schema_version": "portable-resume/install-journal-v1",
            "state": "committing",
            "generation": 2,
            "claim": "x",
            "stage_dir": None,
            "backup_root": None,
            "paths": {
                "../outside.txt": {
                    "state": "committed",
                    "sha256": "00" * 32,
                    "backup": str(outside),
                }
            },
        }
        Path(journal_path(self.root)).write_text(
            json.dumps(journal, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaises(DiagnosticError) as caught:
            recover_root(self.root)
        self.assertEqual(caught.exception.code, "E_RECOVERY_REQUIRED")
        self.assertFalse(outside.exists())

    def test_uninstall_preserves_unrelated_claim_on_shared_explicit_root(self) -> None:
        # two claims on distinct host roots — uninstall only selected claim
        root_a = str(self.project / "skills-a")
        root_b = str(self.project / "skills-b")
        execute_install(plan_install(host="claude", scope="project", root=root_a))
        execute_install(plan_install(host="grok", scope="project", root=root_b))
        uninstall_claim(host="claude", scope="project", root=root_a)
        self.assertIsNone(load_manifest(root_a))
        self.assertIsNotNone(load_manifest(root_b))
        verify_root(root_b)

    def test_verify_materializes_and_hashes_once_per_host(self) -> None:
        shared_root = str(self.project / "shared-skills")
        execute_install(plan_install(host="claude", scope="global", root=shared_root))
        execute_install(plan_install(host="claude", scope="project", root=shared_root))

        original_materialize = transaction_module.materialize_plan
        original_identity = transaction_module.package_identity
        with (
            mock.patch.object(
                transaction_module,
                "materialize_plan",
                wraps=original_materialize,
            ) as materialize,
            mock.patch.object(
                transaction_module,
                "package_identity",
                wraps=original_identity,
            ) as identity,
        ):
            verify_root(shared_root)

        self.assertEqual(materialize.call_count, 1)
        self.assertEqual(identity.call_count, 1)

    def test_selected_source_claims_verify_and_remain_idempotent(self) -> None:
        selected = ("codex",)
        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=self.root,
                sources=selected,
            )
        )
        first = load_manifest(self.root)
        assert first is not None
        claim = next(iter(first.claims))
        self.assertEqual(first.claims[claim]["sources"], ["codex"])
        self.assertTrue(verify_root(self.root)["ok"])

        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=self.root,
                sources=selected,
            )
        )
        second = load_manifest(self.root)
        assert second is not None
        self.assertEqual(second.claims[claim]["sources"], ["codex"])
        self.assertEqual(
            {path for path, entry in second.files.items() if claim in entry.claims},
            set(materialize_plan("claude", sources=selected)),
        )
        self.assertTrue(verify_root(self.root)["ok"])

    def test_multiple_selected_sources_and_all_partial_transitions_verify(self) -> None:
        claim = None
        for selected in (("claude", "grok"), None, ("grok",)):
            execute_install(
                plan_install(
                    host="claude",
                    scope="project",
                    root=self.root,
                    sources=selected,
                )
            )
            manifest = load_manifest(self.root)
            assert manifest is not None
            claim = claim or next(iter(manifest.claims))
            expected_sources = sorted(selected or SOURCE_KEYS)
            self.assertEqual(manifest.claims[claim]["sources"], expected_sources)
            self.assertEqual(
                {path for path, entry in manifest.files.items() if claim in entry.claims},
                set(materialize_plan("claude", sources=selected)),
            )
            self.assertTrue(verify_root(self.root)["ok"])

    def test_shared_root_verifies_each_claim_recorded_source_set(self) -> None:
        shared_root = str(self.project / "source-aware-shared")
        execute_install(
            plan_install(
                host="claude",
                scope="global",
                root=shared_root,
                sources=("codex",),
            )
        )
        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=shared_root,
                sources=("codex", "grok"),
            )
        )
        manifest = load_manifest(shared_root)
        assert manifest is not None
        by_scope = {meta["scope"]: meta["sources"] for meta in manifest.claims.values()}
        self.assertEqual(by_scope, {"global": ["codex"], "project": ["codex", "grok"]})
        self.assertTrue(verify_root(shared_root)["ok"])
        for claim in manifest.claims:
            self.assertTrue(verify_root(shared_root, claim=claim)["ok"])

    def test_uninstall_first_claim_recomputes_top_package_identity(self) -> None:
        """Shared-root multi-claim: uninstalling lex-first claim must not poison verify (#242 P1)."""
        shared_root = str(self.project / "identity-after-uninstall")
        execute_install(
            plan_install(
                host="claude",
                scope="global",
                root=shared_root,
                sources=("codex",),
            )
        )
        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=shared_root,
                sources=("codex", "grok"),
            )
        )
        manifest = load_manifest(shared_root)
        assert manifest is not None
        claims_sorted = sorted(manifest.claims)
        self.assertGreaterEqual(len(claims_sorted), 2)
        first_claim = claims_sorted[0]
        first_host = manifest.claims[first_claim]["host"]
        first_scope = manifest.claims[first_claim]["scope"]
        first_root = manifest.claims[first_claim]["root"]
        # Uninstall the lexicographically first claim (top-level identity used to stick).
        uninstall_claim(host=first_host, scope=first_scope, root=first_root)
        remaining = load_manifest(shared_root)
        assert remaining is not None
        self.assertNotIn(first_claim, remaining.claims)
        self.assertTrue(remaining.claims)
        if all("package_identity" in meta for meta in remaining.claims.values()):
            expected = remaining.claims[sorted(remaining.claims)[0]]["package_identity"]
            self.assertEqual(remaining.package_identity, expected)
        self.assertTrue(verify_root(shared_root)["ok"])

    def test_claimless_generation_zero_manifest_verifies(self) -> None:
        """Empty claims+files generation-zero must not IndexError (#242 P2)."""
        from portable_resume.install.manifest import empty_manifest

        empty = empty_manifest("a" * 64)
        self.assertEqual(empty.claims, {})
        self.assertEqual(empty.files, {})
        transaction_module._atomic_write_support_file(
            self.root,
            transaction_module.MANIFEST_NAME,
            empty.dumps().encode("utf-8"),
        )
        self.assertTrue(verify_root(self.root)["ok"])

    def test_source_metadata_tampering_fails_closed(self) -> None:
        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=self.root,
                sources=("codex",),
            )
        )
        path = Path(manifest_path(self.root))
        original = json.loads(path.read_text(encoding="utf-8"))
        claim = next(iter(original["claims"]))
        skill_rel = next(rel for rel in original["files"] if rel.startswith("resume-"))

        tampered_documents = []
        source_tampered = json.loads(json.dumps(original))
        source_tampered["claims"][claim]["sources"] = ["grok"]
        tampered_documents.append(source_tampered)
        identity_tampered = json.loads(json.dumps(original))
        identity_tampered["claims"][claim]["package_identity"] = "0" * 64
        tampered_documents.append(identity_tampered)
        mode_tampered = json.loads(json.dumps(original))
        mode_tampered["files"][skill_rel]["mode"] = 0o755
        tampered_documents.append(mode_tampered)
        path_set_tampered = json.loads(json.dumps(original))
        del path_set_tampered["files"][skill_rel]
        tampered_documents.append(path_set_tampered)

        for index, tampered in enumerate(tampered_documents):
            with self.subTest(tamper=index):
                path.write_text(json.dumps(tampered), encoding="utf-8")
                with self.assertRaises(DiagnosticError) as caught:
                    verify_root(self.root)
                self.assertEqual(caught.exception.code, "E_VERIFY_MISMATCH")

        path.write_text(json.dumps(original), encoding="utf-8")
        payload_path = Path(self.root) / skill_rel
        payload_path.chmod(0o600)
        with self.assertRaises(DiagnosticError) as caught:
            verify_root(self.root)
        self.assertEqual(caught.exception.code, "E_VERIFY_MISMATCH")

    def test_windows_verify_ignores_non_portable_physical_mode_bits(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        manifest = load_manifest(self.root)
        assert manifest is not None
        payload_rel = next(rel for rel in manifest.files if rel.endswith("SKILL.md"))
        (Path(self.root) / payload_rel).chmod(0o600)

        self.assertTrue(
            transaction_module._physical_mode_matches(0o600, 0o644, platform_name="nt")
        )
        original_mode_matches = transaction_module._physical_mode_matches

        def emulate_windows(actual: int, expected: int) -> bool:
            return original_mode_matches(actual, expected, platform_name="nt")

        with mock.patch.object(
            transaction_module,
            "_physical_mode_matches",
            side_effect=emulate_windows,
        ):
            self.assertTrue(verify_root(self.root)["ok"])

    def test_legacy_source_inference_is_deterministic_and_ambiguous_fails_closed(
        self,
    ) -> None:
        execute_install(
            plan_install(
                host="claude",
                scope="project",
                root=self.root,
                sources=("codex",),
            )
        )
        path = Path(manifest_path(self.root))
        data = json.loads(path.read_text(encoding="utf-8"))
        claim = next(iter(data["claims"]))
        del data["claims"][claim]["sources"]
        del data["claims"][claim]["package_identity"]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(verify_root(self.root)["ok"])

        # A legacy claim that owns only shared runtime files cannot identify
        # which source plan created it, so verification must not guess.
        for entry in data["files"].values():
            if entry["path"].startswith("resume-"):
                entry["claims"].remove(claim)
        data["files"] = {
            rel: entry for rel, entry in data["files"].items() if entry["claims"]
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(DiagnosticError) as caught:
            verify_root(self.root)
        self.assertEqual(caught.exception.code, "E_VERIFY_MISMATCH")

    def test_manifest_path_escape_rejected_on_load_and_uninstall(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        outside = Path(self._tmpdir.name) / "escape-target.txt"
        outside.write_text("keep-me", encoding="utf-8")
        from portable_resume.install.manifest import sha256_file
        from portable_resume.install.transaction import manifest_path

        dig = sha256_file(str(outside))
        man = load_manifest(self.root)
        assert man is not None
        data = man.to_dict()
        data["files"]["../../escape-target.txt"] = {
            "path": "../../escape-target.txt",
            "sha256": dig,
            "claims": [next(iter(man.claims))],
            "mode": 0o644,
            "owner": "portable-resume-owned",
        }
        # Corrupt on disk by writing raw JSON that loads must reject
        import json

        raw_path = manifest_path(self.root)
        with open(raw_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        with self.assertRaises(DiagnosticError) as ctx:
            load_manifest(self.root)
        self.assertEqual(ctx.exception.code, "E_VERIFY_MISMATCH")
        self.assertTrue(outside.exists())
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep-me")

    def test_uninstall_does_not_remove_foreign_empty_skill_dir(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        foreign = Path(self.root) / "other-skill"
        foreign.mkdir(parents=True, exist_ok=True)
        uninstall_claim(host="claude", scope="project", root=self.root)
        self.assertTrue(foreign.exists())

    def test_verify_rejects_tampered_manifest_metadata_and_runtime_hash(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        path = Path(manifest_path(self.root))
        original = json.loads(path.read_text(encoding="utf-8"))

        for field, value in (
            ("schema_version", MANIFEST_SCHEMA + "-tampered"),
            ("bundle_version", BUNDLE_VERSION + "-tampered"),
            ("package_identity", "0" * 64),
        ):
            with self.subTest(field=field):
                tampered = dict(original)
                tampered[field] = value
                path.write_text(json.dumps(tampered), encoding="utf-8")
                with self.assertRaises(DiagnosticError) as caught:
                    verify_root(self.root)
                self.assertEqual(caught.exception.code, "E_VERIFY_MISMATCH")

        path.write_text(json.dumps(original), encoding="utf-8")
        runtime_rel = next(
            rel
            for rel in sorted(materialize_plan("claude"))
            if rel.startswith(".portable-resume/runtime/") and rel.endswith(".py")
        )
        runtime_path = Path(self.root) / runtime_rel
        tampered_bytes = runtime_path.read_bytes() + b"\n# tampered\n"
        runtime_path.write_bytes(tampered_bytes)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][runtime_rel]["sha256"] = sha256_bytes(tampered_bytes)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(DiagnosticError) as caught:
            verify_root(self.root)
        self.assertEqual(caught.exception.code, "E_VERIFY_MISMATCH")

    def test_partial_owned_replacements_are_rolled_back(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        manifest_before = Path(manifest_path(self.root)).read_bytes()
        rels = sorted(materialize_plan("claude"))[:3]
        before: dict[str, bytes] = {}
        for index, rel in enumerate((rels[0], rels[2])):
            path = Path(self.root) / rel
            data = f"pre-transaction-{index}\n".encode()
            path.write_bytes(data)
            before[rel] = data
        (Path(self.root) / rels[1]).unlink()

        plan = plan_install(host="claude", scope="project", root=self.root)
        original_replace = transaction_module.os.replace
        staged_replaces = 0

        def fail_third_staged_replace(src, dst, **kwargs):
            nonlocal staged_replaces
            # Descriptor-relative payload commits pass both src_dir_fd and dst_dir_fd.
            # Control-plane atomic journal/manifest replace also uses dir_fds — exclude those.
            if kwargs.get("src_dir_fd") is not None and kwargs.get("dst_dir_fd") is not None:
                if dst in {"journal.json", "manifest.json"}:
                    return original_replace(src, dst, **kwargs)
                staged_replaces += 1
                if staged_replaces == 3:
                    raise OSError("injected staged replace failure")
            return original_replace(src, dst, **kwargs)

        with mock.patch.object(transaction_module.os, "replace", side_effect=fail_third_staged_replace):
            with self.assertRaises(OSError):
                execute_install(plan)

        for rel, expected in before.items():
            self.assertEqual((Path(self.root) / rel).read_bytes(), expected)
        self.assertFalse((Path(self.root) / rels[1]).exists())
        self.assertEqual(Path(manifest_path(self.root)).read_bytes(), manifest_before)
        self.assertFalse(Path(journal_path(self.root)).exists())

    def test_recover_restores_owned_file_after_interrupted_partial_commit(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        manifest_before = Path(manifest_path(self.root)).read_bytes()
        rels = sorted(materialize_plan("claude"))[:2]
        before: dict[str, bytes] = {}
        for index, rel in enumerate(rels):
            data = f"before-crash-{index}\n".encode()
            (Path(self.root) / rel).write_bytes(data)
            before[rel] = data

        plan = plan_install(host="claude", scope="project", root=self.root)
        original_replace = transaction_module.os.replace
        staged_replaces = 0

        def interrupt_second_staged_replace(src, dst, **kwargs):
            nonlocal staged_replaces
            if kwargs.get("src_dir_fd") is not None and kwargs.get("dst_dir_fd") is not None:
                if dst in {"journal.json", "manifest.json"}:
                    return original_replace(src, dst, **kwargs)
                staged_replaces += 1
                if staged_replaces == 2:
                    raise OSError("simulated process interruption")
            return original_replace(src, dst, **kwargs)

        with (
            mock.patch.object(transaction_module.os, "replace", side_effect=interrupt_second_staged_replace),
            mock.patch.object(transaction_module, "_attempt_rollback"),
        ):
            with self.assertRaises(OSError):
                execute_install(plan)

        self.assertTrue(Path(journal_path(self.root)).exists())
        recovered = recover_root(self.root)
        self.assertTrue(recovered["recovered"])
        for rel, expected in before.items():
            self.assertEqual((Path(self.root) / rel).read_bytes(), expected)
        self.assertEqual(Path(manifest_path(self.root)).read_bytes(), manifest_before)
        self.assertFalse(Path(journal_path(self.root)).exists())


if __name__ == "__main__":
    unittest.main()
