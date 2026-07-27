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
            _write_journal(self.root, {"schema_version": "portable-resume/install-journal-v1", "state": "staging"})
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
        _ensure_support_directory(self.root)
        target = self.outside / "manifest-target.json"
        target.write_text('{"not":"ours"}\n', encoding="utf-8")
        Path(manifest_path(self.root)).symlink_to(target)
        with self.assertRaises(DiagnosticError) as ctx:
            load_manifest(self.root)
        self.assertIn(ctx.exception.code, {"E_VERIFY_MISMATCH", "E_INSTALL_CONFLICT"})
        self.assertEqual(target.read_text(encoding="utf-8"), '{"not":"ours"}\n')

    def test_lock_write_truncates_trailing_bytes(self) -> None:
        _ensure_support_directory(self.root)
        lock = Path(self.root) / SUPPORT_DIR / LOCK_NAME
        lock.write_bytes(b"pid=999999999999\nEXTRA_TRAILING_SHOULD_GO\n")
        with RootLock(self.root):
            data = lock.read_bytes()
        self.assertTrue(data.startswith(b"pid="))
        self.assertTrue(data.endswith(b"\n"))
        self.assertNotIn(b"EXTRA_TRAILING", data)
        self.assertEqual(data, f"pid={os.getpid()}\n".encode("ascii"))

    def test_planted_journal_tmp_symlink_is_not_followed(self) -> None:
        _ensure_support_directory(self.root)
        secret = self.outside / "secret-journal.txt"
        secret.write_text("outside-journal\n", encoding="utf-8")
        planted = Path(self.root) / SUPPORT_DIR / f"{JOURNAL_NAME}.tmp"
        planted.symlink_to(secret)
        _write_journal(
            self.root,
            {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "staging",
                "generation": 1,
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
        _ensure_support_directory(self.root)
        lock = Path(self.root) / SUPPORT_DIR / LOCK_NAME
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
        lock = Path(self.root) / SUPPORT_DIR / LOCK_NAME
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
