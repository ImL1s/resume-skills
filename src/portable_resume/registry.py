from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProfileStatus = Literal["supported", "partial", "experimental", "planned", "research"]

_EIGHT_KEYS: tuple[str, ...] = (
    "antigravity",
    "claude",
    "codex",
    "cursor",
    "grok",
    "kimi",
    "opencode",
    "qwen",
)

_SOURCE_FORMAT_IDS: dict[str, tuple[str, ...]] = {
    "antigravity": ("antigravity-transcript-jsonl-v1",),
    "claude": ("claude-jsonl-v1",),
    "codex": (
        "codex-state-sqlite-v1",
        "codex-rollout-jsonl-v1",
        "codex-rollout-zstd-v1",
    ),
    "cursor": (
        "cursor-cli-chat-v1",
        "cursor-desktop-vscdb-v1",
        "cursor-cli-store-v1",
        "cursor-desktop-composer-v1",
    ),
    "grok": ("grok-updates-jsonl-v1",),
    "kimi": ("kimi-code-wire-jsonl-v1", "kimi-legacy-context-jsonl-v1"),
    "opencode": (
        "opencode-sqlite-v1",
        "opencode-file-store-v1",
        "opencode-export-file-v1",
    ),
    "qwen": ("qwen-chat-jsonl-v1",),
}

_DESTINATION_PAYLOAD_PROFILES: dict[str, str] = {
    "antigravity": "antigravity-v1",
    "claude": "claude-v1",
    "codex": "codex-v1",
    "cursor": "cursor-v1",
    "grok": "grok-v1",
    "kimi": "kimi-code-v2",
    "opencode": "opencode-v1",
    "qwen": "qwen-v1",
    "pi": "pi-v1",
    "openclaw": "openclaw-v1",
    "goose": "goose-v1",
    "crush": "crush-v1",
    "cline": "cline-v1",
    "openhands": "openhands-v1",
    "hermes": "hermes-v1",
    "github-copilot": "github-copilot-v1",
    "gemini": "gemini-v1",
}

_DESTINATION_ROOTS: dict[str, tuple[str, str]] = {
    "antigravity": (".agents/skills", ".gemini/config/skills"),
    "claude": (".claude/skills", ".claude/skills"),
    "codex": (".agents/skills", ".agents/skills"),
    "cursor": (".cursor/skills", ".cursor/skills"),
    "grok": (".grok/skills", ".grok/skills"),
    "kimi": (".kimi-code/skills", ".kimi-code/skills"),
    "opencode": (".opencode/skills", ".config/opencode/skills"),
    "qwen": (".qwen/skills", ".qwen/skills"),
    "pi": (".pi/skills", ".pi/agent/skills"),
    "openclaw": ("skills", ".openclaw/skills"),
    "goose": (".goose/skills", ".config/goose/skills"),
    "crush": (".crush/skills", ".config/crush/skills"),
    "cline": (".cline/skills", ".cline/skills"),
    "openhands": (".agents/skills", ".openhands/skills"),
    "hermes": (".hermes/skills", ".hermes/skills"),
    "github-copilot": (".github/skills", ".copilot/skills"),
    "gemini": (".gemini/skills", ".gemini/skills"),
}


@dataclass(frozen=True, slots=True)
class SourceProfile:
    key: str
    adapter_module: str
    format_ids: tuple[str, ...]
    status: ProfileStatus = "supported"
    local_only: bool = True
    supports_list: bool = True
    supports_show: bool = True
    exact_ref_kinds: tuple[str, ...] = ("id", "path", "text", "latest")
    fixture_profile: str | None = None


@dataclass(frozen=True, slots=True)
class DestinationProfile:
    key: str
    payload_profile: str
    status: ProfileStatus = "supported"
    direct_skill: bool = True
    project_rel: str = ""
    global_rel: str = ""
    native_package_profile: str | None = None
    activation_profile: str | None = None


@dataclass(frozen=True, slots=True)
class PackageSurface:
    key: str
    destination: str
    profile: str
    buildable: bool = True
    last_verified_host_version: str | None = None
    status: ProfileStatus = "supported"


SOURCE_PROFILES: dict[str, SourceProfile] = {
    key: SourceProfile(
        key=key,
        adapter_module=f"portable_resume.adapters.{key}",
        format_ids=_SOURCE_FORMAT_IDS[key],
        status="supported",
    )
    for key in _EIGHT_KEYS
}

