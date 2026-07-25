# Host support matrix

Status date: **2026-07-24**. Installer truth lives in `src/portable_resume/install/catalog.py`; detailed commands are in [`install-hosts.md`](install-hosts.md).

## Evidence levels

- **`verified-filesystem`:** deterministic render, transactional install/verify, and installed-reader smoke.
- **partial live source:** adapters parse synthetic fixtures and bounded local store shapes; vendor formats may change.
- **host-native headless:** the current host CLI discovered/invoked an installed
  Skill and its exact reader command was verified.
- **public marketplace:** a current host installed from the published
  `ImL1s/portable-resume-marketplace` catalog.
- **`not-run`:** the named visual picker-selection path has no recorded evidence.

## Destination profiles

| Profile | Project root | User root | Primary activation | Package route | UI |
|---|---|---|---|---|---|
| `claude-v1` | `.claude/skills` | `~/.claude/skills` | `/resume-<source>` | direct + public Claude marketplace | headless/public install pass; Skill picker `not-run` |
| `codex-v1` | `.agents/skills` | `~/.agents/skills` | `$resume-<source>` | direct + public Codex marketplace | headless/public install pass; Skill picker `not-run` |
| `cursor-v1` | `.cursor/skills` | `~/.cursor/skills` | `/resume-<source>` | direct + public Cursor marketplace | headless/marketplace picker pass; Skill picker `not-run` |
| `opencode-v1` | `.opencode/skills` | `~/.config/opencode/skills` | model loads Skill by name | direct only | headless pass; picker `not-run` |
| `antigravity-v1` | `.agents/skills` | `~/.gemini/config/skills` | name mention | direct + plugin | headless pass; picker `not-run` |
| `grok-v1` | `.grok/skills` | `~/.grok/skills` | `/resume-<source>` | direct + public marketplace | headless/public install pass; picker `not-run` |
| `qwen-v1` | `.qwen/skills` | `~/.qwen/skills` | `/resume-<source>` | direct + public Qwen extension source | headless/public install pass; picker `not-run` |
| `kimi-code-v1` | `.kimi-code/skills` | `$KIMI_CODE_HOME/skills` | `/skill:resume-<source>` | direct + public Kimi catalog | headless/marketplace picker pass; Skill picker `not-run` |

Every profile packages all eight source readers. The portable Skill frontmatter contains only `name` and `description`; host invocation text is model context, not automatic process argv.

## Source adapters

Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, and current/legacy Kimi stores have fixture/parser coverage. Live store support is intentionally bounded and fail-closed. Cursor Desktop full bubble graph remains **not claimed**.

## Platform and release scope

| Layer | Current status |
|---|---|
| Local packaging matrix | 64/64 pass |
| Installed runner matrix | 64/64 pass |
| Native local plugin/extension installs | 7/7 pass with exact 0.3.2 release assets |
| Host-native headless Skill invocation | 8/8 pass |
| Public marketplace installation | 6/6 compatible hosts pass |
| Visual marketplace picker | Cursor and Kimi pass |
| Other visual Skill pickers | not-run |
| Vendor-curated directory listing | not submitted |
| CI definition | Ubuntu/macOS × Python 3.11–3.14 |
| Latest archived remote CI/release | `v0.3.2` pass: main CI and 14-job release run archived |
| Historical release proof | `v0.3.1`, `v0.3.0`, and `v0.2.3` archived separately |
| Windows | fixture/docs only; not a stated V1 release gate |

Official host references and alternate roots are linked from the machine-readable `hosts --json` output and [`install-hosts.md`](install-hosts.md).
