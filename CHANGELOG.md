# Changelog

## Unreleased

### Security
- Installer control plane (#21): pin `.portable-resume`, no-follow regular-file
  opens for lock/journal/manifest, truncate lock metadata, and atomic journal/
  manifest replace via unique temps under the support directory.
- Installer payload plane (#31): rollback restore, orphan delete, uninstall, and
  verify use descriptor-relative no-follow walks under the skill root so
  parent-directory symlink swaps cannot redirect writes or deletes outside the
  root (POSIX). Windows remains fail-closed where dirfd support is absent (#29).

### Fixed
- ReadBudget / Bounds no-raise ceilings (#17): every `Bounds` field is validated
  at construction so callers may lower defaults but cannot raise them; invalid
  or negative ceilings fail with content-free `E_INVALID_INPUT` before source
  I/O. Consume paths still take `min(limits, DEFAULT_BOUNDS)` as defense in depth.
- Session selection identity vs display sanitization (#61): list/show selection
  and `ResolvedRef` use validated raw structural fields (`session_id`,
  `source_path`, `cwd`); public envelopes still redact free-text and path
  content. Secret-shaped native session IDs remain exact-selectable and are not
  collapsed to `[REDACTED]` before adapter `show()`.
- Exact-path no-symlink validation (#68): `require_regular_no_symlinks` no longer
  rewrites an outside symlink via realpath merely because the target sits inside
  the approved root; only configured-root spellings (plus narrow macOS
  `/var`↔`/private/var` reverse alias) are accepted walk roots.
- OpenCode exact selection and large transcripts (#13): SQLite list applies
  `WHERE id = ?` before any newest-session `LIMIT` so older exact IDs stay
  selectable; show joins charge `transcript_records` with `LIMIT n+1`
  fail-closed overflow (no longer borrow `scanned_records`); legacy
  file-store show scopes to `storage/message/<sessionID>/` and
  `storage/part/<messageID>/` instead of decoding every message/part file;
  explicit export JSON is bounded by `source_read_bytes` as one source
  document (not silent inheritance of 16 MiB `record_bytes`).
- Cursor large sessions (#11 / [PR #71](https://github.com/ImL1s/resume-skills/pull/71),
  [PR #72](https://github.com/ImL1s/resume-skills/pull/72)): CLI JSONL
  transcripts stream via `stable_scan_lines` under `source_read_bytes` /
  per-line `record_bytes` / `transcript_records` (no whole-file 16 MiB reject
  for small lines). Live CLI `store.db` fails closed on blob count overflow
  (`LIMIT n+1`) and honors caller `Bounds.record_bytes` for blob payloads.
  Synthetic Desktop list filters archived/subagent rows in SQL before
  `ORDER BY … LIMIT` while admitting up to `scanned_records`; show resolves
  list-normalized UUIDs via case-folded `id`/`composer_id` lookups. Live
  Desktop `composerData` uses a two-phase length gate and re-checks size after
  fetch. Full Cursor bubble-graph restore remains **not claimed**.
- Both console commands now support `--version` and report the package
  single-source version.
- PyPI package metadata now includes project, documentation, repository, issue,
  and changelog links for the next publication.
- Current-release documentation scopes 7/7 native-package, 8/8 headless, 6/6
  marketplace, and Cursor/Kimi picker evidence to the recorded v0.3.2-era runs;
  fresh v0.3.4 host reinstall and picker flows remain `not-run`.

## [0.3.4] — 2026-07-27

### Fixed
- Kimi current-store readers no longer treat whole `session_index.jsonl` /
  `wire.jsonl` files as a single 16 MiB record. Index reduce and transcript
  show stream via `stable_scan_lines` under `source_read_bytes` (aggregate) and
  `record_bytes` (per line). List is metadata-only (state + mtime). Exact-path
  show does not re-scan index/FS (single call budget for the wire; state.json
  supplies title/cwd). List discovery uses append-only index reduce plus
  read-only `sessions/` union, honoring index `deleted` tombstones and skipping
  unsafe per-session candidates without mutating the store
  ([Issue #14](https://github.com/ImL1s/resume-skills/issues/14) / [PR #58](https://github.com/ImL1s/resume-skills/pull/58)).

### Added
- Pi destination filesystem install (`.pi/skills` / `~/.pi/agent/skills`), bringing
  the registry-derived packaging and installed-runner matrix to **9×9=81** cells
  on this release ([PR #56](https://github.com/ImL1s/resume-skills/pull/56)).

### Notes
- Other adapters’ large-session streaming (#7/#8 Codex, Cursor/Qwen/OpenCode/Grok)
  remain open under [Issue #18](https://github.com/ImL1s/resume-skills/issues/18).
- Still inert handoff only — not live process restore.
- Pi native host UI / picker activation remains **not-run**.
- Residual: a syntactically corrupt index *tombstone* line is soft-skipped and
  cannot apply that delete; prior valid tombstones remain authoritative. True
  streaming yield for multi‑10 MiB wires remains deferred to #10/#8.

## [0.3.3] — 2026-07-25

### Fixed
- Live source discovery no longer lets subagent rows crowd parent `cli`/`vscode`
  sessions out of the listing window: filter source and default unarchived
  rows in SQL before `LIMIT`, while exact-ID lookup still reaches archived parents.
- Rollout reads charge whole-file bounds with `source_read_bytes` and
  per-line counts with `transcript_records`, keeping `record_bytes` as the
  single-record ceiling (including remaining capacity for zstd and fallback paths).
- Custom transcript ceilings can no longer exceed the global 50,000-line default.
- Prefer bounded `BytesIO.readline` over full `splitlines` materialization for
  large JSONL parsing; stable-read verification uses incremental hashing so
  peak memory no longer keeps three full source copies.

### Changed
- CI pins `actions/checkout` to v7.0.1 and `actions/setup-python` to v7.0.0
  (SHA-pinned).

### Notes
- Still inert handoff only — not live process restore.
- Head-only probe / filesystem list fallback and full streaming show reducers
  remain follow-up work (Issues #7 / #8).

## [0.3.2] — 2026-07-24

### Fixed
- Generate `SHA256SUMS` with flat GitHub Release asset basenames rather than
  build-tree paths, so a normal downloaded release can be checked directly.
- Reject duplicate or unsafe release asset basenames before publishing.

### Added
- Dual-OS release smoke now copies the exact candidate into a flat download
  layout and validates every checksum with the platform-native checker.
- Recorded real host-native headless Skill invocation on all eight destination
  CLIs and exact `0.3.1` local plugin/extension installation on all seven
  supported native package surfaces.

## [0.3.1] — 2026-07-24

### Fixed
- Removed mistakenly scoped destination-host network and documentation-tool
  guidance. Those tools were used to research Qwen/Kimi behavior; they are not
  Portable Resume product features.
- Kept Qwen/Kimi scope explicit: offline context migration, destination
  installation, and inert handoff generation only.
- Added regression coverage so generated Skills and product documentation do
  not reintroduce the mistaken integration claim.

## [0.3.0] — 2026-07-24

### Added
- Qwen Code and current/legacy Kimi CLI session readers, destination profiles,
  synthetic fixtures, and isolated installed-runner coverage.
- Eight destination hosts × eight source adapters (**64 packaging and installed
  runner cells**), including direct skill installation guidance plus each
  host's documented marketplace/plugin route where one exists.
- Tag-gated release CI/CD with exact wheel/sdist smoke tests, host bundle
  assets, checksums, provenance evidence, GitHub attestations, GitHub Releases,
  and optional PyPI Trusted Publishing.
- A `quick-install` command for one or all destination hosts, plus 12
  release-checked localized quick-start guides (English, Traditional/Simplified
  Chinese, Japanese, Korean, Spanish, Brazilian Portuguese, French, German,
  Russian, Arabic, and Hindi).

### Fixed
- Installer verification is anchored to trusted rendered bytes and package
  identity; interrupted replacement and multi-root installs now restore prior
  state.
- Live SQLite opens pin a no-follow descriptor, eliminating the validation/open
  race.
- Bounded discovery no longer chooses `latest` from a lexical prefix, and
  Codex rollback/fallback handling no longer retains invalid suffix records or
  masks corruption.
- Installed runtime packaging now uses an explicit module/resource allowlist,
  and smoke validation checks structured source/session/content identity.

### Verification
- Release claims require the four canonical local gates plus dual-OS CI,
  exact-distribution smoke, artifact digests, and an archived Actions URL/SHA.
- Host UI natural-language/picker activation remains **not-run** until recorded
  separately; Cursor full bubble graph remains **not claimed**.

## [0.2.3] — 2026-07-22

### Added
- Claude large-session reads now use bounded head/tail metadata windows for listing and a private `0700`/`0600` stable snapshot for full recovery.
- Full Claude transcripts are streamed into a lightweight graph index with a separate 50,000-record ceiling; only the selected lineage is loaded for rendering.

### Fixed
- Claude sessions larger than the former 16 MiB single-record bound can now resume without fixed-tail truncation or a false `W_BROKEN_CHAIN`.
- Replay duplicates are accepted only when semantic content matches; envelope-only changes use the latest physical parent, while cross-type or content conflicts fail closed.
- Session qualification uses the first recorded primary cwd, so subagent and worktree cwd values do not reject the parent session or create false matches.

### Security
- Regular-file snapshots use descriptor-relative no-follow opens, repeated content/stat/membership verification, bounded retries, unconditional temporary cleanup, and immutable caller ceilings.
- Metadata window hashes are explicitly distinct from full-file content hashes, and overlapping head/tail bytes are deduplicated.

### Verification
- **211 tests**, secret/path gate, self-verify, real large-session structural E2E, and installed-runner smoke **36/36** pass locally.

## [0.2.2] — 2026-07-22

### Fixed
- `install --host all` now preflights every destination and rejects divergent host profiles that resolve to one physical directory (including symlink aliases) before writing any files.
- `verify --host <host>` now requires and verifies that host's exact ownership claim instead of accepting another host's manifest in a shared directory.
- Codex probing and listing now fall back from a repeatedly busy bounded SQLite snapshot to the same read-only, query-only live path used for oversized databases.
- OpenCode install guidance now calls out duplicate-name shadowing across its native, Claude-compatible, and agent-compatible discovery roots.
- Package metadata now reports the repository's actual Apache-2.0 license instead of MIT.

### Verification
- Local release gates: 196 tests, secret/path gate clean, and installed-runner smoke 36/36.

## [0.2.1] — 2026-07-21

Improve-deep hardening + installed-runner matrix smoke (still experimental).

### Added
- `scripts/smoke_installed_matrix.py` — **36/36** installed skill `run_reader` smoke (not host UI NL)
- `pyproject.toml` (stdlib package metadata, requires-python ≥3.11)
- `AGENTS.md`, `docs/host-ui-smoke.md`, `docs/release-claim.md`, `docs/research/cursor-bubble-schema.md`
- `plans/` improve-deep index (001–025)
- Adapter splits: `cursor_live.py`, `codex_sqlite.py`, `adapters/common.py`
- Cursor Desktop: best-effort multi-turn extraction from `composerData` (bubble **graph** still not claimed)
- Dual-OS **release claim** archive for CI run on SHA `2245516` (Ubuntu+macOS × 3.11/3.12)

### Fixed / hardened
- Install: path containment on verify/uninstall; orphan journal; no-follow hash/backup; empty-dir scope; runtime whitelist (exclude `install/`)
- Live: Cursor meta `stable_read_bytes` + blob `ORDER BY`; Cursor/Grok/AGY latest ranking; Codex large-DB query-only; ReadBudget record accounting; Grok coalesce cap; UUID case selection
- CI: Python **3.11 + 3.12** on Ubuntu and macOS
- Secrets: broader `check_secrets` + runtime PEM/Slack/AIza redaction patterns

### Honesty (unchanged gates)
- Host UI **NL/picker** activation: **not-run**
- Cursor full bubble graph: **not claimed**
- No PyPI CD

### Verification
```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

## [0.2.0] — 2026-07-21

First public multi-source **live list/show** release (experimental).

### Added
- Grok-style skill UX: `run_reader.py show|list [ref] --cwd` primary; request-v1 optional
- Per-host install guide + `install-resume-skills hosts`
- Live readers (partial, honest bounds):
  - Claude: cwd-slug discovery, attachment parent-chain bridge
  - Codex: SQLite column superset, cwd-scoped list, within-min≤0, unknown outer skip, compact/tools
  - Cursor CLI: `chats/*/store.db` + `meta.json` (`cursor-cli-store-v1`)
  - Cursor Desktop: App Support `composerHeaders` list + composerData text (`cursor-desktop-composer-v1`)
  - OpenCode: multi-GiB DB via query-only live SQLite
  - Antigravity: no-index brain scan + live USER_INPUT/PLANNER_RESPONSE streams
  - Grok: skip co-located files, cwd-prefer, oversized updates summary-only list
- Large-DB helpers: `query_only_live_sqlite` with WAL/SHM no-symlink checks
- Docs: `docs/install-hosts.md`, STATUS live-evidence tables, superpowers plans

### Security / honesty
- Still offline, no source CLI exec, inert handoff markers
- Live host UI activation (36 cells): **not-run**
- Cursor full bubble graph, dual-OS release claim: **not claimed**
- Clean-room: no copy of `~/.grok/bundled/skills/**`

### Verification
- `python3 scripts/self_verify.py` PASS
- `python3 scripts/check_secrets.py` CLEAN
- unittest suite green on release machine

## [0.1.0] — 2026-07-20

Initial open-source tree: six-source adapters, 36-cell packaging matrix, installer, fixtures, CI.
