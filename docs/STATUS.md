# Project status (2026-07-21)

## Maturity snapshot

| Gate | Status |
|---|---|
| Version | **0.2.1** experimental |
| Packaging cells | **36/36** |
| Source live list/show | **partial** (all six sources) |
| Installed skill runner smoke | **36/36** (`scripts/smoke_installed_matrix.py`) |
| Host UI NL / picker activation | **not-run** |
| Dual-OS CI | **green** (Ubuntu + macOS × Python 3.11/3.12) |
| Dual-OS **release claim** | **claimed** for SHA with archived Actions run (see below) |
| Cursor full bubble graph | **not claimed** (multi-turn composerData best-effort) |

## What is done (deterministic bar)

| Area | Status | Evidence |
|---|---|---|
| Six source adapters | **done** | `src/portable_resume/adapters/*`, fixtures, unittests |
| Shared core | **done** | sanitize, snapshot, handoff, request-v1, select |
| 36-cell packaging matrix | **done** | `install-resume-skills matrix --json` |
| Source live list/show (six) | **partial live** | STATUS parity table + CHANGELOG 0.2.0/0.2.1 |
| Installer transaction | **done** | path containment, orphan journal, no-follow hash/backup |
| Installed runner 36-cell smoke | **done** | `scripts/smoke_installed_matrix.py` → 36/36 |
| Source CLI isolation | **done** | `tests/security/*` |
| Public-tree secret gate | **done** | `scripts/check_secrets.py` |
| CI dual-OS + dual-Python | **done** | `.github/workflows/ci.yml` |
| Improve-deep hardening (001–025) | **done** | `plans/README.md`, commits `690b7d5`…`2245516`+ |

## What is not done (honest)

| Area | Status | Notes |
|---|---|---|
| Live host UI NL activation (36 cells) | **not-run** | Installed `run_reader` smoke ≠ host slash-command / picker activation inside Claude/Cursor/etc. |
| Cursor full bubble graph | **not claimed** | Desktop may recover multi-turn text from `composerData`; parent/bubble graph incomplete (`W_MISSING_BLOB`) |
| PyPI CD / auto-publish | **not yet** | `pyproject.toml` exists; no auto-release pipeline |
| Full PRD “V1 complete” | **no** | Needs host UI NL evidence for primary hosts |

## Dual-OS release claim

| Field | Value |
|---|---|
| Status | **claimed** (CI archive) |
| Reference SHA (pre-0.2.1 harden tip) | `2245516` |
| Actions run | https://github.com/ImL1s/resume-skills/actions/runs/29763469462 |
| Jobs green | `ubuntu-latest` py3.11 + py3.12; `macos-latest` py3.11 + py3.12 |
| Local gates | `self_verify` + `check_secrets` on release machine |
| Policy | See `docs/release-claim.md` — re-claim each tag |

After `v0.2.1` is tagged, attach that tag’s green Actions URL in `docs/evidence-summary.md` if different from the SHA above.

## Source live parity

| Area | Status | Notes |
|---|---|---|
| Skill UX (show/list argv) | **done** | Grok-style; request-v1 optional |
| Claude | **partial live** | cwd-slug, attachment parent bridge, within_min≤0 |
| Codex | **partial live** | SQLite superset, large-DB query-only, cwd-scoped list |
| Grok | **partial live** | mtime-ranked discovery, coalesce cap, skip co-located files |
| OpenCode | **partial live** | multi-GiB query-only live SQLite |
| Antigravity | **partial live** | no-index + index mtime rank, USER_INPUT/PLANNER_RESPONSE |
| Cursor CLI | **partial live** | store.db + meta stable-read, blob ORDER BY, latest by updatedAt |
| Cursor Desktop | **partial live** | composerHeaders list; composerData multi-turn best-effort |
| Host UI NL activation | **not-run** | unchanged product gate |

## How to re-verify

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

## CI/CD

| Layer | Status |
|---|---|
| **CI** | Ubuntu + macOS; Python 3.11 + 3.12 |
| **CD** | No PyPI auto-release |

## Related docs

- `docs/evidence-summary.md` — public verification + dual-OS archive links
- `docs/host-ui-smoke.md` — NL host activation protocol (still open)
- `docs/release-claim.md` — dual-OS claim checklist
- `docs/install-hosts.md` — per-host install paths
- `docs/source-formats.md` — format IDs + provenance anchors
- `docs/research/cursor-bubble-schema.md` — bubble graph residual
- `plans/README.md` — improve-deep plan index
- `AGENTS.md` — agent contributor rules
- `SECURITY.md` / `CONTRIBUTING.md`
