"""Darwin APFS clone ABI and descriptor-binding tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from portable_resume.platform_fs.darwin_apfs import (
    clone_file_from_fd,
    is_apfs_fd,
)


class DarwinApfsTests(unittest.TestCase):
    def test_real_fclonefileat_clones_from_pinned_source_fd(self) -> None:
        if sys.platform != "darwin":
            self.assertFalse(is_apfs_fd(-1))
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.write_bytes(b"pinned-original")
            source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            destination_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                self.assertTrue(is_apfs_fd(source_fd))
                original = root / "original"
                source.rename(original)
                source.write_bytes(b"pathname-replacement")
                clone_file_from_fd(source_fd, destination_fd, "private-clone")
            finally:
                os.close(destination_fd)
                os.close(source_fd)

            self.assertEqual((root / "private-clone").read_bytes(), b"pinned-original")


if __name__ == "__main__":
    unittest.main()
