# Project status (2026-07-24)

## Current release: 0.3.2

| Gate | Status |
|---|---|
| Source adapters | 8: Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi |
| Destination profiles | 8 |
| Packaging matrix | **64/64 pass locally** |
| Installed runner matrix | **64/64 pass locally** |
| Python test suite | **267 pass locally** |
| Wheel + sdist smoke | **pass outside checkout**, including public PyPI installation |
| Native local plugin/extension install | **7/7 pass** with exact 0.3.2 release assets |
| Host-native headless Skill activation | **8/8 pass** |
| Visual host picker activation | **not-run** |
| Public marketplace installation | **not-run** |
| CI | **pass**: [Ubuntu + macOS × Python 3.11–3.14](https://github.com/ImL1s/resume-skills/actions/runs/30093652499) |
| `v0.3.2` release workflow | **pass**: [14 jobs through GitHub Release and PyPI](https://github.com/ImL1s/resume-skills/actions/runs/30093776529) |
| Published release | **pass**: [GitHub Release v0.3.2](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2) |
| Public PyPI installation | **pass for 0.3.2**: isolated install, 64-cell self-check, and all 8 host install/verify cells |
| Cursor full bubble graph | **not claimed** |

## Corrected and verified in 0.3.2

- Release checksums now contain flat GitHub asset basenames, reject duplicate
  names, and are tested in a simulated flat download on Ubuntu and macOS.
- All eight current destination CLIs invoked an installed `resume-claude`
  Skill and ran the expected reader against a synthetic fixture.
- All seven native plugin/extension formats accepted the exact 0.3.2 release
  archive in an isolated local install; Cursor also executed the bundled reader.

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

## Evidence gates

| Area | Status | Required evidence |
|---|---|---|
| Current local release gates | pass | four canonical commands, 2026-07-24 |
| `v0.3.2` dual-OS release | pass | [Actions run 30093776529](https://github.com/ImL1s/resume-skills/actions/runs/30093776529), commit `284865a4dc8c1c3dca16ee40f5204053cabb3a92` |
| `v0.3.2` PyPI publication | pass | [portable-resume 0.3.2](https://pypi.org/project/portable-resume/0.3.2/) |
| `v0.3.1` dual-OS release | pass | [Actions run 30089194956](https://github.com/ImL1s/resume-skills/actions/runs/30089194956), commit `d50a1e33db2824830dabc469b7d566031aa45697` |
| `v0.3.1` PyPI publication | pass | [portable-resume 0.3.1](https://pypi.org/project/portable-resume/0.3.1/) |
| Host-native headless activation | 8/8 pass | rows in `docs/host-ui-smoke.md` |
| Native plugin/extension install | 7/7 pass | exact 0.3.2 rows in `docs/host-ui-smoke.md` |
| Visual picker activation | not-run | interactive picker selection evidence |
| Public marketplace publication | not-run | public listing/install evidence |
| Cursor graph completeness | not claimed | upstream schema/recovery work beyond current best effort |

The latest published GitHub release is
[`v0.3.2`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2).
PyPI publication is a package-distribution claim, not evidence of any host's
public marketplace listing or visual picker activation.

## Historical release evidence

`v0.3.0` is archived at commit
`78c2acd0f9841d90d87f85eff151b842a80dc011` with [release run
30084711240](https://github.com/ImL1s/resume-skills/actions/runs/30084711240).
`v0.2.3` remains an older historical claim at commit
`5ff9eba503e28971e5044015cd0666c2807a3d89` with [Actions run
29890453185](https://github.com/ImL1s/resume-skills/actions/runs/29890453185).

## Required local verification

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

See [`evidence-summary.md`](evidence-summary.md), [`release-claim.md`](release-claim.md), and [`host-ui-smoke.md`](host-ui-smoke.md) for proof boundaries.
