"""Six-host × six-source packaging catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..diagnostics import SOURCE_KEYS

HOST_KEYS = frozenset({"claude", "codex", "cursor", "opencode", "antigravity", "grok"})
SOURCE_SKILL_NAMES = tuple(f"resume-{key}" for key in sorted(SOURCE_KEYS))
BUNDLE_VERSION = "0.1.0"
MANIFEST_SCHEMA = "portable-resume/install-manifest-v1"


@dataclass(frozen=True, slots=True)
class HostProfile:
    key: str
    profile_id: str
    project_rel: str
    global_rel: str
    activation_help: str
    arguments_note: str
    evidence_level: str = "verified-filesystem"


HOST_PROFILES: dict[str, HostProfile] = {
    "claude": HostProfile(
        key="claude",
        profile_id="claude-v1",
        project_rel=".claude/skills",
        global_rel=".claude/skills",
        activation_help=(
            "Invoke `/resume-<source>` (or let the model auto-select by description). "
            "Any invocation tail is substituted into the skill prompt only; it is never process argv."
        ),
        arguments_note=(
            "If this host expands `$ARGUMENTS` into the skill body, treat that text as labeled "
            "prompt context only. Still write a request-v1 file before invoking the runner."
        ),
    ),
    "codex": HostProfile(
        key="codex",
        profile_id="codex-v1",
        project_rel=".agents/skills",
        global_rel=".agents/skills",
        activation_help=(
            "Invoke `$resume-<source>` followed by ordinary labeled text. "
            "There is no implicit skill-to-process argv binding."
        ),
        arguments_note="Do not invent positional argv placeholders for this host.",
    ),
    "cursor": HostProfile(
        key="cursor",
        profile_id="cursor-v1",
        project_rel=".cursor/skills",
        global_rel=".cursor/skills",
        activation_help=(
            "Explicitly select `/resume-<source>` (or let the agent choose by description) and "
            "include labeled `resume_ref:` / `cwd:` in the same message."
        ),
        arguments_note="Do not depend on an undocumented invocation-tail-to-argv binding.",
    ),
    "opencode": HostProfile(
        key="opencode",
        profile_id="opencode-v1",
        project_rel=".opencode/skills",
        global_rel=".config/opencode/skills",
        activation_help=(
            "Ask the model to use the skill by name so it can call native skill loading. "
            "Optional OpenCode custom commands are separate and not required for this package."
        ),
        arguments_note="No skill argv channel is claimed for this host.",
    ),
    "antigravity": HostProfile(
        key="antigravity",
        profile_id="antigravity-v1",
        project_rel=".agents/skills",
        global_rel=".gemini/config/skills",
        activation_help=(
            "Mention the skill by name in natural language. `/skills` only lists skills; "
            "do not invent a `/resume-*` argv grammar."
        ),
        arguments_note="No invented slash-command argv channel is claimed for this host.",
    ),
    "grok": HostProfile(
        key="grok",
        profile_id="grok-v1",
        project_rel=".grok/skills",
        global_rel=".grok/skills",
        activation_help=(
            "Invoke `/resume-<source>` with labeled payload text. "
            "Any `$ARGUMENTS` expansion is prompt substitution only."
        ),
        arguments_note=(
            "If `$ARGUMENTS` appears in the rendered body, treat it as labeled prompt context only. "
            "Still write a request-v1 file before invoking the runner."
        ),
    ),
}

SOURCE_TITLES = {
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "cursor": "Cursor",
    "opencode": "OpenCode",
    "antigravity": "Antigravity CLI",
    "grok": "Grok Build",
}


def description_for(source: str) -> str:
    title = SOURCE_TITLES[source]
    return (
        f"Import inert local {title} session context into a fresh session "
        "using a validated request document."
    )


def skill_name_for(source: str) -> str:
    return f"resume-{source}"


def matrix_cells(hosts: Iterable[str] | None = None) -> list[tuple[str, str]]:
    selected = sorted(hosts or HOST_KEYS)
    cells: list[tuple[str, str]] = []
    for host in selected:
        if host not in HOST_KEYS:
            raise KeyError(host)
        for source in sorted(SOURCE_KEYS):
            cells.append((host, source))
    return cells


def resolve_skill_root(
    *,
    host: str,
    scope: str,
    project_dir: str | None,
    home_dir: str,
) -> str:
    import os

    profile = HOST_PROFILES[host]
    if scope == "project":
        if not project_dir:
            raise ValueError("project scope requires --project")
        return os.path.join(os.path.realpath(project_dir), profile.project_rel)
    if scope == "global":
        return os.path.join(os.path.realpath(home_dir), profile.global_rel)
    raise ValueError(f"unknown scope: {scope}")
