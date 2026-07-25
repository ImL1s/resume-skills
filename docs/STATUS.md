# Project status (2026-07-25)

## Current release: 0.3.2

| Gate | Status |
|---|---|
| Source adapters | 8: Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi |
| Destination profiles | 8 |
| Packaging matrix | **64/64 pass locally** |
| Installed runner matrix | **64/64 pass locally** |
| Python test suite | **274 pass locally** (main @ `48746c4`) |
| Wheel + sdist smoke | **pass outside checkout**, including public PyPI installation |
| Native local plugin/extension install | **7/7 pass** with exact 0.3.2 release assets |
| Host-native headless Skill activation | **8/8 pass** |
| Public marketplace installation | **6/6 compatible hosts pass** |
| Visual marketplace picker | **Cursor and Kimi pass** |
| Other visual Skill picker activation | **not-run** |
| Vendor-curated directory listing | **not submitted** |
| CI | **pass**: [Ubuntu + macOS × Python 3.11–3.14](https://github.com/ImL1s/resume-skills/actions/runs/30093652499) |
| `v0.3.2` release workflow | **pass**: [14 jobs through GitHub Release and PyPI](https://github.com/ImL1s/resume-skills/actions/runs/30093776529) |
| Published release | **pass**: [GitHub Release v0.3.2](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2) |
| Public PyPI installation | **pass for 0.3.2**: isolated install, 64-cell self-check, and all 8 host install/verify cells |
| Cursor full bubble graph | **not claimed** |
| Codex large-rollout budget + parent list filter (Issue #3) | **done on main** [PR #4](https://github.com/ImL1s/resume-skills/pull/4) merge `48746c4` — P0 hotfix (not full streaming) |
| Codex probe head-only + list FS fallback | **not done** — [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) + [plan 026](../plans/026-codex-probe-list-discovery.md) |
| Codex streaming show / reducer | **not done** — [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) + [plan 027](../plans/027-codex-streaming-show.md) (PR #4 removed eager `splitlines`; still whole-file + `list[dict]`) |
| Codex-native live resume / `codex resume` from hosts | **not claimed** (inert handoff only) |

## Open work (honest backlog)

| Item | Track | Notes |
|---|---|---|
| Issue #3 parent list + large rollout reject | **Closed** via PR #4 → `48746c4` | P0 on main: SQL parent pre-filter; `source_read_bytes` / `transcript_records`; remaining zstd/source budgets; bounded readline; transcript raise clamp; stable-read hash verification. Maintainer verify before merge: secrets clean, **274** tests, self_verify, 64/64 matrix. |
| Discovery false unsupported / stale SQLite | [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) + plan 026 | P1a: head-only probe; no full `sessions/` walk; read-only FS head fallback. Do not mutate `~/.codex`. (#5 closed as duplicate of #7.) |
| Peak memory on large show | [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) + plan 027 | P1b: true chunked stable streaming + reducer + synthetic 17–30 MiB test. Not live process restore. (#6 closed as duplicate of #8.) |

`/resume-codex` remains **context migration** (Skill + reader), not Grok Build native `/resume` and not Codex CLI live resume.

## Corrected and verified in 0.3.2

- Release checksums now contain flat GitHub asset basenames, reject duplicate
  names, and are tested in a simulated flat download on Ubuntu and macOS.
- All eight current destination CLIs invoked an installed `resume-claude`
  Skill and ran the expected reader against a synthetic fixture.
- All seven native plugin/extension formats accepted the exact 0.3.2 release
  archive in an isolated local install; Cursor also executed the bundled reader.
- The independent public
  [`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
  installed on Claude, Codex, Cursor, Qwen, Grok, and Kimi. Cursor and Kimi
  were verified through their marketplace pickers.

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
| Public marketplace publication/install | 6/6 compatible hosts pass | public repository, install rows, and `docs/evidence/public-marketplace-v0.3.2.json` |
| Visual marketplace picker | Cursor and Kimi pass | interactive selection rows in `docs/host-ui-smoke.md` |
| Other visual Skill pickers | not-run | per-host interactive picker evidence |
| Vendor-curated directory listing | not submitted | authenticated vendor submission/readback |
| Cursor graph completeness | not claimed | upstream schema/recovery work beyond current best effort |

The latest published GitHub release is
[`v0.3.2`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2).
The independent public marketplace is published separately at
[`ImL1s/portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace).
PyPI and marketplace evidence remain distinct claims.

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
