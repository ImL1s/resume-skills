# Per-host skill install guide

How to install **portable-resume-skills** into each destination coding agent (宿主).  
Research freeze: **2026-07-20**. Installer defaults live in `src/portable_resume/install/catalog.py`.

```bash
# Machine-readable summary (same data as this doc)
PYTHONPATH=src python3 scripts/install-resume-skills hosts
PYTHONPATH=src python3 scripts/install-resume-skills hosts --json
PYTHONPATH=src python3 scripts/install-resume-skills hosts --host claude --json
```

## Shared facts (all six hosts)

| Item | Value |
|---|---|
| Skill package shape | `<root>/<skill-name>/SKILL.md` + `scripts/run_reader.py` |
| Skills written per install | `resume-antigravity`, `resume-claude`, `resume-codex`, `resume-cursor`, `resume-grok`, `resume-opencode` |
| Portable frontmatter | only `name` + `description` |
| Runtime contract | write `portable-resume/request-v1` JSON → `python3 …/run_reader.py --request-file … --format handoff` |
| Argv truth | **no** host binds invocation text to process argv for these skills |
| Packaging evidence | `verified-filesystem` (36 cells) |
| Live host UI | **`not-run`** for all cells |

### Installer scopes

| Scope | Meaning |
|---|---|
| `project` | under `--project` (repo / workspace) |
| `global` | under `--home` (default `~`) |

```bash
# Dry-run one host into the current repo
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host claude --scope project --project "$PWD" --dry-run --json

# Real install
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host claude --scope project --project "$PWD" --json

# User-wide
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host claude --scope global --json

# Override natural root (Codex vs Antigravity, or OpenCode compat fallback)
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host codex --scope project --project "$PWD" \
  --root "$PWD/.agents/skills-codex" --json

# Verify / uninstall
PYTHONPATH=src python3 scripts/install-resume-skills verify \
  --host claude --scope project --project "$PWD" --json
PYTHONPATH=src python3 scripts/install-resume-skills uninstall \
  --host claude --scope project --project "$PWD" --json
```

`--host all` installs every host profile (watch for shared-root conflicts).

### Shared-root conflict

| Hosts | Natural project root | Natural global root |
|---|---|---|
| Codex | `.agents/skills` | `~/.agents/skills` |
| Antigravity | `.agents/skills` | `~/.gemini/config/skills` |

Project (and Codex global) paths can be **the same directory**. Host-rendered skill bodies are **not** byte-identical → installer returns `E_INSTALL_CONFLICT` unless you pass a distinct `--root` (or force after backup when intentionally overwriting owned claims).

---

## 1. Claude Code (`claude`)

