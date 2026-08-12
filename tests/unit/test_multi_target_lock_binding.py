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
    @staticmethod
    def _tree_entries(root: Path) -> list[tuple[str, str, bytes | None]]:
        entries: list[tuple[str, str, bytes | None]] = []
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append((rel, "symlink", os.readlink(path).encode()))
            elif path.is_dir():
                entries.append((rel, "dir", None))
            else:
                entries.append((rel, "file", path.read_bytes()))
        return entries

    def test_retarget_between_bind_and_lock_never_touches_new_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            phys_a = base / "phys_a"
            phys_b = base / "phys_b"
            phys_a.mkdir()
            phys_b.mkdir()
            (phys_a / "a.txt").write_bytes(b"a")
            (phys_b / "b.txt").write_bytes(b"b")
            leaf = base / "leaf"
            leaf.symlink_to(phys_a, target_is_directory=True)
            before_a = self._tree_entries(phys_a)
            before_b = self._tree_entries(phys_b)
            original_bind = transaction_module.bind_multi_target_roots

            def bind_then_retarget(
                targets: list[tuple[str, str]],
            ) -> list[MultiTargetBinding]:
                bindings = original_bind(targets)
                leaf.unlink()
                leaf.symlink_to(phys_b, target_is_directory=True)
                return bindings

            with mock.patch.object(
                transaction_module,
                "bind_multi_target_roots",
                side_effect=bind_then_retarget,
            ):
                with self.assertRaises(DiagnosticError) as ctx:
                    install_multi_targets([("claude", str(leaf))], scope="global")

            self.assertEqual(ctx.exception.code, "E_INSTALL_CONFLICT")
            self.assertEqual(self._tree_entries(phys_a), before_a)
            self.assertEqual(self._tree_entries(phys_b), before_b)

    def test_intermediate_symlink_root_is_rejected_before_outside_control_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            skills = outside / "skills"
            skills.mkdir()
            (skills / "sentinel.txt").write_bytes(b"keep")
            layout = base / "layout"
            layout.mkdir()
            (layout / "link").symlink_to(outside, target_is_directory=True)
            requested = layout / "link" / "skills"
            before = self._tree_entries(outside)

            with self.assertRaises(DiagnosticError) as caught:
                install_multi_targets([("claude", str(requested))], scope="global")

            self.assertIn(caught.exception.code, {"E_UNSAFE_PATH", "E_INSTALL_CONFLICT"})
            self.assertEqual(self._tree_entries(outside), before)

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

    def test_late_retarget_after_claim_check_does_not_mutate_wrong_tree(self) -> None:
        """#253: retarget leaf only after locked replan/claim, during mutation classify.

        Preflight ``plan_install`` may still classify the leaf spelling; that is
        not the residual window. Only record/assert classify roots while
        ``execute_install`` is on the stack (mutation body). Mutation roots must
        be frozen physical paths so a late leaf retarget cannot redirect writes.
        """
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            phys_a = base / "phys_a"
            phys_b = base / "phys_b"
            phys_a.mkdir()
            phys_b.mkdir()
            # Marker so we can prove phys_b payload was not clobbered by a hijack.
            sentinel = phys_b / "pre-existing.txt"
            sentinel.write_bytes(b"keep")
            leaf_a = base / "leaf_a"
            leaf_b = base / "leaf_b"
            leaf_a.symlink_to(phys_a, target_is_directory=True)
            leaf_b.symlink_to(phys_b, target_is_directory=True)

            original_classify = transaction_module._classify_dest
            original_execute = transaction_module.execute_install
            retargeted = {"done": False}
            in_execute = {"active": False}
            mutation_classify_roots: list[str] = []

            def retarget_on_mutation_classify(*, root: str, **kwargs: object):
                # Ignore preflight / locked replan classify noise (leaf spellings).
                if in_execute["active"]:
                    mutation_classify_roots.append(root)
                    # Inject after identity/claim checks entered the mutation body.
                    if not retargeted["done"]:
                        if leaf_a.is_symlink() or leaf_a.exists():
                            leaf_a.unlink()
                        leaf_a.symlink_to(phys_b, target_is_directory=True)
                        retargeted["done"] = True
                return original_classify(root=root, **kwargs)

            def wrap_execute(plan, *, force_with_backup=False, lock=None, locked_root=None):
                in_execute["active"] = True
                try:
                    return original_execute(
                        plan,
                        force_with_backup=force_with_backup,
                        lock=lock,
                        locked_root=locked_root,
                    )
                finally:
                    in_execute["active"] = False

            with mock.patch.object(
                transaction_module,
                "_classify_dest",
                side_effect=retarget_on_mutation_classify,
            ), mock.patch.object(
                transaction_module,
                "execute_install",
                side_effect=wrap_execute,
            ):
                results = install_multi_targets(
                    [("claude", str(leaf_a)), ("grok", str(leaf_b))],
                    scope="global",
                )
            self.assertTrue(retargeted["done"])
            self.assertTrue(all(r["ok"] for r in results))
            self.assertTrue(mutation_classify_roots)
            phys_keys = {
                os.path.realpath(str(phys_a)),
                os.path.realpath(str(phys_b)),
            }
            for seen in mutation_classify_roots:
                # Mutations never used the leaf spelling (would re-follow retarget).
                self.assertNotEqual(seen, str(leaf_a))
                self.assertFalse(os.path.islink(seen))
                self.assertIn(os.path.realpath(seen), phys_keys)
            # Correct trees installed; retarget destination payload not hijacked.
            self.assertIsNotNone(load_manifest(str(phys_a)))
            self.assertIsNotNone(load_manifest(str(phys_b)))
            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_execute_install_threads_frozen_locked_root_not_lock_root(self) -> None:
        """Multi-target must pass locked_root=physical_key into execute_install."""
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

            captured: list[dict[str, object]] = []
            original = transaction_module.execute_install

            def capture_execute(plan, *, force_with_backup=False, lock=None, locked_root=None):
                captured.append(
                    {
                        "plan_root": plan.root,
                        "lock_root": None if lock is None else lock.root,
                        "locked_root": locked_root,
                    }
                )
                return original(
                    plan,
                    force_with_backup=force_with_backup,
                    lock=lock,
                    locked_root=locked_root,
                )

            with mock.patch.object(
                transaction_module,
                "execute_install",
                side_effect=capture_execute,
            ):
                install_multi_targets(
                    [("claude", str(leaf_a)), ("grok", str(leaf_b))],
                    scope="global",
                )
            self.assertEqual(len(captured), 2)
            for item in captured:
                self.assertIsNotNone(item["locked_root"])
                # Frozen root is physical, not the leaf symlink spelling.
                self.assertFalse(os.path.islink(str(item["locked_root"])))
                self.assertEqual(
                    os.path.realpath(str(item["locked_root"])),
                    os.path.realpath(str(item["plan_root"])),
                )
                # Must not pass only lock.root as mutation root when leaf symlink.
                if os.path.islink(str(item["lock_root"])):
                    self.assertNotEqual(item["locked_root"], item["lock_root"])


if __name__ == "__main__":
    unittest.main()
