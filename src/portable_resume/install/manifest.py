"""Install manifest schema: claims, hashes, generation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from .catalog import BUNDLE_VERSION, MANIFEST_SCHEMA

OWNER_MARKER = "portable-resume-owned"


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
    claims: dict[str, dict[str, str]]
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
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    @classmethod
    def loads(cls, text: str) -> "Manifest":
        data = json.loads(text)
        files = {
            path: FileEntry(
                path=path,
                sha256=entry["sha256"],
                claims=list(entry.get("claims", [])),
                mode=int(entry.get("mode", 0o644)),
            )
            for path, entry in data.get("files", {}).items()
        }
        return cls(
            schema_version=data["schema_version"],
            bundle_version=data["bundle_version"],
            generation=int(data["generation"]),
            package_identity=data["package_identity"],
            claims={k: dict(v) for k, v in data.get("claims", {}).items()},
            files=files,
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def claim_key(*, host: str, scope: str, root: str) -> str:
    return f"{host}|{scope}|{os.path.realpath(root)}"


def build_manifest(
    *,
    files: dict[str, bytes],
    claim: str,
    host: str,
    scope: str,
    root: str,
    package_identity: str,
    generation: int,
    existing: Manifest | None = None,
) -> Manifest:
    claims = dict(existing.claims) if existing else {}
    claims[claim] = {
        "host": host,
        "scope": scope,
        "root": os.path.realpath(root),
        "bundle_version": BUNDLE_VERSION,
    }
    file_map: dict[str, FileEntry] = dict(existing.files) if existing else {}
    # Drop previous claim references, then re-add for this claim's files.
    for entry in file_map.values():
        entry.claims = [c for c in entry.claims if c != claim]
    for rel, data in files.items():
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
