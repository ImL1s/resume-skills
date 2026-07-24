# Project status (2026-07-24)

## Current tree: 0.3.1 correction candidate

| Gate | Status |
|---|---|
| Source adapters | 8: Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi |
| Destination profiles | 8 |
| Packaging matrix | **64/64 pass locally** |
| Installed runner matrix | **64/64 pass locally** |
| Python test suite | **265 pass locally** |
| Wheel + sdist smoke | **pass outside checkout**, including verified quick-install |
| Native local plugin/extension install | **6/7 pass**; Cursor live load not-run |
| Host UI / picker activation | **not-run** |
| Public marketplace installation | **not-run** |
| CI | **pass**: Ubuntu + macOS × Python 3.11–3.14 |
| `v0.3.1` release workflow | **not-run remotely** |
| Published `v0.3.0` workflow | **pass**: annotated tag through GitHub Release and PyPI |
| Public PyPI installation | **pass for 0.3.0**: isolated install, 64-cell matrix, Qwen install/verify |
| Cursor full bubble graph | **not claimed** |

## Corrected in 0.3.1

- Removed mistakenly scoped destination-host network/documentation-tool
  guidance from generated Skills and public documentation.
- Clarified that Qwen/Kimi support covers offline context migration and
  destination installation only.
- Added regression tests that reject the removed product claim.

## Implemented in 0.3.0

- Qwen Code chat/archive reader and current/legacy Kimi session readers.
- Eight-host transactional installer with trusted verification, no-follow reads, rollback recovery, and cross-root compensation.
- Explicit installed-runtime allowlist and packaged schema.
- Deterministic eight direct Skill archives plus seven plugin/marketplace archives.
- CI gates, exact wheel/sdist smoke, annotated-tag release validation, checksums, artifact attestations, staged GitHub Release, and PyPI Trusted Publishing.
- Qwen and Kimi source adapters plus destination installation profiles; readers remain offline.

## Honest open gates

| Area | Status | Required evidence |
|---|---|---|
| Current local release gates | pass | four canonical commands, 2026-07-24 |
| `v0.3.1` dual-OS release | not-run | tagged Actions URL + immutable SHA + successful release jobs |
| `v0.3.1` PyPI publication | not-run | published project/version URL |
| Host activation | not-run | rows in `docs/host-ui-smoke.md` |
| Cursor native plugin load | not-run | accepted local package in current Cursor host |
| Public marketplace publication | not-run | public listing/install evidence |
| Cursor graph completeness | not claimed | upstream schema/recovery work beyond current best effort |

The latest published GitHub release remains
[`v0.3.0`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.0) until
the 0.3.1 release evidence is archived. PyPI publication is a
package-distribution claim, not evidence of any host's marketplace listing or
picker activation.

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
