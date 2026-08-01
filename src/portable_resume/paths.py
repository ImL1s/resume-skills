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
    """Validate request-v1's absolute/NFC grammar and return its canonical path."""

    if not isinstance(value, str):
        raise DiagnosticError.invalid()
    reject_controls(value)
    normalized = normalize_unicode(value)
    if value != normalized or not os.path.isabs(value):
        raise DiagnosticError.invalid()
    return canonicalize_cwd(value)


def canonical_root(root: str | os.PathLike[str]) -> str:
    path = canonicalize_cwd(root)
    try:
        mode = os.stat(path, follow_symlinks=False).st_mode
    except OSError as error:
        raise DiagnosticError.unsafe_path() from error
    if not stat.S_ISDIR(mode):
        raise DiagnosticError.unsafe_path()
    return path


def canonical_source_root(root: str | os.PathLike[str]) -> str:
    """Approve CLI ``--source-root`` as either a directory or a regular file.

    Adapters that pin exact store files (``events.jsonl``, ``crush.db``,
    ``state.db``, …) must receive the file path unchanged. Directory-only
    ``canonical_root`` rejects those spellings with ``E_UNSAFE_PATH``.
    """

    path = canonicalize_cwd(root)
    try:
        mode = os.stat(path, follow_symlinks=False).st_mode
    except OSError as error:
        raise DiagnosticError.unsafe_path() from error
    if stat.S_ISDIR(mode) or stat.S_ISREG(mode):
        return path
    raise DiagnosticError.unsafe_path()


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


def _lexical_under(path: str, root: str) -> str | None:
    """Return the relative path if *path* is lexically beneath *root*, else None.

    Uses abspath spellings only — never realpath — so an outside symlink that
    happens to resolve inside *root* is still treated as outside.
    """

    try:
        relative = os.path.relpath(path, root)
    except ValueError:
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
        return None
    return relative


def _platform_root_aliases(raw_root: str, base: str) -> list[str]:
    """Return accepted walk-root spellings for the configured root only.

    Includes the lexical configured root and its pinned canonical form. On
    macOS, also includes the reverse ``/var`` spelling when the canonical root
    lives under ``/private/var`` and ``/var`` is the OS-owned alias for that
    prefix. Arbitrary user-created aliases of the root are never added.
    """

    aliases: list[str] = []
    for candidate in (raw_root, base):
        if candidate not in aliases:
            aliases.append(candidate)

    private_prefix = "/private/var"
    var_prefix = "/var"
    if base == private_prefix or base.startswith(private_prefix + os.sep):
        try:
            if os.path.islink(var_prefix) and canonicalize_cwd(var_prefix) == private_prefix:
                alt = var_prefix + base[len(private_prefix) :]
                if alt not in aliases:
                    aliases.append(alt)
        except (OSError, DiagnosticError):
            pass
    return aliases


def require_regular_no_symlinks(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> tuple[str, str]:
    """Reject symlinks in every user-controlled component below an approved root.

    Accepted walk roots are only spellings of the *configured* root:

    - the lexical ``abspath`` form of the configured root
    - the pinned canonical form of that same root
    - narrow OS-owned reverse aliases of that root (macOS ``/var`` ↔
      ``/private/var``), derived from the root — never from the supplied path

    The supplied path must be lexically under one of those roots. An unrelated
    outside path is never rewritten via realpath merely because its target sits
    inside the approved tree.
    """

    base = canonical_root(root)
    raw_root = normalize_unicode(os.path.abspath(os.fspath(root)))
    original = normalize_unicode(os.path.abspath(os.fspath(path)))
    reject_controls(raw_root)
    reject_controls(original)

    walk_root: str | None = None
    relative: str | None = None
    for candidate in _platform_root_aliases(raw_root, base):
        candidate_relative = _lexical_under(original, candidate)
        if candidate_relative is not None:
            walk_root = candidate
            relative = candidate_relative
            break
    if walk_root is None or relative is None:
        raise DiagnosticError.unsafe_path()

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
