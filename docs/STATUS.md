# Project status (2026-07-26)

## Current release: 0.3.3

| Gate | Status |
|---|---|
| Source adapters | 9: Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi, **Pi (source only)** |
| Destination profiles | 8 (Pi destination not supported) |
| Packaging matrix | **72/72 pass locally** (currently **9×8=72**, derived from registries) |
| Installed runner matrix | **72/72 pass locally** (currently **9×8=72**, derived from registries) |
| Python test suite | **352 pass locally** (OpenClaw + goose fixtures PR A) |
| Wheel + sdist smoke | **pass outside checkout**, including public PyPI installation |
| Native local plugin/extension install | **7/7 pass** with exact 0.3.2 release assets |
| Host-native headless Skill activation | **8/8 pass** |
| Public marketplace installation | **6/6 compatible hosts pass** |
| Visual marketplace picker | **Cursor and Kimi pass** |
| Other visual Skill picker activation | **not-run** |
| Vendor-curated directory listing | **not submitted** |
| CI (main @ `d9152cd`) | **pass**: [Ubuntu + macOS × Python 3.11–3.14 + dist smoke](https://github.com/ImL1s/resume-skills/actions/runs/30203656076) ([PR #51](https://github.com/ImL1s/resume-skills/pull/51)) |
| Phase 0 / Milestone N1 | **merged** [PR #49](https://github.com/ImL1s/resume-skills/pull/49) → `7b5192c` |
| `v0.3.2` release workflow | **pass**: [14 jobs through GitHub Release and PyPI](https://github.com/ImL1s/resume-skills/actions/runs/30093776529) |
| Published release | **pass**: [GitHub Release v0.3.2](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2) / [v0.3.3](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.3) |
| Public PyPI installation | **pass for 0.3.3**: isolated install and registry-derived matrix self-check |
| Cursor full bubble graph | **not claimed** |
| Codex large-rollout budget + parent list filter (Issue #3) | **done on main** [PR #4](https://github.com/ImL1s/resume-skills/pull/4) merge `48746c4` — P0 hotfix (not full streaming) |
| Codex probe head-only + list FS fallback | **not done** — [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) + [plan 026](../plans/026-codex-probe-list-discovery.md) |
| Codex streaming show / reducer | **not done** — [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) + [plan 027](../plans/027-codex-streaming-show.md) (PR #4 removed eager `splitlines`; still whole-file + `list[dict]`) |
| Codex-native live resume / `codex resume` from hosts | **not claimed** (inert handoff only) |

## PR #49 AI review disposition (closed for merge)

Codex/multi-CLI merge blockers on [PR #49](https://github.com/ImL1s/resume-skills/pull/49) were addressed before squash-merge `7b5192c`. GitHub may still show **outdated** inline threads (`line=null` / old SHAs); treat this table as the source of truth.

| Finding | Severity | Disposition |
|---|---|---|
| Close intermediate dirfds on success | P1 | **Done** — `_open_directory_under_root` closes intermediates before return |
| Bound scan memory when `budget=None` | P1 | **Done** — `stable_scan_lines` always uses `effective_budget` |
| Fail closed without descriptor-relative replace | P1 | **Done** — non-dirfd platforms fail closed |
| Pin recovery stage before delete / typed cleanup | P1 | **Done** — authorized stage/backup roles + support dirfd |
| Pin every root path component before commit | P1 | **Done** — component walk from `/` with `O_NOFOLLOW` |
| Reject symlinked cleanup targets | P1 | **Done** — no-follow authorization before delete |
| Keep ancestor fds pinned across symlink hops | P1 | **Done** — open replacement before releasing ancestors |
| Preserve force-with-backup trees on complete recover | P1 | **Done** — complete journal clears stage only |
| Reject non-regular staged entries before replace | P1 | **Done** — `_validate_staged_regular_file` + regressions |
| Restrict backup cleanup to generated names | P2 | **Done** — basename gate for installer backups |
| Close relative-symlink probe intermediates | P2 | **Done** — probe fds closed on success path |
| CRLF boundary / parent-relative skill-root edge cases | P2 | **Deferred** — non-blocking; track under #10 / #31 if reproduced |
| Final `@codex review` thumbs-up on last SHA | n/a | **Not obtained** (bot `Unknown error`); merge gate was CI + disposition above |

## Open work (honest backlog)

| Item | Track | Notes |
|---|---|---|
| Issue #3 parent list + large rollout reject | **Closed** via PR #4 → `48746c4` | P0 on main. |
| Discovery false unsupported / stale SQLite | [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) + plan 026 | P1a: head-only probe; no full `sessions/` walk; read-only FS head fallback. Do not mutate `~/.codex`. |
| Peak memory on large show | [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) + plan 027 | P1b: true chunked stable streaming + reducer + synthetic 17–30 MiB test. |
| Capability registries + dynamic matrix | [Issue #36](https://github.com/ImL1s/resume-skills/issues/36) | **Partial via PR #49:** source/destination registries + dynamic direct-runner matrix (now **9×8** with Pi source-only). `PACKAGE_SURFACES` scaffold empty; package builders not registry-driven. Keep #36 open. |
| Shared `stable_scan_lines` (#10) | [Issue #10](https://github.com/ImL1s/resume-skills/issues/10) + PR #49 | Foundation on main; **adopted by Pi source adapter**; remaining adapters still pending. True streaming yield remains with #8. |
| ReadBudget raise clamp (#17) | [Issue #17](https://github.com/ImL1s/resume-skills/issues/17) + PR #49 | **Partial:** four consume counters clamp to `DEFAULT_BOUNDS`. Full Bounds construction-time validation still open. |
| Installer recover containment (#20) | **Closed** via [PR #49](https://github.com/ImL1s/resume-skills/pull/49) → `7b5192c` | Typed stage/backup authorization + pinned support dirfd deletes + adversarial tests in `tests/unit/test_install_recover_containment.py`. |
| Descriptor-relative install (#31) | [Issue #31](https://github.com/ImL1s/resume-skills/issues/31) + PR #49 | **Partial:** POSIX forward commit is dirfd-based; rollback/manifest/orphan/Windows still pathname or fail-closed. |
| Next-wave agent roadmap (Pi, OpenClaw, goose, …) | [Issue #48](https://github.com/ImL1s/resume-skills/issues/48) + [Issue #38](https://github.com/ImL1s/resume-skills/issues/38) | Phase 0 on `7b5192c`. **Pi PR B: source adapter supported** (`pi-session-jsonl-v3` / v2 read-only); **Pi destination not-run** (PR C). **OpenClaw PR A: fixtures-only** (`openclaw-agent-sqlite-v1`, no adapter). **goose PR A: fixtures-only** (`goose-sessions-sqlite-v15` synthetic; adapter #39 not landed). |

`/resume-codex` remains **context migration** (Skill + reader), not Grok Build native `/resume` and not Codex CLI live resume.

## Corrected after PR #51

- **Pi source adapter supported** (`pi-session-jsonl-v3` / v2 read-only); **Pi destination not-run**.
- Verify at merge tip: **340** unittest, **72/72** installed-runner smoke, self_verify, secrets gate,
  [CI run 30203656076](https://github.com/ImL1s/resume-skills/actions/runs/30203656076) on `d9152cd`.
- Honesty follow-up: suite **342** (corrupt-list warning + 17–30 MiB budget pad); STATUS/README counts aligned.

## Corrected and verified on main after 0.3.3 (PR #49)

- Phase 0 / Milestone N1: independent source/destination registries, dynamic
  8×8 matrix, `stable_scan_lines` foundation, ReadBudget consume clamps,
  installer recover containment, and POSIX descriptor-relative payload commits.
- Merge: [PR #49](https://github.com/ImL1s/resume-skills/pull/49) → `7b5192c`.
- Verify at merge: **329** unittest, 64/64 installed-runner smoke, self_verify,
  secrets gate, [CI run 30191800004](https://github.com/ImL1s/resume-skills/actions/runs/30191800004).

## Corrected and verified in 0.3.3

- Adapter list/show budgets and parent-session SQL pre-filter landed on main
  (PR #4 / `48746c4`), including remaining zstd/source capacity, bounded
  readline parsing, transcript raise clamp, and stable-read verification hashing.
- CI GitHub Actions pins: checkout v7.0.1, setup-python v7.0.0.
- Unit suite: **274** tests locally before tag.

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
