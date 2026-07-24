# Host support matrix

Status date: **2026-07-24**. Installer truth lives in `src/portable_resume/install/catalog.py`; detailed commands are in [`install-hosts.md`](install-hosts.md).

## Evidence levels

- **`verified-filesystem`:** deterministic render, transactional install/verify, and installed-reader smoke.
- **partial live source:** adapters parse synthetic fixtures and bounded local store shapes; vendor formats may change.
- **`not-run`:** no real host UI/picker activation evidence is recorded.

## Destination profiles

| Profile | Project root | User root | Primary activation | Package route | UI |
|---|---|---|---|---|---|
| `claude-v1` | `.claude/skills` | `~/.claude/skills` | `/resume-<source>` | direct + Claude marketplace | `not-run` |
| `codex-v1` | `.agents/skills` | `~/.agents/skills` | `$resume-<source>` | direct + Codex marketplace | `not-run` |
| `cursor-v1` | `.cursor/skills` | `~/.cursor/skills` | `/resume-<source>` | direct + Cursor marketplace | `not-run` |
| `opencode-v1` | `.opencode/skills` | `~/.config/opencode/skills` | model loads Skill by name | direct only | `not-run` |
| `antigravity-v1` | `.agents/skills` | `~/.gemini/config/skills` | name mention | direct + plugin | `not-run` |
| `grok-v1` | `.grok/skills` | `~/.grok/skills` | `/resume-<source>` | direct + plugin | `not-run` |
| `qwen-v1` | `.qwen/skills` | `~/.qwen/skills` | `/resume-<source>` | direct + Qwen extension | `not-run` |
| `kimi-code-v1` | `.kimi-code/skills` | `$KIMI_CODE_HOME/skills` | `/skill:resume-<source>` | direct + Kimi plugin | `not-run` |

Every profile packages all eight source readers. The portable Skill frontmatter contains only `name` and `description`; host invocation text is model context, not automatic process argv.

## Source adapters

Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, and current/legacy Kimi stores have fixture/parser coverage. Live store support is intentionally bounded and fail-closed. Cursor Desktop full bubble graph remains **not claimed**.

## Platform and release scope

| Layer | Current status |
|---|---|
| Local packaging matrix | 64/64 pass |
| Installed runner matrix | 64/64 pass |
| Native local plugin/extension installs | 6/7 pass; Cursor live load not-run |
| CI definition | Ubuntu/macOS × Python 3.11–3.14 |
| `v0.3.0` remote CI/release | not-run until a tag is pushed |
| Historical release proof | `v0.2.3` archived separately |
| Windows | fixture/docs only; not a stated V1 release gate |

Official host references and alternate roots are linked from the machine-readable `hosts --json` output and [`install-hosts.md`](install-hosts.md).
