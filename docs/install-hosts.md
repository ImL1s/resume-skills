# Destination installation guide

This repository ships eight `resume-<source>` Skills to eight destination hosts. The reader remains offline and stdlib-only; plugin/marketplace packages contain the same inert Skills and no network integration.

## Build or inspect packages

```bash
PYTHONPATH=src python3 scripts/install-resume-skills hosts --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json
python3 scripts/build_host_packages.py --output-dir host-packages
```

The package builder creates eight `*-<host>-skills.zip` archives, seven supported plugin/marketplace archives, and `host-packages.json` with SHA-256 digests. Replace `<version>` below with the release version.

## Fastest safe install

From a checkout:

```bash
pipx install .
install-resume-skills quick-install qwen        # user-global Qwen profile
install-resume-skills quick-install all         # all eight user-global profiles
install-resume-skills quick-install qwen --project "$PWD"
```

After publication, `pipx install portable-resume` installs the same two CLI entry
points from PyPI. `quick-install` defaults to user-global roots; use the lower-level
transactional commands below for dry runs, explicit roots, verification, backup
replacement, or uninstall.

## Direct installer (all hosts)

```bash
# Preview, install, verify, then uninstall one profile
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --dry-run --json
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --json
PYTHONPATH=src python3 scripts/install-resume-skills verify \
  --host qwen --scope project --project "$PWD" --json
PYTHONPATH=src python3 scripts/install-resume-skills uninstall \
  --host qwen --scope project --project "$PWD" --json
```

Use `--scope global` for the user root or `--root <path>` for an explicit root. `--host all` preflights every physical destination before writing and compensates earlier roots if a later root fails. Codex and Antigravity both default to `.agents/skills` at project scope but render different host instructions, so install one to a distinct `--root`; otherwise the installer returns `E_INSTALL_CONFLICT` before mutation.

## Per-host routes

| Host | Direct Skill root (project / user) | Release plugin or marketplace route | Activation |
|---|---|---|---|
| Claude Code (`claude`) | `.claude/skills` / `~/.claude/skills` | Extract `claude-marketplace.zip`; `claude plugin marketplace add <extracted-root>`, then `claude plugin install portable-resume@portable-resume --scope user` | `/resume-codex` |
| Codex (`codex`) | `.agents/skills` / `~/.agents/skills` | Extract `codex-marketplace.zip`; `codex plugin marketplace add <extracted-root>`, then `codex plugin add portable-resume@portable-resume` | `$resume-codex`; `/skills` lists |
| Cursor (`cursor`) | `.cursor/skills` / `~/.cursor/skills` | Extract `cursor-marketplace.zip`; copy/symlink `plugins/portable-resume` to `~/.cursor/plugins/local/portable-resume`, or use `cursor agent --plugin-dir <.../plugins/portable-resume>` for one run. A Git marketplace can be added with `cursor agent plugin marketplace add <git-url>`, but plugin installation remains `/add-plugin portable-resume`. | `/resume-codex` |
| OpenCode (`opencode`) | `.opencode/skills` / `~/.config/opencode/skills` | Direct Skill only. OpenCode plugins are executable JS/TS modules, not a packaging format for inert Skills. | Ask it to use `resume-codex` |
| Antigravity (`antigravity`) | `.agents/skills` / `~/.gemini/config/skills` | Extract `antigravity-plugin.zip`; `agy plugin validate <extracted-dir>`, then `agy plugin install <extracted-dir>`. Manual fallback: `.agents/plugins/portable-resume` or `~/.gemini/config/plugins/portable-resume`. | Mention `resume-codex`; `/skills` lists |
| Grok Build (`grok`) | `.grok/skills` / `~/.grok/skills` | Extract `grok-plugin.zip`; `grok plugin validate <extracted-dir>`, then, after review, `grok plugin install <extracted-dir> --trust` | `/resume-codex` |
| Qwen Code (`qwen`) | `.qwen/skills` / `~/.qwen/skills` | `qwen extensions install /path/portable-resume-<version>-qwen-extension.zip`; add `--scope project` for project scope | `/resume-codex`; `/skills` lists |
| Kimi Code CLI (`kimi`) | `.kimi-code/skills` / `$KIMI_CODE_HOME/skills` (default `~/.kimi-code/skills`) | Download and extract `kimi-plugin.zip`, then `/plugins install <extracted-dir>`; an exact release ZIP URL also works. Run `/plugins reload`, `/reload`, or start a new session. | `/skill:resume-codex` |

For direct archives, extract the archive contents into the selected Skill root. Each archive contains `resume-antigravity`, `resume-claude`, `resume-codex`, `resume-cursor`, `resume-grok`, `resume-kimi`, `resume-opencode`, and `resume-qwen`.

## Host-specific notes

- **Claude:** cloud/Cowork sessions do not automatically read local user Skills; use project or account-enabled Skills there.
- **Codex/Cursor/OpenCode/Kimi:** compatible `.agents/skills` roots may cause duplicate names. Keep one authoritative copy per host and inspect discovery when upgrading.
- **Qwen:** installing from the repository URL is not recommended for this monorepo because the extension manifest is a release asset, not at repository root. Use the exact Qwen extension ZIP.
- **Kimi:** the destination bundle targets current Kimi Code CLI. Legacy Python Kimi CLI session data is readable as a source, but its plugin format and `~/.kimi` data root are different.
- **All plugin routes:** plugins can have broader execution authority than Skills. Inspect the archive and verify its published SHA-256 first.

## Evidence boundary

Filesystem render/install/verify and installed `run_reader` behavior cover
**64/64** cells. Isolated local package installation also passed on current
Claude, Codex, Qwen, Grok, Antigravity, and Kimi CLIs/TUI; versions and archive
digests are recorded in [`host-ui-smoke.md`](host-ui-smoke.md). Cursor native
plugin loading, public marketplace publication, host picker/slash-command
activation, and natural-language routing remain **not-run**.
