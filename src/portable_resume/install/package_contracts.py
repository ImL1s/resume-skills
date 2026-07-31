"""Versioned host-package compatibility contracts (#27).

Offline gates consume these contracts to validate archives beyond bare ZIP
shape checks. Native host CLI install/invoke remains a separate evidence
layer (``native_evidence_status``), never silently upgraded to pass.
"""

from __future__ import annotations

import hashlib
import io
import json
import stat
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable, Mapping

from .. import __version__ as BUNDLE_VERSION
from ..build_identity import (
    MAX_BUILD_IDENTITY_BYTES,
    identity_json_bytes,
    load_identity_bytes,
    registry_sha256,
)
from ..diagnostics import DiagnosticError, SOURCE_KEYS
from ..snapshot import stable_read_bytes

# Schema of this contracts module itself (bumped when contract fields change).
PACKAGE_CONTRACTS_SCHEMA = "portable-resume/package-contracts-v1"
RUNTIME_IDENTITY_RELATIVE = (
    ".portable-resume/runtime/portable_resume/resources/build-identity.json"
)
RUNTIME_SCHEMA_RELATIVE = (
    ".portable-resume/runtime/portable_resume/resources/portable-resume-v1.schema.json"
)
MAX_MANIFEST_MEMBER_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP_EOCD_SIZE = 22
_ZIP_MAX_COMMENT_BYTES = 0xFFFF

# Shared forbidden path fragments inside any package archive (match root-relative
# and nested spellings — do not require a leading slash).
FORBIDDEN_PATH_SUBSTRINGS: tuple[str, ...] = (
    "portable_resume/install/",
    "portable_resume\\install\\",
    ".portable-resume/.state/",
)


