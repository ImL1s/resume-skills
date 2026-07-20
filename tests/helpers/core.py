from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any


def tree_snapshot(root: str | os.PathLike[str]) -> dict[str, tuple[Any, ...]]:
    base = Path(root)
    output: dict[str, tuple[Any, ...]] = {}
    for path in sorted((base, *base.rglob("*")), key=lambda item: str(item)):
        relative = "." if path == base else str(path.relative_to(base))
        current = path.lstat()
        digest = None
        if stat.S_ISREG(current.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        output[relative] = (
            current.st_dev,
            current.st_ino,
            current.st_mode,
            current.st_size,
            current.st_mtime_ns,
            digest,
        )
    return output
