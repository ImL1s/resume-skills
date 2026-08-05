"""#254: POSIX RootLock pin — pathname rename/replace must not mutate replacement trees."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install import transaction as transaction_module
from portable_resume.install.transaction import (
    RootLock,
    install_multi_targets,
    load_manifest,
)


@unittest.skipUnless(
    hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and os.name != "nt",
    "POSIX dirfd pin path",
)
class PosixRootInodePinTests(unittest.TestCase):
    def test_root_fd_closed_on_enter_failure(self) -> None:
        """Failed lock enter must not leak a pinned root fd."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            root.mkdir()
            opened: list[int] = []
            original_open = transaction_module._open_skill_root_descriptor

            def track_open(path: str) -> int:
                fd = original_open(path)
                opened.append(fd)
                return fd

            with mock.patch.object(
                transaction_module,
                "_open_support_control_file_under_fd",
                side_effect=DiagnosticError("E_INSTALL_BUSY"),
            ), mock.patch.object(
                transaction_module,
                "_open_skill_root_descriptor",
                side_effect=track_open,
            ):
                with self.assertRaises(DiagnosticError):
                    with RootLock(str(root)):
                        pass
            # All tracked root fds must be closed (EBADF on fstat).
            for fd in opened:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_locked_root_rename_then_symlink_replacement_never_mutates_replacement(
        self,
    ) -> None:
        """After lock+claim path, rename A and put symlink→B at old path; never write B."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            phys_a = base / "phys_a"
            phys_b = base / "phys_b"
            phys_a.mkdir()
            phys_b.mkdir()
            sentinel = phys_b / "sentinel.txt"
            sentinel.write_bytes(b"keep-b")
            leaf_a = base / "leaf_a"
            leaf_b = base / "leaf_b"
            leaf_a.symlink_to(phys_a, target_is_directory=True)
            leaf_b.symlink_to(phys_b, target_is_directory=True)

            original_classify = transaction_module._classify_dest_under_fd
            original_execute = transaction_module.execute_install
            swapped = {"done": False}
            in_execute = {"active": False}
            phys_a_path = str(phys_a.resolve())
            phys_b_path = str(phys_b.resolve())

            def on_classify_under_fd(*, root_fd: int, **kwargs: object):
                if in_execute["active"] and not swapped["done"]:
                    # Late: rename locked physical A, place symlink to B at old path.
                    if os.path.isdir(phys_a_path) and not os.path.islink(phys_a_path):
                        os.rename(phys_a_path, str(base / "phys_a_moved"))
                        os.symlink(phys_b_path, phys_a_path)
                        swapped["done"] = True
                return original_classify(root_fd=root_fd, **kwargs)

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
                "_classify_dest_under_fd",
                side_effect=on_classify_under_fd,
            ), mock.patch.object(
                transaction_module,
                "execute_install",
                side_effect=wrap_execute,
            ):
                try:
                    results = install_multi_targets(
                        [("claude", str(leaf_a)), ("grok", str(leaf_b))],
                        scope="global",
                    )
                    ok = all(r.get("ok") for r in results)
                except DiagnosticError as error:
                    ok = False
                    results = error

            self.assertTrue(swapped["done"])
            # Replacement B must never receive claude-only wrong-tree install noise
            # beyond legitimate grok target. Sentinel intact; no journal under B
            # that belongs to a hijacked A install.
            self.assertEqual(sentinel.read_bytes(), b"keep-b")
            # phys_b may have grok ownership from host B — that is expected.
            # Ensure we did not leave install journal pending from a hijack.
            journal_b = phys_b / ".portable-resume" / ".state" / "journal.json"
            self.assertFalse(journal_b.is_file())
            # Symlink path must not be the sole mutation authority for A.
            # Either A_moved has ownership (continued via pin) or fail-closed with none.
            moved = base / "phys_a_moved"
            if ok:
                # Pin continued: original inode (moved) got the install.
                self.assertTrue(moved.is_dir())
                self.assertIsNotNone(load_manifest(str(moved)))
            else:
                # Fail closed is also acceptable.
                self.assertIsNone(load_manifest(str(moved)) if moved.exists() else None)

    def test_locked_root_rename_then_directory_replacement_never_mutates_replacement(
        self,
    ) -> None:
        """Rename A and create a *real directory* at old path — must not mutate it."""
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

            original_classify = transaction_module._classify_dest_under_fd
            original_execute = transaction_module.execute_install
            swapped = {"done": False}
            in_execute = {"active": False}
            phys_a_path = str(phys_a.resolve())
            replacement_marker = {"path": ""}

            def on_classify_under_fd(*, root_fd: int, **kwargs: object):
                if in_execute["active"] and not swapped["done"]:
                    if os.path.isdir(phys_a_path) and not os.path.islink(phys_a_path):
                        os.rename(phys_a_path, str(base / "phys_a_moved"))
                        # Real directory replacement (not symlink) — O_NOFOLLOW alone insufficient.
                        os.mkdir(phys_a_path)
                        marker = Path(phys_a_path) / "replacement-only.txt"
                        marker.write_bytes(b"do-not-touch")
                        replacement_marker["path"] = str(marker)
                        swapped["done"] = True
                return original_classify(root_fd=root_fd, **kwargs)

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
                "_classify_dest_under_fd",
                side_effect=on_classify_under_fd,
            ), mock.patch.object(
                transaction_module,
                "execute_install",
                side_effect=wrap_execute,
            ):
                try:
                    install_multi_targets(
                        [("claude", str(leaf_a)), ("grok", str(leaf_b))],
                        scope="global",
                    )
                except DiagnosticError:
                    pass

            self.assertTrue(swapped["done"])
            marker = Path(replacement_marker["path"])
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.read_bytes(), b"do-not-touch")
            # Replacement directory must not hold a portable-resume manifest/payload.
            repl = Path(phys_a_path)
            self.assertIsNone(load_manifest(str(repl)))
            self.assertFalse((repl / "resume-claude").exists())
            self.assertFalse(
                (repl / ".portable-resume" / ".state" / "journal.json").exists()
            )

    def test_compensation_uses_pinned_root_inode_after_path_replacement(self) -> None:
        """After first target succeeds, replace its path; compensation must not hit replacement."""
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

            original = transaction_module.execute_install
            calls = {"n": 0}
            phys_a_path = str(phys_a.resolve())

            def fail_second(plan, *, force_with_backup=False, lock=None, locked_root=None):
                calls["n"] += 1
                if calls["n"] == 2:
                    # First target fully completed (in ``completed``); then rename its
                    # physical root before failing the second target so compensation
                    # runs under the still-held pin (#254).
                    if os.path.isdir(phys_a_path) and not os.path.islink(phys_a_path):
                        os.rename(phys_a_path, str(base / "phys_a_moved"))
                        os.mkdir(phys_a_path)
                        (Path(phys_a_path) / "replacement-sentinel.txt").write_bytes(
                            b"keep"
                        )
                        # Pre-seed empty skill dir to detect wrongful path cleanup.
                        (Path(phys_a_path) / "resume-claude").mkdir()
                    raise OSError("injected second-target failure")
                return original(
                    plan,
                    force_with_backup=force_with_backup,
                    lock=lock,
                    locked_root=locked_root,
                )

            with mock.patch.object(
                transaction_module, "execute_install", side_effect=fail_second
            ):
                with self.assertRaises(OSError):
                    install_multi_targets(
                        [("claude", str(leaf_a)), ("grok", str(leaf_b))],
                        scope="global",
                    )

            # Replacement at old pathname must not be compensated/deleted into.
            repl_path = Path(phys_a_path)
            self.assertTrue((repl_path / "replacement-sentinel.txt").is_file())
            self.assertEqual(
                (repl_path / "replacement-sentinel.txt").read_bytes(), b"keep"
            )
            self.assertIsNone(load_manifest(str(repl_path)))
            # Pre-seeded empty dir must survive (pathname cleanup must not touch it).
            self.assertTrue((repl_path / "resume-claude").is_dir())
            self.assertEqual(list((repl_path / "resume-claude").iterdir()), [])
            # Original inode compensated via pin (install rolled back).
            # Empty ancestor dirs may remain when pathname cleanup is skipped after
            # rename (#254); payload + ownership must be gone.
            moved = base / "phys_a_moved"
            self.assertTrue(moved.is_dir())
            self.assertIsNone(load_manifest(str(moved)))
            self.assertFalse((moved / "resume-claude" / "SKILL.md").exists())
            self.assertFalse(
                any(moved.rglob("SKILL.md")),
                msg="compensated pin must not retain skill payloads",
            )

    def test_initial_leaf_symlink_happy_path(self) -> None:
        """#245–#253: initial leaf symlink still installs into the physical tree."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical = base / "physical"
            physical.mkdir()
            leaf = base / "leaf"
            leaf.symlink_to(physical, target_is_directory=True)
            results = install_multi_targets(
                [("claude", str(leaf)), ("grok", str(physical))],
                scope="global",
            )
            self.assertTrue(all(r["ok"] for r in results))
            self.assertIsNotNone(load_manifest(str(physical)))
            self.assertTrue((physical / "resume-claude").is_dir())
            self.assertTrue((physical / "resume-claude" / "SKILL.md").is_file())
            # Shared physical root — single ownership tree.
            self.assertTrue(leaf.is_symlink())
            self.assertEqual(os.path.realpath(leaf), os.path.realpath(physical))


if __name__ == "__main__":
    unittest.main()