def _read_exact_at(handle: BinaryIO, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0:
        raise ValueError("archive is not a valid zip")
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("archive is not a valid zip")
    return data


def _preflight_zip_archive(handle: BinaryIO) -> int:
    """Bound the ZIP entry table before ``zipfile`` materializes it."""

    handle.seek(0, io.SEEK_END)
    archive_size = handle.tell()
    tail_size = min(archive_size, _ZIP_EOCD_SIZE + _ZIP_MAX_COMMENT_BYTES)
    tail_offset = archive_size - tail_size
    tail = _read_exact_at(handle, tail_offset, tail_size)
    search_end = len(tail)
    while True:
        relative_eocd = tail.rfind(_ZIP_EOCD_SIGNATURE, 0, search_end)
        if relative_eocd < 0:
            raise ValueError("archive is not a valid zip")
        if relative_eocd + _ZIP_EOCD_SIZE <= len(tail):
            candidate = tail[relative_eocd : relative_eocd + _ZIP_EOCD_SIZE]
            candidate_comment_size = struct.unpack_from("<H", candidate, 20)[0]
            if relative_eocd + _ZIP_EOCD_SIZE + candidate_comment_size == len(tail):
                eocd = candidate
                break
        search_end = relative_eocd

    (
        disk_number,
        central_disk,
        entries_on_disk,
        entries_total,
        central_size,
        central_offset,
        comment_size,
    ) = struct.unpack_from("<HHHHIIH", eocd, 4)
    if comment_size != candidate_comment_size:
        raise ValueError("archive is not a valid zip")
    eocd_offset = tail_offset + relative_eocd
    if disk_number != 0 or central_disk != 0 or entries_on_disk != entries_total:
        raise ValueError("multi-disk ZIP archives are unsupported")

    central_limit = eocd_offset
    needs_zip64 = (
        entries_total == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
    )
    if needs_zip64:
        locator_offset = eocd_offset - 20
        locator = _read_exact_at(handle, locator_offset, 20)
        if locator[:4] != _ZIP64_LOCATOR_SIGNATURE:
            raise ValueError("archive ZIP64 locator is invalid")
        locator_disk, zip64_offset, total_disks = struct.unpack_from(
            "<IQI", locator, 4
        )
        if locator_disk != 0 or total_disks != 1:
            raise ValueError("multi-disk ZIP64 archives are unsupported")
        zip64_eocd = _read_exact_at(handle, zip64_offset, 56)
        if zip64_eocd[:4] != _ZIP64_EOCD_SIGNATURE:
            raise ValueError("archive ZIP64 record is invalid")
        record_size = struct.unpack_from("<Q", zip64_eocd, 4)[0]
        zip64_disk, zip64_central_disk = struct.unpack_from("<II", zip64_eocd, 16)
        entries_on_disk, entries_total = struct.unpack_from("<QQ", zip64_eocd, 24)
        central_size, central_offset = struct.unpack_from("<QQ", zip64_eocd, 40)
        if (
            record_size < 44
            or zip64_offset > locator_offset
            or record_size > locator_offset - zip64_offset - 12
            or zip64_disk != 0
            or zip64_central_disk != 0
            or entries_on_disk != entries_total
        ):
            raise ValueError("archive ZIP64 record is invalid")
        central_limit = zip64_offset

    if entries_total > MAX_ARCHIVE_MEMBERS:
        raise ValueError("archive exceeds the member-count bound")
    if central_size > MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES:
        raise ValueError("archive exceeds the central-directory size bound")
    if central_offset > central_limit or central_size > central_limit - central_offset:
        raise ValueError("archive central directory is out of bounds")
    handle.seek(0)
    return int(entries_total)


@dataclass(frozen=True, slots=True)
class PackageContract:
    """Closed offline contract for one package surface or direct-skills zip."""

    contract_id: str
    package_type: str
    destination: str | None
    # Paths that must exist in the archive (posix).
    required_members: tuple[str, ...]
    # Primary machine-readable manifest path (may be empty for direct-skills).
    primary_manifest: str | None
    # Required top-level keys in primary_manifest JSON (if set).
    required_manifest_keys: frozenset[str]
    # Optional exact key→value pairs (string equality after str()).
    required_manifest_values: dict[str, str]
    # Prefix under which resume-*/SKILL.md trees must live.
    skills_prefix: str
    # Marketplace/plugin entry must resolve into this relative plugin root.
    plugin_root: str | None
    # Where host docs say package version comes from.
    version_source: str
    # Canonical operator-facing installation hint embedded in build reports.
    install_hint: str
    # Native CLI install/activate evidence for this contract (honest default).
    native_evidence_status: str = "not-run"
    # Historical last-known native revalidation tag/commit (informational).
    last_native_evidence_ref: str | None = "v0.3.2"
    docs_checked_date: str = "2026-07-26"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "package_type": self.package_type,
            "destination": self.destination,
            "required_members": list(self.required_members),
            "primary_manifest": self.primary_manifest,
            "required_manifest_keys": sorted(self.required_manifest_keys),
            "required_manifest_values": dict(sorted(self.required_manifest_values.items())),
            "skills_prefix": self.skills_prefix,
            "plugin_root": self.plugin_root,
            "version_source": self.version_source,
            "install_hint": self.install_hint,
            "native_evidence_status": self.native_evidence_status,
            "last_native_evidence_ref": self.last_native_evidence_ref,
            "docs_checked_date": self.docs_checked_date,
        }


def _common_required_manifest_values() -> dict[str, str]:
    return {
        "name": "portable-resume",
        "version": BUNDLE_VERSION,
        "license": "Apache-2.0",
    }


