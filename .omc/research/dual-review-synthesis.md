# Multi-seat dual-review synthesis — portable-resume-skills V1

Date: 2026-07-20  
Rule: **strictest wins**

## Seats

| Seat | Path | Verdict |
|---|---|---|
| Codex CLI (`gpt-5.6-sol` max) | `dual-review-codex.md` | **BLOCKED** (usage limit until 2026-07-25) |
| Claude Fable 5 xhigh | `dual-review-fable.md` | **APPROVE WITH MINOR FIXES** |
| Grok CLI | `dual-review-grok.md` | **APPROVE WITH MINOR FIXES** |
| Antigravity (`agy`) | `dual-review-agy.md` | **APPROVE WITH MINOR FIXES** (pre-fix u018 note; suite now green) |
| Subagent security | `dual-review-subagent-security.md` | **APPROVE WITH MINOR FIXES** |
| Subagent architect critic | `dual-review-subagent-architect.md` | **REQUEST CHANGES** (claim honesty + journal) |
| Subagent code-reviewer | `dual-review-subagent-code.md` | **REQUEST CHANGES** (budget + test theater) |

## Combined verdict

### For deterministic / ship-to-use bar
**APPROVE WITH MINOR FIXES** (Fable + Grok + security after fixes applied this session)

### For full PRD V1 **release claim** (AC-10 live 36 + AC-18 dual-OS)
**REQUEST CHANGES / NOT READY** — evidence gates still open (all seats agree):

1. Live host UI activation smokes still **not-run** (packaging 36/36 + installed runtime handoff proven)
2. Linux peer clean runner **not run** (Docker daemon unavailable after start attempt)
3. Codex independent seat **BLOCKED** by quota (cannot replace with self-approval)

## Critical (must fix before full release claim)

| Item | Source | Status after this session |
|---|---|---|
| AC-10 live 36 cells | Architect / Grok / docs | Still **not-run** for UI activation |
| AC-18 Linux gate | Architect / linux-gate-report | **NOT RUN** (docker daemon down) |
| Codex dual-review seat | Codex log | **BLOCKED** usage limit |

## Important fixed this session (orchestrator)

| Issue | Fix |
|---|---|
| Installer plan/execute TOCTOU | Re-classify ownership under lock before each replace |
| Journal path escape `..` | `_safe_rel_path` + sandboxed recover |
| `expected-source` soft bind | Strip overrides; hard-force skill source in `run_reader` template |
| ReadBudget mis-cap on raw I/O | Separate `source_read_bytes` from `normalized_content_bytes` |
| Hostile handoff soft assert | Require recovered imperatives on `>` lines |
| Installed runner e2e cwd mismatch | Align cwd + assert successful handoff; prove override ignored |
| Claude null-title drop | Allow list without inventing title |
| Journal durability | fsync file + best-effort dir fsync |

## Residual Important / Minor (not all closed)

- Manifest atomic replace + full PRD fsync matrix (partial: journal fsync only)
- Fixture `expected_code` not always oracle-driven (test theater residual)
- Shared `.agents/skills` host divergence still requires distinct roots
- Secret redaction best-effort

## Live packaging smoke (this session)

See `live-smoke-report.md`: **36/36** skills materialize under isolated roots; installed `run_reader` handoff exit 0 with untrusted marker. Host UI activation still **not-run**.

## Linux gate (this session)

See `linux-gate-report.md`: Docker Desktop start attempted; daemon still unavailable → **do not claim AC-18**.

## Decision

- **May commit / continue local use** of deterministic package after green suite (146 tests).
- **Must not** advertise “PRD V1 fully complete / 36 live cells / dual-OS green / dual-review Codex APPROVE” until remaining evidence seats close.
- Independent multi-agent review: **partially satisfied** via Fable+Grok+agy+3 subagents; **Codex seat blocked by quota** (honest).
