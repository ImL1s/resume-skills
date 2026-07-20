"""Strict request-v1 file boundary; user values remain JSON data, never argv."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from typing import Any

from .bounds import DEFAULT_BOUNDS
from .contracts import REQUEST_KEYS
from .diagnostics import DiagnosticError, SOURCE_KEYS
from .paths import reject_controls, validate_canonical_absolute


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


class _DuplicateKey(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise _DuplicateKey
        output[key] = value
    return output


def _read_regular_request(path: str) -> bytes:
    try:
        before_path = os.lstat(path)
    except OSError as error:
        raise DiagnosticError.invalid() from error
    if stat.S_ISLNK(before_path.st_mode) or not stat.S_ISREG(before_path.st_mode):
        raise DiagnosticError.invalid()
    if before_path.st_size > DEFAULT_BOUNDS.request_bytes:
        raise DiagnosticError.invalid()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DiagnosticError.invalid() from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > DEFAULT_BOUNDS.request_bytes:
            raise DiagnosticError.invalid()
        chunks: list[bytes] = []
        remaining = DEFAULT_BOUNDS.request_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        final_path = os.lstat(path)
    except OSError as error:
        raise DiagnosticError.invalid() from error
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ) == (
        final_path.st_dev,
        final_path.st_ino,
        final_path.st_mode,
        final_path.st_size,
        final_path.st_mtime_ns,
    )
    if not stable or len(data) > DEFAULT_BOUNDS.request_bytes:
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
