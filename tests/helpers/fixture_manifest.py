"""Reusable fail-closed validation for independently authored fixture manifests."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from portable_resume.diagnostics import ERROR_EXIT_CODES, SOURCE_KEYS, WARNING_CODES

_REQUIRED = frozenset(
    {
        "synthetic",
        "source",
        "format_id",
        "case",
        "expected_operation",
        "expected_code",
        "expected_warnings",
        "provenance_ref",
    }
)
_SLUG = re.compile(r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
_PRIVATE_PATH = re.compile(r"(?:^|[\\/])(?:Users|home)[\\/][^\\/]+", re.IGNORECASE)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


class FixtureManifestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FixtureManifest:
    source: str
    format_id: str
    case: str
    expected_operation: str
    expected_code: int
    expected_warnings: tuple[str, ...]
    provenance_ref: str
    synthetic: bool = True


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def validate_fixture_manifest(path: str | os.PathLike[str]) -> FixtureManifest:
    """Validate exact fixture metadata without opening any transcript payload."""

    candidate = Path(path)
    try:
        raw = candidate.read_bytes()
    except OSError as error:
        raise FixtureManifestError("fixture manifest is unreadable") from error
    if len(raw) > 16 * 1024:
        raise FixtureManifestError("fixture manifest exceeds 16 KiB")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
        raise FixtureManifestError("fixture manifest is invalid JSON") from error
    if not isinstance(payload, dict) or set(payload) != _REQUIRED:
        raise FixtureManifestError("fixture manifest keys are not exact")
    if payload["synthetic"] is not True:
        raise FixtureManifestError("fixture must be explicitly synthetic")
    if payload["source"] not in SOURCE_KEYS:
        raise FixtureManifestError("fixture source is unsupported")
    for key in ("format_id", "case"):
        value = payload[key]
        if not isinstance(value, str) or len(value) > 128 or _SLUG.fullmatch(value) is None:
            raise FixtureManifestError(f"fixture {key} is invalid")
    if payload["expected_operation"] not in {"list", "show", "error"}:
        raise FixtureManifestError("fixture operation is invalid")
    expected_codes = {0, *(int(code) for code in set(ERROR_EXIT_CODES.values()))}
    if type(payload["expected_code"]) is not int or payload["expected_code"] not in expected_codes:
        raise FixtureManifestError("fixture exit code is invalid")
    warnings = payload["expected_warnings"]
    if not isinstance(warnings, list) or len(warnings) > 256 or any(item not in WARNING_CODES for item in warnings):
        raise FixtureManifestError("fixture warnings are invalid")
    provenance = payload["provenance_ref"]
    if not isinstance(provenance, str) or not provenance.startswith("docs/source-formats.md#") or len(provenance) > 256:
        raise FixtureManifestError("fixture provenance is invalid")
    for value in _all_strings(payload):
        if os.path.isabs(value) or _WINDOWS_ABSOLUTE.match(value) or _PRIVATE_PATH.search(value):
            raise FixtureManifestError("fixture manifest contains a private-looking absolute path")
    return FixtureManifest(
        source=payload["source"],
        format_id=payload["format_id"],
        case=payload["case"],
        expected_operation=payload["expected_operation"],
        expected_code=payload["expected_code"],
        expected_warnings=tuple(warnings),
        provenance_ref=provenance,
    )


def validate_fixture_tree(root: str | os.PathLike[str]) -> tuple[FixtureManifest, ...]:
    """Validate every fixture.json below a synthetic fixture tree deterministically."""

    paths = sorted(Path(root).rglob("fixture.json"), key=lambda item: item.as_posix())
    return tuple(validate_fixture_manifest(path) for path in paths)


def _all_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)
