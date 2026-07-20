# Project status (2026-07-20)

## What is done (deterministic V1 bar)

| Area | Status | Evidence |
|---|---|---|
| Six source adapters | **done** | `src/portable_resume/adapters/*`, `tests/adapters/*`, synthetic fixtures |
| Shared core (sanitize, snapshot, handoff, request-v1) | **done** | `src/portable_resume/*`, unit/security suites |
| 36-cell packaging matrix | **done (filesystem)** | `install-resume-skills matrix --json` → `packaging_cells_supported: 36`, `live_cells_supported: 0` |
| Installer dry-run / install / verify / drift / uninstall | **done** | `tests/integration/*`, self-verify script |
| Source CLI isolation + immutability | **done** | `tests/security/*` |
| macOS clean gate | **done** | full unittest green on darwin |
| Multi-seat independent review | **partial** | Fable / Grok / agy + subagents; Codex seat **BLOCKED** (usage limit) |
| First git commit | **done** | `main` |

## What is not done (honest)

| Area | Status | Notes |
|---|---|---|
| Live host UI activation (AC-10 live 36) | **not-run** | Packaging + installed runtime handoff proven; host picker/NL activation not claimed |
| Linux peer clean runner (AC-18) | **not-run** | Docker daemon unavailable on last attempt |
| Codex dual-review APPROVE | **blocked** | Quota; re-run `.omc/research/_run_codex_only.sh` after reset |
| Full PRD “V1 release complete” claim | **no** | Requires live smokes + dual-OS + remaining review seats |

## How to re-verify

```bash
# full suite
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -q

# shipped entry points
PYTHONPATH=src python3 scripts/portable-resume self-check --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json

# one-shot self verify (prints PASS/FAIL)
python3 .omc/research/_self_verify_now.py
```

## Review artifacts

Under `.omc/research/`:

- `dual-review-synthesis.md` — combined multi-seat verdict
- `dual-review-fable.md`, `dual-review-grok.md`, `dual-review-agy.md`
- `dual-review-codex.md` — BLOCKED (quota)
- `live-smoke-report.md`, `linux-gate-report.md`

## Test count (last self-verify)

- `Ran 146 tests` — **OK**
