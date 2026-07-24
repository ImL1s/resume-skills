#!/usr/bin/env python3
"""Write checksums for the flat filenames uploaded to a GitHub Release."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9._+-]+$")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_manifest(output: Path, inputs: list[Path]) -> None:
    assets: dict[str, Path] = {}
    for path in inputs:
        if not path.is_file():
            raise ValueError(f"release asset is not a file: {path}")
        name = path.name
        if SAFE_ASSET_NAME.fullmatch(name) is None:
            raise ValueError(f"unsafe release asset basename: {name!r}")
        previous = assets.get(name)
        if previous is not None:
            raise ValueError(
                f"duplicate release asset basename {name!r}: {previous} and {path}"
            )
        assets[name] = path

    if not assets:
        raise ValueError("at least one release asset is required")
    if output.name in assets:
        raise ValueError("checksum manifest cannot include itself")

    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{_digest(assets[name])}  {name}\n" for name in sorted(assets)]
    descriptor, temporary = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.writelines(lines)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(output)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("assets", nargs="+", type=Path)
    namespace = parser.parse_args(argv)
    try:
        write_manifest(namespace.output, namespace.assets)
    except (OSError, ValueError) as error:
        print(f"CHECKSUM_MANIFEST FAIL {error}", file=sys.stderr)
        return 1
    print(
        f"CHECKSUM_MANIFEST PASS output={namespace.output} "
        f"assets={len(namespace.assets)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