PACKAGE_CONTRACTS: dict[str, PackageContract] = {
    "direct-skills": PackageContract(
        contract_id="direct-skills-v1",
        package_type="direct-skills",
        destination=None,
        required_members=(),
        primary_manifest=None,
        required_manifest_keys=frozenset(),
        required_manifest_values={},
        skills_prefix="",
        plugin_root=None,
        version_source="portable_resume.__version__ baked into skill runner metadata",
        install_hint=(
            "extract into the host skill root documented in docs/install-hosts.md"
        ),
        native_evidence_status="not-run",
        last_native_evidence_ref="v0.3.2",
    ),
    "claude-marketplace": PackageContract(
        contract_id="claude-marketplace-v1",
        package_type="claude-marketplace",
        destination="claude",
        required_members=(
            ".claude-plugin/marketplace.json",
            "plugins/portable-resume/.claude-plugin/plugin.json",
        ),
        primary_manifest="plugins/portable-resume/.claude-plugin/plugin.json",
        required_manifest_keys=frozenset(
            {"name", "version", "description", "author", "license", "homepage", "repository"}
        ),
        required_manifest_values=_common_required_manifest_values(),
        skills_prefix="plugins/portable-resume/skills/",
        plugin_root="plugins/portable-resume",
        version_source="plugin.json version + marketplace plugins[].version",
        install_hint=(
            "claude plugin marketplace add <extracted-dir>; "
            "claude plugin install portable-resume@portable-resume"
        ),
    ),
    "codex-marketplace": PackageContract(
        contract_id="codex-marketplace-v1",
        package_type="codex-marketplace",
        destination="codex",
        required_members=(
            ".agents/plugins/marketplace.json",
            "plugins/portable-resume/.codex-plugin/plugin.json",
        ),
        primary_manifest="plugins/portable-resume/.codex-plugin/plugin.json",
        required_manifest_keys=frozenset(
            {
                "name",
                "version",
                "description",
                "author",
                "license",
                "homepage",
                "repository",
                "skills",
            }
        ),
        required_manifest_values={
            **_common_required_manifest_values(),
            "skills": "./skills/",
        },
        skills_prefix="plugins/portable-resume/skills/",
        plugin_root="plugins/portable-resume",
        version_source="plugin.json version",
        install_hint=(
            "codex plugin marketplace add <extracted-dir>; "
            "codex plugin add portable-resume@portable-resume"
        ),
    ),
    "cursor-marketplace": PackageContract(
        contract_id="cursor-marketplace-v1",
        package_type="cursor-marketplace",
        destination="cursor",
        required_members=(
            ".cursor-plugin/marketplace.json",
            "plugins/portable-resume/.cursor-plugin/plugin.json",
        ),
        primary_manifest="plugins/portable-resume/.cursor-plugin/plugin.json",
        required_manifest_keys=frozenset(
            {
                "name",
                "displayName",
                "version",
                "description",
                "author",
                "homepage",
                "repository",
                "license",
                "skills",
            }
        ),
        required_manifest_values={
            **_common_required_manifest_values(),
            "skills": "./skills/",
        },
        skills_prefix="plugins/portable-resume/skills/",
        plugin_root="plugins/portable-resume",
        version_source="plugin.json version",
        install_hint=(
            "copy or symlink <extracted-dir>/plugins/portable-resume to "
            "~/.cursor/plugins/local/portable-resume, or run "
            "cursor agent --plugin-dir <extracted-dir>/plugins/portable-resume"
        ),
    ),
    "antigravity-plugin": PackageContract(
        contract_id="antigravity-plugin-v1",
        package_type="antigravity-plugin",
        destination="antigravity",
        required_members=("plugin.json",),
        primary_manifest="plugin.json",
        required_manifest_keys=frozenset({"name"}),
        required_manifest_values={"name": "portable-resume"},
        skills_prefix="skills/",
        plugin_root=None,
        version_source="bundle version only (plugin.json name-only profile)",
        install_hint=(
            "agy plugin validate <extracted-dir>; agy plugin install <extracted-dir>"
        ),
    ),
    "grok-plugin": PackageContract(
        contract_id="grok-plugin-v1",
        package_type="grok-plugin",
        destination="grok",
        required_members=("plugin.json",),
        primary_manifest="plugin.json",
        required_manifest_keys=frozenset(
            {"name", "version", "description", "author", "license", "homepage", "repository"}
        ),
        required_manifest_values=_common_required_manifest_values(),
        skills_prefix="skills/",
        plugin_root=None,
        version_source="plugin.json version",
        install_hint=(
            "grok plugin validate <extracted-dir>; "
            "grok plugin install <extracted-dir> --trust"
        ),
    ),
    "qwen-extension": PackageContract(
        contract_id="qwen-extension-v1",
        package_type="qwen-extension",
        destination="qwen",
        required_members=("qwen-extension.json",),
        primary_manifest="qwen-extension.json",
        required_manifest_keys=frozenset({"name", "version", "description", "skills"}),
        required_manifest_values={
            "name": "portable-resume",
            "version": BUNDLE_VERSION,
            "skills": "skills",
        },
        skills_prefix="skills/",
        plugin_root=None,
        version_source="qwen-extension.json version",
        install_hint="qwen extensions install <archive-or-url>",
    ),
    "kimi-plugin": PackageContract(
        contract_id="kimi-plugin-v1",
        package_type="kimi-plugin",
        destination="kimi",
        required_members=("kimi.plugin.json",),
        primary_manifest="kimi.plugin.json",
        required_manifest_keys=frozenset(
            {
                "name",
                "version",
                "description",
                "author",
                "license",
                "homepage",
                "repository",
                "skills",
            }
        ),
        required_manifest_values={
            **_common_required_manifest_values(),
            "skills": "./skills/",
        },
        skills_prefix="skills/",
        plugin_root=None,
        version_source="kimi.plugin.json version",
        install_hint=(
            "/plugins install <extracted-dir-or-zip-url-or-github-url>; "
            "/plugins reload"
        ),
    ),
}


