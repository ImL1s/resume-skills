"""#245: leaf skill-root junction/symlink resolution for install RootLock."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.transaction import (
    RootLock,
    _execute_install_under_lock,
    execute_install,
    plan_install,
    resolve_skill_root_for_lock,
    verify_root,
)


class ResolveSkillRootForLockTests(unittest.TestCase):
    def test_real_directory_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            root.mkdir()
            resolved = resolve_skill_root_for_lock(str(root))
            self.assertEqual(os.path.realpath(resolved), os.path.realpath(root))

    def test_missing_root_returns_abspath(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "not-yet"
            resolved = resolve_skill_root_for_lock(str(missing))
            self.assertEqual(resolved, os.path.abspath(str(missing)))
            self.assertFalse(os.path.lexists(resolved))

    def test_leaf_symlink_resolves_to_real_directory(self) -> None:
        """POSIX parity: leaf skill-root symlink → physical directory (skills-sync)."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical = base / "real-skills"
            physical.mkdir()
            leaf = base / "gemini-skills"
            leaf.symlink_to(physical, target_is_directory=True)
            resolved = resolve_skill_root_for_lock(str(leaf))
            self.assertEqual(os.path.realpath(resolved), os.path.realpath(physical))
            self.assertFalse(os.path.islink(resolved))
            self.assertTrue(os.path.isdir(resolved))

    def test_leaf_symlink_to_file_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "not-a-dir"
            target.write_bytes(b"x")
            leaf = base / "skills"
            leaf.symlink_to(target)
            with self.assertRaises(DiagnosticError) as ctx:
                resolve_skill_root_for_lock(str(leaf))
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_regular_file_root_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "file-root"
            path.write_bytes(b"nope")
            with self.assertRaises(DiagnosticError) as ctx:
                resolve_skill_root_for_lock(str(path))
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_windows_reparse_attribute_resolves_like_symlink(self) -> None:
        """Simulate Win32 reparse bit on lstat without requiring real junctions."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical = base / "physical"
            physical.mkdir()
            leaf = base / "junction-spelling"
            leaf.mkdir()

            real_lstat = os.lstat

            def fake_lstat(path: str | os.PathLike[str], *args: object, **kwargs: object):
                st = real_lstat(path, *args, **kwargs)
                if os.path.abspath(os.fspath(path)) == os.path.abspath(str(leaf)):
                    # Pretend leaf is a reparse point (junction) while remaining a dir.
                    mode = st.st_mode
                    # Build a stat_result-like object with reparse attribute set.
                    return mock.Mock(
                        st_mode=mode,
                        st_file_attributes=0x400,
                        st_ino=st.st_ino,
                        st_dev=st.st_dev,
                        st_uid=getattr(st, "st_uid", 0),
                        st_gid=getattr(st, "st_gid", 0),
                        st_size=st.st_size,
                    )
                return st

            with mock.patch("portable_resume.install.transaction.os.lstat", side_effect=fake_lstat):
                with mock.patch(
                    "portable_resume.install.transaction.os.path.realpath",
                    return_value=os.path.realpath(physical),
                ):
                    resolved = resolve_skill_root_for_lock(str(leaf))
            self.assertEqual(os.path.realpath(resolved), os.path.realpath(physical))


class LockedRootMutationBindingTests(unittest.TestCase):
    def test_execute_install_under_lock_rejects_mismatched_locked_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            root.mkdir()
            other = Path(temporary) / "other"
            other.mkdir()
            plan = plan_install(host="claude", scope="project", root=str(root))
            with self.assertRaises(DiagnosticError) as ctx:
                _execute_install_under_lock(plan, locked_root=str(other))
            self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")

    def test_execute_install_mutations_use_locked_physical_root(self) -> None:
        """#245 Codex P1: pin payload/control writes to lock.root, not a repointable spelling."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical = base / "real-skills"
            physical.mkdir()
            leaf = base / "junction-spelling"
            leaf.symlink_to(physical, target_is_directory=True)
            plan = plan_install(host="claude", scope="project", root=str(leaf))
            # Simulate Windows RootLock bind: mutations must target physical root.
            result = _execute_install_under_lock(plan, locked_root=str(physical))
            self.assertTrue(result["ok"])
            self.assertTrue((physical / ".portable-resume" / ".state" / "manifest.json").is_file())
            # Junction spelling still observes the same tree via the link.
            verified = verify_root(str(leaf))
            self.assertTrue(verified["ok"])


@unittest.skipUnless(
    os.name == "nt" and hasattr(os, "name"),
    "RootLock Win32 leaf-junction enter requires Windows",
)
class RootLockWindowsLeafJunctionTests(unittest.TestCase):
    def test_leaf_junction_rootlock_and_install_verify(self) -> None:
        """#245: install+verify via leaf skill-root junction spelling succeeds."""
        try:
            import _winapi
        except ImportError:  # pragma: no cover
            self.skipTest("_winapi unavailable")

        from portable_resume.install.transaction import execute_install, plan_install, verify_root
        from portable_resume.platform_fs.select import _reset_backend_cache

        _reset_backend_cache()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                physical = base / "real-skills"
                physical.mkdir()
                leaf = base / "gemini-skills"
                # CreateJunction(src, dst): dst is the junction path, src is target.
                # WinAPI: CreateJunction(name, target_dir) — check signature.
                _winapi.CreateJunction(str(physical), str(leaf))
                self.assertTrue(os.path.isdir(leaf))
                st = os.lstat(leaf)
                self.assertTrue(bool(getattr(st, "st_file_attributes", 0) & 0x400) or os.path.islink(leaf))

                with RootLock(str(leaf)) as lock:
                    self.assertEqual(os.path.realpath(lock.root), os.path.realpath(physical))
                    self.assertFalse(
                        bool(getattr(os.lstat(lock.root), "st_file_attributes", 0) & 0x400)
                        and not os.path.isdir(lock.root)
                    )
                    self.assertTrue((Path(lock.root) / ".portable-resume" / ".state").is_dir())

                plan = plan_install(host="claude", scope="project", root=str(leaf))
                result = execute_install(plan)
                self.assertTrue(result["ok"])
                # Control state must land on the physical tree (junction target).
                self.assertTrue((physical / ".portable-resume" / ".state" / "manifest.json").is_file())
                verified = verify_root(str(leaf))
                self.assertTrue(verified["ok"])
                verified_phys = verify_root(str(physical))
                self.assertTrue(verified_phys["ok"])
        finally:
            _reset_backend_cache()


if __name__ == "__main__":
    unittest.main()
