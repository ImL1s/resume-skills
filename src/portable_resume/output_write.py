"""Atomic no-clobber writers for already-rendered reader output.

This module never reads source-agent stores. Callers pass fully rendered
text or bytes; the helper only places those bytes on disk (or signals
stdout).

Public contract
---------------
``write_output_text`` / ``write_output_bytes``
    * ``path == "-"`` → raise :class:`OutputToStdout` (not a diagnostic).
      CLI / orchestrator must catch this and write the rendered payload to
      stdout instead of a file.
    * empty path → :class:`~portable_resume.diagnostics.DiagnosticError`
      with ``E_INVALID_INPUT``.
    * destination exists and ``clobber=False`` (default) → same diagnostic.
    * missing parent directory → same diagnostic.
    * final path is a symlink and ``clobber=False`` → refuse (no follow).
    * success → returns the absolute path written.

Atomicity
---------
Payload is written to an exclusive temp file
``.portable-resume-output-<hex>.tmp`` in the destination parent, fsynced,
then ``os.replace``d onto the final path so readers never observe a
half-written destination. Private mode ``0o600`` is best-effort (Unix).
"""

from __future__ import annotations

import os
import secrets
import stat as stat_mod
from typing import Final

from .diagnostics import DiagnosticError

_TMP_PREFIX: Final[str] = ".portable-resume-output-"
_TMP_SUFFIX: Final[str] = ".tmp"
_PRIVATE_MODE: Final[int] = 0o600


class OutputToStdout(Exception):
    """Caller should emit rendered content on stdout, not a filesystem path.

    Raised when the output path is exactly ``"-"``. This is a control-flow
    signal for CLI wiring, not a user-facing diagnostic failure.
    """


def write_output_text(
    path: str,
    text: str,
    *,
    clobber: bool = False,
    encoding: str = "utf-8",
) -> str:
    """Write *text* atomically to *path*. Returns the absolute path written.

    See module docstring for ``"-"``, no-clobber, and atomic-replace rules.
    """
    # Fail closed on path policy (including ``"-"``) before encoding work.
    if not isinstance(path, str) or path == "":
        raise DiagnosticError.invalid()
    if path == "-":
        raise OutputToStdout()
    if not isinstance(text, str):
        raise DiagnosticError.invalid()
    if not isinstance(encoding, str) or not encoding:
        raise DiagnosticError.invalid()
    try:
        payload = text.encode(encoding)
    except (LookupError, UnicodeError) as error:
        raise DiagnosticError.invalid() from error
    return write_output_bytes(path, payload, clobber=clobber)


def write_output_bytes(
    path: str,
    data: bytes | bytearray | memoryview,
    *,
    clobber: bool = False,
) -> str:
    """Write *data* atomically to *path*. Returns the absolute path written.

    See module docstring for ``"-"``, no-clobber, and atomic-replace rules.
    """
    abs_path = _resolve_output_path(path, clobber=clobber)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise DiagnosticError.invalid()
    payload = bytes(data)

    parent = os.path.dirname(abs_path)
    tmp_path = _stage_output_bytes(parent, payload)
    try:
        _commit_staged_output(tmp_path, abs_path, clobber=clobber)
    except BaseException:
        # Commit unlinks on failure; if staging left a file and commit
        # raised before taking ownership of cleanup, drop the temp.
        try:
            if os.path.lexists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return abs_path


def _resolve_output_path(path: object, *, clobber: bool) -> str:
    """Validate path policy and return an absolute destination path."""
    if not isinstance(path, str) or path == "":
        raise DiagnosticError.invalid()
    if path == "-":
        raise OutputToStdout()

    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if not parent or parent == abs_path:
        # Empty dirname or root-as-file (e.g. "/") is not a writable file path.
        raise DiagnosticError.invalid()
    if not os.path.isdir(parent):
        raise DiagnosticError.invalid()

    if os.path.lexists(abs_path):
        try:
            st = os.lstat(abs_path)
        except OSError as error:
            raise DiagnosticError.invalid() from error
        if stat_mod.S_ISLNK(st.st_mode) and not clobber:
            raise DiagnosticError.invalid()
        if not clobber:
            raise DiagnosticError.invalid()
        # Clobber only replaces a regular file or a symlink leaf (replace
        # does not follow). Directories / specials are refused.
        if not (stat_mod.S_ISREG(st.st_mode) or stat_mod.S_ISLNK(st.st_mode)):
            raise DiagnosticError.invalid()

    return abs_path


def _stage_output_bytes(parent: str, data: bytes) -> str:
    """Write *data* to a new exclusive temp under *parent*; return temp path.

    Does **not** replace any final destination. Used so crash-before-replace
    leaves only a temp sibling; the final path is untouched until commit.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise DiagnosticError.invalid()
    payload = bytes(data)
    if not parent or not os.path.isdir(parent):
        raise DiagnosticError.invalid()

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    cloexec = getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags |= cloexec | nofollow

    # Retry a few times if an exclusive name collides (extremely unlikely).
    last_error: OSError | None = None
    for _ in range(8):
        name = f"{_TMP_PREFIX}{secrets.token_hex(8)}{_TMP_SUFFIX}"
        tmp_path = os.path.join(parent, name)
        try:
            fd = os.open(tmp_path, flags, _PRIVATE_MODE)
        except FileExistsError as error:
            last_error = error
            continue
        except OSError as error:
            raise DiagnosticError.invalid() from error
        try:
            try:
                os.fchmod(fd, _PRIVATE_MODE)
            except (AttributeError, OSError):
                pass
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write to output temp")
                view = view[written:]
            try:
                os.fsync(fd)
            except OSError:
                pass
        except OSError as error:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise DiagnosticError.invalid() from error
        else:
            try:
                os.close(fd)
            except OSError as error:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise DiagnosticError.invalid() from error
            return tmp_path

    raise DiagnosticError.invalid() from last_error


def _commit_staged_output(tmp_path: str, abs_path: str, *, clobber: bool) -> None:
    """Atomically ``os.replace`` a fully-written temp onto *abs_path*.

    Re-checks no-clobber after the temp is complete to shrink the TOCTOU
    window. Unlinks the temp on any failure so failed flights do not leave
    durable junk when cleanup is possible.
    """
    if not isinstance(tmp_path, str) or not tmp_path:
        raise DiagnosticError.invalid()
    if not isinstance(abs_path, str) or not abs_path:
        raise DiagnosticError.invalid()

    try:
        if not clobber and os.path.lexists(abs_path):
            raise DiagnosticError.invalid()
        if clobber and os.path.lexists(abs_path):
            try:
                st = os.lstat(abs_path)
            except OSError as error:
                raise DiagnosticError.invalid() from error
            if not (stat_mod.S_ISREG(st.st_mode) or stat_mod.S_ISLNK(st.st_mode)):
                raise DiagnosticError.invalid()
        os.replace(tmp_path, abs_path)
    except DiagnosticError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    except OSError as error:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise DiagnosticError.invalid() from error
