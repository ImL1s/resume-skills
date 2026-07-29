# Host support matrix

Status date: **2026-07-27**. Installer truth lives in `src/portable_resume/install/catalog.py` and `src/portable_resume/registry.py`; matrix dimensions are **derived from registries** (currently **9×9=81** cells). Detailed commands are in [`install-hosts.md`](install-hosts.md).

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
| `claude-v1` | `.claude/skills` | `~/.claude/skills` | `/resume-<source>` | direct + public Claude marketplace | v0.3.2-era headless/public install pass; fresh v0.3.4 reinstall `not-run`; Skill picker `not-run` |
| `codex-v1` | `.agents/skills` | `~/.agents/skills` | `$resume-<source>` | direct + public Codex marketplace | v0.3.2-era headless/public install pass; fresh v0.3.4 reinstall `not-run`; Skill picker `not-run` |
| `cursor-v1` | `.cursor/skills` | `~/.cursor/skills` | `/resume-<source>` | direct + public Cursor marketplace | v0.3.2-era headless/marketplace picker pass; fresh v0.3.4 reinstall/picker `not-run`; Skill picker `not-run` |
| `opencode-v1` | `.opencode/skills` | `~/.config/opencode/skills` | model loads Skill by name | direct only | v0.3.2-era headless pass; picker `not-run` |
| `antigravity-v1` | `.agents/skills` | `~/.gemini/config/skills` | name mention | direct + plugin | v0.3.2-era headless pass; picker `not-run` |
| `grok-v1` | `.grok/skills` | `~/.grok/skills` | `/resume-<source>` | direct + public marketplace | v0.3.2-era headless/public install pass; fresh v0.3.4 reinstall `not-run`; picker `not-run` |
| `qwen-v1` | `.qwen/skills` | `~/.qwen/skills` | `/resume-<source>` | direct + public Qwen extension source | v0.3.2-era headless/public install pass; fresh v0.3.4 reinstall `not-run`; picker `not-run` |
| `kimi-code-v1` | `.kimi-code/skills` | `$KIMI_CODE_HOME/skills` | `/skill:resume-<source>` | direct + public Kimi catalog | v0.3.2-era headless/marketplace picker pass; fresh v0.3.4 reinstall/picker `not-run`; Skill picker `not-run` |
| `pi-v1` | `.pi/skills` | `~/.pi/agent/skills` | `/skill:resume-<source>` | direct only | filesystem install pass; native picker `not-run` |

Every profile packages all nine source readers. The portable Skill frontmatter contains only `name` and `description`; host invocation text is model context, not automatic process argv.

## Source adapters

Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi, and **Pi** have fixture/parser coverage. Live store support is intentionally bounded and fail-closed. Cursor Desktop full bubble graph remains **not claimed**. Pi native host UI / picker activation remains **not-run** (filesystem install is supported).

## Platform and release scope

| Layer | Current status |
|---|---|
| Local packaging matrix | 81/81 pass (currently 9×9, derived from registries) |
| Installed runner matrix | 81/81 pass (currently 9×9, derived from registries) |
| Native local plugin/extension installs | 7/7 pass with exact v0.3.2 release assets |
| Host-native headless Skill invocation | 8/8 pass from v0.3.2-era evidence; Pi not-run |
| Public marketplace installation | 6/6 compatible hosts pass on v0.3.2; fresh v0.3.4 reinstall not-run |
| Visual marketplace picker | Cursor and Kimi pass on v0.3.2; fresh v0.3.4 picker flow not-run |
| Other visual Skill pickers | not-run |
| Vendor-curated directory listing | not submitted |
| CI definition | Ubuntu/macOS × Python 3.11–3.14 |
| Latest archived remote CI/release | `v0.3.4` pass: release-commit CI and 14-job release run archived |
| Historical release proof | Earlier releases are archived separately in `evidence-summary.md` |
| Windows | **mutating installer unsupported** (`E_INSTALL_UNSUPPORTED_PLATFORM`); reader/matrix/dry-run/verify may remain where individually safe; not a V1 release gate |

### Installer containment notes (Phase 0 / PR #49 + #29)

- **POSIX descriptor-relative commits (#31):** payload files are committed with `dir_fd` / `O_NOFOLLOW` under the skill root. The skill-root path itself may be a symlink (common dotfiles layouts); it is resolved once with `realpath`, then the final directory is opened no-follow. Intermediate payload parents never follow symlinks.
- **Windows platform gate (#29 Policy B):** `install` (non-dry-run), `uninstall` (non-dry-run), and `recover` (when a journal exists) fail closed with `E_INSTALL_UNSUPPORTED_PLATFORM` **before** creating support directories or claiming a root lock. Silent unlocked mutation is not permitted. Exclusive Windows locking (Policy A) is not claimed.
- **Recover (#20):** complete journals must not `rmtree` a `stage_dir` outside `.portable-resume/`.

Official host references and alternate roots are linked from the machine-readable `hosts --json` output and [`install-hosts.md`](install-hosts.md).
