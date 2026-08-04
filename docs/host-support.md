# Host support matrix

Status date: **2026-08-01**. Installer truth lives in `src/portable_resume/install/catalog.py` and `src/portable_resume/registry.py`. Detailed commands are in [`install-hosts.md`](install-hosts.md).

<!-- generated:matrix-summary:begin (run scripts/render_docs.py --write) -->
This repository ships **17** enabled source Skills to **18** destination hosts (registry-derived; currently **17×18=306** cells).
<!-- generated:matrix-summary:end (run scripts/render_docs.py --write) -->

## Evidence levels

- **`verified-filesystem`:** deterministic render, transactional install/verify, and installed-reader smoke.
- **partial live source:** adapters parse synthetic fixtures and bounded local store shapes; vendor formats may change.
- **host-native headless:** the current host CLI discovered/invoked an installed
  Skill and its exact reader command was verified.
- **public marketplace:** a current host installed from the published
  `ImL1s/portable-resume-marketplace` catalog.
- **`not-run`:** the named visual picker-selection path has no recorded evidence.

## Destination profiles

<!-- generated:host-support-table:begin (run scripts/render_docs.py --write) -->
| Host | Profile | Project root | Global root |
|---|---|---|---|
| Antigravity / agy | `antigravity-v1` | `<workspace>/.agents/skills/<name>/SKILL.md` | `~/.gemini/config/skills/<name>/SKILL.md` |
| Claude Code | `claude-v1` | `<project>/.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` |
| Cline | `cline-v1` | `<project>/.cline/skills/<name>/SKILL.md` | `~/.cline/skills/<name>/SKILL.md` |
| Codex CLI / IDE | `codex-v1` | `<project>/.agents/skills/<name>/SKILL.md (CWD → repo root)` | `~/.agents/skills/<name>/SKILL.md` |
| Crush | `crush-v1` | `<project>/.crush/skills/<name>/SKILL.md` | `~/.config/crush/skills/<name>/SKILL.md` |
| Cursor Agent | `cursor-v1` | `<project>/.cursor/skills/<name>/SKILL.md` | `~/.cursor/skills/<name>/SKILL.md` |
| Gemini CLI | `gemini-v1` | `<project>/.gemini/skills/<name>/SKILL.md` | `$GEMINI_CLI_HOME/.gemini/skills or ~/.gemini/skills/<name>/SKILL.md` |
| GitHub Copilot CLI | `github-copilot-v1` | `<project>/.github/skills/<name>/SKILL.md` | `$COPILOT_HOME/skills/<name>/SKILL.md (default ~/.copilot/skills/)` |
| goose | `goose-v1` | `<project>/.goose/skills/<name>/SKILL.md` | `~/.config/goose/skills/<name>/SKILL.md` |
| Grok Build | `grok-v1` | `<repo>/.grok/skills/<name>/SKILL.md (CWD + repo root)` | `~/.grok/skills/<name>/SKILL.md` |
| Hermes Agent | `hermes-v1` | `<project>/.hermes/skills/<name>/SKILL.md` | `$HERMES_HOME/skills/<name>/SKILL.md (default ~/.hermes/skills/)` |
| Kilo CLI | `kilo-v1` | `<project>/.kilocode/skills/<name>/SKILL.md` | `$KILO_CONFIG_DIR/skills or ~/.config/kilo/skills/<name>/SKILL.md` |
| Kimi Code CLI | `kimi-code-v2` | `<project>/.kimi-code/skills/<name>/SKILL.md` | `$KIMI_CODE_HOME/skills/<name>/SKILL.md (default ~/.kimi-code/skills)` |
| OpenClaw | `openclaw-v1` | `<workspace>/skills/<name>/SKILL.md` | `~/.openclaw/skills/<name>/SKILL.md` |
| OpenCode | `opencode-v1` | `<project>/.opencode/skills/<name>/SKILL.md` | `~/.config/opencode/skills/<name>/SKILL.md` |
| OpenHands | `openhands-v1` | `<project>/.agents/skills/<name>/SKILL.md` | `~/.openhands/skills/<name>/SKILL.md` |
| Pi agent | `pi-v1` | `<project>/.pi/skills/<name>/SKILL.md` | `~/.pi/agent/skills/<name>/SKILL.md` |
| Qwen Code | `qwen-v1` | `<project>/.qwen/skills/<name>/SKILL.md` | `~/.qwen/skills/<name>/SKILL.md` |
<!-- generated:host-support-table:end (run scripts/render_docs.py --write) -->

Every profile packages every enabled source reader. The portable Skill frontmatter contains only `name` and `description`; host invocation text is model context, not automatic process argv.

## Source adapters

Enabled source adapters and their store families are listed in the root README. Live store support is intentionally bounded and fail-closed. Cursor Desktop full bubble graph remains **not claimed**. Native host UI / picker activation stays separately recorded in `host-ui-smoke.md`.

## Platform and release scope

| Layer | Current status |
|---|---|
| Local packaging matrix | 306/306 pass (currently 17×18, derived from registries) |
| Installed runner matrix | **Ubuntu hard gate 306/306** (17×18); **Windows** uses focused product-install smoke (`smoke_windows_product_install.py`, 3 hosts: claude/cursor/codex) — **not** claimed 306/306 on Windows |
| Native local plugin/extension installs | 7/7 pass with exact v0.3.2 release assets |
| Host-native headless Skill invocation | 8/8 pass from v0.3.2-era evidence; fresh through 0.4.1 and Pi not-run |
| Public marketplace installation | 6/6 compatible hosts pass on v0.3.2; fresh through 0.4.1 reinstall not-run |
| Visual marketplace picker | Cursor and Kimi pass on v0.3.2; fresh through 0.4.1 picker flow not-run |
| Other visual Skill pickers | not-run |
| Vendor-curated directory listing | not submitted |
| CI definition | Ubuntu/macOS × Python 3.11–3.14 + windows-latest / Python 3.12 (nt gates + focused product install smoke) |
| Latest archived remote CI/release | `v0.3.4` pass: release-commit CI and 14-job release run archived |
| Historical release proof | Earlier releases are archived separately in `evidence-summary.md` |
| Dual-OS product V1 (win+mac) | **Windows native + macOS** readers/CI verified; mutating install supported on both; WSL2/musl/BSD **not-run** (out of V1 scope) |
| Windows | **mutating install supported** (Phase 7 / #125): Win32 exclusive locking, reparse-safe relative mutations, parent-chain defenses, adversarial product-path evidence; `install`/`uninstall`/`recover` execute on real `nt` |

### Installer containment notes (Phase 0 / PR #49 + #29)

- **POSIX descriptor-relative commits (#31):** payload files are committed with `dir_fd` / `O_NOFOLLOW` under the skill root. The skill-root path itself may be a symlink (common dotfiles layouts); it is resolved once with `realpath`, then the final directory is opened no-follow. Intermediate payload parents never follow symlinks.
- **Windows platform gate (#29 Policy B — lifted by Phase 7 / #125):** `install`, `uninstall`, and `recover` now execute on real Windows (`os.name == "nt"` and `sys.platform.startswith("win")`). Spoofed `os.name == "nt"` on non-Windows hosts still fail-closed. Phases 1–6 established Win32 exclusive locking (`LockFileEx`), reparse-safe relative mutations, parent-chain reparse point defenses, and adversarial product-path evidence on `windows-latest`.
- **Recover (#20):** complete journals must not `rmtree` a `stage_dir` outside `.portable-resume/`.

Official host references and alternate roots are linked from the machine-readable `hosts --json` output and [`install-hosts.md`](install-hosts.md).
