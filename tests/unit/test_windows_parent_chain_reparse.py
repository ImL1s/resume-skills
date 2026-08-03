"""Unit test suite for Windows parent-chain reparse point defenses (Issue #125 Phase 5)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.transaction import (
    execute_install,
    plan_install,
    recover_root,
    uninstall_claim,
)
from portable_resume.platform_fs.windows import WindowsFilesystemBackend

try:
    import _winapi

    _HAS_WINAPI = True
except ImportError:
    _HAS_WINAPI = False


@unittest.skipUnless(os.name == "nt", "Windows parent-chain reparse tests require os.name == 'nt'")
class WindowsParentChainReparseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name).resolve()
        self.root_dir = (self.tmp_path / "skill_root").resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.external_dir = (self.tmp_path / "external").resolve()
        self.external_dir.mkdir(parents=True, exist_ok=True)
        self.backend = WindowsFilesystemBackend()

    def create_junction(self, src: Path, dst_target: Path) -> None:
        if not _HAS_WINAPI:
            self.skipTest("_winapi is not available on this platform")
        _winapi.CreateJunction(str(src.resolve()), str(dst_target))

    # -------------------------------------------------------------------------
    # 1. Mid-path junction escape tests
    # -------------------------------------------------------------------------

    def test_mkdirs_beneath_midpath_junction_escape_rejected(self) -> None:
        sub = self.root_dir / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        junc = sub / "junc"
        self.create_junction(self.external_dir, junc)

        target_dir = junc / "escaped_dir" / "nested"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.mkdirs_beneath(target_dir, root=self.root_dir)

        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
        self.assertFalse((self.external_dir / "escaped_dir").exists())

    def test_unlink_beneath_midpath_junction_escape_rejected(self) -> None:
        secret = self.external_dir / "secret.txt"
        secret.write_bytes(b"sensitive_data")

        sub = self.root_dir / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        junc = sub / "junc"
        self.create_junction(self.external_dir, junc)

        target_file = junc / "secret.txt"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.unlink_beneath(target_file, root=self.root_dir)

        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
        self.assertTrue(secret.exists())
        self.assertEqual(secret.read_bytes(), b"sensitive_data")

    def test_replace_beneath_midpath_junction_dst_escape_rejected(self) -> None:
        ext_target = self.external_dir / "ext_target.txt"
        ext_target.write_bytes(b"original_content")

        payload = self.root_dir / "payload.txt"
        payload.write_bytes(b"new_content")

        sub = self.root_dir / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        junc = sub / "junc"
        self.create_junction(self.external_dir, junc)

        target_file = junc / "ext_target.txt"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(payload, target_file, root=self.root_dir)

        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
        self.assertEqual(ext_target.read_bytes(), b"original_content")
        self.assertTrue(payload.exists())

    def test_replace_beneath_midpath_junction_src_escape_rejected(self) -> None:
        ext_source = self.external_dir / "ext_source.txt"
        ext_source.write_bytes(b"ext_source_content")

        target = self.root_dir / "target.txt"
        target.write_bytes(b"target_content")

        sub = self.root_dir / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        junc = sub / "junc"
        self.create_junction(self.external_dir, junc)

        src_file = junc / "ext_source.txt"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(src_file, target, root=self.root_dir)

        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
        self.assertTrue(ext_source.exists())
        self.assertEqual(target.read_bytes(), b"target_content")

    def test_acquire_exclusive_lock_midpath_junction_escape_rejected(self) -> None:
        support_junc = self.root_dir / ".portable-resume"
        self.create_junction(self.external_dir, support_junc)

        lock_file = support_junc / ".state" / "install.lock"

        with self.assertRaises(DiagnosticError) as ctx:
            with self.backend.acquire_exclusive_lock(lock_file):
                pass

        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
        self.assertFalse((self.external_dir / ".state").exists())

    def test_inspect_object_identity_midpath_junction_rejected(self) -> None:
        ext_file = self.external_dir / "ext.txt"
        ext_file.write_bytes(b"ext")

        sub = self.root_dir / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        junc = sub / "junc"
        self.create_junction(self.external_dir, junc)

        target = junc / "ext.txt"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.inspect_object_identity(target, root=self.root_dir)

        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_read_regular_stable_midpath_junction_rejected(self) -> None:
        ext_file = self.external_dir / "ext.txt"
        ext_file.write_bytes(b"ext")

        sub = self.root_dir / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        junc = sub / "junc"
        self.create_junction(self.external_dir, junc)

        target = junc / "ext.txt"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.read_regular_stable(target, root=self.root_dir)

        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    # -------------------------------------------------------------------------
    # 2. Clean paths under root continue to succeed
    # -------------------------------------------------------------------------

    def test_clean_paths_under_root_succeed(self) -> None:
        clean_dir = self.backend.mkdirs_beneath(
            self.root_dir / "dir1" / "dir2" / "dir3", root=self.root_dir
        )
        self.assertTrue(Path(clean_dir).exists())

        file_path = Path(clean_dir) / "test.txt"
        file_path.write_bytes(b"hello world")

        ident = self.backend.inspect_object_identity(file_path, root=self.root_dir)
        self.assertEqual(ident.object_type, "file")
        self.assertEqual(ident.size, 11)

        read_res = self.backend.read_regular_stable(file_path, root=self.root_dir)
        self.assertEqual(read_res.data, b"hello world")

        new_file_path = Path(clean_dir) / "replaced.txt"
        self.backend.replace_beneath(file_path, new_file_path, root=self.root_dir)
        self.assertFalse(file_path.exists())
        self.assertTrue(new_file_path.exists())

        lock_path = self.root_dir / ".portable-resume" / ".state" / "install.lock"
        with self.backend.acquire_exclusive_lock(lock_path) as fd:
            self.assertGreater(fd, 0)

        self.backend.unlink_beneath(new_file_path, root=self.root_dir)
        self.assertFalse(new_file_path.exists())

    # -------------------------------------------------------------------------
    # 3. Product CLI Policy B lifted (Phase 7)
    # -------------------------------------------------------------------------

    def test_product_cli_execute_install_succeeds_on_nt(self) -> None:
        """Phase 7: execute_install succeeds on real Windows."""
        dest_root = self.tmp_path / "dest_skill_root"
        plan = plan_install(host="claude", scope="project", root=str(dest_root), dry_run=False)

        res = execute_install(plan)

        self.assertTrue(res["ok"])
        self.assertFalse(res["dry_run"])
        self.assertTrue(dest_root.exists())

    def test_product_cli_uninstall_claim_succeeds_on_nt(self) -> None:
        """Phase 7: uninstall_claim succeeds on real Windows."""
        dest_root = self.tmp_path / "uninstall_root"
        dest_root.mkdir(parents=True, exist_ok=True)

        # First install, then uninstall
        plan = plan_install(host="claude", scope="project", root=str(dest_root))
        execute_install(plan)

        res = uninstall_claim(host="claude", scope="project", root=str(dest_root))
        self.assertTrue(res["ok"])

    def test_product_cli_recover_root_succeeds_on_nt(self) -> None:
        """Phase 7: recover_root succeeds on real Windows."""
        dest_root = self.tmp_path / "recover_root"
        state_dir = dest_root / ".portable-resume" / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        journal = state_dir / "journal.json"
        import json
        journal_data = {
            "schema_version": "portable-resume/install-journal-v1",
            "state": "staging",
            "generation": 1,
            "claim": "claude:project",
            "stage_dir": str(state_dir / "portable-resume-stage-test"),
            "operation": "install",
            "paths": {},
        }
        journal.write_text(json.dumps(journal_data), encoding="utf-8")
        keep_file = dest_root / "keep.txt"
        keep_file.write_bytes(b"keep")

        res = recover_root(str(dest_root))
        self.assertTrue(res["ok"])
        self.assertEqual(keep_file.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
