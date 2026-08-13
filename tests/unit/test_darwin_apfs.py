"""Darwin APFS clone ABI and descriptor-binding tests."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import portable_resume.platform_fs.darwin_apfs as darwin_apfs

from portable_resume.platform_fs.darwin_apfs import (
    clone_data_id,
    clone_file_from_fd,
    descriptor_fd_path,
    is_apfs_fd,
    unique_unlink_supported,
    unlink_volume_inode,
    volume_inode_path,
)


class DarwinApfsTests(unittest.TestCase):
    def test_unique_unlink_capability_probe_is_non_mutating_and_kernel_bound(self) -> None:
        for error_number, expected in (
            (errno.EBADF, True),
            (errno.EINVAL, False),
            (getattr(errno, "ENOTSUP", errno.EINVAL), False),
        ):
            with self.subTest(error_number=error_number):
                function = mock.Mock()

                def probe(*_args: object) -> int:
                    ctypes.set_errno(error_number)
                    return -1

                function.side_effect = probe
                library = SimpleNamespace(unlinkat=function)
                with (
                    mock.patch.object(darwin_apfs.sys, "platform", "darwin"),
                    mock.patch.object(darwin_apfs, "_libc", return_value=library),
                ):
                    self.assertEqual(unique_unlink_supported(), expected)
                function.assert_called_once_with(-1, b".", 0x8000)

    def test_real_unique_unlink_probe_does_not_create_or_remove_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "keep"
            marker.write_bytes(b"probe")
            before_scratch = {
                str(path)
                for path in Path(tempfile.gettempdir()).glob("portable-resume-cow-*")
            }
            before_entries = tuple(sorted(path.name for path in root.iterdir()))
            supported = unique_unlink_supported()
            if sys.platform != "darwin":
                self.assertFalse(supported)
            else:
                self.assertIsInstance(supported, bool)
            self.assertEqual(marker.read_bytes(), b"probe")
            self.assertEqual(
                tuple(sorted(path.name for path in root.iterdir())),
                before_entries,
            )
            self.assertEqual(
                {
                    str(path)
                    for path in Path(tempfile.gettempdir()).glob("portable-resume-cow-*")
                },
                before_scratch,
            )

    def test_real_fclonefileat_clones_from_pinned_source_fd(self) -> None:
        if sys.platform != "darwin":
            self.assertFalse(is_apfs_fd(-1))
            self.skipTest("real fclonefileat proof requires Darwin")
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
            self.skipTest("descriptor fd paths require Darwin")
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
            self.skipTest("volume inode paths require Darwin")
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
            self.skipTest("unique unlink requires Darwin")
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
