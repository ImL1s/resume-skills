"""Unit tests for WindowsFilesystemBackend relative mutation primitives (#125 Phase 4)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError, ExitCode
from portable_resume.install.catalog import resolve_skill_root
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


@unittest.skipUnless(os.name == "nt", "Windows relative mutations require os.name == 'nt'")
class WindowsRelativeMutationsTests(unittest.TestCase):
    """Test WindowsFilesystemBackend relative mutation methods and security enforcement."""

    def setUp(self) -> None:
        self.backend = WindowsFilesystemBackend()

    def test_capabilities_relative_mutations_enabled(self) -> None:
        self.assertIs(self.backend.capabilities.relative_mutations, True)
        self.assertIs(self.backend.capabilities.exclusive_locking, True)
        self.assertIs(self.backend.capabilities.handle_locking, True)

    def test_mkdirs_beneath_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target = root / "a" / "b" / "c"
            res = self.backend.mkdirs_beneath(target, root=root)
            self.assertTrue(target.is_dir())
            self.assertEqual(Path(res), target.resolve())

    def test_mkdirs_beneath_existing_directory_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target = root / "existing"
            target.mkdir()
            res = self.backend.mkdirs_beneath(target, root=root)
            self.assertEqual(Path(res), target.resolve())

    def test_unlink_beneath_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            sub = root / "sub"
            sub.mkdir()
            leaf = sub / "file.txt"
            leaf.write_bytes(b"hello")
            self.assertTrue(leaf.is_file())

            self.backend.unlink_beneath(leaf, root=root)
            self.assertFalse(leaf.exists())

    def test_replace_beneath_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            sub = root / "sub"
            sub.mkdir()
            src = sub / "source.txt"
            dst = sub / "target.txt"
            src.write_bytes(b"payload")

            self.backend.replace_beneath(src, dst, root=root)
            self.assertFalse(src.exists())
            self.assertTrue(dst.is_file())
            self.assertEqual(dst.read_bytes(), b"payload")

    def test_reparse_junction_escape_mkdirs_fails_closed(self) -> None:
        if not _HAS_WINAPI:
            self.skipTest("_winapi not available")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            ext_dir = tmp / "external"
            ext_dir.mkdir()
            root = tmp / "root"
            root.mkdir()
            junc = root / "junc"
            _winapi.CreateJunction(str(ext_dir), str(junc))

            escape_target = junc / "escaped"
            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.mkdirs_beneath(escape_target, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
            self.assertFalse((ext_dir / "escaped").exists())

    def test_reparse_junction_escape_unlink_fails_closed(self) -> None:
        if not _HAS_WINAPI:
            self.skipTest("_winapi not available")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            ext_dir = tmp / "external"
            ext_dir.mkdir()
            secret = ext_dir / "secret.txt"
            secret.write_bytes(b"topsecret")
            root = tmp / "root"
            root.mkdir()
            junc = root / "junc"
            _winapi.CreateJunction(str(ext_dir), str(junc))

            escape_target = junc / "secret.txt"
            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.unlink_beneath(escape_target, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
            self.assertTrue(secret.exists())
            self.assertEqual(secret.read_bytes(), b"topsecret")

    def test_reparse_junction_escape_replace_fails_closed(self) -> None:
        if not _HAS_WINAPI:
            self.skipTest("_winapi not available")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            ext_dir = tmp / "external"
            ext_dir.mkdir()
            secret = ext_dir / "secret.txt"
            secret.write_bytes(b"topsecret")
            root = tmp / "root"
            root.mkdir()
            junc = root / "junc"
            _winapi.CreateJunction(str(ext_dir), str(junc))

            src = root / "payload.txt"
            src.write_bytes(b"newpayload")
            escape_dst = junc / "secret.txt"

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.replace_beneath(src, escape_dst, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
            self.assertEqual(secret.read_bytes(), b"topsecret")
            self.assertTrue(src.exists())

    def test_rejection_of_parent_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            outside = root.parent / "outside.txt"

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.mkdirs_beneath(root / ".." / "outside", root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.unlink_beneath(outside, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.replace_beneath(outside, root / "dst.txt", root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_rejection_of_ads_colons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ads_path = root / "file.txt:stream"

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.mkdirs_beneath(ads_path, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.unlink_beneath(ads_path, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.replace_beneath(ads_path, root / "dst.txt", root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_rejection_of_reserved_device_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for reserved_name in ["CON", "NUL", "COM1", "LPT1.txt", "AUX.json"]:
                bad_path = root / reserved_name
                with self.assertRaises(DiagnosticError) as ctx:
                    self.backend.mkdirs_beneath(bad_path, root=root)
                self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

                with self.assertRaises(DiagnosticError) as ctx:
                    self.backend.unlink_beneath(bad_path, root=root)
                self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

                with self.assertRaises(DiagnosticError) as ctx:
                    self.backend.replace_beneath(bad_path, root / "dst.txt", root=root)
                self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_rejection_of_control_chars_and_malformed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for bad_str in ["dir\x00name", "dir ", "dir."]:
                bad_path = os.path.join(str(root), bad_str)
                with self.assertRaises(DiagnosticError) as ctx:
                    self.backend.mkdirs_beneath(bad_path, root=root)
                self.assertIn(ctx.exception.code, ("E_UNSAFE_PATH", "E_INVALID_INPUT"))

                with self.assertRaises(DiagnosticError) as ctx:
                    self.backend.unlink_beneath(bad_path, root=root)
                self.assertIn(ctx.exception.code, ("E_UNSAFE_PATH", "E_INVALID_INPUT"))

    def test_unlink_root_itself_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.unlink_beneath(root, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_replace_root_itself_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            src = root / "file.txt"
            src.write_bytes(b"content")

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.replace_beneath(root, src, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

            with self.assertRaises(DiagnosticError) as ctx:
                self.backend.replace_beneath(src, root, root=root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_product_cli_policy_b_fail_closed_gate(self) -> None:
        """Product CLI install/uninstall/recover must raise E_INSTALL_UNSUPPORTED_PLATFORM on nt."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "home"
            project = Path(tmp_dir) / "project"
            home.mkdir()
            project.mkdir()
            root = resolve_skill_root(
                host="claude",
                scope="project",
                project_dir=str(project),
                home_dir=str(home),
            )
            plan = plan_install(host="claude", scope="project", root=root)

            # execute_install fails closed
            with self.assertRaises(DiagnosticError) as ctx:
                execute_install(plan)
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED)
            self.assertFalse(Path(root).exists())

            # uninstall_claim fails closed
            skills_root = Path(tmp_dir) / "skills"
            skills_root.mkdir()
            sentinel = skills_root / "keep.txt"
            sentinel.write_bytes(b"unchanged")

            with self.assertRaises(DiagnosticError) as ctx:
                uninstall_claim(host="claude", scope="project", root=str(skills_root))
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(sentinel.read_bytes(), b"unchanged")

            # recover_root with journal fails closed
            support = skills_root / ".portable-resume" / ".state"
            support.mkdir(parents=True)
            journal = support / "journal.json"
            journal.write_text("{}", encoding="utf-8")

            with self.assertRaises(DiagnosticError) as ctx:
                recover_root(str(skills_root))
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            self.assertEqual(sentinel.read_bytes(), b"unchanged")


if __name__ == "__main__":
    unittest.main()
