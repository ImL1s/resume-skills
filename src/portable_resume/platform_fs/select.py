"""Deterministic backend selector with environment anti-spoofing."""

from __future__ import annotations

import os
import sys

from .api import FilesystemBackend
from .posix import PosixFilesystemBackend
from .windows import WindowsFilesystemBackend

_CACHED_BACKEND: FilesystemBackend | None = None


def get_filesystem_backend() -> FilesystemBackend:
    """Return the deterministic FilesystemBackend for the host system.

    Selection relies strictly on os.name / sys.platform. Environment variables
    are explicitly ignored to prevent capability spoofing.
    """
    global _CACHED_BACKEND
    if _CACHED_BACKEND is not None:
        return _CACHED_BACKEND

    if os.name == "posix":
        backend = PosixFilesystemBackend()
    elif os.name == "nt" or sys.platform.startswith("win"):
        backend = WindowsFilesystemBackend()
    else:
        backend = PosixFilesystemBackend()

    _CACHED_BACKEND = backend
    return _CACHED_BACKEND


def _reset_backend_cache() -> None:
    """Clear cached backend instance (for unit test isolation)."""
    global _CACHED_BACKEND
    _CACHED_BACKEND = None
