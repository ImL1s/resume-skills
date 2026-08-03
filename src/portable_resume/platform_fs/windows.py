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
from ..paths import (
    _lexical_under,
    _platform_root_aliases,
    canonical_root,
    canonicalize_cwd,
    is_within,
    normalize_unicode,
    reject_controls,
)
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
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
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
    """True if *handle* is not a usable Win32 HANDLE (pointer-width aware).

    Compares against full pointer-width ``INVALID_HANDLE_VALUE`` only. Do **not**
    treat a low-32-bit ``0xFFFFFFFF`` mask alone as decisive — on 64-bit Windows
    a truncated comparison can mis-classify handles.
    """
    if handle is None:
        return True
    h_val = getattr(handle, "value", handle)
    try:
        as_int = int(h_val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True
    if as_int in (0, -1):
        return True
    return as_int == _invalid_handle_value()


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


def _get_lexical_rel(
    path: str | os.PathLike[str],
    root: str | os.PathLike[str],
) -> tuple[str, str, str]:
    path_str = os.fspath(path)
    root_str = os.fspath(root)
    reject_controls(path_str)
    reject_controls(root_str)

    raw_root = normalize_unicode(os.path.abspath(root_str))
    base_root = canonical_root(root_str)
    original = normalize_unicode(os.path.abspath(path_str))

    if os.name == "nt":
        if len(raw_root) >= 2 and raw_root[1] == ":":
            raw_root = raw_root[0].upper() + raw_root[1:]
        if len(original) >= 2 and original[1] == ":":
            original = original[0].upper() + original[1:]

    walk_root: str | None = None
    rel: str | None = None
    for candidate in _platform_root_aliases(raw_root, base_root):
        cand_rel = _lexical_under(original, candidate)
        if cand_rel is not None:
            walk_root = candidate
            rel = cand_rel
            break

    if walk_root is None or rel is None:
        raise DiagnosticError.unsafe_path()

    return walk_root, base_root, rel


def _check_reparse_components(
    path: str | os.PathLike[str],
    root: str | os.PathLike[str],
    *,
    allow_nonexistent: bool = False,
) -> None:
    walk_root, base_root, rel = _get_lexical_rel(path, root)
    if rel in ("", "."):
        return

    norm_rel = rel.replace("/", "\\") if os.name == "nt" else rel
    parts = [p for p in norm_rel.replace("/", "\\").split("\\") if p and p != "."]
    current = walk_root
    num_parts = len(parts)
    for idx, component in enumerate(parts):
        if component == os.pardir:
            raise DiagnosticError.unsafe_path()
        is_leaf = (idx == num_parts - 1)
        current = os.path.join(current, component)
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            if allow_nonexistent:
                break
            raise
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

        if stat.S_ISLNK(st.st_mode):
            raise DiagnosticError.unsafe_path()

        attrs = getattr(st, "st_file_attributes", 0)
        if bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT):
            raise DiagnosticError.unsafe_path()

        if not is_leaf and not stat.S_ISDIR(st.st_mode):
            raise DiagnosticError.unsafe_path()

    original = normalize_unicode(os.path.abspath(os.fspath(path)))
    if os.path.exists(original):
        canonical = canonicalize_cwd(original)
        if not is_within(canonical, base_root):
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
        # Read-only product surfaces + Phase 1 exclusive lock primitive + Phase 4 relative mutations (#125).
        # Product install/uninstall/recover remain fail-closed in transaction.py
        # until Phase 7.
        self._capabilities = FilesystemCapabilities(
            descriptor_relative=False,
            nofollow_reads=True,
            relative_mutations=True,
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

        _check_reparse_components(path, root, allow_nonexistent=False)

        kernel32 = _get_kernel32()
        if kernel32 is not None:
            h_file = kernel32.CreateFileW(
                abs_path,
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
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
        from ..snapshot import _stable_read_bytes_impl

        _validate_win32_path(path, root)
        _check_reparse_components(path, root, allow_nonexistent=False)

        return _stable_read_bytes_impl(
            path,
            root=root,
            max_bytes=max_bytes,
            attempts=attempts,
            membership_limit=membership_limit,
            budget=budget,
            hook=hook,
        )


    def mkdirs_beneath(
        self,
        directory: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> str:
        _validate_win32_path(directory, root)
        walk_root, base_root, rel = _get_lexical_rel(directory, root)
        _check_reparse_components(directory, root, allow_nonexistent=True)

        abs_dir = canonicalize_cwd(directory)
        if not is_within(abs_dir, base_root):
            raise DiagnosticError.unsafe_path()
        if rel in ("", ".") or abs_dir == base_root:
            return base_root

        norm_rel = rel.replace("/", "\\") if os.name == "nt" else rel
        parts = [p for p in norm_rel.replace("/", "\\").split("\\") if p and p != "."]
        current = walk_root
        for component in parts:
            if component == os.pardir:
                raise DiagnosticError.unsafe_path()
            current = os.path.join(current, component)
            try:
                st = os.lstat(current)
            except FileNotFoundError:
                try:
                    os.mkdir(current, 0o700)
                except OSError as error:
                    raise DiagnosticError.unsafe_path() from error
                try:
                    st = os.lstat(current)
                except OSError as error:
                    raise DiagnosticError.unsafe_path() from error
            except OSError as error:
                raise DiagnosticError.unsafe_path() from error

            if stat.S_ISLNK(st.st_mode):
                raise DiagnosticError.unsafe_path()
            attrs = getattr(st, "st_file_attributes", 0)
            if bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT):
                raise DiagnosticError.unsafe_path()
            if not stat.S_ISDIR(st.st_mode):
                raise DiagnosticError.unsafe_path()

        return canonicalize_cwd(current)

    def unlink_beneath(
        self,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        _validate_win32_path(path, root)
        walk_root, base_root, rel = _get_lexical_rel(path, root)

        abs_path = canonicalize_cwd(path)
        if not is_within(abs_path, base_root) or abs_path == base_root:
            raise DiagnosticError.unsafe_path()

        raw_abs = normalize_unicode(os.path.abspath(os.fspath(path)))
        dirname = os.path.dirname(raw_abs)
        if canonicalize_cwd(dirname) != base_root:
            _check_reparse_components(dirname, root, allow_nonexistent=False)

        try:
            st = os.lstat(abs_path)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

        is_reparse = bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
        is_link = stat.S_ISLNK(st.st_mode)
        if stat.S_ISDIR(st.st_mode) and not (is_link or is_reparse):
            raise DiagnosticError.unsafe_path()

        try:
            os.unlink(abs_path)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

    def replace_beneath(
        self,
        source_path: str | os.PathLike[str],
        target_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> None:
        _validate_win32_path(source_path, root)
        _validate_win32_path(target_path, root)

        src_walk, base_root, src_rel = _get_lexical_rel(source_path, root)
        dst_walk, _, dst_rel = _get_lexical_rel(target_path, root)

        src_abs = canonicalize_cwd(source_path)
        dst_abs = canonicalize_cwd(target_path)

        if (
            not is_within(src_abs, base_root)
            or not is_within(dst_abs, base_root)
            or src_abs == base_root
            or dst_abs == base_root
        ):
            raise DiagnosticError.unsafe_path()

        src_raw = normalize_unicode(os.path.abspath(os.fspath(source_path)))
        dst_raw = normalize_unicode(os.path.abspath(os.fspath(target_path)))

        src_parent = os.path.dirname(src_raw)
        dst_parent = os.path.dirname(dst_raw)
        if canonicalize_cwd(src_parent) != base_root:
            _check_reparse_components(src_parent, root, allow_nonexistent=False)
        if canonicalize_cwd(dst_parent) != base_root:
            _check_reparse_components(dst_parent, root, allow_nonexistent=True)

        src_drive, _ = os.path.splitdrive(src_abs)
        dst_drive, _ = os.path.splitdrive(dst_abs)
        if src_drive.upper() != dst_drive.upper():
            raise DiagnosticError.unsafe_path()

        try:
            os.replace(src_abs, dst_abs)
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error

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
        if parent:
            drive, rest = os.path.splitdrive(parent)
            parts = [p for p in rest.replace("/", "\\").split("\\") if p]
            current = (drive + "\\") if drive else "\\"
            for part in parts:
                current = os.path.join(current, part)
                try:
                    st = os.lstat(current)
                except FileNotFoundError:
                    try:
                        os.mkdir(current, 0o700)
                    except OSError as error:
                        raise DiagnosticError.unsafe_path() from error
                    try:
                        st = os.lstat(current)
                    except OSError as error:
                        raise DiagnosticError.unsafe_path() from error
                except OSError as error:
                    raise DiagnosticError.unsafe_path() from error

                if stat.S_ISLNK(st.st_mode):
                    raise DiagnosticError.unsafe_path()
                attrs = getattr(st, "st_file_attributes", 0)
                if bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT):
                    raise DiagnosticError.unsafe_path()
                if not stat.S_ISDIR(st.st_mode):
                    raise DiagnosticError.unsafe_path()

        # OPEN_ALWAYS + OPEN_REPARSE_POINT + BACKUP_SEMANTICS: open the leaf itself if it is a reparse point or directory handle.
        handle = kernel32.CreateFileW(
            target,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
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

        # Require proven leaf attributes before locking (Phase-2 safety).
        # Fail closed if metadata cannot be read or leaf is reparse/directory.
        try:
            info = BY_HANDLE_FILE_INFORMATION()
            if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
                handle = None  # type: ignore[assignment]
                raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM")
            if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
                handle = None  # type: ignore[assignment]
                raise DiagnosticError.unsafe_path()
            if info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
                handle = None  # type: ignore[assignment]
                raise DiagnosticError.unsafe_path()
        except DiagnosticError:
            raise
        except Exception as error:
            if handle is not None:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
                handle = None  # type: ignore[assignment]
            raise DiagnosticError("E_INSTALL_UNSUPPORTED_PLATFORM") from error

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
