"""Destination-host × source packaging catalog and per-host install roots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .. import __version__ as BUNDLE_VERSION
from ..diagnostics import SOURCE_KEYS

HOST_KEYS = frozenset(
    {
        "antigravity",
        "claude",
        "codex",
        "cursor",
        "grok",
        "kimi",
        "opencode",
        "qwen",
    }
)
SOURCE_SKILL_NAMES = tuple(f"resume-{key}" for key in sorted(SOURCE_KEYS))
MANIFEST_SCHEMA = "portable-resume/install-manifest-v1"

# Portable skill layout under any skill root (Agent Skills standard):
#   <root>/<skill-name>/SKILL.md
#   <root>/<skill-name>/scripts/run_reader.py
SKILL_DIR_LAYOUT = "<skill-name>/SKILL.md + scripts/run_reader.py"


@dataclass(frozen=True, slots=True)
class HostProfile:
    key: str
    profile_id: str
    project_rel: str
    global_rel: str
    activation_help: str
    arguments_note: str
    evidence_level: str = "verified-filesystem"
    display_name: str = ""
    official_docs: tuple[str, ...] = ()
    # Human paths shown in docs/CLI (tilde-friendly, not resolved)
    project_layout: str = ""
    global_layout: str = ""
    alternate_project_roots: tuple[str, ...] = ()
    alternate_global_roots: tuple[str, ...] = ()
    install_methods: tuple[str, ...] = ()
    activation_examples: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    evidence_notes: str = ""


HOST_PROFILES: dict[str, HostProfile] = {
    "claude": HostProfile(
        key="claude",
        profile_id="claude-v1",
        project_rel=".claude/skills",
        global_rel=".claude/skills",
        display_name="Claude Code",
        official_docs=(
            "https://code.claude.com/docs/en/skills",
            "https://code.claude.com/docs/en/discover-plugins",
            "https://code.claude.com/docs/en/plugin-marketplaces",
        ),
        project_layout="<project>/.claude/skills/<name>/SKILL.md",
        global_layout="~/.claude/skills/<name>/SKILL.md",
        alternate_project_roots=(),
        alternate_global_roots=(),
        install_methods=(
            "This installer (recommended): install-resume-skills install --host claude --scope project|global",
            "Manual: copy each resume-*/ folder into .claude/skills/ or ~/.claude/skills/",
            "Also: nested monorepo .claude/skills/ under packages (Claude discovers on demand)",
            "Plugin package: claude plugin install portable-resume@<marketplace> --scope user|project|local",
            "Marketplace setup: claude plugin marketplace add <owner/repo>, then /reload-plugins after updates",
        ),
        activation_help=(
            "Invoke `/resume-<source>` (or let the model auto-select by description). "
            "Any invocation tail is substituted into the skill prompt only; it is never process argv."
        ),
        activation_examples=(
            "/resume-codex",
            "/resume-claude resume_ref: latest cwd: /abs/path",
            "What did I leave unfinished in my last Codex session? (model may auto-load by description)",
        ),
        arguments_note=(
            "If this host expands `$ARGUMENTS` / invocation tail into the skill prompt, "
            "use that text as the session <ref> (or omit for latest). "
            "It is never process argv by itself. "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "Cowork/cloud sessions do not read local ~/.claude/skills; use account-enabled or repo skills.",
            "Visual picker interaction and public marketplace publication are separate evidence claims.",
        ),
        evidence_notes=(
            "Official Claude Code skills docs: personal + project roots, /skill-name, "
            "$ARGUMENTS prompt substitution only (2026-07-20)."
        ),
    ),
    "codex": HostProfile(
        key="codex",
        profile_id="codex-v1",
        project_rel=".agents/skills",
        global_rel=".agents/skills",
        display_name="Codex CLI / IDE",
        official_docs=(
            "https://learn.chatgpt.com/docs/build-skills",
            "https://learn.chatgpt.com/docs/build-plugins",
        ),
        project_layout="<project>/.agents/skills/<name>/SKILL.md (CWD → repo root)",
        global_layout="~/.agents/skills/<name>/SKILL.md",
        alternate_project_roots=(),
        alternate_global_roots=(
            "/etc/codex/skills (ADMIN; explicit --root only)",
            "~/.codex/skills (community / older layouts; not this installer's default)",
        ),
        install_methods=(
            "This installer: install-resume-skills install --host codex --scope project|global",
            "Manual: place under .agents/skills/ (repo) or ~/.agents/skills/ (user)",
            "Local release package: codex plugin marketplace add <extracted-dir>, then codex plugin add portable-resume@portable-resume",
            "Published repository: codex plugin marketplace add <owner/repo> [--ref <tag>], then codex plugin add portable-resume@portable-resume",
            "Repository catalog: .agents/plugins/marketplace.json; package manifest: .codex-plugin/plugin.json",
            "Symlinks into ~/.agents/skills are supported by Codex discovery",
        ),
        activation_help=(
            "Invoke `$resume-<source>` followed by ordinary labeled text. "
            "There is no implicit skill-to-process argv binding."
        ),
        activation_examples=(
            "$resume-codex",
            "$resume-claude resume_ref: latest cwd: /abs/path",
            "/skills  # list skills in CLI/IDE",
        ),
        arguments_note="Do not invent positional argv placeholders for this host.",
        caveats=(
            "Shares project/global .agents/skills with Antigravity → use distinct --root or expect E_INSTALL_CONFLICT.",
            "Official skill grammar is $skill-name, not /skill-name.",
            "No $ARGUMENTS argv API; text after $skill stays user/model context.",
        ),
        evidence_notes=(
            "Codex Build skills docs: REPO .agents/skills (CWD up to root), USER ~/.agents/skills, "
            "ADMIN /etc/codex/skills; $skill / /skills; no argv binding (2026-07-20)."
        ),
    ),
    "cursor": HostProfile(
        key="cursor",
        profile_id="cursor-v1",
        project_rel=".cursor/skills",
        global_rel=".cursor/skills",
        display_name="Cursor Agent",
        official_docs=(
            "https://cursor.com/docs/context/skills",
            "https://cursor.com/marketplace",
            "https://cursor.com/blog/marketplace",
        ),
        project_layout="<project>/.cursor/skills/<name>/SKILL.md",
        global_layout="~/.cursor/skills/<name>/SKILL.md",
        alternate_project_roots=(
            ".agents/skills/ (also first-class project root)",
            ".claude/skills/ and .codex/skills/ (compatibility)",
        ),
        alternate_global_roots=(
            "~/.agents/skills/",
            "~/.claude/skills/ and ~/.codex/skills/ (compatibility)",
        ),
        install_methods=(
            "This installer (native Cursor root): install-resume-skills install --host cursor --scope project|global",
            "Manual into .cursor/skills/ or .agents/skills/ (both official)",
            "Local plugin package: copy/symlink plugins/portable-resume to ~/.cursor/plugins/local/portable-resume",
            "One run only: cursor agent --plugin-dir <extracted-dir>/plugins/portable-resume",
            "Git marketplace: cursor agent plugin marketplace add <git-url> [--git-ref <tag>], then /add-plugin portable-resume",
            "Published marketplace: search for the plugin after repository submission and review",
            "Nested package .cursor/skills/ directories are discovered recursively",
        ),
        activation_help=(
            "Explicitly select `/resume-<source>` (or let the agent choose by description) and "
            "include labeled `resume_ref:` / `cwd:` in the same message."
        ),
        activation_examples=(
            "/resume-codex",
            "Type / in Agent chat and pick resume-claude",
            "Include: resume_ref: latest  cwd: /abs/path",
        ),
        arguments_note="Do not depend on an undocumented invocation-tail-to-argv binding.",
        caveats=(
            "Installer defaults to .cursor/skills (native); Cursor also loads .agents/skills as first-class.",
            "If you already install Codex into .agents/skills, Cursor may see those skills too.",
            "No documented tail→argv API.",
            "The CLI can add a Git marketplace but installing its plugin remains the /add-plugin host UI step.",
        ),
        evidence_notes=(
            "Cursor skills docs list .agents/skills and .cursor/skills (project+user) plus Claude/Codex "
            "compat roots; /skill-name manual invoke (2026-07-20)."
        ),
    ),
    "opencode": HostProfile(
        key="opencode",
        profile_id="opencode-v1",
        project_rel=".opencode/skills",
        global_rel=".config/opencode/skills",
        display_name="OpenCode",
        official_docs=(
            "https://opencode.ai/docs/skills/",
            "https://opencode.ai/docs/plugins/",
        ),
        project_layout="<project>/.opencode/skills/<name>/SKILL.md",
        global_layout="~/.config/opencode/skills/<name>/SKILL.md",
        alternate_project_roots=(
            ".claude/skills/ (Claude-compatible)",
            ".agents/skills/ (agent-compatible)",
        ),
        alternate_global_roots=(
            "~/.claude/skills/",
            "~/.agents/skills/",
        ),
        install_methods=(
            "This installer (native OpenCode roots): install-resume-skills install --host opencode --scope project|global",
            "Manual into .opencode/skills/ or ~/.config/opencode/skills/",
            "Fallback: install into .claude/skills or .agents/skills if your build only discovers compat roots",
            "OpenCode has local/JS/npm executable plugins but no official marketplace; this package stays a data-only skill",
        ),
        activation_help=(
            "Ask the model to use the skill by name so it can call native skill loading. "
            "Optional OpenCode custom commands are separate and not required for this package."
        ),
        activation_examples=(
            "Use the resume-codex skill",
            "skill({ name: \"resume-codex\" })  # model-side native tool",
            "Then provide: resume_ref: latest  cwd: /abs/path",
        ),
        arguments_note="No skill argv channel is claimed for this host.",
        caveats=(
            "Some OpenCode builds have only proven .claude/.agents discovery in local probes; "
            "confirm native .opencode/skills loads before claiming host support.",
            "OpenCode scans its native, Claude-compatible, and agent-compatible roots together; "
            "keep each skill name unique across those roots or inspect which copy won.",
            "No stable user-facing /skill-name grammar for skills (commands are separate).",
            "permission.skill patterns in opencode.json can hide skills.",
            "Do not confuse this inert SKILL.md package with OpenCode executable plugins.",
        ),
        evidence_notes=(
            "OpenCode docs: native .opencode/skills + ~/.config/opencode/skills plus Claude/agents "
            "compat; model loads via skill({name}) (2026-07-20)."
        ),
    ),
    "antigravity": HostProfile(
        key="antigravity",
        profile_id="antigravity-v1",
        project_rel=".agents/skills",
        global_rel=".gemini/config/skills",
        display_name="Antigravity / agy",
        official_docs=(
            "https://www.antigravity.google/docs/skills",
            "https://www.antigravity.google/docs/plugins",
            "https://codelabs.developers.google.com/getting-started-with-antigravity-skills",
        ),
        project_layout="<workspace>/.agents/skills/<name>/SKILL.md",
        global_layout="~/.gemini/config/skills/<name>/SKILL.md",
        alternate_project_roots=(
            ".agent/skills/ (legacy singular; still supported)",
        ),
        alternate_global_roots=(
            "~/.gemini/skills/ (Gemini CLI primary user root — different product)",
            "~/.gemini/antigravity/skills/ or ~/.gemini/antigravity-cli/skills/ (flavor-specific)",
            "~/.agents/skills/ (interop alias used by Gemini CLI)",
        ),
        install_methods=(
            "This installer: install-resume-skills install --host antigravity --scope project|global",
            "Manual project: <workspace>/.agents/skills/<name>/",
            "Manual global (cross-flavor): ~/.gemini/config/skills/<name>/",
            "If only Gemini CLI: prefer ~/.gemini/skills/ or ~/.agents/skills/ with --root",
            "Local plugin archive: agy plugin validate <extracted-dir>, then agy plugin install <extracted-dir>",
            "Manual plugin fallback: .agents/plugins/portable-resume or ~/.gemini/config/plugins/portable-resume",
            "Antigravity documents bundled/manual plugins, not a public general marketplace; direct skills are the lower-trust default",
        ),
        activation_help=(
            "Mention the skill by name in natural language. `/skills` only lists skills; "
            "do not invent a `/resume-*` argv grammar."
        ),
        activation_examples=(
            "Use the resume-codex skill",
            "/skills  # list only",
            "resume_ref: latest  cwd: /abs/path",
        ),
        arguments_note="No invented slash-command argv channel is claimed for this host.",
        caveats=(
            "Project .agents/skills collides with Codex — use distinct --root when both hosts need divergent skill bodies.",
            "AGY / AGY CLI / AGY IDE may scan different global paths; ~/.gemini/config/skills is the cross-product global default here.",
            "Gemini CLI uses ~/.gemini/skills and .gemini/skills with .agents/skills alias precedence — not identical to Antigravity defaults.",
        ),
        evidence_notes=(
            "Antigravity official: workspace .agents/skills + global ~/.gemini/config/skills; "
            "legacy .agent/skills; NL activation + /skills list (2026-07-20)."
        ),
    ),
    "grok": HostProfile(
        key="grok",
        profile_id="grok-v1",
        project_rel=".grok/skills",
        global_rel=".grok/skills",
        display_name="Grok Build",
        official_docs=(
            "https://docs.x.ai/build/features/skills-plugins-marketplaces",
            "https://x.ai/news/grok-plugin-marketplace",
        ),
        project_layout="<repo>/.grok/skills/<name>/SKILL.md (CWD + repo root)",
        global_layout="~/.grok/skills/<name>/SKILL.md",
        alternate_project_roots=(
            ".agents/skills/ (always scanned)",
            ".claude/skills/ and .cursor/skills/ when compat enabled",
        ),
        alternate_global_roots=(
            "~/.agents/skills/",
            "~/.claude/skills/ and ~/.cursor/skills/ (compat toggles)",
            "config [skills].paths extra directories",
            "plugin-provided skills",
        ),
        install_methods=(
            "This installer: install-resume-skills install --host grok --scope project|global",
            "Manual: ./.grok/skills/ or ~/.grok/skills/",
            "Local plugin archive: grok plugin validate <extracted-dir>, then grok plugin install <extracted-dir> --trust",
            "Git plugin: grok plugin install <owner/repo[@ref]> --trust after review",
            "Marketplace UI: open /plugins (or /skills) and review a configured Marketplace source",
            "Extra dirs: [skills].paths in ~/.grok/config.toml",
        ),
        activation_help=(
            "Invoke `/resume-<source>` with labeled payload text. "
            "Any `$ARGUMENTS` expansion is prompt substitution only."
        ),
        activation_examples=(
            "/resume-codex",
            "/resume-claude resume_ref: latest cwd: /abs/path",
            "grok inspect  # list discovered skills",
        ),
        arguments_note=(
            "If this host expands `$ARGUMENTS` / invocation tail into the skill prompt, "
            "use that text as the session <ref> (or omit for latest). "
            "It is never process argv by itself. "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "$ARGUMENTS substitution is documented in Grok source/user guide; still not process argv.",
            "Bundled skills extract into ~/.grok/skills on startup — do not overwrite unrelated bundled dirs.",
            "Review executable plugin contents before passing --trust; direct skills have a smaller trust surface.",
            "Live UI activation for portable-resume cells is not-run.",
        ),
        evidence_notes=(
            "Official Grok Build docs: ./.grok/skills, ~/.grok/skills, .agents, Claude/Cursor compat, "
            "/skill-name, $ARGUMENTS prompt-only, and plugin marketplace installation (checked 2026-07-24)."
        ),
    ),
    "qwen": HostProfile(
        key="qwen",
        profile_id="qwen-v1",
        project_rel=".qwen/skills",
        global_rel=".qwen/skills",
        display_name="Qwen Code",
        official_docs=(
            "https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/",
            "https://qwenlm.github.io/qwen-code-docs/en/users/extension/introduction/",
            "https://qwenlm.github.io/qwen-code-docs/en/users/extension/extension-releasing/",
        ),
        project_layout="<project>/.qwen/skills/<name>/SKILL.md",
        global_layout="~/.qwen/skills/<name>/SKILL.md",
        alternate_project_roots=(
            ".qwen/extensions/<extension>/skills/ (extension-provided)",
        ),
        alternate_global_roots=(
            "~/.qwen/extensions/<extension>/skills/ (extension-provided)",
        ),
        install_methods=(
            "This installer: install-resume-skills install --host qwen --scope project|global",
            "Manual: copy each resume-*/ folder into .qwen/skills/ or ~/.qwen/skills/",
            "Extension release asset: qwen extensions install <archive-or-git-source>",
            "Qwen can also install compatible Claude/Gemini marketplace extensions; verify the source before installation",
        ),
        activation_help=(
            "Invoke `/resume-<source>` or choose it from `/skills`; the model may also "
            "select a skill from its description."
        ),
        activation_examples=(
            "/resume-codex",
            "/resume-qwen resume_ref: latest cwd: /abs/path",
            "/skills",
        ),
        arguments_note=(
            "Invocation text is model context; the skill still runs its owned reader explicitly."
        ),
        caveats=(
            "Qwen Code currently requires Node.js 22+ for npm installs; direct skill bundles only require Python 3.11+ at runtime.",
            "Extensions can execute code or configure MCP; review them before installation.",
            "Visual picker interaction and public marketplace publication are separate evidence claims.",
        ),
        evidence_notes=(
            "Official Qwen Code docs: project/user .qwen/skills, /skills and /<skill>, "
            "qwen-extension.json, local/archive/git/npm/marketplace extension installs "
            "(checked 2026-07-24)."
        ),
    ),
    "kimi": HostProfile(
        key="kimi",
        profile_id="kimi-code-v1",
        project_rel=".kimi-code/skills",
        global_rel=".kimi-code/skills",
        display_name="Kimi Code CLI",
        official_docs=(
            "https://www.kimi.com/code/docs/en/kimi-code-cli/customization/skills.html",
            "https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html",
            "https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/data-locations.html",
        ),
        project_layout="<project>/.kimi-code/skills/<name>/SKILL.md",
        global_layout="$KIMI_CODE_HOME/skills/<name>/SKILL.md (default ~/.kimi-code/skills)",
        alternate_project_roots=(
            ".agents/skills/ (cross-tool)",
        ),
        alternate_global_roots=(
            "~/.agents/skills/ (cross-tool)",
            "~/.config/agents/skills/ (legacy Kimi CLI generic root)",
        ),
        install_methods=(
            "This installer: install-resume-skills install --host kimi --scope project|global",
            "Manual: copy each resume-*/ folder into .kimi-code/skills/ or $KIMI_CODE_HOME/skills/",
            "Current plugin release asset: /plugins install <local-directory, ZIP URL, or GitHub URL>, then /plugins reload",
            "Legacy Python Kimi CLI uses different ~/.kimi roots and kimi plugin; do not mix plugin formats",
        ),
        activation_help=(
            "Invoke `/skill:resume-<source>` or mention the skill by name; start a new "
            "session or `/reload` after installing a plugin."
        ),
        activation_examples=(
            "/skill:resume-codex",
            "/skill:resume-kimi",
            "Use the resume-qwen skill with resume_ref: latest",
        ),
        arguments_note=(
            "No skill-to-process argv binding is claimed; pass labeled context and run the owned reader."
        ),
        caveats=(
            "This destination profile targets current Kimi Code CLI (~/.kimi-code), not legacy Python Kimi CLI (~/.kimi).",
            "Current and legacy plugin manifests are incompatible.",
            "Plugins can execute tools; direct SKILL.md installation is the lower-trust default.",
            "Visual picker interaction and public marketplace publication are separate evidence claims.",
        ),
        evidence_notes=(
            "Official Kimi Code docs: .kimi-code/skills, cross-tool .agents roots, "
            "/skill:<name>, kimi.plugin.json, ZIP/GitHub plugin installs, and custom "
            "marketplace catalogs (checked 2026-07-24)."
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
    "kimi": "Kimi CLI / Kimi Code CLI",
    "qwen": "Qwen Code",
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


def host_install_record(
    host: str,
    *,
    project_dir: str | None = None,
    home_dir: str | None = None,
) -> dict[str, Any]:
    """Machine-readable install guide for one destination host."""
    import os

    profile = HOST_PROFILES[host]
    home = home_dir if home_dir is not None else os.path.expanduser("~")
    project = project_dir if project_dir is not None else os.getcwd()
    project_root = resolve_skill_root(
        host=host, scope="project", project_dir=project, home_dir=home
    )
    global_root = resolve_skill_root(
        host=host, scope="global", project_dir=None, home_dir=home
    )
    return {
        "host": host,
        "profile_id": profile.profile_id,
        "display_name": profile.display_name or host,
        "installer_defaults": {
            "project_rel": profile.project_rel,
            "global_rel": profile.global_rel,
            "project_root_resolved": project_root,
            "global_root_resolved": global_root,
            "skill_layout": SKILL_DIR_LAYOUT,
        },
        "official_layouts": {
            "project": profile.project_layout,
            "global": profile.global_layout,
        },
        "alternate_project_roots": list(profile.alternate_project_roots),
        "alternate_global_roots": list(profile.alternate_global_roots),
        "install_methods": list(profile.install_methods),
        "installer_commands": {
            "project_dry_run": (
                f"PYTHONPATH=src python3 scripts/install-resume-skills install "
                f"--host {host} --scope project --project <PROJECT> --dry-run --json"
            ),
            "project": (
                f"PYTHONPATH=src python3 scripts/install-resume-skills install "
                f"--host {host} --scope project --project <PROJECT> --json"
            ),
            "global": (
                f"PYTHONPATH=src python3 scripts/install-resume-skills install "
                f"--host {host} --scope global --json"
            ),
            "custom_root": (
                f"PYTHONPATH=src python3 scripts/install-resume-skills install "
                f"--host {host} --scope project --project <PROJECT> --root <DISTINCT_ROOT> --json"
            ),
            "verify": (
                f"PYTHONPATH=src python3 scripts/install-resume-skills verify "
                f"--host {host} --scope project --project <PROJECT> --json"
            ),
            "uninstall": (
                f"PYTHONPATH=src python3 scripts/install-resume-skills uninstall "
                f"--host {host} --scope project --project <PROJECT> --json"
            ),
        },
        "activation_help": profile.activation_help,
        "activation_examples": list(profile.activation_examples),
        "arguments_note": profile.arguments_note,
        "caveats": list(profile.caveats),
        "official_docs": list(profile.official_docs),
        "evidence_level": profile.evidence_level,
        "evidence_notes": profile.evidence_notes,
        "live_ui": "not-run",
        "skills_installed": list(SOURCE_SKILL_NAMES),
    }


def hosts_report(
    *,
    project_dir: str | None = None,
    home_dir: str | None = None,
    hosts: Iterable[str] | None = None,
) -> dict[str, Any]:
    selected = sorted(hosts or HOST_KEYS)
    records = [
        host_install_record(host, project_dir=project_dir, home_dir=home_dir)
        for host in selected
    ]
    return {
        "ok": True,
        "host_count": len(records),
        "shared_root_pairs": [
            {
                "hosts": ["codex", "antigravity"],
                "path": ".agents/skills",
                "note": "Divergent skill bodies → E_INSTALL_CONFLICT unless --root is distinct.",
            }
        ],
        "hosts": records,
        "docs": "docs/install-hosts.md",
    }
