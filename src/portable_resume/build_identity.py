"""Deterministic, dependency-free build provenance for release artifacts.

The public package version remains the PEP 440 base version from
``portable_resume.__version__``.  A build identity adds checkout provenance
without making normal runtime behavior depend on Git or a third-party version
plugin.  Source archives without Git metadata stay deterministic and report
unknown commit/dirty state honestly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from . import __version__

BUILD_IDENTITY_SCHEMA_V1 = "portable-resume/build-identity-v1"
BUILD_IDENTITY_SCHEMA_V2 = "portable-resume/build-identity-v2"
BUILD_IDENTITY_SCHEMA = BUILD_IDENTITY_SCHEMA_V2
LATEST_RELEASE_SCHEMA = "portable-resume/latest-release-v1"

_RELEASE_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DEVELOPMENT_VERSION = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\.dev(0|[1-9]\d*)$"
)
_IDENTITY_VERSION = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:\.dev(0|[1-9]\d*))?(?:\+[0-9a-z]+(?:\.[0-9a-z]+)*)?$"
)
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_V1_REQUIRED_KEYS = frozenset(
    {
        "schema",
        "version",
        "base_version",
        "release_channel",
        "commit_sha",
        "dirty",
        "registry_sha256",
        "source_sha256",
    }
)
_V2_REQUIRED_KEYS = _V1_REQUIRED_KEYS | {"build_inputs_sha256"}
_OPTIONAL_KEYS = frozenset({"provenance"})
_GENERATED_IDENTITY = Path("resources/build-identity.json")
_LATEST_RELEASE = Path("resources/latest-release.json")
MAX_BUILD_IDENTITY_BYTES = 16 * 1024
MAX_SOURCE_FILE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 512 * 1024 * 1024


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _registry_payload() -> dict[str, object]:
    """Return the closed registry representation used by identity hashing."""
    from .registry import DESTINATION_PROFILES, PACKAGE_SURFACES, SOURCE_PROFILES

    return {
        "sources": {
            key: asdict(SOURCE_PROFILES[key]) for key in sorted(SOURCE_PROFILES)
        },
        "destinations": {
            key: asdict(DESTINATION_PROFILES[key])
            for key in sorted(DESTINATION_PROFILES)
        },
        "packages": {
            key: asdict(PACKAGE_SURFACES[key]) for key in sorted(PACKAGE_SURFACES)
        },
    }


def latest_release(package_root: Path | None = None) -> dict[str, object]:
    """Load and validate the immutable latest-published-release baseline."""
    root = (
        Path(package_root).resolve()
        if package_root is not None
        else Path(__file__).resolve().parent
    )
    try:
        value = json.loads((root / _LATEST_RELEASE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("latest release baseline is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("latest release baseline has the wrong shape")
    required = {
        "schema",
        "version",
        "tag",
        "commit_sha",
        "registry_sha256",
        "source_sha256",
        "matrix_dimensions",
        "artifact_classes",
        "published_at",
        "github_release",
        "pypi",
    }
    if set(value) != required or value.get("schema") != LATEST_RELEASE_SCHEMA:
        raise ValueError("latest release baseline fields are invalid")
    version = value.get("version")
    if not isinstance(version, str) or _RELEASE_VERSION.fullmatch(version) is None:
        raise ValueError("latest release version is invalid")
    if value.get("tag") != f"v{version}":
        raise ValueError("latest release tag does not match its version")
    if not isinstance(value.get("commit_sha"), str) or _HEX_40.fullmatch(
        str(value["commit_sha"])
    ) is None:
        raise ValueError("latest release commit is invalid")
    for key in ("registry_sha256", "source_sha256"):
        if not isinstance(value.get(key), str) or _SHA256.fullmatch(
            str(value[key])
        ) is None:
            raise ValueError(f"latest release {key} is invalid")
    dimensions = value.get("matrix_dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != {
        "sources",
        "destinations",
        "cells",
    }:
        raise ValueError("latest release matrix dimensions are invalid")
    if not all(type(dimensions[key]) is int and dimensions[key] > 0 for key in dimensions):
        raise ValueError("latest release matrix counts are invalid")
    if dimensions["sources"] * dimensions["destinations"] != dimensions["cells"]:
        raise ValueError("latest release matrix is not rectangular")
    classes = value.get("artifact_classes")
    if (
        not isinstance(classes, list)
        or not classes
        or not all(isinstance(item, str) and item for item in classes)
        or classes != sorted(set(classes))
    ):
        raise ValueError("latest release artifact classes are invalid")
    for key in ("published_at", "github_release", "pypi"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError(f"latest release {key} is invalid")
    return value


def registry_sha256(
    *, registry_payload: Mapping[str, object] | None = None
) -> str:
    """Hash the canonical source/destination/package profile representation."""
    payload: Mapping[str, object]
    if registry_payload is None:
        payload = _registry_payload()
    else:
        payload = registry_payload
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _stat_fingerprint(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable_regular_file(
    path: Path,
    *,
    before: os.stat_result,
    max_bytes: int,
    subject: str,
) -> bytes:
    """Read one bounded inode without following a swapped final symlink."""
    if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
        raise ValueError(f"{subject} is not a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{subject} is unreadable") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size > max_bytes
            or _stat_fingerprint(opened) != _stat_fingerprint(before)
        ):
            raise ValueError(f"{subject} changed before open")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(data) > max_bytes:
            raise ValueError(f"{subject} is oversized")
        if _stat_fingerprint(after) != _stat_fingerprint(opened):
            raise ValueError(f"{subject} changed during read")
    finally:
        os.close(descriptor)
    try:
        final_path = path.lstat()
    except OSError as error:
        raise ValueError(f"{subject} changed after read") from error
    if _stat_fingerprint(final_path) != _stat_fingerprint(opened):
        raise ValueError(f"{subject} changed after read")
    return data


def source_sha256(package_root: Path) -> str:
    """Hash runtime package sources, excluding generated/cached identity bytes."""
    root = package_root.resolve()
    if not root.is_dir():
        raise ValueError("package root is not a directory")
    digest = hashlib.sha256()
    found = False
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or relative == _GENERATED_IDENTITY:
            continue
        try:
            metadata = path.lstat()
        except OSError as error:
            raise ValueError("package source is unreadable") from error
        name = relative.as_posix().encode("utf-8")
        mode = stat.S_IMODE(metadata.st_mode).to_bytes(4, "big")
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(name)
            digest.update(b"\0directory\0")
            digest.update(mode)
            digest.update(b"\0")
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("package source contains a non-regular file")
        if path.suffix in {".pyc", ".pyo"}:
            continue
        data = _read_stable_regular_file(
            path,
            before=metadata,
            max_bytes=MAX_SOURCE_FILE_BYTES,
            subject="package source file",
        )
        total_bytes += len(data)
        if total_bytes > MAX_SOURCE_TOTAL_BYTES:
            raise ValueError("package source exceeds the aggregate bound")
        digest.update(name)
        digest.update(b"\0file\0")
        digest.update(mode)
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        found = True
    if not found:
        raise ValueError("package root contains no source files")
    return digest.hexdigest()


def _validate_base_version(base_version: str) -> str:
    if _RELEASE_VERSION.fullmatch(base_version):
        return "stable"
    if _DEVELOPMENT_VERSION.fullmatch(base_version):
        return "development"
    raise ValueError("base version must be strict X.Y.Z or X.Y.Z.devN")


def build_identity(
    *,
    package_root: Path | None = None,
    base_version: str | None = None,
    commit_sha: str | None = None,
    dirty: bool | None = None,
    exact_tag: bool = False,
    build_inputs_sha256: str | None = None,
) -> dict[str, object]:
    """Return a closed identity from explicit, already-collected build facts.

    This product-path function never invokes Git or any other process.  Normal
    reader/installer runtimes therefore report an honest source-archive
    fallback.  Explicit build and release tooling may collect Git facts outside
    ``src/portable_resume`` and pass them here.
    """
    package = (
        Path(package_root).resolve()
        if package_root is not None
        else Path(__file__).resolve().parent
    )
    base = base_version or __version__
    base_kind = _validate_base_version(base)
    if type(exact_tag) is not bool:
        raise ValueError("exact tag state must be boolean")
    if commit_sha is None:
        if dirty is not None or exact_tag or build_inputs_sha256 is not None:
            raise ValueError("dirty/tag facts require a commit SHA")
    else:
        if _HEX_40.fullmatch(commit_sha) is None:
            raise ValueError("invalid commit SHA")
        if type(dirty) is not bool:
            raise ValueError("Git identity requires a boolean dirty state")
        if (
            not isinstance(build_inputs_sha256, str)
            or _SHA256.fullmatch(build_inputs_sha256) is None
        ):
            raise ValueError("Git identity requires a build inputs digest")

    release = base_kind == "stable" and exact_tag and dirty is False
    release_channel = "release" if release else "development"
    if release:
        version = base
    elif commit_sha is not None:
        version = f"{base}+g{commit_sha[:12]}"
        if dirty:
            version += ".dirty"
    else:
        # A raw source archive cannot prove a commit or cleanliness.  Retain the
        # deterministic base version and expose the unknowns as null fields.
        version = base

    identity: dict[str, object] = {
        "schema": BUILD_IDENTITY_SCHEMA,
        "version": version,
        "base_version": base,
        "release_channel": release_channel,
        "commit_sha": commit_sha,
        "dirty": dirty,
        "build_inputs_sha256": build_inputs_sha256,
        "registry_sha256": registry_sha256(),
        "source_sha256": source_sha256(package),
        "provenance": "git" if commit_sha is not None else "source-archive",
    }
    validate_identity(identity)
    return identity


def validate_identity(identity: Mapping[str, Any]) -> None:
    """Validate the closed identity schema; raise ``ValueError`` on drift."""
    schema = identity.get("schema")
    if schema == BUILD_IDENTITY_SCHEMA_V1:
        required_keys = _V1_REQUIRED_KEYS
    elif schema == BUILD_IDENTITY_SCHEMA_V2:
        required_keys = _V2_REQUIRED_KEYS
    else:
        raise ValueError("unsupported build identity schema")
    keys = frozenset(identity)
    if not required_keys.issubset(keys) or not keys.issubset(
        required_keys | _OPTIONAL_KEYS
    ):
        raise ValueError("build identity fields are incomplete or unknown")
    version = identity.get("version")
    base = identity.get("base_version")
    if not isinstance(version, str) or _IDENTITY_VERSION.fullmatch(version) is None:
        raise ValueError("invalid identity version")
    if not isinstance(base, str):
        raise ValueError("invalid base version")
    _validate_base_version(base)
    if identity.get("release_channel") not in {"release", "development"}:
        raise ValueError("invalid release channel")
    commit = identity.get("commit_sha")
    if commit is not None and (
        not isinstance(commit, str) or _HEX_40.fullmatch(commit) is None
    ):
        raise ValueError("invalid commit SHA")
    dirty = identity.get("dirty")
    if dirty is not None and type(dirty) is not bool:
        raise ValueError("invalid dirty state")
    build_inputs_digest = identity.get("build_inputs_sha256")
    if build_inputs_digest is not None and (
        not isinstance(build_inputs_digest, str)
        or _SHA256.fullmatch(build_inputs_digest) is None
    ):
        raise ValueError("invalid build_inputs_sha256")
    for key in ("registry_sha256", "source_sha256"):
        value = identity.get(key)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"invalid {key}")
    provenance = identity.get("provenance")
    if provenance is not None and provenance not in {
        "git",
        "source-archive",
        "embedded",
    }:
        raise ValueError("invalid provenance")
    channel = identity.get("release_channel")
    if commit is None:
        if dirty is not None or build_inputs_digest is not None:
            raise ValueError("dirty state requires a commit SHA")
        expected_version = base
        if provenance not in {None, "source-archive", "embedded"}:
            raise ValueError("commitless identity has invalid provenance")
    else:
        if type(dirty) is not bool:
            raise ValueError("Git identity requires a boolean dirty state")
        if schema == BUILD_IDENTITY_SCHEMA_V2 and not isinstance(
            build_inputs_digest, str
        ):
            raise ValueError("Git identity requires a build inputs digest")
        expected_version = f"{base}+g{commit[:12]}"
        if dirty:
            expected_version += ".dirty"
        if provenance not in {None, "git", "embedded"}:
            raise ValueError("commit identity has invalid provenance")
    if channel == "release":
        if (
            _RELEASE_VERSION.fullmatch(base) is None
            or commit is None
            or dirty is not False
        ):
            raise ValueError("release identity must be an exact clean Git commit")
        expected_version = base
        if version != expected_version:
            raise ValueError("release identity must use the exact base version")
    elif version != expected_version:
        raise ValueError("development identity version does not match its build facts")


def validate_current_identity(identity: Mapping[str, Any]) -> None:
    """Require the current schema for newly produced or verified artifacts."""
    validate_identity(identity)
    if identity.get("schema") != BUILD_IDENTITY_SCHEMA:
        raise ValueError("artifact operations require the current identity schema")


def identity_json_bytes(identity: Mapping[str, Any]) -> bytes:
    """Serialize a validated identity as canonical UTF-8 JSON."""
    validate_identity(identity)
    return _canonical_json_bytes(identity)


def assert_identity_matches_package(
    identity: Mapping[str, Any],
    *,
    package_root: Path | None = None,
) -> None:
    """Require identity digests to describe the complete package source tree."""
    validate_identity(identity)
    root = (
        Path(package_root).resolve()
        if package_root is not None
        else Path(__file__).resolve().parent
    )
    if identity.get("base_version") != __version__:
        raise ValueError("build identity base version differs from package")
    if identity.get("registry_sha256") != registry_sha256():
        raise ValueError("build identity registry differs from package")
    if identity.get("source_sha256") != source_sha256(root):
        raise ValueError("build identity source digest differs from package")


def load_identity_bytes(data: bytes) -> dict[str, object]:
    """Load one bounded canonical identity document from bytes."""
    if not isinstance(data, bytes) or len(data) > MAX_BUILD_IDENTITY_BYTES:
        raise ValueError("build identity is oversized")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("build identity is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("build identity has the wrong shape")
    validate_identity(value)
    if data != identity_json_bytes(value):
        raise ValueError("build identity is not canonical")
    return dict(value)


def load_identity_file(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    """Read a canonical identity through a bounded no-follow regular file."""
    if expected_sha256 is not None and _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("expected build identity digest is invalid")
    identity_path = Path(path)
    try:
        before = identity_path.lstat()
    except FileNotFoundError:
        raise
    except OSError as error:
        raise ValueError("build identity is unreadable") from error
    data = _read_stable_regular_file(
        identity_path,
        before=before,
        max_bytes=MAX_BUILD_IDENTITY_BYTES,
        subject="build identity",
    )
    if expected_sha256 is not None and not hmac.compare_digest(
        hashlib.sha256(data).hexdigest(),
        expected_sha256,
    ):
        raise ValueError("build identity digest mismatch")
    return load_identity_bytes(data)


def load_embedded_identity(
    package_root: Path | None = None,
) -> dict[str, object] | None:
    """Load the fixed packaged identity, or return ``None`` when absent."""
    root = (
        Path(package_root).resolve()
        if package_root is not None
        else Path(__file__).resolve().parent
    )
    try:
        identity = load_identity_file(root / _GENERATED_IDENTITY)
    except FileNotFoundError:
        return None
    if identity.get("base_version") != __version__:
        raise ValueError("embedded identity base version differs from runtime")
    if identity.get("registry_sha256") != registry_sha256():
        raise ValueError("embedded identity registry differs from runtime")
    return identity


def runtime_identity(package_root: Path | None = None) -> dict[str, object]:
    """Return embedded artifact provenance or an honest source-only fallback.

    Runtime lookup uses only the fixed packaged resource. It never consults an
    environment-selected path and never invokes Git or another process.
    """
    root = (
        Path(package_root).resolve()
        if package_root is not None
        else Path(__file__).resolve().parent
    )
    embedded = load_embedded_identity(root)
    if embedded is not None:
        return embedded
    return build_identity(package_root=root)