SOURCE_PROFILES["pi"] = SourceProfile(
    key="pi",
    adapter_module="portable_resume.adapters.pi",
    format_ids=("pi-session-jsonl-v3", "pi-session-jsonl-v2"),
    status="supported",
    fixture_profile="pi-session-jsonl-v3",
)

SOURCE_PROFILES["openclaw"] = SourceProfile(
    key="openclaw",
    adapter_module="portable_resume.adapters.openclaw",
    format_ids=("openclaw-agent-sqlite-v1",),
    status="supported",
    fixture_profile="openclaw-agent-sqlite-v1",
)

SOURCE_PROFILES["goose"] = SourceProfile(
    key="goose",
    adapter_module="portable_resume.adapters.goose",
    format_ids=("goose-sessions-sqlite-v15",),
    status="supported",
    fixture_profile="goose-sessions-sqlite-v15",
)

SOURCE_PROFILES["crush"] = SourceProfile(
    key="crush",
    adapter_module="portable_resume.adapters.crush",
    format_ids=("crush-sqlite-v1",),
    status="supported",
    fixture_profile="crush-sqlite-v1",
)

SOURCE_PROFILES["cline"] = SourceProfile(
    key="cline",
    adapter_module="portable_resume.adapters.cline",
    format_ids=("cline-session-json-v1",),
    status="supported",
    fixture_profile="cline-session-json-v1",
)

SOURCE_PROFILES["openhands"] = SourceProfile(
    key="openhands",
    adapter_module="portable_resume.adapters.openhands",
    format_ids=("openhands-cli-events-v1",),
    status="supported",
    fixture_profile="openhands-cli-events-v1",
)

SOURCE_PROFILES["hermes"] = SourceProfile(
    key="hermes",
    adapter_module="portable_resume.adapters.hermes",
    format_ids=("hermes-state-sqlite-v1",),
    status="supported",
    fixture_profile="hermes-state-sqlite-v1",
)

# Destination lands first (#44). Source stays research until events.jsonl schema is pinned.
SOURCE_PROFILES["github-copilot"] = SourceProfile(
    key="github-copilot",
    adapter_module="portable_resume.adapters.github_copilot",
    format_ids=(),
    status="research",
    fixture_profile=None,
)

SOURCE_PROFILES["gemini"] = SourceProfile(
    key="gemini",
    adapter_module="portable_resume.adapters.gemini",
    format_ids=("gemini-cli-session-jsonl-v1",),
    status="supported",
    fixture_profile="gemini-cli-session-jsonl-v1",
)

# Native package surface key per destination (independent of direct Skills).
# Hosts with only direct-skill install leave this unset (opencode, pi, …).
_NATIVE_PACKAGE_BY_DESTINATION: dict[str, str] = {
    "antigravity": "antigravity-plugin",
    "claude": "claude-marketplace",
    "codex": "codex-marketplace",
    "cursor": "cursor-marketplace",
    "grok": "grok-plugin",
    "kimi": "kimi-plugin",
    "qwen": "qwen-extension",
}

DESTINATION_PROFILES: dict[str, DestinationProfile] = {
    key: DestinationProfile(
        key=key,
        payload_profile=_DESTINATION_PAYLOAD_PROFILES[key],
        status="supported",
        direct_skill=True,
        project_rel=_DESTINATION_ROOTS[key][0],
        global_rel=_DESTINATION_ROOTS[key][1],
        native_package_profile=_NATIVE_PACKAGE_BY_DESTINATION.get(key),
    )
    for key in _EIGHT_KEYS
}

DESTINATION_PROFILES["pi"] = DestinationProfile(
    key="pi",
    payload_profile="pi-v1",
    status="supported",
    direct_skill=True,
    project_rel=".pi/skills",
    global_rel=".pi/agent/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["openclaw"] = DestinationProfile(
    key="openclaw",
    payload_profile="openclaw-v1",
    status="supported",
    direct_skill=True,
    project_rel="skills",
    global_rel=".openclaw/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["goose"] = DestinationProfile(
    key="goose",
    payload_profile="goose-v1",
    status="supported",
    direct_skill=True,
    project_rel=".goose/skills",
    global_rel=".config/goose/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["crush"] = DestinationProfile(
    key="crush",
    payload_profile="crush-v1",
    status="supported",
    direct_skill=True,
    project_rel=".crush/skills",
    global_rel=".config/crush/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["cline"] = DestinationProfile(
    key="cline",
    payload_profile="cline-v1",
    status="supported",
    direct_skill=True,
    project_rel=".cline/skills",
    global_rel=".cline/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["openhands"] = DestinationProfile(
    key="openhands",
    payload_profile="openhands-v1",
    status="supported",
    direct_skill=True,
    project_rel=".agents/skills",
    global_rel=".openhands/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["hermes"] = DestinationProfile(
    key="hermes",
    payload_profile="hermes-v1",
    status="supported",
    direct_skill=True,
    project_rel=".hermes/skills",
    global_rel=".hermes/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["github-copilot"] = DestinationProfile(
    key="github-copilot",
    payload_profile="github-copilot-v1",
    status="supported",
    direct_skill=True,
    project_rel=".github/skills",
    global_rel=".copilot/skills",
    native_package_profile=None,
)

