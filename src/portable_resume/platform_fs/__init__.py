"""Cross-platform safe-filesystem backend package."""

from .api import FilesystemBackend, FilesystemCapabilities, FilesystemIdentity, FilesystemObjectIdentity
from .select import get_filesystem_backend
from .unsupported import UnsupportedFilesystemBackend

__all__ = [
    "FilesystemBackend",
    "FilesystemCapabilities",
    "FilesystemIdentity",
    "FilesystemObjectIdentity",
    "UnsupportedFilesystemBackend",
    "get_filesystem_backend",
]
