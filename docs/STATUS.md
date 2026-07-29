# Project status (2026-07-28)

## Current release: 0.3.4

| Gate | Status |
|---|---|
| Source adapters | 9: Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi, **Pi** |
| Destination profiles | 9 including **Pi** (filesystem install supported) |
| Packaging matrix | **81/81 pass** (currently **9×9=81**, derived from registries; claimed for this `0.3.4` release) |
| Installed runner matrix | **81/81 pass** (currently **9×9=81**, derived from registries; claimed for this `0.3.4` release) |
| Python test suite | **426 pass locally** (**426 collected**) after Wave 0 activation baseline validators (pre-Wave 0 main was **407** post-#11/#72; v0.3.4 tag was 375; historical Pi destination PR C local suite remains **359**). |
| Wheel + sdist smoke | **pass outside checkout**, including public PyPI installation |
| Native local plugin/extension install | **7/7 pass** with exact 0.3.2 release assets |
| Host-native headless Skill activation | **8/8 tested CLI surfaces pass** in v0.3.2-era evidence; fresh v0.3.4 host activation and Pi native activation **not-run** |
| Public marketplace installation | **6/6 compatible hosts pass on v0.3.2**; fresh v0.3.4 host reinstall **not-run** |
| Visual marketplace picker | **Cursor and Kimi pass on v0.3.2**; fresh v0.3.4 picker flow **not-run** |
| Other visual Skill picker activation | **not-run** |
| Vendor-curated directory listing | **not submitted** |
| CI (v0.3.4 release commit @ `fa1344b`) | **pass**: [Ubuntu + macOS × Python 3.11–3.14 + dist smoke](https://github.com/ImL1s/resume-skills/actions/runs/30269684151) |
| Phase 0 / Milestone N1 | **merged** [PR #49](https://github.com/ImL1s/resume-skills/pull/49) → `7b5192c` |
| `v0.3.4` release workflow | **pass**: [14 jobs through GitHub Release and PyPI](https://github.com/ImL1s/resume-skills/actions/runs/30269713516) |
| Published release | **pass**: [GitHub Release v0.3.4](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4) |
| Public PyPI installation | **pass for 0.3.4** ([portable-resume 0.3.4](https://pypi.org/project/portable-resume/0.3.4/), 81-cell artifact); prior `0.3.3` remains 64-cell historical |
| Public marketplace catalog | **synced** [`portable-resume-marketplace@7833e4a`](https://github.com/ImL1s/portable-resume-marketplace/commit/7833e4a3628213f78eb8458f30e9873d43a95fa6) / [marketplace `v0.3.4`](https://github.com/ImL1s/portable-resume-marketplace/releases/tag/v0.3.4); fresh host reinstall **not-run** |
| Cursor full bubble graph | **not claimed** |
| Codex large-rollout budget + parent list filter (Issue #3) | **done on main** [PR #4](https://github.com/ImL1s/resume-skills/pull/4) merge `48746c4` — P0 hotfix (not full streaming) |
| Codex probe head-only + list FS fallback | **not done** — [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) + [plan 026](../plans/026-codex-probe-list-discovery.md) |
| Codex streaming show / reducer | **not done** — [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) + [plan 027](../plans/027-codex-streaming-show.md) (PR #4 removed eager `splitlines`; still whole-file + `list[dict]`) |
| Kimi index/wire large-session recovery (Issue #14) | **done on main** [PR #58](https://github.com/ImL1s/resume-skills/pull/58) → `79d32ae` — stream index + wire via `stable_scan_lines`; metadata-only list; exact-path show + FS fallback; no silent 16 MiB whole-file reject. Issue **closed** 2026-07-27. CI green: [run 30267866248](https://github.com/ImL1s/resume-skills/actions/runs/30267866248). Current-head Codex review returned no major issues for `4ecf2b5` before merge: [review callback](https://github.com/ImL1s/resume-skills/pull/58#issuecomment-5091411213). |
| Cursor large-session silent truncation (Issue #11) | **Closed** via [PR #71](https://github.com/ImL1s/resume-skills/pull/71) + skeptic follow-up [PR #72](https://github.com/ImL1s/resume-skills/pull/72) (`3e94dea`) — CLI JSONL `stable_scan_lines`; live CLI blob `LIMIT n+1` fail-closed + honor `budget.record_bytes`; Desktop SQL filter-before-LIMIT with `scanned_records+1` admit window; show path `lower(id)`/`lower(composer_id)` after list normalizes UUIDs; live Desktop composerData two-phase length gate. Full bubble graph still **not claimed**. |
| OpenCode exact selection + large transcripts (Issue #13) | **Implemented on branch** `program/issue-13-opencode-exact` — SQLite exact-ID before `LIMIT`; show uses `transcript_records` + `LIMIT n+1`; file-store show session-scoped paths; export bound = `source_read_bytes`. Merge/CI/Codex review **pending** parent accept. |
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
| Capability registries + dynamic matrix | [Issue #36](https://github.com/ImL1s/resume-skills/issues/36) | **Done (product axes):** independent source/destination/package registries; rectangular matrix derived from enabled sets (9×9=81); package surfaces drive native zip builds; schema source enum matches enabled sources (incl. `pi`). Residual: auto-generated docs tables / planned-profile release gates still manual. |
| Reader CLI option honesty (#65) | [Issue #65](https://github.com/ImL1s/resume-skills/issues/65) | **Done:** `self-check` closed parser (rejects unknown args); request-file rejects `--within-min`; explicit `--format table|json|handoff` with show rejecting table. |
| CI stage de-duplication (#67) | [Issue #67](https://github.com/ImL1s/resume-skills/issues/67) | **Done:** `self_verify` named stages + profiles (`local` / `ci-compat` / `ci-quality`); matrix runs suite once; docs+secrets once in quality job; package needs both. |
| Shared `stable_scan_lines` (#10) | [Issue #10](https://github.com/ImL1s/resume-skills/issues/10) + PR #49 | Foundation on main; **adopted by Pi, Kimi, Cursor CLI, Qwen, Grok, Antigravity** for transcript JSONL. Codex streaming show (#8) still open. Claude private graph index retained. True streaming yield (no collect-then-yield) remains residual with #8. |
| Exact snapshot sibling ceiling (#16) | [Issue #16](https://github.com/ImL1s/resume-skills/issues/16) | **Done:** exact `stable_read_*` / `snapshot_regular_file` pin target basename via dir_fd (not whole-parent scandir); 2k+ siblings no longer `E_LIMIT_EXCEEDED`. SQLite family tracks main/wal/shm/journal only. |
| Pi source + destination (#38) | [Issue #38](https://github.com/ImL1s/resume-skills/issues/38) | **Done (filesystem/product path):** source `pi-session-jsonl-v3` (+ v2 read-only fixtures); destination `.pi/skills` / `~/.pi/agent/skills`; matrix 81 includes Pi×all. Residual: Pi native host UI/picker activation **not-run** (PR D evidence separate). |
| Kimi append-only index + wire (#14) | [Issue #14](https://github.com/ImL1s/resume-skills/issues/14) | **Closed / COMPLETED** via [PR #58](https://github.com/ImL1s/resume-skills/pull/58) → `79d32ae` (stream reduce, metadata list, exact show, FS fallback). Residual: corrupt tombstone soft-skip; true streaming yield still #10/#8. |
| ReadBudget raise clamp (#17) | [Issue #17](https://github.com/ImL1s/resume-skills/issues/17) + PR #80 | **Done:** every `Bounds` field rejects raised/negative/non-int ceilings at construction (`E_INVALID_INPUT`); consume paths keep `min(limits, DEFAULT_BOUNDS)` defense in depth. |
| Handoff serialized output budget (#63) | [Issue #63](https://github.com/ImL1s/resume-skills/issues/63) | **Done:** `handoff_output_bytes` separate from `normalized_content_bytes`; recovered quotes shrink with `W_TRUNCATED`; security banner + checklist reserved. |
| Install lock replan (#35) | [Issue #35](https://github.com/ImL1s/resume-skills/issues/35) | **Done:** execute rebuilds plan under lock from exact current manifest digest; preflight plan advisory only; claim-aware classify. |
| Install control schemas (#28) | [Issue #28](https://github.com/ImL1s/resume-skills/issues/28) | **Done:** strict bounded manifest/journal validation; duplicate-key reject; recover fails closed on malformed journals. |
| Owned skill runners (#26) | [Issue #26](https://github.com/ImL1s/resume-skills/issues/26) | **Done:** owned package path resolution + realpath bind; strip/force `--expected-source`; simple-ref argv vs request-file lanes; no free-text shell splice. |
| Windows install lock gate (#29) | [Issue #29](https://github.com/ImL1s/resume-skills/issues/29) | **Done (Policy B):** mutating install/uninstall/recover fail closed with `E_INSTALL_UNSUPPORTED_PLATFORM` on `os.name == "nt"` before support/lock creation; no silent unlocked mutation. |
| Installer recover containment (#20) | **Closed** via [PR #49](https://github.com/ImL1s/resume-skills/pull/49) → `7b5192c` | Typed stage/backup authorization + pinned support dirfd deletes + adversarial tests in `tests/unit/test_install_recover_containment.py`. |
| Installer control-plane pin/atomic (#21) | [Issue #21](https://github.com/ImL1s/resume-skills/issues/21) | **Closed** via [PR #64](https://github.com/ImL1s/resume-skills/pull/64) on main: support-dir pin through staging, no-follow lock/journal/manifest, lock truncate, unique-tmp atomic replace, no ambient destructive control fallbacks. Residual: Windows exclusive lock productization (#29); optional previous-manifest generation journal enrichment. |
| Descriptor-relative install (#31) | [Issue #31](https://github.com/ImL1s/resume-skills/issues/31) + PR #49/#64 | **Closed** via [PR #64](https://github.com/ImL1s/resume-skills/pull/64) on main for commit + stage pin + rollback + orphan delete + uninstall + verify (dirfd/`O_NOFOLLOW`, quarantine unlink, required snapshot digests, no post-manifest payload rollback). Windows mutating ops fail closed without dirfd (#29). |
| Post-manifest stale journal recover (#64 gate P1) | [PR #70](https://github.com/ImL1s/resume-skills/pull/70) → `e6a26b1` | **Fixed on main:** if complete journal write fails after ownership manifest publish, `recover_root` matches journal target generation to on-disk manifest and clears stage/journal only (no payload rollback). Regressions in `test_install_control_store`. |
| Cursor #11 post-merge skeptic P1s | [PR #72](https://github.com/ImL1s/resume-skills/pull/72) → `3e94dea` | **Fixed on main:** Desktop list window = `scanned_records+1` (not `listed_sessions*4`); show case-fold for stored UUID; live CLI blob respects lowered `Bounds.record_bytes`. CI green on pre-merge HEAD. |
| Next-wave agent roadmap (Pi, OpenClaw, goose, …) | [Issue #48](https://github.com/ImL1s/resume-skills/issues/48) + [Issue #38](https://github.com/ImL1s/resume-skills/issues/38) | Phase 0 on `7b5192c`. **Pi PR B: source adapter supported** (`pi-session-jsonl-v3` / v2 read-only). **Pi PR C: destination filesystem install supported** (`.pi/skills` / `~/.pi/agent/skills`; 81-cell smoke pass). **Pi PR D: native host UI / picker activation not-run**. **OpenClaw PR A: fixtures-only** (`openclaw-agent-sqlite-v1`, no adapter). **goose PR A: fixtures-only** (`goose-sessions-sqlite-v15` synthetic; adapter #39 not landed). |

`/resume-codex` remains **context migration** (Skill + reader), not Grok Build native `/resume` and not Codex CLI live resume.

## Corrected after Pi destination PR C

- **Pi destination install: supported (filesystem)** — `.pi/skills` / `~/.pi/agent/skills` direct Skill roots; **81/81** installed-runner smoke pass on `main`.
- **Pi native host UI / picker activation: not-run** (PR D evidence separate from filesystem install).
- Verify locally: **359** unittest, **81/81** installed-runner smoke, self_verify, secrets gate, check_docs.

## Corrected after PR #51

- **Pi source adapter supported** (`pi-session-jsonl-v3` / v2 read-only).
- Verify at merge tip: **340** unittest, **72/72** installed-runner smoke, self_verify, secrets gate,
  [CI run 30203656076](https://github.com/ImL1s/resume-skills/actions/runs/30203656076) on `d9152cd`.
- Honesty follow-up: suite **345** (tail-window list fix + max-tool-chars + UTF-8 header
  regressions); README/STATUS now claim **81/81** for published `0.3.4`.

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
- All eight destination CLIs enabled for v0.3.2 invoked an installed `resume-claude`
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
| Current local release gates | pass | **426 pass locally** + 81/81 installed-runner after Wave 0 baseline validators (2026-07-28); pre-Wave 0 main was 407; historical 378-tests claim is pre-#11/#72 growth |
| `v0.3.4` dual-OS release | pass | [Actions run 30269713516](https://github.com/ImL1s/resume-skills/actions/runs/30269713516), commit `fa1344bf62eb26332baea7b7ef4540a1a37acba8` |
| `v0.3.4` PyPI publication | pass | [portable-resume 0.3.4](https://pypi.org/project/portable-resume/0.3.4/), public isolated 81-cell self-check |
| `v0.3.2` dual-OS release | pass | [Actions run 30093776529](https://github.com/ImL1s/resume-skills/actions/runs/30093776529), commit `284865a4dc8c1c3dca16ee40f5204053cabb3a92` |
| `v0.3.2` PyPI publication | pass | [portable-resume 0.3.2](https://pypi.org/project/portable-resume/0.3.2/) |
| `v0.3.1` dual-OS release | pass | [Actions run 30089194956](https://github.com/ImL1s/resume-skills/actions/runs/30089194956), commit `d50a1e33db2824830dabc469b7d566031aa45697` |
| `v0.3.1` PyPI publication | pass | [portable-resume 0.3.1](https://pypi.org/project/portable-resume/0.3.1/) |
| Host-native headless activation | 8/8 tested CLI surfaces pass in v0.3.2-era evidence; fresh v0.3.4 host activation and Pi native activation not-run | rows in `docs/host-ui-smoke.md` |
| Native plugin/extension install | 7/7 pass | exact 0.3.2 rows in `docs/host-ui-smoke.md` |
| Public marketplace catalog | v0.3.4 published | [marketplace release v0.3.4](https://github.com/ImL1s/portable-resume-marketplace/releases/tag/v0.3.4) and CI in `docs/evidence-summary.md` |
| Public marketplace host install | 6/6 compatible hosts pass on v0.3.2; v0.3.4 not-run | install rows and `docs/evidence/public-marketplace-v0.3.2.json` |
| Visual marketplace picker | Cursor and Kimi pass on v0.3.2; v0.3.4 not-run | interactive selection rows in `docs/host-ui-smoke.md` |
| Other visual Skill pickers | not-run | per-host interactive picker evidence |
| Vendor-curated directory listing | not submitted | authenticated vendor submission/readback |
| Cursor graph completeness | not claimed | upstream schema/recovery work beyond current best effort |

The latest published GitHub release is
[`v0.3.4`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4).
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
