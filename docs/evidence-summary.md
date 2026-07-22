# Evidence summary (public)

## Deterministic bar

Commands (also run in CI on Ubuntu + macOS):

```bash
python3 scripts/check_secrets.py
python3 scripts/self_verify.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Expected:

- unittest suite green
- `self-check --json` → `ok: true`, six adapters
- matrix → packaging cells **36**, host-UI live cells **0**
- installed-runner smoke → **36/36**
- fixture list/show handoff contains untrusted/stale markers
- secret/path gate **CLEAN**

## Packaging vs live vs installed-runner

| Claim | Status |
|---|---|
| 36 skill packages render/install with strict frontmatter | **yes** (filesystem) |
| Installed skill `run_reader` list/show against fixtures (6×6) | **yes** (`smoke_installed_matrix.py`) |
| Host UI discovers skill + NL/picker activation inside host | **not-run** |
| CI Linux + macOS × Python 3.11/3.12 | **yes** (GitHub Actions) |
| Dual-OS release claim (archived green run) | **claimed** — see below |
| Cursor full bubble graph | **not claimed** |

## Dual-OS release claim archive

| Field | Value |
|---|---|
| Claimed | **yes** (2026-07-22) |
| Tag | `v0.2.3` → `5ff9eba503e28971e5044015cd0666c2807a3d89` |
| Workflow | `ci` |
| Run URL (tag tip) | https://github.com/ImL1s/resume-skills/actions/runs/29890453185 |
| Prior release claim | `v0.2.2` / https://github.com/ImL1s/resume-skills/actions/runs/29886518842 |
| Jobs | ubuntu py3.11, ubuntu py3.12, macos py3.11, macos py3.12 — all **success** |
| Local | `self_verify` + `check_secrets` + 211 unittests + real large-session structural E2E + `smoke_installed_matrix` PASS |
| Sign-off | Maintainer: dual-OS CI archive for v0.2.3; re-claim on each release tag |

## Improve-deep hardening (0.2.1)

Shipped after v0.2.0 (see `plans/README.md` and git history `690b7d5`…tip):

- Install path containment; orphan journal; no-follow hash/backup; runtime whitelist (no `install/` in skill runtime)
- Live latest ranking (Grok/AGY/Cursor CLI); Codex large-DB query-only; Cursor meta stable-read + blob order
- Secret gate + redaction expansion; pyproject + CI 3.11; AGENTS.md; module split (`cursor_live`, `codex_sqlite`)

## Multi-seat review

Independent review seats ran during development. High-level outcomes mixed APPROVE-WITH-FIXES and honesty gates. Raw review logs are not shipped.

## Doc audits (2026-07-20)

Point-in-time audits (may be stale relative to 0.2.1):

- `docs/audit-docs-vs-code.md`
- `docs/audit-host-docs-evidence.md`
- `docs/audit-security-docs.md`
