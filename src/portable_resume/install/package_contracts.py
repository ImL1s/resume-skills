"""Versioned host-package compatibility contracts (#27).

Offline gates consume these contracts to validate archives beyond bare ZIP
shape checks. Native host CLI install/invoke remains a separate evidence
layer (``native_evidence_status``), never silently upgraded to pass.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

from .. import __version__ as BUNDLE_VERSION
from ..diagnostics import SOURCE_KEYS

# Schema of this contracts module itself (bumped when contract fields change).
PACKAGE_CONTRACTS_SCHEMA = "portable-resume/package-contracts-v1"

# Shared forbidden path fragments inside any package archive.
FORBIDDEN_PATH_SUBSTRINGS: tuple[str, ...] = (
    "/portable_resume/install/",
    "\\portable_resume\\install\\",
    "/.portable-resume/.state/",
)


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


def validate_marketplace_source(
    archive: zipfile.ZipFile,
    contract: PackageContract,
) -> list[str]:
    """Ensure marketplace entries point at an existing plugin root in-archive."""

    if not contract.plugin_root:
        return []
    failures: list[str] = []
    names = set(archive.namelist())
    plugin_root = contract.plugin_root.rstrip("/") + "/"
    if not any(name.startswith(plugin_root) for name in names):
        failures.append(f"missing plugin root tree: {plugin_root}")
    # Claude / Cursor / Codex marketplace files are listed in required_members.
    for member in contract.required_members:
        if "marketplace.json" not in member:
            continue
        try:
            marketplace = json.loads(archive.read(member).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            failures.append(f"unreadable marketplace {member}: {type(error).__name__}")
            continue
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            failures.append(f"marketplace {member} missing plugins list")
            continue
        for entry in plugins:
            if not isinstance(entry, dict):
                failures.append(f"marketplace entry not an object in {member}")
                continue
            source = entry.get("source")
            if isinstance(source, str):
                rel = source[2:] if source.startswith("./") else source
                rel = rel.rstrip("/") + "/"
                if not any(name.startswith(rel) for name in names):
                    failures.append(f"marketplace source missing tree: {source}")
            elif isinstance(source, dict):
                path = source.get("path")
                if isinstance(path, str):
                    rel = path[2:] if path.startswith("./") else path
                    rel = rel.rstrip("/") + "/"
                    if not any(name.startswith(rel) for name in names):
                        failures.append(f"marketplace source.path missing tree: {path}")
    return failures


def validate_archive_bytes(
    data: bytes,
    *,
    package_type: str,
) -> dict[str, Any]:
    """Validate one zip archive against its package contract. Never installs."""

    contract = contract_for_package_type(package_type)
    failures: list[str] = []
    try:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            failures.extend(validate_member_paths(names))
            for required in contract.required_members:
                if required not in names:
                    failures.append(f"missing required member: {required}")
            failures.extend(
                validate_skills_layout(names, skills_prefix=contract.skills_prefix)
            )
            if contract.primary_manifest:
                try:
                    raw = archive.read(contract.primary_manifest)
                    manifest = json.loads(raw.decode("utf-8"))
                except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    failures.append(
                        f"primary manifest unreadable: {type(error).__name__}"
                    )
                else:
                    failures.extend(validate_manifest_document(manifest, contract))
            failures.extend(validate_marketplace_source(archive, contract))
            # Schema resource must exist under skills runtime for direct/plugin.
            schema_hits = [
                n
                for n in names
                if n.endswith("resources/portable-resume-v1.schema.json")
            ]
            if not schema_hits:
                failures.append("missing portable-resume-v1.schema.json resource")
    except zipfile.BadZipFile as error:
        failures.append(f"bad zip: {error}")

    return {
        "ok": not failures,
        "contract_id": contract.contract_id,
        "package_type": package_type,
        "native_evidence_status": contract.native_evidence_status,
        "last_native_evidence_ref": contract.last_native_evidence_ref,
        "failures": failures,
    }


def validate_archive_path(path: str, *, package_type: str) -> dict[str, Any]:
    with open(path, "rb") as handle:
        data = handle.read()
    report = validate_archive_bytes(data, package_type=package_type)
    report["path"] = path
    return report