DESTINATION_PROFILES["gemini"] = DestinationProfile(
    key="gemini",
    payload_profile="gemini-v1",
    status="supported",
    direct_skill=True,
    project_rel=".gemini/skills",
    global_rel=".gemini/skills",
    native_package_profile=None,
)

PACKAGE_SURFACES: dict[str, PackageSurface] = {
    surface_key: PackageSurface(
        key=surface_key,
        destination=destination,
        profile=f"{surface_key}-v1",
        buildable=True,
        status="supported",
    )
    for destination, surface_key in sorted(_NATIVE_PACKAGE_BY_DESTINATION.items())
}


def source_keys() -> frozenset[str]:
    return frozenset(SOURCE_PROFILES)


def destination_keys() -> frozenset[str]:
    return frozenset(DESTINATION_PROFILES)


def package_keys() -> frozenset[str]:
    return frozenset(PACKAGE_SURFACES)


def enabled_source_keys() -> frozenset[str]:
    return frozenset(k for k, p in SOURCE_PROFILES.items() if p.status == "supported")


def enabled_destination_keys() -> frozenset[str]:
    return frozenset(
        k
        for k, p in DESTINATION_PROFILES.items()
        if p.status == "supported" and p.direct_skill
    )


def enabled_package_keys() -> frozenset[str]:
    """Buildable native package surfaces (not the direct-runner matrix)."""

    return frozenset(
        k
        for k, p in PACKAGE_SURFACES.items()
        if p.status == "supported" and p.buildable
    )


def matrix_dimensions() -> dict[str, int]:
    sources = len(enabled_source_keys())
    destinations = len(enabled_destination_keys())
    return {
        "sources": sources,
        "destinations": destinations,
        "cells": sources * destinations,
    }


def rectangular_cells(
    *,
    sources: frozenset[str],
    destinations: frozenset[str],
) -> list[tuple[str, str]]:
    """Return (destination, source) pairs in deterministic sort order."""
    cells: list[tuple[str, str]] = []
    for destination in sorted(destinations):
        for source in sorted(sources):
            cells.append((destination, source))
    return cells


def _validate_maps(
    sources: dict[str, SourceProfile],
    destinations: dict[str, DestinationProfile],
    packages: dict[str, PackageSurface],
) -> None:
    if len(sources) != len({p.key for p in sources.values()}):
        raise ValueError("duplicate source keys")
    if len(destinations) != len({p.key for p in destinations.values()}):
        raise ValueError("duplicate destination keys")
    if len(packages) != len({p.key for p in packages.values()}):
        raise ValueError("duplicate package keys")
    for key, surface in packages.items():
        if key != surface.key:
            raise ValueError(f"package map key mismatch: {key}")
        if surface.destination not in destinations:
            raise ValueError(
                f"package surface owner missing: {surface.destination}"
            )
    for key, profile in sources.items():
        if key != profile.key:
            raise ValueError(f"source map key mismatch: {key}")
        if profile.status == "supported" and not profile.format_ids:
            raise ValueError(f"supported source missing format_ids: {key}")
        if profile.status == "supported" and not profile.adapter_module.startswith(
            "portable_resume.adapters."
        ):
            raise ValueError(f"bad adapter_module: {key}")
    for key, profile in destinations.items():
        if key != profile.key:
            raise ValueError(f"destination map key mismatch: {key}")
        if profile.native_package_profile is not None:
            surface = packages.get(profile.native_package_profile)
            if surface is None:
                raise ValueError(
                    f"destination native_package_profile missing: {key}"
                )
            if surface.destination != key:
                raise ValueError(
                    f"native_package_profile owner mismatch: {key}"
                )


def validate_registries() -> None:
    _validate_maps(SOURCE_PROFILES, DESTINATION_PROFILES, PACKAGE_SURFACES)
