# Host support matrix

Status: packaging roots and activation contracts frozen from planning evidence dated 2026-07-20.  
Evidence levels used here:

| Level | Meaning |
|---|---|
| `verified-filesystem` | Roots/frontmatter/render/install/verify proven by deterministic harness |
| `verified-live` | Installed host version actually discovered the skill and ran request→handoff |
| `partial` | Some providers or scopes work; gaps recorded |
| `unsupported` | Not claimed |
| `not-run` | Live smoke not executed in this environment |

## Profiles

| Profile | Project root | Global root | Portable frontmatter | Activation (documented) | Packaging evidence | Live smoke |
|---|---|---|---|---|---|---|
| `claude-v1` | `<project>/.claude/skills` | `~/.claude/skills` | `name`+`description` only | `/resume-<source> ...`; `$ARGUMENTS` prompt-only | `verified-filesystem` (2026-07-20 isolated install+verify; installed runtime handoff OK) | `not-run` (host UI picker/NL activation) |
| `codex-v1` | `<project>/.agents/skills` | `~/.agents/skills` | `name`+`description` only | `$resume-<source>` + labels; no implicit argv | `verified-filesystem` (isolated install+verify; explicit root when shared with antigravity) | `not-run` |
| `cursor-v1` | `<project>/.cursor/skills` | `~/.cursor/skills` | `name`+`description` only | explicit `/resume-<source>` + labels | `verified-filesystem` (isolated install+verify) | `not-run` |
| `opencode-v1` | `<project>/.opencode/skills` | `~/.config/opencode/skills` | `name`+`description` only | model/native skill selection + labels | `verified-filesystem` (isolated install+verify) | `not-run` |
| `antigravity-v1` | `<project>/.agents/skills` | `~/.gemini/config/skills` | `name`+`description` only | name mention; `/skills` lists only | `verified-filesystem` (isolated install+verify on distinct root) | `not-run` |
| `grok-v1` | `<project>/.grok/skills` | `~/.grok/skills` | `name`+`description` only | `/resume-<source> ...`; `$ARGUMENTS` prompt-only | `verified-filesystem` (isolated install+verify) | `not-run` |

Evidence log: `.omc/research/live-smoke-report.md` (36/36 cells materialize; binaries version-probed: claude/codex/opencode/agy/grok/cursor-agent present).

## Shared-root note

Codex project/global `.agents/skills` and Antigravity project `.agents/skills` can resolve to the same path. Host-specific skill bodies are not byte-identical, so the installer correctly returns `E_INSTALL_CONFLICT` unless an explicit distinct root is chosen or renders are made identical.

## Official evidence pointers

See `.omx/context/host-profile-official-evidence-20260720.md` for URLs, versions, and the frozen universal request-file boundary.

## Platform runners

| OS | Deterministic compile/unit/security/integration/e2e/install gate | Notes |
|---|---|---|
| macOS (darwin) | run when `platform.system()==Darwin` or `PORTABLE_RESUME_EXPECT_OS=darwin` | primary development host for this repository |
| Linux | run only on a Linux runner/container with `PORTABLE_RESUME_EXPECT_OS=linux` | **not claimed** unless that runner’s artifacts are archived |
| Windows | fixture/docs only | not a V1 release blocker per AC-19 |

Live interactive host UI walks remain `not-run` in this environment.

## Related status

- Project status and open gates: `docs/STATUS.md`
- Multi-seat review synthesis: `.omc/research/dual-review-synthesis.md`
- Last packaging smoke log: `.omc/research/live-smoke-report.md`
- Linux gate log: `.omc/research/linux-gate-report.md`
