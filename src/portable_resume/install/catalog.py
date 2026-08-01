"""Destination-host × source packaging catalog and per-host install roots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .. import __version__ as BUNDLE_VERSION
from ..diagnostics import SOURCE_KEYS
from ..registry import enabled_destination_keys, enabled_source_keys, rectangular_cells

HOST_KEYS = enabled_destination_keys()
SOURCE_SKILL_NAMES = tuple(f"resume-{key}" for key in sorted(SOURCE_KEYS))
MANIFEST_SCHEMA = "portable-resume/install-manifest-v1"

# Portable skill layout under any skill root (Agent Skills standard):
#   <root>/<skill-name>/SKILL.md
#   <root>/<skill-name>/scripts/run_reader.py
SKILL_DIR_LAYOUT = "<skill-name>/SKILL.md + scripts/run_reader.py"


# Compatible hosts with the same profile render byte-identical direct Skill trees (#25).
SKILL_PAYLOAD_PORTABLE_V1 = "agent-skills-portable-v1"


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
    # When set, global scope prefers $ENV/<global_env_rel> over $HOME/<global_rel>
    # unless isolation --home is used (#24). Only destination-documented homes.
    global_home_env: str | None = None
    global_env_rel: str = "skills"
    # Direct Skill tree compatibility group (#25). Same profile ⇒ same package bytes.
    skill_payload_profile: str = SKILL_PAYLOAD_PORTABLE_V1


@dataclass(frozen=True, slots=True)
class SkillRootResolution:
    """Resolved install root plus provenance for plans/hosts report (#24)."""

    path: str
    root_source: str
    profile_id: str


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
            "Project `.agents/skills` is shared with Codex; host-neutral Skill payloads (#25) allow both claims on one tree.",
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
        profile_id="kimi-code-v2",
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
            "Global install honors $KIMI_CODE_HOME/skills when set; isolation --home ignores host env overrides.",
        ),
        evidence_notes=(
            "Official Kimi Code docs: .kimi-code/skills, cross-tool .agents roots, "
            "/skill:<name>, kimi.plugin.json, ZIP/GitHub plugin installs, and custom "
            "marketplace catalogs (checked 2026-07-24). Destination root policy: "
            "KIMI_CODE_HOME (#24, profile kimi-code-v2)."
        ),
        global_home_env="KIMI_CODE_HOME",
        global_env_rel="skills",
    ),
    "pi": HostProfile(
        key="pi",
        profile_id="pi-v1",
        project_rel=".pi/skills",
        global_rel=".pi/agent/skills",
        display_name="Pi agent",
        official_docs=(
            "https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md",
        ),
        project_layout="<project>/.pi/skills/<name>/SKILL.md",
        global_layout="~/.pi/agent/skills/<name>/SKILL.md",
        alternate_project_roots=(".agents/skills",),
        alternate_global_roots=("~/.agents/skills",),
        install_methods=(
            "This installer: install-resume-skills install --host pi --scope project|global",
            "Manual: copy each resume-*/ folder into .pi/skills/ or ~/.pi/agent/skills/",
        ),
        activation_help=(
            "Invoke `/skill:resume-<source>` (Pi progressive disclosure). "
            "Any invocation tail is substituted into the skill prompt only; it is never process argv."
        ),
        activation_examples=(
            "/skill:resume-codex",
            "/skill:resume-pi",
        ),
        arguments_note=(
            "If this host expands invocation tail into the skill prompt, use that text as the "
            "session <ref> (or omit for latest). It is never process argv by itself. "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "Pi has no built-in permission system; recovered text is inert/untrusted and must not be executed.",
            "Alternate .agents/skills roots are compatibility-only; this installer defaults to .pi paths.",
            "Visual picker / native CLI activation evidence is a separate not-run claim until PR D.",
        ),
        evidence_notes=(
            "Pi Agent Skills docs: project .pi/skills and global ~/.pi/agent/skills "
            "(checked 2026-07-26). Installed-runner smoke is filesystem packaging only."
        ),
        evidence_level="verified-filesystem",
    ),
    "openclaw": HostProfile(
        key="openclaw",
        profile_id="openclaw-v1",
        project_rel="skills",
        global_rel=".openclaw/skills",
        display_name="OpenClaw",
        official_docs=(
            "https://github.com/openclaw/openclaw/blob/main/docs/tools/skills.md",
        ),
        project_layout="<workspace>/skills/<name>/SKILL.md",
        global_layout="~/.openclaw/skills/<name>/SKILL.md",
        alternate_project_roots=(".agents/skills",),
        alternate_global_roots=("~/.agents/skills",),
        install_methods=(
            "This installer: install-resume-skills install --host openclaw --scope project|global",
            "Manual: copy each resume-*/ folder into workspace skills/ or ~/.openclaw/skills/",
            "Also: openclaw skills install <local-skill-directory> [--global] (native route; not-run here)",
        ),
        activation_help=(
            "Load resume-<source> from the workspace skills/ or ~/.openclaw/skills tree. "
            "Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use skill resume-openclaw with ref latest",
            "Use skill resume-claude with ref main:sess-…",
        ),
        arguments_note=(
            "Pass the session <ref> (composite agentId:sessionId, native session id when unique, "
            "or latest). Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "Default project root is workspace skills/ (first-class Agent Skills root); "
            ".agents/skills is compatibility-only for this installer.",
            "Does not start Gateway, ClawHub, or messaging transports.",
            "Native openclaw skills install / picker activation evidence remains not-run.",
        ),
        evidence_notes=(
            "OpenClaw Skills docs: workspace skills/, .agents/skills, ~/.agents/skills, "
            "~/.openclaw/skills (checked 2026-07-26). Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
    ),
    "goose": HostProfile(
        key="goose",
        profile_id="goose-v1",
        project_rel=".goose/skills",
        global_rel=".config/goose/skills",
        display_name="goose",
        official_docs=(
            "https://github.com/aaif-goose/goose/blob/main/documentation/docs/guides/context-engineering/using-skills.md",
        ),
        project_layout="<project>/.goose/skills/<name>/SKILL.md",
        global_layout="~/.config/goose/skills/<name>/SKILL.md",
        alternate_project_roots=(".agents/skills",),
        alternate_global_roots=("~/.agents/skills",),
        install_methods=(
            "This installer: install-resume-skills install --host goose --scope project|global",
            "Manual: copy each resume-*/ folder into .goose/skills/ or ~/.config/goose/skills/",
        ),
        activation_help=(
            "Load resume-<source> from the goose skills tree. "
            "Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use skill resume-goose with ref latest",
            "Use skill resume-goose with a session id",
        ),
        arguments_note=(
            "Pass the session <ref> (native session id or latest). "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "SQLite sessions.db is the only supported source store; legacy JSONL is out of scope.",
            "Does not invoke goose CLI/Desktop, Chat Recall, MCP, or ACP.",
            "Native goose UI / picker activation evidence remains not-run.",
        ),
        evidence_notes=(
            "goose Agent Skills docs + sessions.db schema v15 fixtures (checked 2026-07-26). "
            "Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
    ),
    "crush": HostProfile(
        key="crush",
        profile_id="crush-v1",
        project_rel=".crush/skills",
        global_rel=".config/crush/skills",
        display_name="Crush",
        official_docs=(
            "https://github.com/charmbracelet/crush",
        ),
        project_layout="<project>/.crush/skills/<name>/SKILL.md",
        global_layout="~/.config/crush/skills/<name>/SKILL.md",
        alternate_project_roots=(".agents/skills",),
        alternate_global_roots=("~/.agents/skills", "~/.claude/skills"),
        install_methods=(
            "This installer: install-resume-skills install --host crush --scope project|global",
            "Manual: copy each resume-*/ folder into .crush/skills/ or ~/.config/crush/skills/",
        ),
        activation_help=(
            "Load resume-<source> from the Crush skills tree. "
            "Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use skill resume-crush with ref latest",
            "Use skill resume-crush with a session id",
        ),
        arguments_note=(
            "Pass the session <ref> (native session id or latest). "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "Per-project .crush/crush.db is the supported store; no recursive home scan.",
            "Does not invoke Crush CLI/TUI, crush serve, migrations, MCP, or providers.",
            "Native Crush UI / picker activation evidence remains not-run.",
        ),
        evidence_notes=(
            "Crush crush.db goose_db_version=7 fixtures + Agent Skills roots "
            "(checked 2026-07-30). Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
    ),
    "cline": HostProfile(
        key="cline",
        profile_id="cline-v1",
        project_rel=".cline/skills",
        global_rel=".cline/skills",
        display_name="Cline",
        official_docs=(
            "https://docs.cline.bot/customization/skills",
        ),
        project_layout="<project>/.cline/skills/<name>/SKILL.md",
        global_layout="~/.cline/skills/<name>/SKILL.md",
        alternate_project_roots=(".clinerules/skills", ".claude/skills"),
        alternate_global_roots=(),
        install_methods=(
            "This installer: install-resume-skills install --host cline --scope project|global",
            "Manual: copy each resume-*/ folder into .cline/skills/ or ~/.cline/skills/",
        ),
        activation_help=(
            "Load resume-<source> from the Cline skills tree via use_skill or slash command. "
            "Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use skill resume-cline with ref latest",
            "Use skill resume-cline with a session id",
        ),
        arguments_note=(
            "Pass the session <ref> (native session id or latest). "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "SQLite index is discovery-only; messages JSON is authoritative for transcripts.",
            "Does not invoke Cline CLI/hub/SDK, connectors, or migrations.",
            "Native Cline UI / picker activation evidence remains not-run.",
        ),
        evidence_notes=(
            "Cline sessions.db + messages.json v1 fixtures + Skills docs "
            "(checked 2026-07-30). Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
    ),
    "openhands": HostProfile(
        key="openhands",
        profile_id="openhands-v1",
        project_rel=".agents/skills",
        global_rel=".openhands/skills",
        display_name="OpenHands",
        official_docs=(
            "https://docs.openhands.dev/overview/skills",
            "https://docs.openhands.dev/overview/skills/adding",
        ),
        project_layout="<project>/.agents/skills/<name>/SKILL.md",
        global_layout="~/.openhands/skills/<name>/SKILL.md",
        alternate_project_roots=(),
        alternate_global_roots=(),
        install_methods=(
            "This installer: install-resume-skills install --host openhands --scope project|global",
            "Manual: copy each resume-*/ folder into .agents/skills/ or ~/.openhands/skills/",
        ),
        activation_help=(
            "Load resume-<source> from the OpenHands skills tree. "
            "Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use skill resume-openhands with ref latest",
            "Use skill resume-openhands with a conversation id",
        ),
        arguments_note=(
            "Pass the session <ref> (native conversation id or latest). "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "Local CLI event-file store only; does not query OpenHands Cloud or ACP.",
            "Does not invoke openhands CLI/SDK, register default tools, or load org skills.",
            "Native OpenHands UI / picker activation evidence remains not-run.",
        ),
        evidence_notes=(
            "OpenHands CLI LocalFileStore event-*.json fixtures + Skills docs "
            "(checked 2026-07-31). Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
    ),
    "hermes": HostProfile(
        key="hermes",
        profile_id="hermes-v1",
        project_rel=".hermes/skills",
        global_rel=".hermes/skills",
        display_name="Hermes Agent",
        official_docs=(
            "https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md",
        ),
        project_layout="<project>/.hermes/skills/<name>/SKILL.md",
        global_layout="$HERMES_HOME/skills/<name>/SKILL.md (default ~/.hermes/skills/)",
        alternate_project_roots=(),
        alternate_global_roots=(),
        install_methods=(
            "This installer: install-resume-skills install --host hermes --scope project|global",
            "Manual: copy each resume-*/ folder into $HERMES_HOME/skills or ~/.hermes/skills/",
        ),
        activation_help=(
            "Load resume-<source> from the Hermes skills tree via slash command. "
            "Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use skill resume-hermes with ref latest",
            "Use skill resume-hermes with a session id",
        ),
        arguments_note=(
            "Pass the session <ref> (native session id or latest). "
            "Optional advanced path: write portable-resume/request-v1 then "
            "`run_reader.py --request-file <path>`."
        ),
        caveats=(
            "SQLite state.db schema 23 is the supported store; legacy JSONL is out of scope.",
            "Does not invoke Hermes CLI/gateway, Skill hub, taps, or messaging platforms.",
            "Native Hermes UI / picker activation evidence remains not-run.",
            "Global installs honor HERMES_HOME when set (absolute path).",
        ),
        evidence_notes=(
            "Hermes state.db schema 23 fixtures + Skills docs "
            "(checked 2026-07-31). Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
        global_home_env="HERMES_HOME",
        global_env_rel="skills",
    ),
    "github-copilot": HostProfile(
        key="github-copilot",
        profile_id="github-copilot-v1",
        project_rel=".github/skills",
        global_rel=".copilot/skills",
        display_name="GitHub Copilot CLI",
        official_docs=(
            "https://docs.github.com/en/copilot/concepts/agents/about-agent-skills",
            "https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills",
            "https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference",
        ),
        project_layout="<project>/.github/skills/<name>/SKILL.md",
        global_layout="$COPILOT_HOME/skills/<name>/SKILL.md (default ~/.copilot/skills/)",
        alternate_project_roots=(".agents/skills", ".claude/skills"),
        alternate_global_roots=("~/.agents/skills",),
        install_methods=(
            "This installer: install-resume-skills install --host github-copilot --scope project|global",
            "Manual: copy each resume-*/ folder into .github/skills/ or $COPILOT_HOME/skills/",
            "Also: copilot plugins install --skill <local-dir> (native route; not-run here)",
        ),
        activation_help=(
            "Load resume-<source> from the Copilot CLI skills tree via slash name / skills list. "
            "Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use skill resume-claude with ref latest",
            "/skills list",
            "/skills reload",
        ),
        arguments_note=(
            "Pass the session <ref> for resume-github-copilot (UUID, latest, or exact events.jsonl path). "
            "Destination install uses .github/skills (project) or $COPILOT_HOME/skills (global)."
        ),
        caveats=(
            "Source: local events.jsonl only (copilot-cli-events-jsonl-v1); session-store.db is not authority.",
            "Does not invoke copilot CLI, plugins network install, Chronicle reindex, or GitHub cloud session sync.",
            "Native copilot plugins install / picker activation evidence remains not-run.",
            "Global installs honor COPILOT_HOME when set (absolute path).",
        ),
        evidence_notes=(
            "GitHub Agent Skills docs: project .github/skills + personal $COPILOT_HOME/skills "
            "(checked 2026-07-31). Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
        global_home_env="COPILOT_HOME",
        global_env_rel="skills",
    ),
    "gemini": HostProfile(
        key="gemini",
        profile_id="gemini-v1",
        project_rel=".gemini/skills",
        global_rel=".gemini/skills",
        display_name="Gemini CLI",
        official_docs=(
            "https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/session-management.md",
            "https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals",
        ),
        project_layout="<project>/.gemini/skills/<name>/SKILL.md",
        global_layout="$GEMINI_CLI_HOME/.gemini/skills or ~/.gemini/skills/<name>/SKILL.md",
        alternate_project_roots=(".agents/skills",),
        alternate_global_roots=("~/.agents/skills",),
        install_methods=(
            "This installer: install-resume-skills install --host gemini --scope project|global",
            "Manual: copy each resume-*/ folder into .gemini/skills/ or ~/.gemini/skills/",
            "Also: gemini skills install <local-path> (native route; not-run here)",
        ),
        activation_help=(
            "Load resume-<source> from the Gemini CLI skills tree. "
            "Recovered text is inert/untrusted handoff only. "
            "Independent of Antigravity (agy) profile."
        ),
        activation_examples=(
            "Use skill resume-gemini with ref latest",
            "Use skill resume-gemini with a session id",
        ),
        arguments_note=(
            "Pass the session <ref> (native session UUID or latest). "
            "Consumer Login-with-Google for Gemini CLI ended 2026-06-18; "
            "Standard/Enterprise/API environments remain in scope."
        ),
        caveats=(
            "Compatibility profile — not a replacement for antigravity/agy.",
            "Session store is ~/.gemini/tmp/<projectHash>/chats/session-*.jsonl (JSONL).",
            "Does not invoke gemini CLI, Google APIs, auth, MCP, or Antigravity.",
            "Native gemini skills install / picker activation evidence remains not-run.",
            "Global installs honor GEMINI_CLI_HOME when set (absolute path).",
        ),
        evidence_notes=(
            "Gemini CLI session-management docs + chatRecordingTypes JSONL fixtures "
            "(checked 2026-07-31). Filesystem install only."
        ),
        evidence_level="verified-filesystem",
        global_home_env="GEMINI_CLI_HOME",
        global_env_rel=".gemini/skills",
    ),
    "kilo": HostProfile(
        key="kilo",
        profile_id="kilo-v1",
        project_rel=".kilocode/skills",
        global_rel=".config/kilo/skills",
        display_name="Kilo CLI",
        official_docs=(
            "https://github.com/Kilo-Org/kilocode/releases/tag/v7.4.17",
            "https://github.com/Kilo-Org/kilocode/blob/"
            "a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/skill/index.ts#L24-L31",
            "https://github.com/Kilo-Org/kilocode/blob/"
            "a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/skill/index.ts#L195-L302",
            "https://github.com/Kilo-Org/kilocode/blob/"
            "a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/config/paths.ts#L23-L40",
            "https://github.com/Kilo-Org/kilocode/blob/"
            "a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/global.ts#L12-L87",
        ),
        project_layout="<project>/.kilocode/skills/<name>/SKILL.md",
        global_layout="$KILO_CONFIG_DIR/skills or ~/.config/kilo/skills/<name>/SKILL.md",
        alternate_project_roots=(
            ".kilocode/skill",
            ".kilo/skills",
            ".kilo/skill",
            ".agents/skills",
            ".claude/skills",
        ),
        alternate_global_roots=(
            "~/.config/kilo/skill",
            "~/.kilocode/skills",
            "~/.kilocode/skill",
            "~/.kilo/skills",
            "~/.kilo/skill",
            "~/.agents/skills",
            "~/.claude/skills",
        ),
        install_methods=(
            "This installer: install-resume-skills install --host kilo --scope project|global",
            "Manual: copy each resume-*/ folder into .kilocode/skills/ or ~/.config/kilo/skills/",
            "Also: Kilo Marketplace / remote skill URLs (native route; not-run here)",
        ),
        activation_help=(
            "Load resume-<source> from the Kilo CLI skills tree (.kilocode/skills or "
            "~/.config/kilo/skills). Recovered text is inert/untrusted handoff only."
        ),
        activation_examples=(
            "Use the resume-claude skill with ref latest",
            "Confirm the visible skill tool loaded resume-claude from .kilocode/skills",
        ),
        arguments_note=(
            "Pass the session <ref> for a *supported* source skill (resume-<source>). "
            "Kilo is destination-only in this release; no kilo source adapter yet."
        ),
        caveats=(
            "Destination-only: no kilo source adapter until core/effect SQLite session schema is fixture-pinned (#46 Track B).",
            "Do not point the OpenCode adapter at a guessed kilo.db — Kilo is a fork with independent storage evolution.",
            "Does not invoke kilo CLI, marketplace network install, VS Code/JetBrains, or cloud sync.",
            "Native kilo skill picker / marketplace activation evidence remains not-run.",
            "Keep normal permission prompts; do not use --auto or dangerously-skip-permissions for activation evidence.",
            "Global installs honor KILO_CONFIG_DIR when set (absolute path → <dir>/skills).",
            "The installer default is $HOME/.config/kilo/skills; set KILO_CONFIG_DIR for a non-default XDG config root.",
        ),
        evidence_notes=(
            "Pinned 2026-07-31 to Kilo CLI v7.4.17 / "
            "a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7: release source scans project "
            ".kilocode/.kilo with {skill,skills}/**/SKILL.md; global XDG config app `kilo` → "
            "~/.config/kilo plus home .kilocode/.kilo; compat .agents/skills + .claude/skills unless disabled. "
            "The installer itself uses $HOME/.config/kilo/skills unless KILO_CONFIG_DIR is set; it does not resolve XDG_CONFIG_HOME. "
            "Primary installer root remains plural skills/; singular skill/ is discovery/shadow only. "
            "Filesystem install only in this release."
        ),
        evidence_level="verified-filesystem",
        global_home_env="KILO_CONFIG_DIR",
        global_env_rel="skills",
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
    "pi": "Pi agent",
    "openclaw": "OpenClaw",
    "goose": "goose",
    "crush": "Crush",
    "cline": "Cline",
    "openhands": "OpenHands",
    "hermes": "Hermes Agent",
    "gemini": "Gemini CLI",
    "github-copilot": "GitHub Copilot CLI",
    "qwen": "Qwen Code",
}


def description_for(source: str) -> str:
    """Trigger-first frontmatter description (plan 055).

    Hosts route Skills by this string. Prefer user vocabulary (resume /
    continue / last session / handoff) over mechanism-first "request document"
    wording. Still describes offline inert context migration only — never live
    process or session restore.
    """

    title = SOURCE_TITLES[source]
    return (
        f"Resume or continue the last {title} session: pick up previous work, "
        f"import inert offline handoff context into a fresh session "
        f"(never live process restore)."
    )


def skill_name_for(source: str) -> str:
    return f"resume-{source}"


def matrix_cells(hosts: Iterable[str] | None = None) -> list[tuple[str, str]]:
    destinations = frozenset(hosts) if hosts is not None else enabled_destination_keys()
    unknown = destinations - enabled_destination_keys()
    if unknown:
        raise KeyError(sorted(unknown)[0])
    return rectangular_cells(sources=enabled_source_keys(), destinations=destinations)


def _is_isolation_home(home_dir: str) -> bool:
    """True when --home is not the process real user home (tests/isolation)."""

    import os

    try:
        return os.path.realpath(home_dir) != os.path.realpath(os.path.expanduser("~"))
    except OSError:
        return True


def _validate_env_home(raw: str, *, env_name: str) -> str:
    """Reject empty/relative/NUL host config homes (#24)."""

    import os

    if "\x00" in raw:
        raise ValueError(f"invalid {env_name}: contains NUL")
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"invalid {env_name}: empty")
    expanded = os.path.expanduser(stripped)
    if not os.path.isabs(expanded):
        raise ValueError(f"invalid {env_name}: must be an absolute path")
    return os.path.realpath(expanded)


def resolve_skill_root_info(
    *,
    host: str,
    scope: str,
    project_dir: str | None,
    home_dir: str,
    environ: dict[str, str] | None = None,
    isolation: bool | None = None,
) -> SkillRootResolution:
    """Resolve Skill root and provenance for install/verify/uninstall/hosts (#24).

    Precedence for global scope:
    1. Host env home (e.g. ``KIMI_CODE_HOME``) + ``global_env_rel`` when the env
       is set and isolation is false (default: isolation when ``home_dir`` is not
       the real user home / explicit test ``--home``)
    2. ``home_dir`` + ``global_rel``

    Explicit CLI ``--root`` is applied by callers before this resolver.
    """

    import os

    profile = HOST_PROFILES[host]
    env = environ if environ is not None else os.environ
    if isolation is None:
        isolation = _is_isolation_home(home_dir)
    if scope == "project":
        if not project_dir:
            raise ValueError("project scope requires --project")
        path = os.path.join(os.path.realpath(project_dir), profile.project_rel)
        return SkillRootResolution(
            path=path,
            root_source="project",
            profile_id=profile.profile_id,
        )
    if scope == "global":
        if profile.global_home_env and not isolation and profile.global_home_env in env:
            base = _validate_env_home(
                env[profile.global_home_env],
                env_name=profile.global_home_env,
            )
            path = os.path.join(base, profile.global_env_rel)
            return SkillRootResolution(
                path=path,
                root_source=f"env:{profile.global_home_env}",
                profile_id=profile.profile_id,
            )
        path = os.path.join(os.path.realpath(home_dir), profile.global_rel)
        return SkillRootResolution(
            path=path,
            root_source="home",
            profile_id=profile.profile_id,
        )
    raise ValueError(f"unknown scope: {scope}")


def resolve_skill_root(
    *,
    host: str,
    scope: str,
    project_dir: str | None,
    home_dir: str,
    environ: dict[str, str] | None = None,
    isolation: bool | None = None,
) -> str:
    return resolve_skill_root_info(
        host=host,
        scope=scope,
        project_dir=project_dir,
        home_dir=home_dir,
        environ=environ,
        isolation=isolation,
    ).path


def _installer_command_pair(
    *argv_tail: str,
) -> dict[str, Any]:
    """Primary installed console entrypoint + optional source-checkout form (#66).

    JSON prefers argv arrays for automation; human text uses display strings.
    Placeholders such as ``<PROJECT>`` stay unquoted tokens.
    """

    installed_argv = ["install-resume-skills", *argv_tail]
    source_argv = [
        "python3",
        "scripts/install-resume-skills",
        *argv_tail,
    ]
    return {
        "installed_argv": installed_argv,
        "installed": " ".join(installed_argv),
        "source_checkout_argv": ["env", "PYTHONPATH=src", *source_argv],
        "source_checkout": "PYTHONPATH=src " + " ".join(source_argv),
    }


def host_catalog_snapshot(
    *, hosts: Iterable[str] | None = None
) -> dict[str, Any]:
    """Return environment-independent structural host documentation data."""

    selected = sorted(hosts or HOST_KEYS)
    records: list[dict[str, Any]] = []
    for host in selected:
        profile = HOST_PROFILES[host]
        records.append(
            {
                "host": host,
                "profile_id": profile.profile_id,
                "display_name": profile.display_name or host,
                "official_layouts": {
                    "project": profile.project_layout,
                    "global": profile.global_layout,
                },
                "installer_commands": {
                    "project": _installer_command_pair(
                        "install",
                        "--host",
                        host,
                        "--scope",
                        "project",
                        "--project",
                        "<PROJECT>",
                    ),
                    "global": _installer_command_pair(
                        "install",
                        "--host",
                        host,
                        "--scope",
                        "global",
                    ),
                },
                "activation_help": profile.activation_help,
            }
        )
    return {"host_count": len(records), "hosts": records}


def _discovery_roots_payload(host: str) -> list[dict[str, Any]]:
    """Lazy import avoids catalog↔discovery import cycle at module load."""

    from .discovery import discovery_roots_for_host

    return [entry.to_dict() for entry in discovery_roots_for_host(host)]


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
    project_res = resolve_skill_root_info(
        host=host, scope="project", project_dir=project, home_dir=home
    )
    global_res = resolve_skill_root_info(
        host=host, scope="global", project_dir=None, home_dir=home
    )
    return {
        "host": host,
        "profile_id": profile.profile_id,
        "skill_payload_profile": profile.skill_payload_profile,
        "display_name": profile.display_name or host,
        "installer_defaults": {
            "project_rel": profile.project_rel,
            "global_rel": profile.global_rel,
            "project_root_resolved": project_res.path,
            "global_root_resolved": global_res.path,
            "project_root_source": project_res.root_source,
            "global_root_source": global_res.root_source,
            "global_home_env": profile.global_home_env,
            "skill_layout": SKILL_DIR_LAYOUT,
        },
        "official_layouts": {
            "project": profile.project_layout,
            "global": profile.global_layout,
        },
        "alternate_project_roots": list(profile.alternate_project_roots),
        "alternate_global_roots": list(profile.alternate_global_roots),
        # Executable discovery policy (#34); supersedes prose-only alternate lists.
        "discovery_roots": _discovery_roots_payload(host),
        "install_methods": list(profile.install_methods),
        # #32: install/verify/uninstall always emit install-result-v1 JSON (no --json flag).
        "installer_commands": {
            "project_dry_run": _installer_command_pair(
                "install",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                "<PROJECT>",
                "--dry-run",
            ),
            "project": _installer_command_pair(
                "install",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                "<PROJECT>",
            ),
            "global": _installer_command_pair(
                "install",
                "--host",
                host,
                "--scope",
                "global",
            ),
            "custom_root": _installer_command_pair(
                "install",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                "<PROJECT>",
                "--root",
                "<DISTINCT_ROOT>",
            ),
            "verify": _installer_command_pair(
                "verify",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                "<PROJECT>",
            ),
            "uninstall": _installer_command_pair(
                "uninstall",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                "<PROJECT>",
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
    shared_root_pairs: list[dict[str, Any]] = []
    # Only emit when the selected set includes both conflicting hosts (#66).
    if "codex" in selected and "antigravity" in selected:
        shared_root_pairs.append(
            {
                "hosts": ["codex", "antigravity"],
                "path": ".agents/skills",
                "note": (
                    "Divergent skill bodies → E_INSTALL_CONFLICT unless --root is distinct."
                ),
            }
        )
    return {
        "ok": True,
        "host_count": len(records),
        "shared_root_pairs": shared_root_pairs,
        "hosts": records,
        "docs": "docs/install-hosts.md",
    }
