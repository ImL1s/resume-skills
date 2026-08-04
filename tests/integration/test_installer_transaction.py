"""Installer journal recovery, mutation blocking, and claim lifecycle (shipped APIs)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError, SOURCE_KEYS
from portable_resume.install.catalog import BUNDLE_VERSION, MANIFEST_SCHEMA, resolve_skill_root
from portable_resume.install.manifest import sha256_bytes
from portable_resume.install.render import materialize_plan
import portable_resume.install.transaction as transaction_module
from portable_resume.install.transaction import (
    execute_install,
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
