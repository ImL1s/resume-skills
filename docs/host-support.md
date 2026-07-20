# Host support matrix

Status: packaging roots match `src/portable_resume/install/catalog.py` (2026-07-20).  
Activation text below is **documented / planning-era guidance**, not a live host smoke. Re-verify against current host docs when upgrading.

Evidence levels:

| Level | Meaning |
|---|---|
| `verified-filesystem` | Roots/frontmatter/render/install/verify proven by deterministic harness |
| `verified-live` | Installed host version actually discovered the skill and completed request→handoff in the host UI |
| `partial` | Some providers or scopes work; gaps recorded |
| `unsupported` | Not claimed |
| `not-run` | Live smoke not executed |

## Profiles

| Profile | Project root (installer default) | Global root (installer default) | Notes / alternate roots | Activation (documented guidance) | Packaging | Live UI |
|---|---|---|---|---|---|---|
| `claude-v1` | `<project>/.claude/skills` | `~/.claude/skills` | — | `/resume-<source> ...`; `$ARGUMENTS` is prompt substitution only | `verified-filesystem` (install/verify; installed `run_reader` handoff against fixtures) | `not-run` |
| `codex-v1` | `<project>/.agents/skills` | `~/.agents/skills` | Admin `/etc/codex/skills` only if chosen explicitly; some setups also mention `.codex/skills` (not default here) | `$resume-<source>` + labeled text; no skill argv API claimed | `verified-filesystem` (use distinct `--root` if sharing with antigravity) | `not-run` |
| `cursor-v1` | `<project>/.cursor/skills` | `~/.cursor/skills` | Cursor also documents `.agents/skills` compatibility roots; this installer default is the native `.cursor/skills` path | explicit `/resume-<source>` + labels; no promised tail→argv | `verified-filesystem` | `not-run` |
| `opencode-v1` | `<project>/.opencode/skills` | `~/.config/opencode/skills` | **Caveat:** native OpenCode skill discovery has varied by version; confirm your install actually loads this root before claiming host support | model/native skill selection + labels; custom commands are a separate surface | `verified-filesystem` (directory packaging only) | `not-run` |
| `antigravity-v1` | `<project>/.agents/skills` | `~/.gemini/config/skills` | Multi-flavor installs may differ; freeze is for current documented agy roots | name mention; `/skills` lists skills — do not invent slash argv grammar | `verified-filesystem` (distinct root when conflicting with codex) | `not-run` |
| `grok-v1` | `<project>/.grok/skills` | `~/.grok/skills` | May also scan `.agents`/compat roots depending on version | `/resume-<source> ...`; `$ARGUMENTS` prompt-only (source-verified in planning notes, not a live claim) | `verified-filesystem` | `not-run` |

Portable frontmatter for all profiles: only `name` + `description` in the core skill body.

## Shared-root note

Codex project/global `.agents/skills` and Antigravity project `.agents/skills` can resolve to the same path. Host-specific skill bodies are not byte-identical, so the installer returns `E_INSTALL_CONFLICT` unless an explicit distinct root is chosen or renders are made identical.

## Official evidence

Public product documentation for Agent Skills and each host’s skills pages informed the roots/activation guidance. Local planning extracts are **not shipped** with this repository. Re-check upstream docs when host versions change.

## Platform runners

| OS | Deterministic gate | Notes |
|---|---|---|
| macOS (darwin) | Local + CI (`macos-latest`) | Primary development host |
| Linux | CI (`ubuntu-latest`) runs the same unittest/self-check/matrix gates | CI green ≠ archived dual-OS **release** claim if you need offline artifacts |
| Windows | Fixture/docs only | Not a V1 release blocker for this project’s stated scope |

Live interactive host UI walks remain `not-run`.

## Related

- `docs/STATUS.md` — done / not-done gates  
- `docs/evidence-summary.md` — public evidence notes  
