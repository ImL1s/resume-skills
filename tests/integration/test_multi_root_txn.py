"""#23: multi-root install locks all roots before checkpoint/mutation."""

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
import portable_resume.install.transaction as transaction_module
from portable_resume.install.transaction import (
    RootLock,
    execute_install,
    install_multi_targets,
    load_manifest,
    plan_install,
    restore_install_checkpoint,
    capture_install_checkpoint,
    verify_root,
    _supports_descriptor_relative_commit,
)


@unittest.skipUnless(_supports_descriptor_relative_commit(), "dirfd multi-root path")
class MultiRootTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name) / "home"
        self.home.mkdir()
        self.root_a = resolve_skill_root(
            host="claude",
            scope="global",
            project_dir=str(self.home / "proj"),
            home_dir=str(self.home),
        )
        self.root_b = resolve_skill_root(
            host="grok",
            scope="global",
            project_dir=str(self.home / "proj"),
            home_dir=str(self.home),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_install_multi_targets_happy_path(self) -> None:
        results = install_multi_targets(
            [("claude", self.root_a), ("grok", self.root_b)],
            scope="global",
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["ok"] for r in results))
        verify_root(self.root_a)
        verify_root(self.root_b)

    def test_lock_order_is_canonical_realpath(self) -> None:
        acquired: list[str] = []
        original_enter = RootLock.__enter__

        def track_enter(self):
            acquired.append(os.path.realpath(self.root))
            return original_enter(self)

        with mock.patch.object(RootLock, "__enter__", track_enter):
            install_multi_targets(
                [("claude", self.root_a), ("grok", self.root_b)],
                scope="global",
            )
        self.assertEqual(acquired, sorted(acquired))
        self.assertEqual(len(acquired), 2)

    def test_lock_failure_leaves_roots_untouched(self) -> None:
        holder = RootLock(self.root_a, wait_seconds=0.2)
        holder.__enter__()
        try:
            with self.assertRaises(DiagnosticError) as ctx:
                install_multi_targets(
                    [("claude", self.root_a), ("grok", self.root_b)],
                    scope="global",
                )
            self.assertEqual(ctx.exception.code, "E_INSTALL_BUSY")
        finally:
            holder.__exit__(None, None, None)
        self.assertIsNone(load_manifest(self.root_a))
        self.assertIsNone(load_manifest(self.root_b))
        self.assertFalse((Path(self.root_b) / ".portable-resume" / "manifest.json").exists())

    def test_later_failure_compensates_under_held_locks(self) -> None:
        original = transaction_module.execute_install
        calls = 0

        def fail_second(plan, *, force_with_backup=False, lock=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected")
            return original(plan, force_with_backup=force_with_backup, lock=lock)

        with mock.patch.object(transaction_module, "execute_install", side_effect=fail_second):
            with self.assertRaises(OSError):
                install_multi_targets(
                    [("claude", self.root_a), ("grok", self.root_b)],
                    scope="global",
                )
        self.assertIsNone(load_manifest(self.root_a))
        self.assertIsNone(load_manifest(self.root_b))

    def test_compensation_refuses_foreign_drift(self) -> None:
        execute_install(plan_install(host="claude", scope="global", root=self.root_a))
        plan = plan_install(host="claude", scope="global", root=self.root_a)
        with RootLock(self.root_a):
            checkpoint = capture_install_checkpoint(plan)
            # Simulate successful reinstall-ish mutation then foreign drift.
            skill = Path(self.root_a) / "resume-claude" / "SKILL.md"
            skill.write_bytes(skill.read_bytes() + b"\n# foreign-edit\n")
            with self.assertRaises(DiagnosticError) as ctx:
                restore_install_checkpoint(checkpoint)
            self.assertEqual(ctx.exception.code, "E_RECOVERY_REQUIRED")
        # Foreign edit preserved.
        self.assertIn(b"foreign-edit", skill.read_bytes())

    def test_second_process_blocked_while_multi_root_holds_locks(self) -> None:
        hold = threading.Event()
        release = threading.Event()
        ready = threading.Event()

        original = transaction_module.execute_install
        calls = {"n": 0}

        def slow_first(plan, *, force_with_backup=False, lock=None):
            calls["n"] += 1
            if calls["n"] == 1:
                ready.set()
                hold.wait(timeout=5.0)
            return original(plan, force_with_backup=force_with_backup, lock=lock)

        def worker() -> None:
            with mock.patch.object(transaction_module, "execute_install", side_effect=slow_first):
                install_multi_targets(
                    [("claude", self.root_a), ("grok", self.root_b)],
                    scope="global",
                )
            release.set()

        t = threading.Thread(target=worker)
        t.start()
        self.assertTrue(ready.wait(timeout=5.0))
        # Concurrent single-root install must see busy while multi-root holds locks.
        with self.assertRaises(DiagnosticError) as ctx:
            with RootLock(self.root_a, wait_seconds=0.3):
                pass
        self.assertEqual(ctx.exception.code, "E_INSTALL_BUSY")
        hold.set()
        t.join(timeout=10)
        self.assertTrue(release.is_set())


if __name__ == "__main__":
    unittest.main()