def contract_for_package_type(package_type: str) -> PackageContract:
    if package_type not in PACKAGE_CONTRACTS:
        raise KeyError(package_type)
    return PACKAGE_CONTRACTS[package_type]


def contracts_report() -> dict[str, Any]:
    return {
        "schema_version": PACKAGE_CONTRACTS_SCHEMA,
        "bundle_version": BUNDLE_VERSION,
        "contracts": {
            key: contract.to_dict() for key, contract in sorted(PACKAGE_CONTRACTS.items())
        },
    }


def _skill_names() -> tuple[str, ...]:
    return tuple(f"resume-{key}" for key in sorted(SOURCE_KEYS))


def validate_member_paths(names: Iterable[str]) -> list[str]:
    """Return path-safety failures for archive member names."""

    failures: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            failures.append(f"duplicate or empty member: {name!r}")
            continue
        seen.add(name)
        pure = PurePosixPath(name)
        if pure.is_absolute() or "\\" in name or ".." in pure.parts:
            failures.append(f"unsafe member path: {name!r}")
        for fragment in FORBIDDEN_PATH_SUBSTRINGS:
            if fragment in name:
                failures.append(f"forbidden path fragment {fragment!r} in {name!r}")
    return failures


def _zip_info_is_regular(info: zipfile.ZipInfo) -> bool:
    unix_type = stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)
    return not info.is_dir() and unix_type in {0, stat.S_IFREG}


def _zip_info_is_safe_member(info: zipfile.ZipInfo) -> bool:
    unix_type = stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)
    if info.is_dir():
        return unix_type in {0, stat.S_IFDIR}
    return unix_type in {0, stat.S_IFREG}


def _read_bounded_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    max_bytes: int,
) -> bytes:
    info = archive.getinfo(name)
    return _read_bounded_info(archive, info, max_bytes=max_bytes)


def _read_bounded_info(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_bytes: int,
) -> bytes:
    if not _zip_info_is_regular(info) or info.file_size > max_bytes:
        raise ValueError("archive member is not a bounded regular file")
    try:
        with archive.open(info) as handle:
            data = handle.read(max_bytes + 1)
    except (RuntimeError, NotImplementedError) as error:
        raise ValueError("archive member is unreadable") from error
    if len(data) > max_bytes:
        raise ValueError("archive member exceeds its decompressed size bound")
    return data


def validate_skills_layout(names: Iterable[str], *, skills_prefix: str) -> list[str]:
    """Every enabled source must have SKILL.md + run_reader under *skills_prefix*."""

    name_set = set(names)
    failures: list[str] = []
    for skill in _skill_names():
        skill_md = f"{skills_prefix}{skill}/SKILL.md"
        runner = f"{skills_prefix}{skill}/scripts/run_reader.py"
        if skill_md not in name_set:
            failures.append(f"missing skill manifest: {skill_md}")
        if runner not in name_set:
            failures.append(f"missing skill runner: {runner}")
    # SKILL.md name must match directory (Agent Skills convention).
    for name in name_set:
        if not name.endswith("/SKILL.md"):
            continue
        if skills_prefix and not name.startswith(skills_prefix):
            continue
        rel = name[len(skills_prefix) :] if skills_prefix else name
        parts = PurePosixPath(rel).parts
        if len(parts) < 2:
            failures.append(f"unexpected SKILL.md path: {name}")
            continue
        skill_dir = parts[0]
        # Frontmatter name is checked lightly via directory convention only here.
        if not skill_dir.startswith("resume-"):
            failures.append(f"non-resume skill path: {name}")
    return failures


def validate_manifest_document(
    data: dict[str, Any],
    contract: PackageContract,
) -> list[str]:
    failures: list[str] = []
    if not isinstance(data, dict):
        return ["primary manifest is not a JSON object"]
    missing = sorted(contract.required_manifest_keys - set(data))
    if missing:
        failures.append(f"missing manifest keys: {missing}")
    for key, expected in sorted(contract.required_manifest_values.items()):
        if key not in data:
            continue
        actual = data[key]
        # author may be object — only compare scalar declared values
        if not isinstance(actual, (str, int, float, bool)) and key != "author":
            failures.append(f"manifest key {key!r} is not a scalar")
            continue
        if str(actual) != expected:
            failures.append(
                f"manifest {key!r} expected {expected!r}, got {actual!r}"
            )
    return failures


