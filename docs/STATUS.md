# Project status (2026-08-01)

## Current release: 0.4.0

Current `main` advances to `0.4.1.dev0` after publishing immutable `v0.4.0`.
It no longer reuses immutable published `v0.3.4` as the package base. Explicit build/release tooling includes Git
state plus deterministic registry/source digests. One canonical pre-build pin is
embedded byte-for-byte in wheel, sdist, all 18 direct-host ZIPs, and all seven
native package ZIPs; cross-artifact and installed-runtime checks fail closed on
missing, duplicate, misplaced, malformed, or mismatched identity bytes. Runtime
lookup uses only the fixed packaged resource and never Git or a build-pin
environment path; unpackaged source retains the null-commit fallback. The
repository-level immutable `v*` tag policy is active and verified through
[ruleset `20148806`](https://github.com/ImL1s/resume-skills/rules/20148806):
target `tag`, `refs/tags/v*`, update and deletion restrictions, and no bypass
actors. The separate optional trusted-zstd reader boundary remains documented in
`SECURITY.md`.

| Gate | Status |
|---|---|
| Source adapters | 17: Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi, Pi, OpenClaw, goose, Crush, Cline, OpenHands, Hermes, Gemini CLI, **GitHub Copilot CLI** (Kilo source research-only) |
| Destination profiles | 18 including prior hosts + **GitHub Copilot CLI** + **Gemini CLI** + **Kilo CLI** (destination-only Track A) (filesystem install supported) |
| Packaging matrix | **306/306** on current main tip (**17×18**, derived from registries; published `0.3.4` remains historical **9×9=81**) |
| Version identity (#118) | **Implemented and repository policy verified on the `v0.4.0` pin:** base `0.4.0`; `check_version_state.py` rejects reuse of immutable `v0.3.4`; release tags reject `.devN`; one canonical identity is embedded and verified across wheel, sdist, 18 direct ZIPs, seven native ZIPs, host report, and installed runtime. Active tag ruleset [`20148806`](https://github.com/ImL1s/resume-skills/rules/20148806) blocks `v*` update/deletion with no bypass actors. |
| Installed runner matrix | **306/306** on current main tip (**17×18**, derived from registries; published `0.3.4` remains historical **9×9=81**) |
| Python test suite | **944 pass locally** on main after ultra-batch land (`18fe4ca` product tip; 2026-08-01); subsequent commits may be docs-only honesty fixes. v0.3.4 tag was 375. |
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
| Published release | **pass**: [GitHub Release v0.4.0](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.0) (prior [v0.3.4](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4) remains historical) |
| Public PyPI installation | **pass for 0.4.0** ([portable-resume 0.4.0](https://pypi.org/project/portable-resume/0.4.0/), 306-cell artifact); prior `0.3.4` remains 81-cell historical |
| Public marketplace catalog | **synced** [`portable-resume-marketplace@7833e4a`](https://github.com/ImL1s/portable-resume-marketplace/commit/7833e4a3628213f78eb8458f30e9873d43a95fa6) / [marketplace `v0.3.4`](https://github.com/ImL1s/portable-resume-marketplace/releases/tag/v0.3.4); fresh host reinstall **not-run** |
| Cursor full bubble graph | **not claimed** |
| Codex large-rollout budget + parent list filter (Issue #3) | **done on main** [PR #4](https://github.com/ImL1s/resume-skills/pull/4) merge `48746c4` — P0 hotfix (not full streaming) |
| Codex probe head-only + list FS fallback | **done on PR #93** — [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) + [plan 026](../plans/026-codex-probe-list-discovery.md); byte-bounded head, soft probe sample, sparse/stale FS merge+rank. Residual P2: cap head parse by record count not only bytes (non-blocking). |
| Codex streaming show / reducer | **done on main** — [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) + [PR #94](https://github.com/ImL1s/resume-skills/pull/94) → `8ac5549` (+ mtime pin `cba2e34`); plain show streams + reduce. Residual: zstd whole decompress; collect-free `stable_scan_lines` yield (#10) |
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

**Prioritized residual tracker:** [Issue #204](https://github.com/ImL1s/resume-skills/issues/204).  
**Wave 0+1 (`055c071`):** #120 discover/doctor · #159 atomic `--output` · #18 large-session umbrella closed.  
**Wave 2+ product (this land):** list `--limit`/`--since`/`--until`/`--cursor` (#157); `--workspace` + `project explain` (#154); `search` (#156); `pick` + `--privacy`/`--redaction-report` (#124); `config` layers/presets (#152); install `--sources` (#151); smoke `--mode source|destination|full` (#122); universal direct-skills zip by payload profile (#121); matrix docs gate (#119 partial→strengthened); native evidence policy doc (#123); Windows mutating install remains fail-closed Policy B (#125).  
**Cross-platform track (#205–#209 + #125):** `platform_fs` backend ships on main (PR #210–#213 + follow-on fixes). Production `stable_read_bytes` / `snapshot_sqlite_family` / `write_output_bytes` / request-file (Windows path) dispatch through the backend with honest capabilities. CI `test-windows` on `windows-latest` / Python 3.12 is the real `nt` evidence (not Docker): compile + platform unit tests; `self-check` + `matrix`; `sources` / `doctor` / `discover`; hard gate `self_verify --only windows_source_fixtures` requiring **all 17** enabled sources list+show on fixtures (or content-free diagnostic). Mutating `smoke_installed_matrix` is **skipped** on Windows because install remains fail-closed. Windows **mutating** install/uninstall/recover remains **fail-closed** (`E_INSTALL_UNSUPPORTED_PLATFORM`); #125 is **not** product-complete until handle locking + reparse-safe mutation land. WSL / musl / BSD independent runners: **not-run**. Live resume / host UI / marketplace / Kilo source: **not claimed**.  
**Research NO-GO (documented, not enabled):** #200 Kimi active-context · #201 Cursor full bubble · #202/#46 Kilo source — see `docs/research/*-2026-08.md`.  
**Explicitly deferred P2 (not done):** #126 bundle · #127 delta resume · #128 fuzz · #129 qual scaffold · #158 aliases · #160 completions · #173 standup · #47 second-wave agents. #48 roadmap remains umbrella (filesystem done; UI not-run).

| Item | Track | Notes |
|---|---|---|
| Issue #3 parent list + large rollout reject | **Closed** via PR #4 → `48746c4` | P0 on main. |
| Discovery false unsupported / stale SQLite | [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) + plan 026 | **Done (P1a / PR #93 → `7ff33eb`):** probe uses DB signature without sessions walk; soft-capped sample for plain/zstd; byte-bounded head; FS soft merge/rank with `W_TRUNCATED`. Show streaming plain path **done** via #8 / PR #94. |
| Peak memory on large show | [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) + plan 027 | **Done (plain):** PR #94 → `8ac5549` / pin `cba2e34` — `stable_scan_lines` + attempt-local reduce; ~20 MiB regression; updated_at pinned to scanned inode. Residual: zstd full decompress; collect-then-yield still residual with #10. |
| Capability registries + dynamic matrix | [Issue #36](https://github.com/ImL1s/resume-skills/issues/36) | **Done (product axes):** independent source/destination/package registries; rectangular matrix derived from enabled sets (currently **17×18=306** on main; published `0.3.4` was **9×9=81**); package surfaces drive native zip builds; schema source enum matches enabled sources (incl. `pi`, `openclaw`, `goose`). Docs gate: `scripts/render_docs.py` + `assert_matrix_consistent` keep host tables / [`matrix-current.md`](matrix-current.md) / STATUS packaging+installed-runner products aligned with the registry. Residual: planned-profile release gates still manual; host UI / marketplace evidence remains human-recorded. |
| Reader CLI option honesty (#65) | [Issue #65](https://github.com/ImL1s/resume-skills/issues/65) | **Done:** `self-check` closed parser (rejects unknown args); request-file rejects `--within-min`; explicit `--format table|json|handoff` with show rejecting table. |
| CI stage de-duplication (#67) | [Issue #67](https://github.com/ImL1s/resume-skills/issues/67) | **Done:** `self_verify` named stages + profiles (`local` / `ci-compat` / `ci-quality`); matrix runs suite once; docs+secrets once in quality job; package needs both. |
| Hosts command context (#66) | [Issue #66](https://github.com/ImL1s/resume-skills/issues/66) | **Done:** primary `install-resume-skills` argv/display; optional source-checkout labeled; shared-root warning only when codex+antigravity selected. |
| Shared `stable_scan_lines` (#10) | [Issue #10](https://github.com/ImL1s/resume-skills/issues/10) | **Done** foundation + adapters + collect-free spool yield via [PR #101](https://github.com/ImL1s/resume-skills/pull/101). **Adopted by Pi, Kimi, Cursor CLI, Qwen, Grok, Antigravity, Codex plain show**. Claude private graph retained. Residual: zstd whole-decompress (#8). |
| Grok + Antigravity large histories (#15) | [Issue #15](https://github.com/ImL1s/resume-skills/issues/15) | **Done** via [PR #96](https://github.com/ImL1s/resume-skills/pull/96) → `66d0ebf`: Grok metadata-first list + updates mtime freshness; Antigravity exact-show without index dependency; stream-reduce + list header stop. Residual: 17–30 MiB synthetic CI cases optional; collect-free yield still #10. |
| Destination root env homes (#24) | [Issue #24](https://github.com/ImL1s/resume-skills/issues/24) | **Done** via [PR #97](https://github.com/ImL1s/resume-skills/pull/97) → `d2a6e3d`: Kimi `$KIMI_CODE_HOME/skills`, isolation `--home` ignores env, hosts report root_source. Residual P2: plan-field provenance emit / docs table align if needed. |
| Uninstall/verify transactional consistency (#22) | [Issue #22](https://github.com/ImL1s/resume-skills/issues/22) | **Done** via [PR #98](https://github.com/ImL1s/resume-skills/pull/98): journaled uninstall + recover; POSIX locked verify; crash-matrix + durability fixes. Residual: Windows exclusive lock #29; verify shared lock / restore-temp unlink hygiene P2. |
| Multi-root install lock/checkpoint (#23) | [Issue #23](https://github.com/ImL1s/resume-skills/issues/23) | **Done** via [PR #99](https://github.com/ImL1s/resume-skills/pull/99): lock-all canonical order, replan+checkpoint under locks, same-process compensate. Residual: no durable multi-root coordinator; non-cooperating concurrent writers (TOCTOU on quarantine rename) cannot be fully serialized (issue out-of-scope honesty). |
| Host-neutral Skill payloads (#25) | [Issue #25](https://github.com/ImL1s/resume-skills/issues/25) | **Done** via [PR #100](https://github.com/ImL1s/resume-skills/pull/100): portable SKILL body; one package identity across hosts; Codex+Antigravity shared `.agents/skills` lifecycle. Residual: host-native activation smoke for shared payload still not-run. |
| Discovery duplicate/shadow Skills (#34) | [Issue #34](https://github.com/ImL1s/resume-skills/issues/34) | **Done (tooling):** executable `DiscoveryRoot` policy; bounded `audit-host` / install preflight / verify attachment; `E_INSTALL_SHADOW` blocks known higher-precedence divergent copies; equal-tier and unknown precedence warn; identical + same-physical allow. Residual: plugin wildcard trees, host-native loaded-copy provenance smoke, versioned precedence tables under #27. |
| Project-scope payload vs control state (#33) | [Issue #33](https://github.com/ImL1s/resume-skills/issues/33) | **Done (Option A):** control plane under `.portable-resume/.state/`; shareable runtime/resources + narrow `.gitignore`; lock-time v1 migration; verify reports `control_layout=state-v1`. Residual: claim ids still embed absolute roots inside gitignored manifest (not portable rebind without reinstall). |
| Installer CLI contract (#32) | [Issue #32](https://github.com/ImL1s/resume-skills/issues/32) | **Done (Option A):** mutation/status commands always emit `install-result-v1` JSON with `results[]`; removed no-op `--json` and `verify --dry-run`; `hosts` keeps human/`--json`. Residual: no recover dry-run plan yet. |
| Native package contracts (#27) | [Issue #27](https://github.com/ImL1s/resume-skills/issues/27) | **Done (offline contracts):** versioned `package-contracts-v1` per surface; builder fail-closed offline validation; `host-packages-v2` binds `contract_id` + `native_evidence_status=not-run`. Residual: optional native CLI matrix not automated; public marketplace reinstall not-run. |
| Claude exact-ref discovery (#19) | [Issue #19](https://github.com/ImL1s/resume-skills/issues/19) | **Done (discovery optimization):** absolute approved path and exact UUID + cwd slug try direct candidates before broad `~/.claude/projects` enumeration; basename probe fallback remains cwd-safe; metadata windows + private graph unchanged. Not a native-resume claim. |
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
| Next-wave agent roadmap (Pi, OpenClaw, goose, …) | [Issue #48](https://github.com/ImL1s/resume-skills/issues/48) + [Issue #38](https://github.com/ImL1s/resume-skills/issues/38) | Phase 0 on `7b5192c`. **Pi / OpenClaw / goose / Crush / Cline / OpenHands / Hermes / Gemini / Copilot source+dest / Kilo dest** filesystem product paths done (matrix **17×18=306**). Native UI/picker activation not-run for these hosts. Kilo source qualification is pinned but remains NO-GO for enablement (#46 Track B). |
| GitHub Copilot source Track B (#44) | [Issue #44](https://github.com/ImL1s/resume-skills/issues/44) | **Done (filesystem/product path):** `copilot-cli-events-jsonl-v1` from local `session-state/<id>/events.jsonl`; cwd filter; omit reasoning/tool payloads. Residual: Chronicle/cloud sync never used; native UI **not-run**. |
| Kilo destination Track A + source qualification (#46) | [Issue #46](https://github.com/ImL1s/resume-skills/issues/46) | **Destination filesystem done:** `.kilocode/skills` + `~/.config/kilo/skills` (`KILO_CONFIG_DIR`). [Source qualification](research/kilo-cli-v7.4.17-qualification.md) pins CLI v7.4.17 / `a0364858…` and returns **NO-GO for source enablement**: current `session_message` + event/projector + legacy projections, migration state, and cloud-import provenance require clean-room synthetic fixtures and Kilo-specific rejection tests. Source stays research; native activation/UI remains **not-run**. |
| OpenClaw source + destination (#37) | [Issue #37](https://github.com/ImL1s/resume-skills/issues/37) | **Done (filesystem/product path):** source `openclaw-agent-sqlite-v1`; destination workspace `skills/` + `~/.openclaw/skills`. Residual: native `openclaw skills install` / host UI activation **not-run**. |
| goose source + destination (#39) | [Issue #39](https://github.com/ImL1s/resume-skills/issues/39) | **Done (filesystem/product path):** source `goose-sessions-sqlite-v15` (`sessions/sessions.db`); destination `.goose/skills` + `~/.config/goose/skills`. Residual: legacy JSONL out of scope; native goose UI **not-run**. |
| Crush source + destination (#40) | [Issue #40](https://github.com/ImL1s/resume-skills/issues/40) | **Done (filesystem/product path):** source `crush-sqlite-v1` (per-project `.crush/crush.db`, goose_db_version 7); destination `.crush/skills` + `~/.config/crush/skills`; matrix **16×17=272**. Residual: native Crush UI **not-run**; no recursive multi-project home scan. |
| Reader `sources` / `discover` / `doctor` (#120) | plan 044 + reader CLI | **Shipped on main (Wave 0+1):** `portable-resume sources` (presence), `discover` (cross-source metadata candidates with `source:id` tokens + per-source isolation), and `doctor` (registry/matrix/schema/source-presence/platform checks). Residual under #120 only if issue text still asks for more (e.g. richer install audit); host UI / marketplace remain **not-run**. |
| Codex plans 026/027 bookkeeping | plans/README + #7/#8 | **Plans index flipped DONE** to match closed issues and main code. Residual honesty: zstd full decompress / host UI / marketplace / Kilo **source** / Cursor full bubble remain **not claimed** or **not-run** as elsewhere in this file. |
| Atomic reader `--output` (#159) | reader + `output_write.py` | **Shipped:** atomic no-clobber file write for rendered list/show/sources/discover/doctor output; `--force` clobber; `-` = stdout. Not a portable `.prb` bundle (#126). |

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
| Current local release gates | pass | **944 pass locally** after ultra-batch land (`18fe4ca` product tip) + **306/306** registry-derived installed-runner (2026-08-01); Wave 0 snapshot was 426 tests + 81/81 on 2026-07-28 |
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
[`v0.4.0`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.0)
([PyPI 0.4.0](https://pypi.org/project/portable-resume/0.4.0/)); prior
[`v0.3.4`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4) remains
historical. The independent public marketplace is published separately at
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
