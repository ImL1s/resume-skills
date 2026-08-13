"""Darwin APFS clone ABI and descriptor-binding tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from portable_resume.platform_fs.darwin_apfs import (
    clone_data_id,
    clone_file_from_fd,
    descriptor_fd_path,
    is_apfs_fd,
    unlink_volume_inode,
    volume_inode_path,
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
                source_clone_id = clone_file_from_fd(
                    source_fd, destination_fd, "private-clone"
                )
                clone_fd = os.open(
                    "private-clone", os.O_RDWR | os.O_NOFOLLOW, dir_fd=destination_fd
                )
                try:
                    self.assertEqual(clone_data_id(source_fd), source_clone_id)
                    self.assertEqual(clone_data_id(clone_fd), source_clone_id)
                finally:
                    os.close(clone_fd)
            finally:
                os.close(destination_fd)
                os.close(source_fd)

            self.assertEqual((root / "private-clone").read_bytes(), b"pinned-original")
            clone_fd = os.open(root / "private-clone", os.O_RDWR | os.O_NOFOLLOW)
            try:
                os.pwrite(clone_fd, b"changed", 0)
                self.assertNotEqual(clone_data_id(clone_fd), source_clone_id)
            finally:
                os.close(clone_fd)

    def test_descriptor_fd_path_reopens_unlinked_regular_file_identity(self) -> None:
        if sys.platform != "darwin":
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owned = root / "owned"
            owned.write_bytes(b"private")
            descriptor = os.open(owned, os.O_RDWR | os.O_NOFOLLOW)
            try:
                unlink_volume_inode(descriptor)
                self.assertEqual(os.fstat(descriptor).st_nlink, 0)
                path = descriptor_fd_path(descriptor)
                reopened = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    self.assertEqual(
                        (os.fstat(reopened).st_dev, os.fstat(reopened).st_ino),
                        (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino),
                    )
                    self.assertEqual(os.read(reopened, 7), b"private")
                finally:
                    os.close(reopened)
            finally:
                os.close(descriptor)

    def test_volume_inode_path_and_unlink_stay_bound_across_rename(self) -> None:
        if sys.platform != "darwin":
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owned = root / "owned"
            owned.mkdir()
            descriptor = os.open(owned, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            replacement = root / "replacement"
            moved = root / "moved"
            try:
                identity_path = Path(volume_inode_path(descriptor))
                self.assertEqual(identity_path.stat().st_ino, os.fstat(descriptor).st_ino)
                owned.rename(moved)
                replacement.mkdir()
                replacement.rename(owned)
                unlink_volume_inode(descriptor, directory=True)
                self.assertFalse(moved.exists())
                self.assertTrue(owned.is_dir())
            finally:
                os.close(descriptor)

    def test_unique_unlink_rejects_regular_file_with_extra_hard_link(self) -> None:
        if sys.platform != "darwin":
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owned = root / "owned"
            alias = root / "alias"
            owned.write_bytes(b"private")
            os.link(owned, alias)
            descriptor = os.open(owned, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                with self.assertRaises(OSError):
                    unlink_volume_inode(descriptor)
                self.assertTrue(owned.is_file())
                self.assertTrue(alias.is_file())
            finally:
                os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
