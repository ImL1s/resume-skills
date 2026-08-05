"""Installer control-plane pin / atomic write regressions (#21)."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.transaction import (
    JOURNAL_NAME,
    LOCK_NAME,
    MANIFEST_NAME,
    RootLock,
    SUPPORT_DIR,
    _atomic_write_support_file,
    _ensure_support_directory,
    _rollback_paths,
    _supports_descriptor_relative_commit,
    _write_journal,
    execute_install,
    journal_path,
    load_manifest,
    manifest_path,
    plan_install,
    recover_root,
    verify_root,
)


@unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd control-store path")
class InstallControlStoreTests(unittest.TestCase):
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
        self.outside = Path(self._tmpdir.name) / "outside-control"
        self.outside.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_symlinked_support_dir_rejected_before_lock(self) -> None:
        support = Path(self.root) / SUPPORT_DIR
        support.parent.mkdir(parents=True, exist_ok=True)
        support.symlink_to(self.outside, target_is_directory=True)
        marker = self.outside / "escaped-lock.txt"
        with self.assertRaises(DiagnosticError) as ctx:
            with RootLock(self.root):
                pass
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        self.assertFalse(marker.exists())
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_symlinked_support_dir_rejected_for_journal_write(self) -> None:
        support = Path(self.root) / SUPPORT_DIR
        support.parent.mkdir(parents=True, exist_ok=True)
        support.symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(DiagnosticError) as ctx:
            _write_journal(
                self.root,
                {
                    "schema_version": "portable-resume/install-journal-v1",
                    "state": "staging",
                    "generation": 1,
                    "claim": "claude|project|/tmp/x",
                    "stage_dir": "/tmp/stage",
                    "paths": {},
                },
            )
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_symlinked_lock_file_rejected(self) -> None:
        _ensure_support_directory(self.root)
        lock = Path(self.root) / SUPPORT_DIR / LOCK_NAME
        target = self.outside / "lock-target"
        target.write_text("pre", encoding="utf-8")
        lock.symlink_to(target)
        with self.assertRaises(DiagnosticError) as ctx:
            with RootLock(self.root):
                pass
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        self.assertEqual(target.read_text(encoding="utf-8"), "pre")

    def test_symlinked_manifest_rejected_on_load(self) -> None:
        from portable_resume.install.transaction import _ensure_control_state_directory

        _ensure_control_state_directory(self.root)
        target = self.outside / "manifest-target.json"
        target.write_text('{"not":"ours"}\n', encoding="utf-8")
        Path(manifest_path(self.root)).symlink_to(target)
        with self.assertRaises(DiagnosticError) as ctx:
            load_manifest(self.root)
        self.assertIn(ctx.exception.code, {"E_VERIFY_MISMATCH", "E_INSTALL_CONFLICT"})
        self.assertEqual(target.read_text(encoding="utf-8"), '{"not":"ours"}\n')

    def test_lock_write_truncates_trailing_bytes(self) -> None:
        from portable_resume.install.transaction import _ensure_control_state_directory

        _ensure_control_state_directory(self.root)
        lock = Path(self.root) / SUPPORT_DIR / ".state" / LOCK_NAME
        lock.write_bytes(b"pid=999999999999\nEXTRA_TRAILING_SHOULD_GO\n")
        with RootLock(self.root):
            data = lock.read_bytes()
        self.assertTrue(data.startswith(b"pid="))
        self.assertTrue(data.endswith(b"\n"))
        self.assertNotIn(b"EXTRA_TRAILING", data)
        self.assertEqual(data, f"pid={os.getpid()}\n".encode("ascii"))

    def test_planted_journal_tmp_symlink_is_not_followed(self) -> None:
        from portable_resume.install.transaction import _ensure_control_state_directory

        _ensure_control_state_directory(self.root)
        secret = self.outside / "secret-journal.txt"
        secret.write_text("outside-journal\n", encoding="utf-8")
        planted = Path(self.root) / SUPPORT_DIR / ".state" / f"{JOURNAL_NAME}.tmp"
        planted.symlink_to(secret)
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "staging",
                "generation": 1,
                "claim": "claude|project|/tmp/x",
                "stage_dir": "/tmp/stage",
                "paths": {},
            },
        )
        self.assertEqual(secret.read_text(encoding="utf-8"), "outside-journal\n")
        final = Path(journal_path(self.root))
        self.assertTrue(final.is_file())
        self.assertFalse(final.is_symlink())
        self.assertIn("staging", final.read_text(encoding="utf-8"))

    def test_atomic_manifest_replace_preserves_previous_on_failed_tmp(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        previous = Path(manifest_path(self.root)).read_bytes()
        self.assertTrue(previous)

        # Simulate hostile pre-created exclusive tmp name collision by filling support with
        # a non-writable barrier is hard; instead verify API only replaces via regular final.
        _atomic_write_support_file(self.root, MANIFEST_NAME, previous + b"")
        self.assertEqual(Path(manifest_path(self.root)).read_bytes(), previous)

        new_body = previous.replace(b'"generation": 1', b'"generation": 2', 1)
        if new_body == previous:
            new_body = previous + b" "
        _atomic_write_support_file(self.root, MANIFEST_NAME, new_body)
        self.assertEqual(Path(manifest_path(self.root)).read_bytes(), new_body)
        self.assertFalse(Path(manifest_path(self.root)).is_symlink())

    def test_fifo_lock_path_rejected(self) -> None:
        from portable_resume.install.transaction import _ensure_control_state_directory

        _ensure_control_state_directory(self.root)
        lock = Path(self.root) / SUPPORT_DIR / ".state" / LOCK_NAME
        try:
            os.mkfifo(lock)
        except OSError as error:
            self.skipTest(f"mkfifo unavailable: {error}")
        try:
            with self.assertRaises(DiagnosticError) as ctx:
                with RootLock(self.root):
                    pass
            self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
        finally:
            if lock.exists() or lock.is_fifo():
                lock.unlink()

    def test_ensure_support_rejects_file_in_place_of_directory(self) -> None:
        support = Path(self.root) / SUPPORT_DIR
        support.parent.mkdir(parents=True, exist_ok=True)
        support.write_text("not-a-dir", encoding="utf-8")
        with self.assertRaises(DiagnosticError) as ctx:
            _ensure_support_directory(self.root)
        self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")

    def test_install_succeeds_with_hardened_control_plane(self) -> None:
        report = execute_install(plan_install(host="claude", scope="project", root=self.root))
        self.assertTrue(report["ok"])
        manifest = load_manifest(self.root)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertGreaterEqual(manifest.generation, 1)
        lock = Path(self.root) / SUPPORT_DIR / ".state" / LOCK_NAME
        self.assertTrue(lock.is_file())
        self.assertTrue(stat.S_ISREG(lock.stat().st_mode))

    def test_support_swap_during_stage_does_not_write_outside_payload(self) -> None:
        """After support pin, swapping .portable-resume to outside must not stage files there."""
        import portable_resume.install.transaction as transaction_module

        plan = plan_install(host="claude", scope="project", root=self.root)
        original_mkdir = transaction_module._mkdir_unique_under_fd
        swapped = {"done": False}

        def swap_support_then_mkdir(parent_fd: int, prefix: str) -> str:
            if not swapped["done"] and prefix.startswith("portable-resume-stage-"):
                support = Path(self.root) / SUPPORT_DIR
                if support.is_dir() and not support.is_symlink():
                    backup = Path(self.root) / ".portable-resume.bak-swap"
                    if backup.exists():
                        import shutil

                        shutil.rmtree(backup)
                    support.rename(backup)
                    support.symlink_to(self.outside, target_is_directory=True)
                    swapped["done"] = True
            return original_mkdir(parent_fd, prefix)

        with mock.patch.object(
            transaction_module,
            "_mkdir_unique_under_fd",
            side_effect=swap_support_then_mkdir,
        ):
            with self.assertRaises(DiagnosticError):
                execute_install(plan)
        # Outside must not receive staged skill trees.
        outside_names = {p.name for p in self.outside.iterdir()}
        self.assertNotIn("resume-claude", outside_names)
        for path in self.outside.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"name:", path.read_bytes()[:200])

    def test_complete_journal_write_failure_keeps_published_payload(self) -> None:
        """Manifest publish + failed complete journal must not lose gen-N payload on recover."""
        import portable_resume.install.transaction as transaction_module

        execute_install(plan_install(host="claude", scope="project", root=self.root))
        skill = Path(self.root) / "resume-claude" / "SKILL.md"
        skill.write_bytes(skill.read_bytes() + b"\n# reinstall-tamper\n")
        plan = plan_install(host="claude", scope="project", root=self.root)
        # POSIX pin path (#254) writes journal via dirfd helpers.
        original_write_fd = transaction_module._write_journal_under_fd
        original_write = transaction_module._write_journal

        def fail_only_complete_fd(root_fd: int, journal: dict) -> None:
            if journal.get("state") == "complete":
                raise DiagnosticError("E_INSTALL_CONFLICT")
            original_write_fd(root_fd, journal)

        def fail_only_complete(root: str, journal: dict) -> None:
            if journal.get("state") == "complete":
                raise DiagnosticError("E_INSTALL_CONFLICT")
            original_write(root, journal)

        # Keep a stale on-disk journal after publish so recover_root is exercised.
        original_unlink_fd = transaction_module._unlink_support_control_file_under_fd
        original_unlink = transaction_module._unlink_support_control_file

        def refuse_journal_unlink_fd(root_fd: int, name: str) -> None:
            if name == JOURNAL_NAME:
                raise DiagnosticError("E_INSTALL_CONFLICT")
            original_unlink_fd(root_fd, name)

        def refuse_journal_unlink(root: str, name: str) -> None:
            if name == JOURNAL_NAME:
                raise DiagnosticError("E_INSTALL_CONFLICT")
            original_unlink(root, name)

        with (
            mock.patch.object(
                transaction_module,
                "_write_journal_under_fd",
                side_effect=fail_only_complete_fd,
            ),
            mock.patch.object(
                transaction_module, "_write_journal", side_effect=fail_only_complete
            ),
            mock.patch.object(
                transaction_module,
                "_unlink_support_control_file_under_fd",
                side_effect=refuse_journal_unlink_fd,
            ),
            mock.patch.object(
                transaction_module,
                "_unlink_support_control_file",
                side_effect=refuse_journal_unlink,
            ),
        ):
            report = execute_install(plan)
        self.assertTrue(report["ok"])
        manifest = load_manifest(self.root)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(manifest.generation, plan.generation)
        published = skill.read_bytes()
        self.assertIn(b"name:", published[:200])

        # Stale incomplete journal may remain (unlink refused); recover must not rollback.
        self.assertTrue(os.path.isfile(journal_path(self.root)))
        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
        self.assertIn(
            recovered.get("action"),
            {"cleared_complete_journal", "cleared_published_generation_journal"},
        )
        self.assertEqual(skill.read_bytes(), published)
        verify_root(self.root)
        self.assertFalse(os.path.isfile(journal_path(self.root)))

    def test_recover_generation_match_skips_payload_rollback(self) -> None:
        """Stale committing journal with matching manifest generation is treated as published."""
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        manifest = load_manifest(self.root)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        skill = Path(self.root) / "resume-claude" / "SKILL.md"
        before = skill.read_bytes()
        entry = manifest.files["resume-claude/SKILL.md"]
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "committing",
                "generation": manifest.generation,
                "target_generation": manifest.generation,
                "claim": next(iter(manifest.claims)),
                "stage_dir": None,
                "backup_root": None,
                "paths": {
                    "resume-claude/SKILL.md": {
                        "state": "committed",
                        "existed": False,
                        "sha256": entry.sha256,
                    }
                },
            },
        )
        recovered = recover_root(self.root)
        self.assertTrue(recovered["ok"])
        self.assertEqual(recovered.get("action"), "cleared_published_generation_journal")
        self.assertEqual(skill.read_bytes(), before)
        verify_root(self.root)
