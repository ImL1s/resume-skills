# Evidence summary (public)

## Deterministic bar

Commands (also run in CI on Ubuntu + macOS):

```bash
python3 scripts/check_secrets.py
python3 scripts/self_verify.py
```

Expected:

- unittest suite green
- `self-check --json` → `ok: true`, six adapters
- matrix → packaging cells **36**, live cells **0**
- fixture list/show handoff contains untrusted/stale markers
- secret/path gate **CLEAN**

## Packaging vs live

| Claim | Status |
|---|---|
| 36 skill packages render/install with strict frontmatter | **yes** (filesystem) |
| Host UI discovers skill + user activation + request→handoff inside host | **not-run** |
| CI Linux + macOS deterministic jobs | **yes** (GitHub Actions) |
| Formal dual-OS *release* marketing claim | **not claimed** without archived release evidence |

## Multi-seat review

During private development, multiple independent review seats ran. High-level outcomes were mixed APPROVE-WITH-FIXES and honesty/request-changes on live/Linux claims. Raw logs are **not** shipped. Do not invent a Codex APPROVE if that seat was quota-blocked.

## Doc audits (2026-07-20)

Multi-agent audits of documentation accuracy:

- `docs/audit-docs-vs-code.md`
- `docs/audit-host-docs-evidence.md`
- `docs/audit-security-docs.md`
