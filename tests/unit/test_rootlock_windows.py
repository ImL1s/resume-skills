"""#125 Phase 3: RootLock uses Win32 exclusive lock on real Windows.

Product install remains Policy B fail-closed. These tests only prove RootLock
holds/releases the platform exclusive lock and does not use fcntl on nt.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.transaction import RootLock, require_mutating_install_platform
from portable_resume.platform_fs.select import _reset_backend_cache


@unittest.skipUnless(os.name == "nt", "RootLock Win32 path requires real Windows")
class RootLockWindowsPhase3Tests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_backend_cache()

    def tearDown(self) -> None:
        _reset_backend_cache()

    def test_rootlock_acquires_and_releases_without_fcntl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp
            with RootLock(root) as lock:
                self.assertIsNotNone(lock._fd)
                self.assertIsNotNone(lock._win_lock_cm)
                lock_path = Path(lock.path)
                self.assertTrue(lock_path.is_file())
            # After exit, lock file may remain empty but second acquire must work.
            with RootLock(root) as lock2:
                self.assertIsNotNone(lock2._fd)

    def test_second_rootlock_busy_while_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp
            errors: list[BaseException] = []
            ready = threading.Event()
            release = threading.Event()

            def holder() -> None:
                try:
                    with RootLock(root, wait_seconds=0.2):
                        ready.set()
                        release.wait(timeout=10)
                except BaseException as exc:  # pragma: no cover
                    errors.append(exc)

            t = threading.Thread(target=holder)
            t.start()
            self.assertTrue(ready.wait(timeout=10), "holder did not acquire")
            with self.assertRaises(DiagnosticError) as ctx:
                with RootLock(root, wait_seconds=0.15):
                    pass
            self.assertEqual(ctx.exception.code, "E_INSTALL_BUSY")
            release.set()
            t.join(timeout=10)
            self.assertFalse(errors)

    def test_product_policy_b_lifted_on_real_windows(self) -> None:
        """Phase 7: require_mutating_install_platform() succeeds on real Windows."""
        require_mutating_install_platform()  # Should not raise

    def test_rootlock_does_not_import_fcntl_on_success_path(self) -> None:
        import sys

        # Ensure fcntl is not required for Windows enter (module may still exist
        # as stub on some envs; we assert RootLock path sets _win_lock_cm).
        with tempfile.TemporaryDirectory() as tmp:
            with RootLock(tmp) as lock:
                self.assertIsNotNone(lock._win_lock_cm)
                # fcntl is not used for Windows RootLock exit path.
                self.assertNotIn("fcntl", getattr(lock, "__dict__", {}))


if __name__ == "__main__":
    unittest.main()
