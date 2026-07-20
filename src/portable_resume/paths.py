"""Canonical cwd comparison and safe-root path enforcement."""

from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path

from .diagnostics import DiagnosticError


def normalize_unicode(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def reject_controls(value: str) -> None:
    if "\x00" in value or any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in value):
        raise DiagnosticError.invalid()


def canonicalize_cwd(value: str | os.PathLike[str], *, base: str | os.PathLike[str] | None = None) -> str:
    """Return an absolute, real, NFC-normalized path for CLI cwd comparison."""

    text = normalize_unicode(os.fspath(value))
    reject_controls(text)
    if not os.path.isabs(text):
        text = os.path.join(os.fspath(base) if base is not None else os.getcwd(), text)
    return normalize_unicode(os.path.realpath(os.path.abspath(text)))


def validate_canonical_absolute(value: str) -> str:
    """Validate the stricter request-v1 cwd representation without rewriting it."""

    if not isinstance(value, str):
        raise DiagnosticError.invalid()
    reject_controls(value)
    normalized = normalize_unicode(value)
    if value != normalized or not os.path.isabs(value):
        raise DiagnosticError.invalid()
    canonical = canonicalize_cwd(value)
    if canonical != value:
        raise DiagnosticError.invalid()
    return value


def canonical_root(root: str | os.PathLike[str]) -> str:
    path = canonicalize_cwd(root)
    try:
        mode = os.stat(path, follow_symlinks=False).st_mode
    except OSError as error:
        raise DiagnosticError.unsafe_path() from error
    if not stat.S_ISDIR(mode):
        raise DiagnosticError.unsafe_path()
    return path


def is_within(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    canonical = canonicalize_cwd(path)
    canonical_base = canonicalize_cwd(root)
    try:
        return os.path.commonpath((canonical, canonical_base)) == canonical_base
    except ValueError:
        return False


def require_within(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> str:
    canonical = canonicalize_cwd(path)
    base = canonical_root(root)
    if not is_within(canonical, base):
        raise DiagnosticError.unsafe_path()
    return canonical


def require_regular_no_symlinks(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> tuple[str, str]:
    """Reject symlinks in every component below an approved canonical root."""

    base = canonical_root(root)
    raw_root = normalize_unicode(os.path.abspath(os.fspath(root)))
    original = normalize_unicode(os.path.abspath(os.fspath(path)))
    reject_controls(raw_root)
    reject_controls(original)
    try:
        relative = os.path.relpath(original, raw_root)
    except ValueError as error:
        raise DiagnosticError.unsafe_path() from error
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
        # The caller may use a canonical spelling while the configured root
        # crosses an OS-owned alias such as macOS /var -> /private/var.
        canonical = canonicalize_cwd(original)
        if not is_within(canonical, base):
            raise DiagnosticError.unsafe_path()
        original = canonical
        relative = os.path.relpath(original, base)
        walk_root = base
    else:
        walk_root = raw_root

    current = walk_root
    parts = [part for part in Path(relative).parts if part not in ("", ".")]
    if not parts:
        raise DiagnosticError.unsafe_path()
    for index, part in enumerate(parts):
        if part == os.pardir:
            raise DiagnosticError.unsafe_path()
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except OSError as error:
            raise DiagnosticError.unsafe_path() from error
        if stat.S_ISLNK(mode):
            raise DiagnosticError.unsafe_path()
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise DiagnosticError.unsafe_path()
    if not stat.S_ISREG(os.lstat(current).st_mode):
        raise DiagnosticError.unsafe_path()
    canonical = canonicalize_cwd(current)
    if not is_within(canonical, base):
        raise DiagnosticError.unsafe_path()
    return canonical, base


def same_cwd(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return left is right
    return canonicalize_cwd(left) == canonicalize_cwd(right)
