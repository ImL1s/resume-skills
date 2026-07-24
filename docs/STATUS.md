# Project status (2026-07-24)

## Published release: 0.3.0

| Gate | Status |
|---|---|
| Source adapters | 8: Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi |
| Destination profiles | 8 |
| Packaging matrix | **64/64 pass locally** |
| Installed runner matrix | **64/64 pass locally** |
| Python test suite | **264 pass locally** |
| Wheel + sdist smoke | **pass outside checkout**, including verified quick-install |
| Native local plugin/extension install | **6/7 pass**; Cursor live load not-run |
| Host UI / picker activation | **not-run** |
| Public marketplace installation | **not-run** |
| CI | **pass**: Ubuntu + macOS × Python 3.11–3.14 |
| `v0.3.0` release workflow | **pass**: annotated tag through GitHub Release and PyPI |
| Public PyPI installation | **pass**: isolated install, 64-cell matrix, Qwen install/verify |
| Cursor full bubble graph | **not claimed** |

## Implemented in 0.3.0

- Qwen Code chat/archive reader and current/legacy Kimi session readers.
- Eight-host transactional installer with trusted verification, no-follow reads, rollback recovery, and cross-root compensation.
- Explicit installed-runtime allowlist and packaged schema.
- Deterministic eight direct Skill archives plus seven plugin/marketplace archives.
- CI gates, exact wheel/sdist smoke, annotated-tag release validation, checksums, artifact attestations, staged GitHub Release, and PyPI Trusted Publishing.
- Optional host-side web/Context7 guidance; the reader remains offline.

## Honest open gates

| Area | Status | Required evidence |
|---|---|---|
| Current local release gates | pass | four canonical commands, 2026-07-24 |
| `v0.3.0` dual-OS release | **pass** | [release run 30084711240](https://github.com/ImL1s/resume-skills/actions/runs/30084711240), SHA `78c2acd0f9841d90d87f85eff151b842a80dc011` |
| PyPI publication | **pass** | [portable-resume 0.3.0](https://pypi.org/project/portable-resume/0.3.0/) via Trusted Publishing |
| Host activation | not-run | rows in `docs/host-ui-smoke.md` |
| Cursor native plugin load | not-run | accepted local package in current Cursor host |
| Public marketplace publication | not-run | public listing/install evidence |
| Cursor graph completeness | not claimed | upstream schema/recovery work beyond current best effort |

The published GitHub release is
[`v0.3.0`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.0).
PyPI publication is a package-distribution claim, not evidence of any host's
marketplace listing or picker activation.

## Historical release evidence

`v0.2.3` remains an archived historical claim only: SHA `5ff9eba503e28971e5044015cd0666c2807a3d89`, [Actions run 29890453185](https://github.com/ImL1s/resume-skills/actions/runs/29890453185), Ubuntu/macOS × Python 3.11/3.12. It does not prove the 0.3.0 changes.

## Required local verification

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

See [`evidence-summary.md`](evidence-summary.md), [`release-claim.md`](release-claim.md), and [`host-ui-smoke.md`](host-ui-smoke.md) for proof boundaries.
