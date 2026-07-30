"""#22: journaled uninstall crash recovery and locked verify coherence."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.manifest import sha256_file
import portable_resume.install.transaction as transaction_module
from portable_resume.install.transaction import (
    STAGE_PREFIX,
    SUPPORT_DIR,
    RootLock,
    _supports_descriptor_relative_commit,
    _write_journal,
    execute_install,
    journal_path,
    load_manifest,
    plan_install,
    recover_root,
    uninstall_claim,
    verify_root,
)


@unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd uninstall journal path")
class UninstallJournalTransactionTests(unittest.TestCase):
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

    def _install(self) -> None:
        report = execute_install(plan_install(host="claude", scope="project", root=self.root))
        self.assertTrue(report["ok"])

    def test_uninstall_happy_path_clears_journal_and_manifest(self) -> None:
        self._install()
        verify_root(self.root)
        result = uninstall_claim(host="claude", scope="project", root=self.root)
        self.assertTrue(result["ok"])
        self.assertTrue(result["removed_files"])
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        self.assertIsNone(load_manifest(self.root))
        skill = Path(self.root) / "resume-claude" / "SKILL.md"
        self.assertFalse(skill.is_file())

    def test_uninstall_mid_delete_crash_rolls_back_to_old_generation(self) -> None:
        self._install()
        skill = Path(self.root) / "resume-claude" / "SKILL.md"
        before = skill.read_bytes()
        base_generation = load_manifest(self.root).generation
        orig = transaction_module._unlink_regular_under_root_fd
        calls = {"n": 0}

        def boom(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 3:
                raise DiagnosticError("E_INSTALL_CONFLICT")
            return orig(*args, **kwargs)

        with mock.patch.object(
            transaction_module,
            "_unlink_regular_under_root_fd",
            side_effect=boom,
        ):
            with self.assertRaises(DiagnosticError) as ctx:
                uninstall_claim(host="claude", scope="project", root=self.root)
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        # Exception-path rollback should restore payload and clear the journal.
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        manifest = load_manifest(self.root)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(manifest.generation, base_generation)
        self.assertTrue(skill.is_file())
        self.assertEqual(skill.read_bytes(), before)
        verify_root(self.root)

    def test_incomplete_uninstall_journal_recover_restores_payload(self) -> None:
        self._install()
        claim = next(iter(load_manifest(self.root).claims))
        skill = Path(self.root) / "resume-claude" / "SKILL.md"
        body = skill.read_bytes()
        digest = sha256_file(str(skill))
        stage = Path(self.root) / SUPPORT_DIR / f"{STAGE_PREFIX}sim-incomplete"
        rollback = stage / ".rollback" / "resume-claude"
        rollback.mkdir(parents=True)
        snap = rollback / "SKILL.md"
        snap.write_bytes(body)
        skill.unlink()
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "committing",
                "generation": 1,
                "target_generation": 2,
                "claim": claim,
                "stage_dir": str(stage),
                "backup_root": None,
                "operation": "uninstall",
                "paths": {
                    "resume-claude/SKILL.md": {
                        "state": "removed",
                        "existed": True,
                        "rollback_backup": str(snap),
                        "original_sha256": digest,
                        "sha256": digest,
                    }
                },
            },
        )
        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
        self.assertTrue(recovered["recovered"])
        self.assertEqual(recovered.get("action"), "restored_from_journal")
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        self.assertTrue(skill.is_file())
        self.assertEqual(skill.read_bytes(), body)
        verify_root(self.root)

    def test_published_uninstall_journal_recover_does_not_restore_payload(self) -> None:
        self._install()
        claim = next(iter(load_manifest(self.root).claims))
        skill = Path(self.root) / "resume-claude" / "SKILL.md"
        body = skill.read_bytes()
        digest = sha256_file(str(skill))
        stage = Path(self.root) / SUPPORT_DIR / f"{STAGE_PREFIX}sim-published"
        rollback = stage / ".rollback" / "resume-claude"
        rollback.mkdir(parents=True)
        snap = rollback / "SKILL.md"
        snap.write_bytes(body)
        skill.unlink()
        os.unlink(os.path.join(self.root, SUPPORT_DIR, "manifest.json"))
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "publishing_manifest",
                "generation": 1,
                "target_generation": 2,
                "claim": claim,
                "stage_dir": str(stage),
                "backup_root": None,
                "operation": "uninstall",
                "paths": {
                    "resume-claude/SKILL.md": {
                        "state": "removed",
                        "existed": True,
                        "rollback_backup": str(snap),
                        "original_sha256": digest,
                        "sha256": digest,
                    }
                },
            },
        )
        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
        self.assertTrue(recovered["recovered"])
        self.assertIn(recovered.get("action"), {
            "cleared_published_generation_journal",
            "cleared_complete_journal",
        })
        self.assertFalse(os.path.isfile(journal_path(self.root)))
        self.assertFalse(skill.is_file())
        self.assertIsNone(load_manifest(self.root))

    def test_verify_acquires_root_lock(self) -> None:
        self._install()
        holder_started = threading.Event()
        release = threading.Event()

        def hold_lock() -> None:
            with RootLock(self.root, wait_seconds=5.0):
                holder_started.set()
                release.wait(timeout=5.0)

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(holder_started.wait(timeout=2.0))
        try:
            # Short wait so the concurrent verify finishes while the lock is held.
            with mock.patch.object(
                transaction_module,
                "RootLock",
                side_effect=lambda root, *, wait_seconds=5.0: RootLock(root, wait_seconds=0.35),
            ):
                with self.assertRaises(DiagnosticError) as ctx:
                    verify_root(self.root)
            self.assertEqual(ctx.exception.code, "E_INSTALL_BUSY")
        finally:
            release.set()
            holder.join(timeout=5)

    def test_verify_pending_journal_is_recovery_not_mismatch(self) -> None:
        self._install()
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "committing",
                "generation": 1,
                "claim": "synthetic",
                "stage_dir": None,
                "paths": {},
                "operation": "uninstall",
            },
        )
        with self.assertRaises(DiagnosticError) as ctx:
            verify_root(self.root)
        self.assertEqual(ctx.exception.code, "E_RECOVERY_REQUIRED")

    def test_verify_never_installed_root_is_pure(self) -> None:
        empty = Path(self._tmpdir.name) / "empty-skills"
        empty.mkdir()
        with self.assertRaises(DiagnosticError) as ctx:
            verify_root(str(empty))
        self.assertEqual(ctx.exception.code, "E_VERIFY_MISMATCH")
        self.assertFalse((empty / SUPPORT_DIR).exists())

    def test_post_snapshot_drift_is_retained_not_overwritten_on_rollback(self) -> None:
        self._install()
        skill = Path(self.root) / "resume-claude" / "SKILL.md"
        original = skill.read_bytes()
        user_edit = original + b"\n# concurrent-user-edit\n"
        orig_unlink = transaction_module._unlink_regular_under_root_fd

        def unlink_then_drift(root_fd, rel, *, expected_sha256=None):
            if rel == "resume-claude/SKILL.md":
                # Simulate concurrent edit after stage snapshot: digest no longer matches.
                skill.write_bytes(user_edit)
                return False
            return orig_unlink(root_fd, rel, expected_sha256=expected_sha256)

        with mock.patch.object(
            transaction_module,
            "_unlink_regular_under_root_fd",
            side_effect=unlink_then_drift,
        ):
            # Force a later failure after SKILL.md was classified retained.
            real_write = transaction_module._write_journal
            writes = {"n": 0}

            def write_then_fail(root, journal):
                writes["n"] += 1
                real_write(root, journal)
                # After committing path updates include a retained entry, fail.
                paths = journal.get("paths") or {}
                if journal.get("state") == "committing" and any(
                    isinstance(m, dict) and m.get("state") == "retained" for m in paths.values()
                ):
                    raise DiagnosticError("E_INSTALL_CONFLICT")

            with mock.patch.object(
                transaction_module,
                "_write_journal",
                side_effect=write_then_fail,
            ):
                with self.assertRaises(DiagnosticError) as ctx:
                    uninstall_claim(host="claude", scope="project", root=self.root)
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        # User edit must survive rollback of the incomplete uninstall.
        self.assertTrue(skill.is_file())
        self.assertEqual(skill.read_bytes(), user_edit)


if __name__ == "__main__":
    unittest.main()