def _normalize_plugin_rel(path: str) -> str:
    rel = path[2:] if path.startswith("./") else path
    return rel.strip("/").replace("\\", "/")


def validate_marketplace_source(
    archive: zipfile.ZipFile,
    contract: PackageContract,
) -> list[str]:
    """Ensure marketplace entries point at the contracted plugin root in-archive."""

    if not contract.plugin_root:
        return []
    failures: list[str] = []
    names = set(archive.namelist())
    expected_root = _normalize_plugin_rel(contract.plugin_root)
    plugin_prefix = expected_root + "/"
    if not any(name.startswith(plugin_prefix) for name in names):
        failures.append(f"missing plugin root tree: {plugin_prefix}")
    # Claude / Cursor / Codex marketplace files are listed in required_members.
    for member in contract.required_members:
        if "marketplace.json" not in member:
            continue
        try:
            marketplace = json.loads(
                _read_bounded_member(
                    archive,
                    member,
                    max_bytes=MAX_MANIFEST_MEMBER_BYTES,
                ).decode("utf-8")
            )
        except (KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            failures.append(f"unreadable marketplace {member}: {error}")
            continue
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            failures.append(f"marketplace {member} missing plugins list")
            continue
        for entry in plugins:
            if not isinstance(entry, dict):
                failures.append(f"marketplace entry not an object in {member}")
                continue
            # Marketplace entry version must match the bundle when declared.
            if "version" in entry and str(entry["version"]) != BUNDLE_VERSION:
                failures.append(
                    f"marketplace plugin version {entry['version']!r} != {BUNDLE_VERSION!r}"
                )
            source = entry.get("source")
            source_rel: str | None = None
            if isinstance(source, str):
                source_rel = _normalize_plugin_rel(source)
            elif isinstance(source, dict):
                path = source.get("path")
                if isinstance(path, str):
                    source_rel = _normalize_plugin_rel(path)
            if source_rel is None:
                failures.append(f"marketplace entry missing source path in {member}")
                continue
            # Source must be exactly the contracted plugin root, not a subtree.
            if source_rel != expected_root:
                failures.append(
                    f"marketplace source {source_rel!r} != plugin root {expected_root!r}"
                )
                continue
            if not any(name.startswith(source_rel + "/") for name in names):
                failures.append(f"marketplace source missing tree: {source_rel}")
    return failures


def validate_archive_bytes(
    data: bytes,
    *,
    package_type: str,
    expected_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one zip archive against its package contract. Never installs."""

    contract = contract_for_package_type(package_type)
    failures: list[str] = []
    build_identity_sha256: str | None = None
    expected_identity_bytes = (
        identity_json_bytes(expected_identity)
        if expected_identity is not None
        else None
    )
    try:
        if not isinstance(data, bytes) or len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("archive exceeds the compressed size bound")
        archive_stream = io.BytesIO(data)
        declared_entries = _preflight_zip_archive(archive_stream)
        with zipfile.ZipFile(archive_stream) as archive:
            infos = archive.infolist()
            if len(infos) != declared_entries:
                raise ValueError("archive ZIP member count is inconsistent")
            if len(infos) > MAX_ARCHIVE_MEMBERS:
                raise ValueError("archive exceeds the member-count bound")
            if sum(info.file_size for info in infos) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("archive exceeds the total decompressed size bound")
            names = [info.filename for info in infos]
            failures.extend(validate_member_paths(names))
            unsafe_members = [
                info.filename for info in infos if not _zip_info_is_safe_member(info)
            ]
            if unsafe_members:
                failures.append(
                    f"archive contains non-regular members: {unsafe_members[:8]}"
                )
            for required in contract.required_members:
                if required not in names:
                    failures.append(f"missing required member: {required}")
            failures.extend(
                validate_skills_layout(names, skills_prefix=contract.skills_prefix)
            )
            if contract.primary_manifest:
                try:
                    raw = _read_bounded_member(
                        archive,
                        contract.primary_manifest,
                        max_bytes=MAX_MANIFEST_MEMBER_BYTES,
                    )
                    manifest = json.loads(raw.decode("utf-8"))
                except (
                    KeyError,
                    ValueError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ) as error:
                    failures.append(
                        f"primary manifest unreadable: {error}"
                    )
                else:
                    failures.extend(validate_manifest_document(manifest, contract))
            failures.extend(validate_marketplace_source(archive, contract))
            expected_schema_member = f"{contract.skills_prefix}{RUNTIME_SCHEMA_RELATIVE}"
            schema_candidates = [
                info
                for info in infos
                if tuple(PurePosixPath(info.filename).parts[-3:])
                == (
                    "portable_resume",
                    "resources",
                    "portable-resume-v1.schema.json",
                )
            ]
            schema_hits = [
                info
                for info in schema_candidates
                if info.filename == expected_schema_member
            ]
            if len(schema_candidates) != 1 or len(schema_hits) != 1:
                failures.append(
                    "expected exactly one runtime schema at "
                    f"{expected_schema_member!r}, found "
                    f"{len(schema_hits)} exact and {len(schema_candidates)} total"
                )
            elif not _zip_info_is_regular(schema_hits[0]):
                failures.append("runtime schema is not a regular file")
            expected_identity_member = (
                f"{contract.skills_prefix}{RUNTIME_IDENTITY_RELATIVE}"
            )
            identity_candidates = [
                info
                for info in archive.infolist()
                if tuple(PurePosixPath(info.filename).parts[-3:])
                == ("portable_resume", "resources", "build-identity.json")
            ]
            identity_hits = [
                info
                for info in identity_candidates
                if info.filename == expected_identity_member
            ]
            if len(identity_candidates) != 1 or len(identity_hits) != 1:
                failures.append(
                    "expected exactly one embedded build identity at "
                    f"{expected_identity_member!r}, found "
                    f"{len(identity_hits)} exact and {len(identity_candidates)} total"
                )
            else:
                info = identity_hits[0]
                if (
                    not _zip_info_is_regular(info)
                    or info.file_size > MAX_BUILD_IDENTITY_BYTES
                ):
                    failures.append(
                        "embedded build identity is not a bounded regular file"
                    )
                else:
                    try:
                        raw_identity = _read_bounded_info(
                            archive,
                            info,
                            max_bytes=MAX_BUILD_IDENTITY_BYTES,
                        )
                    except ValueError as error:
                        failures.append(
                            f"embedded build identity is unreadable: {error}"
                        )
                    else:
                        try:
                            embedded_identity = load_identity_bytes(raw_identity)
                        except ValueError as error:
                            failures.append(
                                f"embedded build identity is invalid: {error}"
                            )
                        else:
                            if embedded_identity.get("base_version") != BUNDLE_VERSION:
                                failures.append(
                                    "embedded build identity base version differs from bundle"
                                )
                            if (
                                embedded_identity.get("registry_sha256")
                                != registry_sha256()
                            ):
                                failures.append(
                                    "embedded build identity registry differs from bundle"
                                )
                            if (
                                expected_identity_bytes is not None
                                and raw_identity != expected_identity_bytes
                            ):
                                failures.append(
                                    "embedded build identity differs from expected identity"
                                )
                            build_identity_sha256 = hashlib.sha256(
                                raw_identity
                            ).hexdigest()
    except ValueError as error:
        failures.append(str(error))
    except zipfile.BadZipFile as error:
        failures.append(f"bad zip: {error}")

    return {
        "ok": not failures,
        "contract_id": contract.contract_id,
        "package_type": package_type,
        "native_evidence_status": contract.native_evidence_status,
        "last_native_evidence_ref": contract.last_native_evidence_ref,
        "build_identity_sha256": build_identity_sha256,
        "failures": failures,
    }


def validate_archive_path(path: str, *, package_type: str) -> dict[str, Any]:
    source = Path(path).absolute()
    try:
        data = stable_read_bytes(
            source,
            root=source.parent,
            max_bytes=MAX_ARCHIVE_BYTES,
        ).data
    except DiagnosticError:
        contract = contract_for_package_type(package_type)
        report = {
            "ok": False,
            "contract_id": contract.contract_id,
            "package_type": package_type,
            "native_evidence_status": contract.native_evidence_status,
            "last_native_evidence_ref": contract.last_native_evidence_ref,
            "build_identity_sha256": None,
            "failures": ["archive is not a bounded stable regular file"],
        }
    else:
        report = validate_archive_bytes(data, package_type=package_type)
    report["path"] = path
    return report
