"""Cross-platform safe-filesystem backend package."""

from .api import FilesystemBackend, FilesystemCapabilities, FilesystemIdentity
from .select import get_filesystem_backend

__all__ = [
    "FilesystemBackend",
    "FilesystemCapabilities",
    "FilesystemIdentity",
    "get_filesystem_backend",
]
