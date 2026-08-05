"""Immutable multi-target lock bindings (post-#250 residual P1)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install import transaction as transaction_module
from portable_resume.install.transaction import (
    MultiTargetBinding,
    RootLock,
    _assert_binding_still_matches_lock,
    bind_multi_target_roots,
    install_multi_targets,
    load_manifest,
)


class BindMultiTargetRootsTests(unittest.TestCase):
    def test_bindings_freeze_physical_key_from_requested_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical = base / "physical"
            physical.mkdir()
            leaf = base / "leaf"
            leaf.symlink_to(physical, target_is_directory=True)
            bindings = bind_multi_target_roots(
                [("claude", str(leaf)), ("grok", str(physical))]
            )
            self.assertEqual(len(bindings), 2)
            self.assertEqual(bindings[0].host, "claude")
            self.assertEqual(bindings[0].physical_key, os.path.realpath(physical))
            self.assertEqual(bindings[1].physical_key, os.path.realpath(physical))
            # Shared physical tree: same key for junction spelling and real dir.
            self.assertEqual(bindings[0].physical_key, bindings[1].physical_key)

    def test_assert_binding_fails_when_requested_root_retargeted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            phys_a = base / "a"
            phys_b = base / "b"
            phys_a.mkdir()
            phys_b.mkdir()
            leaf = base / "leaf"
            leaf.symlink_to(phys_a, target_is_directory=True)
            binding = MultiTargetBinding(
                host="claude",
                requested_root=str(leaf),
                physical_key=os.path.realpath(phys_a),
            )
            with RootLock(str(phys_a)) as lock:
                _assert_binding_still_matches_lock(binding, lock)
                leaf.unlink()
                leaf.symlink_to(phys_b, target_is_directory=True)
                with self.assertRaises(DiagnosticError) as ctx:
                    _assert_binding_still_matches_lock(binding, lock)
                self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")

    def test_select_lock_never_uses_post_lock_realpath_of_requested(self) -> None:
        """Structural: install_multi_targets must not re-key via realpath(requested)."""
        import inspect

        source = inspect.getsource(transaction_module.install_multi_targets)
        # After bindings are built, the dangerous pattern is realpath(root) for
        # lock_by_key selection from caller spellings. Allow realpath(lock.root)
        # and realpath(live_plan.root) identity checks only.
        self.assertIn("bind_multi_target_roots", source)
        self.assertIn("_assert_binding_still_matches_lock", source)
        self.assertIn("lock_by_key[binding.physical_key]", source)
        # Must not re-resolve the original loop variable `root` from targets
        # after locks for lock selection.
        post = source.split("bindings = bind_multi_target_roots", 1)[1]
        self.assertNotIn("os.path.realpath(root)", post)
        self.assertNotIn("realpath(root)", post)


@unittest.skipUnless(
    hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and os.name != "nt",
    "dirfd multi-root path (POSIX)",
)
class MultiTargetPostLockRetargetTests(unittest.TestCase):
    def test_post_lock_leaf_symlink_retarget_fails_closed(self) -> None:
        """After locks are held, retarget leaf A→B must fail the whole txn."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            phys_a = base / "phys_a"
            phys_b = base / "phys_b"
            phys_a.mkdir()
            phys_b.mkdir()
            leaf_a = base / "leaf_a"
            leaf_b = base / "leaf_b"
            leaf_a.symlink_to(phys_a, target_is_directory=True)
            leaf_b.symlink_to(phys_b, target_is_directory=True)

            original = transaction_module.require_no_pending_journal
            retargeted = {"done": False}

            def retarget_after_locks(root: str) -> None:
                # First journal check after all locks held: retarget leaf_a → phys_b.
                if not retargeted["done"]:
                    if leaf_a.is_symlink() or leaf_a.exists():
                        leaf_a.unlink()
                    leaf_a.symlink_to(phys_b, target_is_directory=True)
                    retargeted["done"] = True
                return original(root)

            with mock.patch.object(
                transaction_module,
                "require_no_pending_journal",
                side_effect=retarget_after_locks,
            ):
                with self.assertRaises(DiagnosticError) as ctx:
                    install_multi_targets(
                        [("claude", str(leaf_a)), ("grok", str(leaf_b))],
                        scope="global",
                    )
            self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
            self.assertTrue(retargeted["done"])
            # No successful ownership on either physical tree.
            self.assertIsNone(load_manifest(str(phys_a)))
            self.assertIsNone(load_manifest(str(phys_b)))


if __name__ == "__main__":
    unittest.main()
