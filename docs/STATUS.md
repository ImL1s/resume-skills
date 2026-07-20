# Project status (2026-07-20)

## What is done (deterministic V1 bar)

| Area | Status | Evidence |
|---|---|---|
| Six source adapters | **done** | `src/portable_resume/adapters/*`, `tests/adapters/*`, synthetic fixtures |
| Shared core (sanitize, snapshot, handoff, request-v1) | **done** | `src/portable_resume/*`, unit/security suites |
| 36-cell packaging matrix | **done (filesystem)** | `install-resume-skills matrix --json` → packaging 36, live 0 |
| Installer dry-run / install / verify / drift / uninstall | **done** | `tests/integration/*`, `scripts/self_verify.py` |
| Source CLI isolation + immutability | **done** | `tests/security/*` |
| macOS clean gate | **done** | full unittest green on darwin |
| Public-tree hygiene gate | **done** | `tests/security/test_public_tree_hygiene.py` |
| Multi-seat independent review | **partial** | external seats during private development; see `docs/evidence-summary.md` |

## What is not done (honest)

| Area | Status | Notes |
|---|---|---|
| Live host UI activation (AC-10 live 36) | **not-run** | Packaging + installed runtime handoff proven; host picker/NL activation not claimed |
| Linux peer clean runner (AC-18) | **not-run** | Requires a real Linux runner/container archive |
| Full PRD “V1 release complete” claim | **no** | Requires live smokes + dual-OS evidence |

## How to re-verify

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
```

## CI/CD

| Layer | Needed? | What we have |
|---|---|---|
| **CI** (test + secret scan on PR/push) | **Yes** for a public repo | `.github/workflows/ci.yml` — Ubuntu + macOS, unittest, `check_secrets.py`, self-check/matrix |
| **CD** (auto PyPI / GitHub Release) | **Not yet** | No package publish pipeline; stdlib source tree is enough until a release process is defined |

CI is the useful part now: it re-proves the deterministic bar and blocks accidental path/secret commits. Full CD can wait until you want tagged PyPI/GitHub Releases.

## Related docs

- `docs/evidence-summary.md` — public evidence notes
- `docs/host-support.md` — host roots and evidence levels
- `SECURITY.md` / `CONTRIBUTING.md` — security and contribution policy
