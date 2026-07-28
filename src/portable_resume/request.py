"""Strict request-v1 file boundary; user values remain JSON data, never argv."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from typing import Any, Callable

from .bounds import DEFAULT_BOUNDS
from .contracts import REQUEST_KEYS
from .diagnostics import DiagnosticError, SOURCE_KEYS
from .paths import reject_controls, validate_canonical_absolute

# Test-only seam: (stage, path) -> None. Not public API; never receives file bytes.
# Stages: after-precheck, after-open, after-read, after-verify, before-final.
RequestReadHook = Callable[[str, str], None]
_request_read_hook: RequestReadHook | None = None


@dataclass(frozen=True, slots=True)
class PortableRequest:
    source: str
    action: str
    resume_ref: str
    cwd: str
    schema_version: str = "portable-resume/request-v1"

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "action": self.action,
            "resume_ref": self.resume_ref,
            "cwd": self.cwd,
        }


@dataclass(frozen=True, slots=True)
class _RequestFingerprint:
    """Identity + stability metadata for one request pathname/descriptor."""

    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int


class _DuplicateKey(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise _DuplicateKey
        output[key] = value
    return output


def _fingerprint(stat_result: os.stat_result) -> _RequestFingerprint:
    return _RequestFingerprint(
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_mode,
        stat_result.st_size,
        stat_result.st_mtime_ns,
    )


def _symlink_safe_request_open_supported() -> bool:
    """True when final-component no-follow open can be guaranteed."""

    return os.name != "nt" and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")


def _invoke_hook(stage: str, path: str) -> None:
    hook = _request_read_hook
    if hook is not None:
        hook(stage, path)


def _open_request_descriptor(path: str) -> int:
    """Open the request basename descriptor-relative with O_NOFOLLOW.

    Intermediate components of the parent path may resolve OS-owned aliases
    (for example macOS ``/var`` → ``/private/var``). Only the final request
    component is opened with ``O_NOFOLLOW`` so a regular→symlink swap cannot
    be followed.
    """

    if not _symlink_safe_request_open_supported():
        raise DiagnosticError.invalid()
    parent = os.path.dirname(path) or os.curdir
    basename = os.path.basename(path)
    if not basename or basename in (".", ".."):
        raise DiagnosticError.invalid()
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    # O_NONBLOCK: reject FIFO/device replacements without hanging on open.
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        parent_fd = os.open(parent, dir_flags)
    except OSError as error:
        raise DiagnosticError.invalid() from error
    try:
        try:
            return os.open(basename, file_flags, dir_fd=parent_fd)
        except (OSError, NotImplementedError) as error:
            raise DiagnosticError.invalid() from error
    finally:
        os.close(parent_fd)


def _read_bounded(descriptor: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = os.read(descriptor, min(4096, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_regular_request(path: str) -> bytes:
    """Read one regular request file on the first opened no-follow descriptor.

    The open is the atomic validation point: there is no pre-open ``lstat``
    identity that can be recycled before open. Symlinks are rejected by
    ``O_NOFOLLOW``; non-regular descriptors (FIFO/device) are rejected after
    non-blocking open via ``fstat``.
    """

    if not _symlink_safe_request_open_supported():
        # Do not claim no-symlink request protection without O_NOFOLLOW/dir_fd.
        raise DiagnosticError.invalid()
    # Compatibility hook for tests that previously mutated after lstat precheck.
    _invoke_hook("after-precheck", path)

    try:
        descriptor = _open_request_descriptor(path)
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError.invalid() from error

    opened: _RequestFingerprint
    data: bytes
    try:
        _invoke_hook("after-open", path)
        opened = _fingerprint(os.fstat(descriptor))
        if not stat.S_ISREG(opened.mode) or opened.size > DEFAULT_BOUNDS.request_bytes:
            raise DiagnosticError.invalid()

        data = _read_bounded(descriptor, DEFAULT_BOUNDS.request_bytes)
        if len(data) > DEFAULT_BOUNDS.request_bytes or len(data) != opened.size:
            raise DiagnosticError.invalid()
        _invoke_hook("after-read", path)

        # Second content pass detects same-stat in-place mutation on this inode.
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError as error:
            raise DiagnosticError.invalid() from error
        verified = _read_bounded(descriptor, DEFAULT_BOUNDS.request_bytes)
        if verified != data:
            raise DiagnosticError.invalid()
        after = _fingerprint(os.fstat(descriptor))
        if after != opened or after.size != len(data):
            raise DiagnosticError.invalid()
        _invoke_hook("after-verify", path)
    finally:
        os.close(descriptor)

    _invoke_hook("before-final", path)
    try:
        final_path = os.lstat(path)
    except OSError as error:
        raise DiagnosticError.invalid() from error
    final = _fingerprint(final_path)
    # Pathname after read must still name the same inode we opened and verified.
    if final != opened:
        raise DiagnosticError.invalid()
    return data


def load_request(path: str, *, expected_source: str) -> PortableRequest:
    """Read and validate one regular, no-symlink, <=16 KiB request file."""

    if expected_source not in SOURCE_KEYS:
        raise DiagnosticError.invalid()
    data = _read_regular_request(path)
    try:
        text = data.decode("utf-8", errors="strict")
        payload = json.loads(text, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
        raise DiagnosticError.invalid() from error
    if not isinstance(payload, dict) or set(payload) != REQUEST_KEYS:
        raise DiagnosticError.invalid()
    if payload["schema_version"] != "portable-resume/request-v1":
        raise DiagnosticError.invalid()
    if payload["source"] != expected_source or payload["source"] not in SOURCE_KEYS:
        raise DiagnosticError.invalid(source=expected_source)
    if payload["action"] != "show":
        raise DiagnosticError.invalid(source=expected_source)
    ref = payload["resume_ref"]
    if not isinstance(ref, str) or not ref or len(ref) > DEFAULT_BOUNDS.ref_chars:
        raise DiagnosticError.invalid(source=expected_source)
    reject_controls(ref)
    cwd = validate_canonical_absolute(payload["cwd"])
    return PortableRequest(source=payload["source"], action="show", resume_ref=ref, cwd=cwd)