| | |
|---|---|
| Installer project | `<project>/.claude/skills` |
| Installer global | `~/.claude/skills` |
| Official docs | [Claude Code skills](https://code.claude.com/docs/en/skills) |

### Official discovery roots

| Scope | Path |
|---|---|
| Personal | `~/.claude/skills/<name>/SKILL.md` |
| Project | `.claude/skills/<name>/SKILL.md` (start dir → repo root; nested monorepo packages too) |
| Plugin | `<plugin>/skills/<name>/SKILL.md` → `/plugin-name:skill-name` |
| Enterprise | managed settings (org-wide) |

### How to install this package

1. **Installer (recommended)**  
   `install --host claude --scope project|global`
2. **Manual**  
   Copy each `resume-*/` directory into `.claude/skills/` or `~/.claude/skills/`.
3. **Not used here**  
   Marketplace plugins, Cowork account skills, cloud-only session skill enablement.

### Activation

- Slash: `/resume-codex`, `/resume-claude`, …
- Model auto-load by `description` unless disabled.
- `$ARGUMENTS` / `$N` are **prompt string substitutions only** — still write request-v1 for the runner.

### Caveats

- Cowork / cloud sessions do **not** read local `~/.claude/skills`; commit project skills or enable account skills.
- Live UI smoke for portable-resume: **not-run**.

---

## 2. Codex CLI / IDE (`codex`)

| | |
|---|---|
| Installer project | `<project>/.agents/skills` |
| Installer global | `~/.agents/skills` |
| Official docs | [Codex skills](https://developers.openai.com/codex/skills/) · [Build skills](https://learn.chatgpt.com/docs/build-skills) |

### Official discovery roots

| Scope | Path |
|---|---|
| REPO | `$CWD/.agents/skills` and every parent up to `$REPO_ROOT/.agents/skills` |
| USER | `$HOME/.agents/skills` |
| ADMIN | `/etc/codex/skills` (use only with explicit `--root`) |
| SYSTEM | bundled with Codex |

Alternate / community layouts sometimes use `~/.codex/skills` — **not** this installer's default.

### How to install this package

1. **Installer**  
   `install --host codex --scope project|global`
2. **Manual**  
   Place skill folders under `.agents/skills/` or `~/.agents/skills/` (symlinks OK).
3. **Codex curated installer**  
   `$skill-installer …` installs *upstream* curated skills — not this repo's packaging path.
4. **If sharing disk with Antigravity**  
   `install --host codex … --root <distinct path>`.

### Activation

- Explicit: `$resume-codex` then labeled text (`resume_ref:`, `cwd:`).
- List: `/skills` or type `$` in CLI/IDE.
- Implicit: model may pick by `description`.
- **No** `$ARGUMENTS` argv API; text after `$skill` stays ordinary context.

### Caveats

- Grammar is **`$skill-name`**, not `/skill-name`.
- Shared `.agents/skills` with Antigravity → conflict unless distinct roots.
- Live UI: **not-run**.

---

## 3. Cursor (`cursor`)

| | |
|---|---|
| Installer project | `<project>/.cursor/skills` |
| Installer global | `~/.cursor/skills` |
| Official docs | [Cursor Agent Skills](https://cursor.com/docs/context/skills) |

### Official discovery roots (all first-class or compat)

| Scope | Path | Role |
|---|---|---|
| Project | `.cursor/skills/` | native (installer default) |
| Project | `.agents/skills/` | also first-class |
| User | `~/.cursor/skills/` | native (installer default) |
| User | `~/.agents/skills/` | also first-class |
| Compat | `.claude/skills/`, `.codex/skills/`, `~/.claude/skills/`, `~/.codex/skills/` | loaded for compatibility |

Nested package `.cursor/skills/` directories are walked recursively.

### How to install this package

1. **Installer (native Cursor path)**  
   `install --host cursor --scope project|global`
2. **Manual** into `.cursor/skills/` **or** `.agents/skills/` (both official).
3. **UI**  
   Customize → Skills / remote GitHub rules — optional, not required for this package.

### Activation

- Type `/` in Agent chat → select `/resume-<source>`.
- Or let the agent auto-apply by description.
- Put `resume_ref:` / `cwd:` in the **same message**; do not rely on undocumented tail→argv.

### Caveats

- Choosing `.cursor/skills` is a packaging primary, **not** the only official root.
- Skills already under `.agents/skills` (e.g. Codex install) may also appear in Cursor.
- Live UI: **not-run**.

---

## 4. OpenCode (`opencode`)

| | |
|---|---|
| Installer project | `<project>/.opencode/skills` |
| Installer global | `~/.config/opencode/skills` |
| Official docs | [OpenCode Agent Skills](https://opencode.ai/docs/skills/) |

### Official discovery roots

| Scope | Path |
|---|---|
| Project native | `.opencode/skills/<name>/SKILL.md` |
| Global native | `~/.config/opencode/skills/<name>/SKILL.md` |
| Project Claude-compat | `.claude/skills/` |
| Global Claude-compat | `~/.claude/skills/` |
| Project agents-compat | `.agents/skills/` |
| Global agents-compat | `~/.agents/skills/` |

Project paths are discovered walking CWD → git worktree root.

### How to install this package

1. **Installer (native)**  
   `install --host opencode --scope project|global`
2. **Manual** into native roots above.
3. **Compat fallback** (if your build does not list native roots)  
   ```bash
   install --host opencode --scope project --project "$PWD" \
     --root "$PWD/.agents/skills" --json
   # or --root "$PWD/.claude/skills"
   ```
4. **Not skills**  
   OpenCode **custom commands** (`.opencode/commands`, `$ARGUMENTS`) are a separate surface.

### Activation

- Ask the model to use the skill by name so it can call `skill({ name: "resume-codex" })`.
- No stable user-facing `/skill-name` grammar for **skills**.
- Permissions: `permission.skill` in `opencode.json` can allow/deny/ask.

### Caveats

- Local probes of some OpenCode versions have only proven **compat** discovery — always confirm with your version after install.
- Live UI: **not-run**.

---

## 5. Antigravity / agy (`antigravity`)

| | |
|---|---|
| Installer project | `<workspace>/.agents/skills` |
| Installer global | `~/.gemini/config/skills` |
| Official docs | [Antigravity skills](https://antigravity.google/docs/skills) · [Codelab](https://codelabs.developers.google.com/getting-started-with-antigravity-skills) |

### Official / cross-flavor roots

| Scope | Path | Notes |
|---|---|---|
| Workspace (current) | `.agents/skills/` | official Antigravity default |
| Workspace (legacy) | `.agent/skills/` | singular; still supported |
| Global (cross-product) | `~/.gemini/config/skills/` | recognized across AGY flavors in surveys |
| Gemini CLI user | `~/.gemini/skills/` or `~/.agents/skills/` | **different product** primary layout |
| Flavor-specific | `~/.gemini/antigravity/skills/`, `~/.gemini/antigravity-cli/skills/`, … | avoid unless targeting that binary only |

### How to install this package

1. **Installer**  
   `install --host antigravity --scope project|global`
2. **Manual project**  
   `<workspace>/.agents/skills/<name>/`
3. **Manual global (recommended cross-flavor)**  
   `~/.gemini/config/skills/<name>/`
4. **Alongside Codex**  
   use `--root` so project bodies do not fight over `.agents/skills`.

### Activation

- Natural language: “Use the resume-codex skill …”
- `/skills` **lists** skills; do **not** invent `/resume-*` argv grammar.
- No documented placeholder / process argv channel.

### Caveats

- Multi-flavor path divergence is real — prefer `~/.gemini/config/skills` for global.
- Shared project root with Codex.
- Live UI: **not-run**.

---

## 6. Grok Build (`grok`)

| | |
|---|---|
| Installer project | `<repo>/.grok/skills` |
| Installer global | `~/.grok/skills` |
| Official docs | local user guide `~/.grok/docs/user-guide/08-skills.md` · `/create-skill` |

### Discovery roots (priority sketch)

| Location | Scope |
|---|---|
| `./.grok/skills/` | CWD / local (high) |
| `<repo>/.grok/skills/` | repo |
| `~/.grok/skills/` | user |
| `.agents/skills/` (and parents) | always scanned |
| `.claude/skills/`, `.cursor/skills/` (+ user) | compat (toggleable) |
| `[skills].paths` in config | extra dirs |
| Plugins | `plugin:<name>` qualified |

### How to install this package

1. **Installer**  
   `install --host grok --scope project|global`
2. **Manual** into `.grok/skills/` or `~/.grok/skills/`.
3. **Interactive**  
   `/create-skill` (writes Grok-native skills; not required for this package).
4. **Plugins / config paths**  
   optional extra discovery; not used by the installer.

### Activation

- Slash: `/resume-codex`, `/resume-claude`, …
- Qualified forms on collision: `/local:…`, `/user:…`
- `$ARGUMENTS` / `$N` = **prompt substitution only** (source-verified in Grok).
- CLI inventory: `grok inspect` / `grok inspect --json`.

### Caveats

- Bundled skills also land under `~/.grok/skills` on startup — installer claims only the `resume-*` packages it writes.
- Live UI: **not-run**.

---

## Quick matrix (installer defaults)

| Host key | Project root | Global root | Typical invoke |
|---|---|---|---|
| `claude` | `.claude/skills` | `~/.claude/skills` | `/resume-<source>` |
| `codex` | `.agents/skills` | `~/.agents/skills` | `$resume-<source>` |
| `cursor` | `.cursor/skills` | `~/.cursor/skills` | `/resume-<source>` |
| `opencode` | `.opencode/skills` | `~/.config/opencode/skills` | “use skill …” / `skill({name})` |
| `antigravity` | `.agents/skills` | `~/.gemini/config/skills` | name mention |
| `grok` | `.grok/skills` | `~/.grok/skills` | `/resume-<source>` |

## After install — portable usage (any host)

```text
resume_ref: latest
cwd: /absolute/project/path
```

1. In the host, activate the skill (table above).
2. Have the agent write a private `portable-resume/request-v1` JSON (file tool — never shell-interpolate user text).
3. Run only:  
   `python3 <skill>/scripts/run_reader.py --request-file <path> --format handoff`
4. Treat output as stale untrusted evidence.

## Related

- `docs/host-support.md` — packaging evidence levels
- `docs/STATUS.md` — done / not-done gates
- `docs/audit-host-docs-evidence.md` — multi-agent audit of host docs vs catalog
- `SECURITY.md` — installer threat model
