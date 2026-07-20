# Project status (2026-07-20)

## What is done (deterministic V1 bar)

| Area | Status | Evidence |
|---|---|---|
| Six source adapters | **done** | `src/portable_resume/adapters/*`, `tests/adapters/*`, synthetic fixtures |
| Shared core (sanitize, snapshot, handoff, request-v1) | **done** | `src/portable_resume/*`, unit/security suites |
| 36-cell packaging matrix | **done (filesystem)** | `matrix --json` → packaging 36, **live 0** |
| Installer dry-run / install / verify / drift / uninstall | **done** | integration tests + `scripts/self_verify.py` |
| Source CLI isolation + immutability | **done** | `tests/security/*` |
| Public-tree hygiene + secret gate | **done** | `test_public_tree_hygiene`, `scripts/check_secrets.py` |
| CI deterministic gates | **done** | `.github/workflows/ci.yml` on **ubuntu-latest** and **macos-latest** |
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

## Related docs

- `docs/evidence-summary.md`
- `docs/install-hosts.md` — per-host install methods (canonical)
- `docs/host-support.md`
- `docs/source-formats.md`
- `docs/audit-docs-vs-code.md` / `docs/audit-host-docs-evidence.md` / `docs/audit-security-docs.md` (multi-agent doc audits)
- `SECURITY.md` / `CONTRIBUTING.md`
