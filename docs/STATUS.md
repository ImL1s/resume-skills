# Project status (2026-07-21)

## What is done (deterministic V1 bar)

| Area | Status | Evidence |
|---|---|---|
| Six source adapters | **done** | `src/portable_resume/adapters/*`, `tests/adapters/*`, synthetic fixtures |
| Shared core (sanitize, snapshot, handoff, request-v1) | **done** | `src/portable_resume/*`, unit/security suites |
| 36-cell packaging matrix | **done (filesystem)** | `matrix --json` → packaging 36; host UI live still **0** (see below) |
| Source live list/show (all six) | **partial live** | Claude/Codex/Grok/OpenCode/Antigravity/Cursor — see parity table |
| Installer dry-run / install / verify / drift / uninstall | **done** | integration tests + `scripts/self_verify.py` |
| Source CLI isolation + immutability | **done** | `tests/security/*` |
| Public-tree hygiene + secret gate | **done** | `test_public_tree_hygiene`, `scripts/check_secrets.py` |
| CI deterministic gates | **done** | `.github/workflows/ci.yml` on **ubuntu-latest** and **macos-latest** (3.11+3.12) |
| Multi-seat independent review | **partial** | summary only in `docs/evidence-summary.md` |

## What is not done (honest)

| Area | Status | Notes |
|---|---|---|
| Live host UI activation (36 cells) | **not-run** | Packaging + installed `run_reader` fixture handoff ≠ host picker/NL activation |
| Dual-OS **release claim** archive | **not claimed** | CI already runs Linux+macOS jobs; a formal dual-OS *release* still needs intentional archived green runs if you want that marketing claim |
| Full PRD “V1 release complete” | **no** | Needs live UI evidence + explicit release process |

## How to re-verify

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
```

## CI/CD

| Layer | Needed? | Status |
|---|---|---|
| **CI** | Yes for public repo | Active: Ubuntu + macOS, unittest, secrets, self-check, matrix, self_verify |
| **CD** | Not yet | No PyPI / auto-release pipeline |

## Grok resume-session parity (2026-07-20)

| Area | Status | Notes |
|---|---|---|
| Skill UX (show/list argv primary) | **done** | request-v1 optional; catalog/docs aligned |
| Claude live list/show | **partial live** | cwd-slug + attachment parent bridge on real stores |
| Codex live list | **partial live** | SQLite column superset + cwd-scoped query + within-min≤0 |
| Grok source live list | **partial live** | skip co-located files; cwd-prefer; oversized updates → summary-only list |
| OpenCode live list | **partial live** | large DB via query-only live SQLite; cwd-scoped LIMIT |
| Antigravity live list/show | **partial live** | no-index brain scan + USER_INPUT/PLANNER_RESPONSE step stream |
| Cursor CLI live list/show | **partial live** | `chats/*/store.db` + meta.json blobs as turns |
| Cursor Desktop live list/show | **partial live** | `composerHeaders` list; show best-effort composerData text only |
| Live host UI activation | **not-run** | unchanged |

Plans: `docs/superpowers/plans/2026-07-20-grok-resume-parity.md`, `docs/superpowers/plans/2026-07-20-remaining-sources-live.md`

## Related docs

- `docs/evidence-summary.md`
- `docs/install-hosts.md` — per-host install methods (canonical)
- `docs/host-support.md`
- `docs/source-formats.md`
- `docs/audit-docs-vs-code.md` / `docs/audit-host-docs-evidence.md` / `docs/audit-security-docs.md` (multi-agent doc audits)
- `SECURITY.md` / `CONTRIBUTING.md`
