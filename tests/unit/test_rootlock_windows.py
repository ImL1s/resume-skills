"""Windows RootLock tests (Phase 3 of issue #125)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.transaction import RootLock


@unittest.skipUnless(os.name == "nt", "Windows-only RootLock tests")
class WindowsRootLockTests(unittest.TestCase):
    def test_exclusive_lock_acquire_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            Path(root).mkdir()
            lock1 = RootLock(root, _allow_win32_internal=True)
            with lock1:
                self.assertIsNotNone(lock1._fd)
                lock_file = Path(lock1.path)
                self.assertTrue(lock_file.exists())
                os.lseek(lock1._fd, 0, os.SEEK_SET)
                content = os.read(lock1._fd, 1024)
                self.assertIn(f"pid={os.getpid()}".encode("ascii"), content)

                lock2 = RootLock(root, wait_seconds=0.1, _allow_win32_internal=True)
                with self.assertRaises(DiagnosticError) as ctx:
                    with lock2:
                        pass
                self.assertEqual(ctx.exception.code, "E_INSTALL_BUSY")

            # After lock1 releases, lock_file is readable and lock3 can acquire
            self.assertIn(f"pid={os.getpid()}".encode("ascii"), lock_file.read_bytes())

            # After lock1 releases, lock3 can acquire
            lock3 = RootLock(root, _allow_win32_internal=True)
            with lock3:
                self.assertIsNotNone(lock3._fd)

    def test_policy_b_product_gated_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            Path(root).mkdir()
            lock = RootLock(root)
            with self.assertRaises(DiagnosticError) as ctx:
                with lock:
                    pass
            self.assertEqual(ctx.exception.code, "E_INSTALL_UNSUPPORTED_PLATFORM")
            support = Path(root) / ".portable-resume"
            self.assertFalse(support.exists())


if __name__ == "__main__":
    unittest.main()
