"""Installer journal recovery, mutation blocking, and claim lifecycle (shipped APIs)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
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
                "backup_root": os.path.join(self.root, ".portable-resume", "backups", "x"),
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

    def test_journal_path_escape_is_ignored_on_recover(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        execute_install(plan)
        os.makedirs(os.path.join(self.root, ".portable-resume"), exist_ok=True)
        outside = Path(self._tmpdir.name) / "outside.txt"
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "committing",
                "generation": 2,
                "claim": "x",
                "stage_dir": None,
                "backup_root": None,
                "paths": {
                    "../outside.txt": {
                        "state": "committed",
                        "sha256": "00",
                        "backup": str(outside),
                    }
                },
            },
        )
        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
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
            if kwargs.get("src_dir_fd") is not None and kwargs.get("dst_dir_fd") is not None:
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
