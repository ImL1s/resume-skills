"""Windows safe-filesystem backend implementation."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import sys
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ..snapshot import AttemptHook, FileFingerprint, SQLiteSnapshot, StableRead

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..paths import canonical_root, canonicalize_cwd, is_within, reject_controls
from .api import FilesystemBackend, FilesystemCapabilities, FilesystemIdentity, FilesystemObjectIdentity

_WIN32_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)

FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
FILE_ATTRIBUTE_DIRECTORY = 0x0010
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
OPEN_ALWAYS = 4
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
# Whole-file exclusive lock range (Microsoft-documented pattern).
_LOCK_MAX_DWORD = 0xFFFFFFFF

try:
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", FILETIME),
            ("ftLastAccessTime", FILETIME),
            ("ftLastWriteTime", FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _HAS_CTYPES = True
except (ImportError, AttributeError):
    _HAS_CTYPES = False

# Win32 last-error codes used by lock/open paths.
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33

_kernel32_configured: object | None = None


def _invalid_handle_value() -> int:
    """Pointer-width INVALID_HANDLE_VALUE (-1 as HANDLE)."""
    if not _HAS_CTYPES:
        return -1
    return int(ctypes.c_void_p(-1).value or -1)


def _handle_is_invalid(handle: object) -> bool:
    if handle is None:
        return True
    h_val = getattr(handle, "value", handle)
    try:
        as_int = int(h_val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True
    if as_int in (0, -1):
        return True
    # Compare full pointer-width invalid value (not low-32 heuristic alone).
    return as_int == _invalid_handle_value() or (as_int & 0xFFFFFFFF) == 0xFFFFFFFF


def _get_kernel32() -> ctypes.WinDLL | None:
    """Return kernel32 with declared Win32 prototypes (pointer-width HANDLE-safe)."""
    global _kernel32_configured
    if not _HAS_CTYPES or os.name != "nt":
        return None
    if _kernel32_configured is not None:
        return _kernel32_configured  # type: ignore[return-value]
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return None

    # CreateFileW
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL

    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL

    kernel32.SetFilePointer.argtypes = [
        wintypes.HANDLE,
        wintypes.LONG,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetFilePointer.restype = wintypes.DWORD

    kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    kernel32.LockFileEx.restype = wintypes.BOOL

    kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    kernel32.UnlockFileEx.restype = wintypes.BOOL

    _kernel32_configured = kernel32
    return kernel32


def _filetime_to_ns(high: int, low: int) -> int:
    ft = (high << 32) | low
    return (ft - 116444736000000000) * 100



def _validate_win32_path(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> None:
    path_str = os.fspath(path)
    reject_controls(path_str)

    if ":" in os.path.splitdrive(path_str)[1]:
        raise DiagnosticError.unsafe_path()

    clean_path = path_str.replace("/", "\\")
    if clean_path.startswith("\\\\?\\") or clean_path.startswith("\\\\.\\"):
        raise DiagnosticError.unsafe_path()

    parts = [part for part in clean_path.split("\\") if part]
    for part in parts:
        stem = part.split(".")[0].upper()
        if stem in _WIN32_RESERVED_NAMES:
            raise DiagnosticError.unsafe_path()
        if part.endswith(" ") or part.endswith("."):
            raise DiagnosticError.unsafe_path()

    base_root = canonicalize_cwd(root)
    abs_path = canonicalize_cwd(path_str)
    if not is_within(abs_path, base_root):
        raise DiagnosticError.unsafe_path()


def _check_reparse_components(path: str, root: str) -> None:
    base_root = canonical_root(root)
    abs_path = canonicalize_cwd(path)
    if not is_within(abs_path, base_root):
        raise DiagnosticError.unsafe_path()

    rel = os.path.relpath(abs_path, base_root)
    if rel == ".":
        return

    norm_rel = rel.replace("/", os.sep).replace("\\", os.sep)
    current = base_root
    for component in norm_rel.split(os.sep):
        if not component or component == ".":
            continue
        current = os.path.join(current, component)
        try:
            st = os.lstat(current)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

        if stat.S_ISLNK(st.st_mode):
            raise DiagnosticError.unsafe_path()

        attrs = getattr(st, "st_file_attributes", 0)
        if bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT):
            raise DiagnosticError.unsafe_path()


class WindowsFilesystemBackend(FilesystemBackend):
    """Reparse-point and Win32-handle aware Windows safe-filesystem backend."""

    def __init__(self) -> None:
        self._identity = FilesystemIdentity(
            os_name=os.name,
            sys_platform=sys.platform,
            is_posix=False,
            is_windows=True,
            backend_name="WindowsFilesystemBackend",
        )
        # Read-only product surfaces + Phase 1 exclusive lock primitive (#125).
        # Product install/uninstall/recover remain fail-closed in transaction.py
        # until RootLock is fully wired to this lock (relative_mutations stays False).
        self._capabilities = FilesystemCapabilities(
            descriptor_relative=False,
            nofollow_reads=True,
            relative_mutations=False,
            sqlite_snapshots=True,
            atomic_output=True,
            exclusive_locking=True,
            reparse_points=True,
            handle_locking=True,
        )

    @property
    def identity(self) -> FilesystemIdentity:
        return self._identity

    @property
    def capabilities(self) -> FilesystemCapabilities:
        return self._capabilities

    def inspect_object_identity(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> FilesystemObjectIdentity:
        _validate_win32_path(path, root)
        base_root = canonical_root(root)
        abs_path = canonicalize_cwd(path)
        if not is_within(abs_path, base_root):
            raise DiagnosticError.unsafe_path()

        _check_reparse_components(abs_path, root)

        kernel32 = _get_kernel32()
        if kernel32 is not None:
            h_file = kernel32.CreateFileW(
                abs_path,
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
            h_val = getattr(h_file, "value", h_file) if h_file is not None else -1
            if h_val != -1 and h_val != 0 and (h_val & 0xFFFFFFFF) != 0xFFFFFFFF:
                try:
                    info = BY_HANDLE_FILE_INFORMATION()
                    if kernel32.GetFileInformationByHandle(h_file, ctypes.byref(info)):
                        attrs = info.dwFileAttributes
                        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                            obj_type = "symlink"
                        elif attrs & FILE_ATTRIBUTE_DIRECTORY:
                            obj_type = "directory"
                        else:
                            obj_type = "file"

                        file_index = (info.nFileIndexHigh << 32) | info.nFileIndexLow
                        size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
                        mtime_ns = _filetime_to_ns(
                            info.ftLastWriteTime.dwHighDateTime,
                            info.ftLastWriteTime.dwLowDateTime,
                        )
                        return FilesystemObjectIdentity(
                            object_type=obj_type,
                            stable_id=f"{info.dwVolumeSerialNumber}:{file_index}",
                            volume_id=str(info.dwVolumeSerialNumber),
                            size=size,
                            mtime_ns=mtime_ns,
                            digest=None,
                        )
                finally:
                    kernel32.CloseHandle(h_file)

        try:
            st = os.lstat(abs_path)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

        if stat.S_ISLNK(st.st_mode):
            obj_type = "symlink"
        elif stat.S_ISREG(st.st_mode):
            obj_type = "file"
        elif stat.S_ISDIR(st.st_mode):
            obj_type = "directory"
        else:
            obj_type = "other"

        return FilesystemObjectIdentity(
            object_type=obj_type,
            stable_id=f"{st.st_dev}:{st.st_ino}",
            volume_id=str(st.st_dev),
            size=st.st_size,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
            digest=None,
        )

    def read_regular_stable(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
        max_bytes: int = DEFAULT_BOUNDS.record_bytes,
        attempts: int = DEFAULT_BOUNDS.snapshot_attempts,
        membership_limit: int = DEFAULT_BOUNDS.scanned_records,
        budget: ReadBudget | None = None,
        hook: AttemptHook | None = None,
    ) -> StableRead:
        from ..snapshot import FileFingerprint, StableRead

        if (
            max_bytes < 0
            or max_bytes > DEFAULT_BOUNDS.sqlite_snapshot_bytes
            or not 1 <= attempts <= DEFAULT_BOUNDS.snapshot_attempts
        ):
            raise DiagnosticError.invalid()

        _validate_win32_path(path, root)
        base_root = canonical_root(root)
        abs_path = canonicalize_cwd(path)
        if not is_within(abs_path, base_root):
            raise DiagnosticError.unsafe_path()

        try:
            st_target = os.lstat(abs_path)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

        if stat.S_ISLNK(st_target.st_mode) or bool(
            getattr(st_target, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise DiagnosticError.unsafe_path()

        if not stat.S_ISREG(st_target.st_mode):
            raise DiagnosticError.unsafe_path()

        _check_reparse_components(abs_path, root)

        _ = membership_limit
        kernel32 = _get_kernel32()

        for attempt in range(1, attempts + 1):
            if hook is not None:
                try:
                    hook("before-read", attempt, abs_path)
                except TypeError:
                    try:
                        hook(abs_path, attempt, "read")
                    except TypeError:
                        pass

            if kernel32 is not None:
                h_file = kernel32.CreateFileW(
                    abs_path,
                    GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    None,
                    OPEN_EXISTING,
                    FILE_FLAG_OPEN_REPARSE_POINT,
                    None,
                )
                h_val = getattr(h_file, "value", h_file) if h_file is not None else -1
                if h_val == -1 or h_val == 0 or (h_val & 0xFFFFFFFF) == 0xFFFFFFFF:
                    err = kernel32.GetLastError() if kernel32 is not None else 0
                    if err in (32, 33):  # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
                        continue
                    raise DiagnosticError.unsafe_path()

                try:
                    info1 = BY_HANDLE_FILE_INFORMATION()
                    if not kernel32.GetFileInformationByHandle(h_file, ctypes.byref(info1)):
                        raise DiagnosticError.unsafe_path()

                    attrs = info1.dwFileAttributes
                    if (attrs & FILE_ATTRIBUTE_REPARSE_POINT) or (attrs & FILE_ATTRIBUTE_DIRECTORY):
                        raise DiagnosticError.unsafe_path()

                    size1 = (info1.nFileSizeHigh << 32) | info1.nFileSizeLow
                    if size1 > max_bytes:
                        raise DiagnosticError.limit_exceeded()

                    buf = ctypes.create_string_buffer(max_bytes + 1)
                    bytes_read = wintypes.DWORD(0)
                    res = kernel32.ReadFile(
                        h_file, buf, max_bytes + 1, ctypes.byref(bytes_read), None
                    )
                    if not res:
                        continue

                    data = buf.raw[: bytes_read.value]
                    if len(data) > max_bytes:
                        raise DiagnosticError.limit_exceeded()

                    if hook is not None:
                        try:
                            hook("after-read", attempt, abs_path)
                        except TypeError:
                            pass

                    kernel32.SetFilePointer(h_file, 0, None, 0)
                    buf2 = ctypes.create_string_buffer(max_bytes + 1)
                    bytes_read2 = wintypes.DWORD(0)
                    res2 = kernel32.ReadFile(
                        h_file, buf2, max_bytes + 1, ctypes.byref(bytes_read2), None
                    )
                    if not res2 or buf2.raw[: bytes_read2.value] != data:
                        continue

                    info2 = BY_HANDLE_FILE_INFORMATION()
                    if not kernel32.GetFileInformationByHandle(h_file, ctypes.byref(info2)):
                        continue

                    stable = (
                        info1.dwVolumeSerialNumber == info2.dwVolumeSerialNumber
                        and info1.nFileIndexHigh == info2.nFileIndexHigh
                        and info1.nFileIndexLow == info2.nFileIndexLow
                        and info1.nFileSizeHigh == info2.nFileSizeHigh
                        and info1.nFileSizeLow == info2.nFileSizeLow
                        and info1.ftLastWriteTime.dwLowDateTime
                        == info2.ftLastWriteTime.dwLowDateTime
                        and info1.ftLastWriteTime.dwHighDateTime
                        == info2.ftLastWriteTime.dwHighDateTime
                    )

                    if stable:
                        try:
                            st_check = os.lstat(abs_path)
                            if (
                                stat.S_ISLNK(st_check.st_mode)
                                or not stat.S_ISREG(st_check.st_mode)
                                or bool(
                                    getattr(st_check, "st_file_attributes", 0)
                                    & FILE_ATTRIBUTE_REPARSE_POINT
                                )
                            ):
                                continue
                        except OSError:
                            continue

                        if budget is not None:
                            budget.consume_bytes(len(data))
                        file_index = (info1.nFileIndexHigh << 32) | info1.nFileIndexLow
                        mtime_ns = _filetime_to_ns(
                            info1.ftLastWriteTime.dwHighDateTime,
                            info1.ftLastWriteTime.dwLowDateTime,
                        )
                        fingerprint = FileFingerprint(
                            device=info1.dwVolumeSerialNumber,
                            inode=file_index,
                            mode=stat.S_IFREG | 0o666,
                            size=size1,
                            mtime_ns=mtime_ns,
                            content_sha256=hashlib.sha256(data).hexdigest(),
                        )
                        return StableRead(data=data, fingerprint=fingerprint, attempts=attempt)
                finally:
                    kernel32.CloseHandle(h_file)
            else:
                try:
                    st1 = os.lstat(abs_path)
                    if stat.S_ISLNK(st1.st_mode) or not stat.S_ISREG(st1.st_mode):
                        raise DiagnosticError.unsafe_path()
                    if bool(getattr(st1, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT):
                        raise DiagnosticError.unsafe_path()
                    if st1.st_size > max_bytes:
                        raise DiagnosticError.limit_exceeded()

                    with open(abs_path, "rb") as fp:
                        data = fp.read(max_bytes + 1)

                    if len(data) > max_bytes:
                        raise DiagnosticError.limit_exceeded()

                    if hook is not None:
                        try:
                            hook("after-read", attempt, abs_path)
                        except TypeError:
                            pass

                    with open(abs_path, "rb") as fp2:
                        data2 = fp2.read(max_bytes + 1)
                    if data2 != data:
                        continue

                    st2 = os.lstat(abs_path)

                    if (st1.st_size, st1.st_mtime_ns, st1.st_ino) == (
                        st2.st_size,
                        st2.st_mtime_ns,
                        st2.st_ino,
                    ):
                        if budget is not None:
                            budget.consume_bytes(len(data))
                        fingerprint = FileFingerprint(
                            device=st1.st_dev,
                            inode=st1.st_ino,
                            mode=st1.st_mode,
                            size=st1.st_size,
                            mtime_ns=getattr(st1, "st_mtime_ns", int(st1.st_mtime * 1e9)),
                            content_sha256=hashlib.sha256(data).hexdigest(),
                        )
                        return StableRead(data=data, fingerprint=fingerprint, attempts=attempt)
                except DiagnosticError:
                    raise
                except (OSError, IOError) as error:
                    raise DiagnosticError.unsafe_path() from error

        raise DiagnosticError.source_busy(attempts=attempts)

    def mkdirs_beneath(
        self,
        directory: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> str:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def unlink_beneath(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def replace_beneath(
        self,
        source_path: str | os.PathLike[str],
        target_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

    def sqlite_family_snapshot(
        self,
        database_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
        max_bytes: int = DEFAULT_BOUNDS.sqlite_snapshot_bytes,
    ) -> SQLiteSnapshot:
        """Private SQLite family snapshot using reparse-safe stable reads.

        Reuses the shared family-copy loop; file bytes come from this
        backend's ``read_regular_stable`` via the public ``stable_read_bytes``
        entry (no POSIX dir_fd).
        """
        if max_bytes < 0 or max_bytes > DEFAULT_BOUNDS.sqlite_snapshot_bytes:
            raise DiagnosticError.invalid()
        _validate_win32_path(database_path, root)
        from ..snapshot import _snapshot_sqlite_family_impl

        return _snapshot_sqlite_family_impl(database_path, root=root, bounds=DEFAULT_BOUNDS)

    def atomic_replace_output(
        self,
        path: str,
        data: bytes | bytearray | memoryview,
        *,
        clobber: bool = False,
    ) -> str:
        """Atomic temp+replace output writer with reserved-name / ADS gates."""
        from ..output_write import _write_output_bytes_impl

        if isinstance(path, str) and path and path != "-":
            reject_controls(path)
            # Basename-only policy: reserved device names and ADS streams.
            basename = os.path.basename(path.replace("/", "\\"))
            stem = basename.split(".")[0].upper()
            if stem in _WIN32_RESERVED_NAMES or ":" in basename:
                raise DiagnosticError.invalid()
        return _write_output_bytes_impl(path, data, clobber=clobber)

    @contextlib.contextmanager
    def acquire_exclusive_lock(
        self,
        lock_path: str | os.PathLike[str],
    ) -> Iterator[int]:
        """Non-blocking exclusive OS lock via CreateFileW + LockFileEx (#125 Phase 1).

        Product install/uninstall/recover still fail closed in transaction.py;
        this primitive is the foundation for a future RootLock wire. Returns an
        integer file descriptor (``msvcrt.open_osfhandle``) while the lock is held.
        On non-Windows hosts (no kernel32) raises ``E_INSTALL_UNSUPPORTED_PLATFORM``.

        Share mode allows concurrent open (``FILE_SHARE_READ|FILE_SHARE_WRITE``) so
        exclusivity comes from ``LockFileEx``, not CreateFile share denial alone.
        """
        kernel32 = _get_kernel32()
        if kernel32 is None or not _HAS_CTYPES:
            raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")

        try:
            import msvcrt
        except ImportError as error:
            raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM") from error

        target = os.path.abspath(os.fspath(lock_path))
        reject_controls(target)
        # Device-namespace and ADS-style colons after drive letter.
        if target.startswith("\\\\?\\") or target.startswith("\\\\.\\"):
            raise DiagnosticError.unsafe_path()
        if ":" in os.path.splitdrive(target)[1]:
            raise DiagnosticError.unsafe_path()
        basename = os.path.basename(target.replace("/", "\\"))
        stem = basename.split(".")[0].upper()
        if stem in _WIN32_RESERVED_NAMES or ":" in basename:
            raise DiagnosticError.unsafe_path()
        # Reject reserved components anywhere in the path (not basename-only).
        for part in target.replace("/", "\\").split("\\"):
            if not part or part.endswith(":") or part.endswith((" ", ".")):
                # Skip drive letter tokens like "C:"; reject trailing space/dot names.
                if part.endswith((" ", ".")) and not part.endswith(":"):
                    raise DiagnosticError.unsafe_path()
                continue
            part_stem = part.split(".")[0].upper()
            if part_stem in _WIN32_RESERVED_NAMES:
                raise DiagnosticError.unsafe_path()

        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as error:
                raise DiagnosticError.invalid() from error

        # OPEN_ALWAYS + OPEN_REPARSE_POINT: open the leaf itself if it is a reparse.
        handle = kernel32.CreateFileW(
            target,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if _handle_is_invalid(handle):
            err = ctypes.get_last_error()
            if err in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
                raise DiagnosticError("E_INSTALL_BUSY")
            raise DiagnosticError("E_INSTALL_BUSY") from None

        h_val = int(getattr(handle, "value", handle))

        def _unlock_handle(h: object) -> None:
            ov = OVERLAPPED()
            ov.Offset = 0
            ov.OffsetHigh = 0
            ov.hEvent = None
            try:
                kernel32.UnlockFileEx(
                    h,
                    0,
                    _LOCK_MAX_DWORD,
                    _LOCK_MAX_DWORD,
                    ctypes.byref(ov),
                )
            except Exception:
                pass

        # Reject lock leaf that is a reparse point (junction/symlink redirect).
        try:
            info = BY_HANDLE_FILE_INFORMATION()
            if kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
                if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
                    kernel32.CloseHandle(handle)
                    raise DiagnosticError.unsafe_path()
                if info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
                    kernel32.CloseHandle(handle)
                    raise DiagnosticError.unsafe_path()
        except DiagnosticError:
            raise
        except Exception:
            # Attribute probe failure: continue; LockFileEx still gates exclusivity.
            pass

        overlapped = OVERLAPPED()
        overlapped.Offset = 0
        overlapped.OffsetHigh = 0
        overlapped.hEvent = None
        locked = False
        fd: int | None = None
        try:
            ok = kernel32.LockFileEx(
                handle,
                LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY,
                0,
                _LOCK_MAX_DWORD,
                _LOCK_MAX_DWORD,
                ctypes.byref(overlapped),
            )
            if not ok:
                err = ctypes.get_last_error()
                raise DiagnosticError("E_INSTALL_BUSY") from None
            locked = True
            try:
                # Transfer handle ownership to a CRT fd; prefer non-inheritable.
                open_flags = getattr(os, "O_NOINHERIT", 0)
                fd = msvcrt.open_osfhandle(h_val, open_flags)
            except (OSError, ValueError, OverflowError) as error:
                raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM") from error
            handle = None  # type: ignore[assignment]
            yield fd
        finally:
            if fd is not None:
                if locked:
                    try:
                        _unlock_handle(msvcrt.get_osfhandle(fd))
                    except Exception:
                        pass
                try:
                    os.close(fd)
                except OSError:
                    pass
            elif handle is not None:
                if locked:
                    _unlock_handle(handle)
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
