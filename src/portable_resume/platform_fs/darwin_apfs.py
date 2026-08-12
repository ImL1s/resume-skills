"""Minimal Darwin ``fclonefileat`` and APFS capability bindings."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from typing import Callable

CLONE_NOFOLLOW = 0x0001
CLONE_NOOWNERCOPY = 0x0002
_CLONE_FLAGS = CLONE_NOFOLLOW | CLONE_NOOWNERCOPY
_MAXPATHLEN = 1024
_MFSTYPENAMELEN = 16
_AT_FDCWD = -2
_AT_REMOVEDIR = 0x0080
_AT_UNIQUE = 0x8000


class DarwinCloneUnavailable(OSError):
    """The current host cannot provide the required descriptor-bound clone."""


class _Fsid(ctypes.Structure):
    _fields_ = [("val", ctypes.c_int32 * 2)]


class _StatFs(ctypes.Structure):
    _fields_ = [
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", _Fsid),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * _MFSTYPENAMELEN),
        ("f_mntonname", ctypes.c_char * _MAXPATHLEN),
        ("f_mntfromname", ctypes.c_char * _MAXPATHLEN),
        ("f_flags_ext", ctypes.c_uint32),
        ("f_reserved", ctypes.c_uint32 * 7),
    ]


def _libc() -> ctypes.CDLL:
    if sys.platform != "darwin":
        raise DarwinCloneUnavailable("Darwin descriptor clone unavailable")
    return ctypes.CDLL(None, use_errno=True)


def is_apfs_fd(descriptor: int) -> bool:
    """Return true only when Darwin reports APFS for the open descriptor."""

    if sys.platform != "darwin" or type(descriptor) is not int or descriptor < 0:
        return False
    try:
        libc = _libc()
        function = libc.fstatfs
    except (AttributeError, OSError):
        return False
    function.argtypes = [ctypes.c_int, ctypes.POINTER(_StatFs)]
    function.restype = ctypes.c_int
    value = _StatFs()
    ctypes.set_errno(0)
    if function(descriptor, ctypes.byref(value)) != 0:
        return False
    return bytes(value.f_fstypename).split(b"\0", 1)[0].lower() == b"apfs"


def volume_inode_path(descriptor: int) -> str:
    """Return Darwin's identity-bound ``/.vol/<device>/<inode>`` path."""

    if sys.platform != "darwin" or type(descriptor) is not int or descriptor < 0:
        raise DarwinCloneUnavailable("Darwin volume inode path unavailable")
    try:
        opened = os.fstat(descriptor)
    except OSError as error:
        raise DarwinCloneUnavailable("cannot inspect descriptor identity") from error
    path = f"/.vol/{opened.st_dev}/{opened.st_ino}"
    try:
        resolved = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise DarwinCloneUnavailable("volume inode path unavailable") from error
    if (
        resolved.st_dev != opened.st_dev
        or resolved.st_ino != opened.st_ino
        or stat.S_IFMT(resolved.st_mode) != stat.S_IFMT(opened.st_mode)
    ):
        raise DarwinCloneUnavailable("volume inode identity mismatch")
    return path


def unlink_volume_inode(descriptor: int, *, directory: bool = False) -> None:
    """Remove exactly one pinned Darwin vnode, rejecting extra path aliases."""

    path = volume_inode_path(descriptor)
    try:
        function = _libc().unlinkat
    except (AttributeError, OSError) as error:
        raise DarwinCloneUnavailable("unlinkat symbol unavailable") from error
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    function.restype = ctypes.c_int
    flags = _AT_UNIQUE | (_AT_REMOVEDIR if directory else 0)
    ctypes.set_errno(0)
    if function(_AT_FDCWD, os.fsencode(path), flags) != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), path)


def clone_file_from_fd(
    source_fd: int,
    destination_dir_fd: int,
    destination_name: str,
    *,
    deadline_check: Callable[[], None] | None = None,
) -> None:
    """Clone one pinned source file into a pinned destination directory."""

    if (
        type(source_fd) is not int
        or source_fd < 0
        or type(destination_dir_fd) is not int
        or destination_dir_fd < 0
        or not isinstance(destination_name, str)
        or not destination_name
        or destination_name in {".", ".."}
        or "/" in destination_name
        or "\0" in destination_name
    ):
        raise ValueError("invalid descriptor clone arguments")
    check = deadline_check or (lambda: None)
    check()
    try:
        function = _libc().fclonefileat
    except AttributeError as error:
        raise DarwinCloneUnavailable("fclonefileat symbol unavailable") from error
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = function(
        source_fd,
        destination_dir_fd,
        os.fsencode(destination_name),
        _CLONE_FLAGS,
    )
    error_number = ctypes.get_errno()
    check()
    if result != 0:
        raise OSError(error_number, os.strerror(error_number))
