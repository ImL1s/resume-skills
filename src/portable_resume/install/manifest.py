"""Install manifest schema: claims, hashes, generation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from ..diagnostics import SOURCE_KEYS
from .catalog import BUNDLE_VERSION, MANIFEST_SCHEMA
from .control_schema import OWNER_MARKER, ControlSchemaError, parse_manifest_document


def validate_rel_path(rel: str) -> str:
    """Reject absolute paths, NUL, and parent escapes in manifest/install relative paths."""
    from pathlib import Path

    if not rel or rel.startswith("/") or rel.startswith("\\") or "\x00" in rel:
        raise ValueError(f"unsafe relative path: {rel!r}")
    parts = Path(rel).parts
    if any(part in {"..", ""} for part in parts):
        raise ValueError(f"unsafe relative path: {rel!r}")
    return Path(*parts).as_posix()


@dataclass(slots=True)
class FileEntry:
    path: str
    sha256: str
    claims: list[str] = field(default_factory=list)
    mode: int = 0o644

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "claims": sorted(self.claims),
            "mode": self.mode,
            "owner": OWNER_MARKER,
        }


@dataclass(slots=True)
class Manifest:
    schema_version: str
    bundle_version: str
    generation: int
    package_identity: str
    claims: dict[str, dict[str, Any]]
    files: dict[str, FileEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_version": self.bundle_version,
            "generation": self.generation,
            "package_identity": self.package_identity,
            "claims": {key: dict(sorted(value.items())) for key, value in sorted(self.claims.items())},
            "files": {path: entry.to_dict() for path, entry in sorted(self.files.items())},
        }

    def dumps(self) -> str:
        text = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        # Self-check: serializers only emit documents the strict parser accepts.
        parse_manifest_document(text)
        return text

    @classmethod
    def loads(cls, text: str) -> "Manifest":
        """Strict bounded parse of install-manifest-v1 (#28)."""

        try:
            data = parse_manifest_document(text)
        except ControlSchemaError as error:
            raise ValueError(str(error)) from error
        files: dict[str, FileEntry] = {}
        for path, entry in data["files"].items():
            files[path] = FileEntry(
                path=entry["path"],
                sha256=entry["sha256"],
                claims=list(entry["claims"]),
                mode=int(entry["mode"]),
            )
        return cls(
            schema_version=data["schema_version"],
            bundle_version=data["bundle_version"],
            generation=int(data["generation"]),
            package_identity=data["package_identity"],
            claims={k: dict(v) for k, v in data["claims"].items()},
            files=files,
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """Hash a regular file without following symlinks when O_NOFOLLOW is available."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError:
        # Fallback: refuse obvious symlinks, then follow-open (platforms without O_NOFOLLOW).
        if os.path.islink(path):
            raise
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        import stat as stat_mod

        mode = os.fstat(fd).st_mode
        if not stat_mod.S_ISREG(mode):
            raise OSError("not a regular file")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def claim_key(*, host: str, scope: str, root: str) -> str:
    return f"{host}|{scope}|{os.path.realpath(root)}"


def normalize_claim_sources(sources: tuple[str, ...] | None) -> tuple[str, ...]:
    """Return the canonical explicit source set stored on new ownership claims."""

    if sources is None:
        return tuple(sorted(SOURCE_KEYS))
    normalized = tuple(sorted(dict.fromkeys(sources)))
    if not normalized or any(source not in SOURCE_KEYS for source in normalized):
        raise ValueError("invalid claim sources")
    return normalized


def resolve_claim_sources(manifest: Manifest, claim: str) -> tuple[str, ...]:
    """Resolve a claim's recorded sources, with bounded legacy inference.

    Pre-field manifests are accepted only when their claim-owned top-level
    ``resume-<source>`` paths identify a non-empty enabled source set. Exact
    path-set validation remains the verifier's responsibility, so incomplete,
    mixed, or otherwise ambiguous legacy ownership fails closed there.
    """

    meta = manifest.claims.get(claim)
    if meta is None:
        raise ValueError("unknown claim")
    recorded = meta.get("sources")
    if recorded is not None:
        if not isinstance(recorded, list):
            raise ValueError("invalid claim sources")
        return normalize_claim_sources(tuple(recorded))
    inferred: set[str] = set()
    for rel, entry in manifest.files.items():
        if claim not in entry.claims:
            continue
        top = rel.split("/", 1)[0]
        if not top.startswith("resume-"):
            continue
        source = top.removeprefix("resume-")
        if source not in SOURCE_KEYS:
            raise ValueError("ambiguous legacy claim sources")
        inferred.add(source)
    if not inferred:
        raise ValueError("ambiguous legacy claim sources")
    return tuple(sorted(inferred))


def build_manifest(
    *,
    files: dict[str, bytes],
    claim: str,
    host: str,
    scope: str,
    root: str,
    package_identity: str,
    generation: int,
    sources: tuple[str, ...] | None = None,
    existing: Manifest | None = None,
) -> Manifest:
    claims = dict(existing.claims) if existing else {}
    claims[claim] = {
        "host": host,
        "scope": scope,
        "root": os.path.realpath(root),
        "bundle_version": BUNDLE_VERSION,
        "package_identity": package_identity,
        "sources": list(normalize_claim_sources(sources)),
    }
    file_map: dict[str, FileEntry] = dict(existing.files) if existing else {}
    # Drop previous claim references, then re-add for this claim's files.
    for entry in file_map.values():
        entry.claims = [c for c in entry.claims if c != claim]
    for rel, data in files.items():
        rel = validate_rel_path(rel)
        mode = 0o755 if rel.endswith("run_reader.py") else 0o644
        digest = sha256_bytes(data)
        if rel in file_map:
            entry = file_map[rel]
            if entry.sha256 != digest:
                # Same path different content while another claim still references it: conflict
                # unless this is the sole remaining claim after drop above.
                if entry.claims:
                    raise ValueError(f"shared path content mismatch: {rel}")
                entry.sha256 = digest
                entry.mode = mode
            if claim not in entry.claims:
                entry.claims.append(claim)
        else:
            file_map[rel] = FileEntry(path=rel, sha256=digest, claims=[claim], mode=mode)
    # Remove unreferenced files from manifest (physical delete handled by transaction).
    file_map = {path: entry for path, entry in file_map.items() if entry.claims}
    # New source-aware claims carry their own plan identity. Once every claim
    # has that field, keep the legacy top-level identity deterministic rather
    # than dependent on which shared-root claim happened to install last.
    if claims and all("package_identity" in meta for meta in claims.values()):
        package_identity = claims[sorted(claims)[0]]["package_identity"]
    return Manifest(
        schema_version=MANIFEST_SCHEMA,
        bundle_version=BUNDLE_VERSION,
        generation=generation,
        package_identity=package_identity,
        claims=claims,
        files=file_map,
    )


def empty_manifest(package_identity: str) -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA,
        bundle_version=BUNDLE_VERSION,
        generation=0,
        package_identity=package_identity,
        claims={},
        files={},
    )


def recompute_top_package_identity(manifest: Manifest) -> None:
    """Align top-level ``package_identity`` with remaining claims after uninstall.

    Prefer the recorded ``package_identity`` of the lexicographically first claim
    (same rule as :func:`build_manifest`). For legacy claims without that field,
    derive identity from host + :func:`resolve_claim_sources` + the materialize
    plan so shared-root uninstall does not leave a removed claim's digest
    (#242 Codex P1).
    """

    if not manifest.claims:
        return
    first = sorted(manifest.claims)[0]
    meta = manifest.claims[first]
    recorded = meta.get("package_identity")
    if isinstance(recorded, str) and recorded:
        # When every claim is source-aware, first-claim identity is authoritative.
        if all(
            isinstance(m.get("package_identity"), str) and m.get("package_identity")
            for m in manifest.claims.values()
        ):
            manifest.package_identity = recorded
            return
    host = meta.get("host")
    if not isinstance(host, str):
        return
    try:
        from .catalog import HOST_PROFILES
        from .render import materialize_plan, package_identity as identity_of

        if host not in HOST_PROFILES:
            return
        sources = resolve_claim_sources(manifest, first)
        manifest.package_identity = identity_of(materialize_plan(host, sources=sources))
    except (ValueError, KeyError, TypeError):
        return
