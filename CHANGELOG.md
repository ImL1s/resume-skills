# Changelog

## Unreleased

- Installer coordinated shared-root upgrades now key on package identity as
  well as the human bundle version. Source-checkout builds that remain
  `0.4.3.dev0` can therefore atomically move every represented claim to a new
  commit payload with one manifest generation/publication; omitted claims and
  divergent alias payload identities still fail closed (#271).
- Windows installer DX now documents a dynamic Python user Scripts-directory
  lookup, explicit User PATH/new-shell setup, per-host verification, shared
  physical-root ownership, and the focused Windows evidence boundary. Static,
  content-free hints for `E_UNSAFE_PATH` and `E_VERIFY_MISMATCH` point operators
  to that workflow without exposing selected paths (#247).
- OpenCode live-WAL handling (#263): oversized/live SQLite families use a
  bounded, descriptor-pinned private snapshot only on Darwin with real APFS
  `fclonefileat`, same-volume private scratch, checksum-valid current-generation
  WAL prefix materialized through its last commit into the private clone,
  exact-vnode `/.vol` SQLite open, identity-bound cleanup, and one absolute
  deadline. Unsupported hosts remain closed as `E_SQLITE_LIVE_WAL`;
  independent qualified file-store/export providers remain usable with
  `W_SOURCE_PROVIDER_SKIPPED`. A real macOS/APFS CI proof explicitly checks and
  asserts the PR head, then archives content-free canonical JSON plus an
  exact-byte SHA-256 sidecar named for that same head; no source SQLite
  connection, SHM copy, WAL deletion,
  checkpoint, live-source `immutable=1`, or new dependency is used. The
  materialized private clone alone is opened `mode=ro&immutable=1` so a scratch
  pathname replacement cannot redirect SQLite and no private SHM is required.
  Cleanup rejects the first unknown scratch entry incrementally without an
  unbounded directory listing.
- SQLite-family initial state capture now participates in bounded retry
  accounting, preserving unsafe/limit/hot-journal hard failures and cleanup.
- Reconciled the two shipped schema warning enums with runtime `WARNING_CODES`
  and added an exact-set regression.
- Setuptools source-checkout upgrades now refresh only the generated
  `build_py` identity inside the reusable build staging tree before copying
  sources. A stale identity from an earlier commit no longer blocks
  `pipx install --force .`, while finalized artifact staging still refuses
  identity drift and symlinked/non-regular staging paths fail closed (#272).

## [0.4.2] — 2026-08-05

- **Security (installer P1):** pin POSIX multi-target / RootLock mutations to the
  locked skill-root **dirfd + (st_dev, st_ino)** so concurrent `rename` plus
  symlink or real-directory replacement at the frozen path cannot receive
  journal/manifest/payload/compensation writes without holding that tree’s lock
  (#255, PR #256). Leaf junction/symlink retarget chain #245–#253 remains closed;
  residual `recover_root` pathname reopen is follow-up only.
- Multi-target lock binding freezes `physical_key` before exclusive locks;
  replan/checkpoint/execute use that key (then the pin) rather than re-resolving
  caller leaf spellings (#251–#253).
- Installer verify/uninstall honesty after source-aware claims (#242 follow-up):
  recompute top-level `package_identity` when a claim is removed; parse
  `--sources` before shadow scan so expanded installs cannot skip new skill
  names; claimless generation-zero manifests no longer IndexError on verify.
- Installer selected-source verification (#240): ownership claims now record a
  normalized explicit source set, and read-only verify/discovery reconstruct the
  manifest-authoritative plan instead of assuming every enabled source. Legacy
  pre-field claims are inferred only from unambiguous owned `resume-*` paths;
  malformed, ambiguous, path-set, identity, hash, mode, or source metadata still
  fails closed.
- Grok `show` supports qualified **compaction v1** sessions (#238): allowlisted
  `compaction_checkpoint` events load a session-local sidecar under
  `compaction_checkpoints/`, project public user/assistant `compacted_history`,
  replace superseded pre-checkpoint turns, and continue with post-checkpoint
  public chunks. Real list-form text blocks are concatenated through the normal
  sanitizer; non-null `synthetic_reason` records and private roles (including
  string-form system content) are omitted.
  Multi-checkpoint reduction is sequential. Sidecar path escape, schema/id
  mismatch, and missing files fail closed. **`rewind_marker` remains unsupported.**

## [0.4.1] — 2026-08-04

- Windows mutating install productization (#125 Phases 1–7): Win32 exclusive
  lock, reparse-safe relative mutations, parent-chain defenses, adversarial
  product-path suite, and Policy B lift on real Windows (`os.name == "nt"` and
  `sys.platform` starts with `win`). Evidence: PR #228 / Actions run 30800595796.
- Platform honesty V1 desktop dual-OS (Windows native + macOS) (#209 reduced
  close): WSL2 / musl / FreeBSD–BSD remain **not-run** (no fake green).
- Windows CI hard gate is focused product-install smoke
  (`smoke_windows_product_install.py`, hosts claude/cursor/codex). Full
  306-cell `smoke_installed_matrix` remains the Ubuntu hard gate — Windows is
  **not** claimed 306/306.
- CI flake fix: list `--format json` / `--output` comparison ignores
  `generated_at` second-boundary drift (PR #232).
- Plan-pack historical banners for completed #125 phases; smoke fixture cwd
  host-normalization for POSIX project paths (PR #232/#233).

## [0.4.0] — 2026-08-01

- Codex busy/hot SQLite degrade (#196, #199): when `state_*.sqlite` is busy or has
  a hot journal, probe/list no longer hard-fail the whole source as
  `unsafe` / total `E_SOURCE_BUSY`. Capability falls through to bounded plain
  rollout discovery with envelope warning `W_STALE_INDEX`, so `/resume-codex`
  can recover parent sessions while Codex is still writing WAL.
- Codex `session_meta.source` dict hardening (#198, #199): non-string
  `payload.source` (live subagent objects) is treated as
  `E_UNSUPPORTED_FORMAT` instead of `TypeError` → opaque `E_INVARIANT`, so FS
  head discovery can skip subagent rollouts cleanly.
- Release identity hardening (#118): advance post-`v0.3.4` development to
  `0.4.0.dev0`; add a dependency-free build identity (commit/dirty state,
  registry digest, source digest, and non-package build-input digest), an
  immutable `v0.3.4` release baseline, and
  a fail-closed version-state gate so changed source cannot continue claiming an
  already-published exact version. Release validation now rejects `.devN`, pins
  all byte-producing jobs to the validated commit SHA, and rechecks the remote
  annotated tag before publish. Artifact builds now pin one canonical identity
  before producing bytes, embed the exact canonical JSON in wheel, sdist, 18
  direct-host ZIPs, and seven native package ZIPs, then cross-verify every
  artifact and installed runtime. Runtime lookup uses only the fixed embedded
  resource, never build-pin environment variables or Git; source checkouts keep
  an honest null-commit fallback. The runtime source digest is stable across
  installation permission modes, while the Git-only build-input digest still
  detects package mode drift before artifacts are produced. CI builds
  wheel/sdist twice with one pin and
  `SOURCE_DATE_EPOCH`, normalizes generated build permissions, requires
  byte-identical output even when the second build starts under `umask 077`, and
  proves the source tree was not mutated. Archive validation bounds compressed
  bytes, member count, total expanded bytes, and manifest reads; encrypted or
  unsupported-compression required members now produce validation failures
  instead of escaping as exceptions. Corrupt DEFLATE, BZIP2, LZMA, and
  Zstandard member payloads use the same bounded decoder-error boundary in
  package and artifact validation;
  unsupported ZIP metadata versions also return controlled failures before
  member reads begin. Truncated or corrupt gzip sdists likewise normalize
  decoder failures instead of emitting tracebacks. Offline package validation
  requires the current v2 identity schema for newly verified artifacts while
  legacy v1 identity loading remains available for runtime inspection. The host
  report is checked against
  registry-derived filenames, family paths, member counts, and canonical install
  hints. The new `MANIFEST.in` path uses `setuptools==83.0.0`, outside
  the affected range of
  [GHSA-h35f-9h28-mq5c](https://github.com/advisories/GHSA-h35f-9h28-mq5c).
  Repository-level immutable `v*` tag enforcement is active and verified by
  API readback as
  [ruleset `20148806`](https://github.com/ImL1s/resume-skills/rules/20148806):
  target `tag`, condition `refs/tags/v*`, update and deletion restrictions, and
  no bypass actors. No new release is claimed.
- GitHub Copilot CLI source (#44 Track B): `copilot-cli-events-jsonl-v1` reader for
  `$COPILOT_HOME/session-state/<id>/events.jsonl` (local authority; not session-store.db /
  Chronicle / cloud sync). Matrix is now **17×18=306**.
- Kilo CLI source qualification (#46 Track B PR 1): pin `@kilocode/cli` v7.4.17 at
  `a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7`; source enablement remains **NO-GO**
  until synthetic exact-schema fixtures prove `session_message`/event/projector authority,
  migration/cloud provenance, and Kilo↔OpenCode wrong-adapter rejection. Counts stay 17×18=306.
- Kilo CLI destination-only (#46 Track A): install into `.kilocode/skills` and
  `~/.config/kilo/skills` (`KILO_CONFIG_DIR` override). Source remains research —
  do not alias OpenCode storage. Matrix became **16×18=288**.
- Gemini CLI compatibility source + destination (#45): `gemini-cli-session-jsonl-v1`
  for `~/.gemini/tmp/<projectHash>/chats/session-*.jsonl` (independent of Antigravity).
  Destination `.gemini/skills` / `~/.gemini/skills`. Matrix became **16×17=272**.
- GitHub Copilot CLI destination (#44 Track A): install `resume-*` Skills into
  `.github/skills` and `$COPILOT_HOME/skills` (default `~/.copilot/skills`).
  Matrix became **15×16=240** (destination without source at that time).
- Hermes source + destination (#43): `hermes-state-sqlite-v1` reader for
  `~/.hermes/state.db` (schema version 23; root sessions; hide child/subagent).
  Destination install to `.hermes/skills` / `~/.hermes/skills`. Matrix is now
  **15×15=225**.
- OpenHands source + destination (#42): `openhands-cli-events-v1` reader for
  `~/.openhands/conversations/<id>/events/event-*.json` (local CLI only; no SDK
  import / cloud / ACP). Destination install to `.agents/skills` and
  `~/.openhands/skills`. Matrix is now **14×14=196**.
- Cline source + destination (#41): `cline-session-json-v1` reader for
  `~/.cline/data` (SQLite `sessions.db` index + authoritative
  `<id>.messages.json` v1); default list hides subagent/child sessions;
  destination install to `.cline/skills` and `~/.cline/skills`. Matrix is now
  registry-derived **13×13=169**. Native Cline UI activation remains not-run.


- Crush source + destination (#40): `crush-sqlite-v1` reader for per-project
  `.crush/crush.db` (pinned goose_db_version max 7); default list hides child
  sessions (`parent_session_id`); destination install to `.crush/skills` and
  `~/.config/crush/skills`. Matrix is now registry-derived **12×12=144**. Native
  Crush UI activation remains not-run.

### Security
- Installer control plane (#21): pin `.portable-resume`, no-follow regular-file
  opens for lock/journal/manifest, truncate lock metadata, and atomic journal/
  manifest replace via unique temps under the support directory.
- Installer payload plane (#31): rollback restore, orphan delete, uninstall, and
  verify use descriptor-relative no-follow walks under the skill root so
  parent-directory symlink swaps cannot redirect writes or deletes outside the
  root (POSIX). Windows remains fail-closed where dirfd support is absent (#29).

### Added
- goose source + destination (#39): `goose-sessions-sqlite-v15` reader for
  `sessions/sessions.db` (schema_version max 15); default list prefers
  `session_type=user` and hides scheduled/sub_agent/hidden/gateway/acp plus
  archived rows (exact id can still select them); destination filesystem
  install to `.goose/skills` and `~/.config/goose/skills`. Matrix is now
  registry-derived **11×11=121**. Legacy JSONL and native goose UI activation
  remain out of scope / not-run.
- OpenClaw source + destination (#37): `openclaw-agent-sqlite-v1` reader for
  per-agent `agents/<id>/agent/openclaw-agent.sqlite` (schema user_version 11);
  composite session ids `agentId:sessionId`; default list filters internal/cron
  runs; destination filesystem install to workspace `skills/` and
  `~/.openclaw/skills`. Native `openclaw skills install` / picker activation
  remains not-run.

### Fixed
- Grok ignored provider arrays (#178): exact show no longer applies the
  discovery `scanned_records` ceiling to non-public `rawOutput` list
  cardinality. Physical-line bytes, duplicate keys, nesting depth, map width,
  public allowlisted arrays, rewind, and compaction remain fail-closed; ignored
  provider payloads are never normalized into turns or handoffs.
- Claude exact-reference discovery (#19): absolute approved
  `projects/<slug>/<uuid>.jsonl` paths are validated/read without enumerating
  unrelated project directories; exact UUID + concrete cwd constructs the
  deterministic slug path first and only broad-scans when that candidate is
  absent or fails recorded-cwd validation (so a cwd-mismatched slug file
  cannot hide a relocated eligible copy). Broad fallback uses a bounded
  basename probe per project (no full per-project session scandir). Recorded
  primary cwd remains authoritative — slug name alone never selects.
  Discovery optimization only; graph/metadata-window behavior unchanged.
- Native package contracts (#27): versioned offline contracts per direct-skill
  and plugin/marketplace surface (`package-contracts-v1`); builder validates
  each archive (members, manifests, skills layout, marketplace source paths,
  forbidden install runtime) before reporting; `host-packages.json` is
  `host-packages-v2` with per-artifact `contract_id`, `offline_validation`,
  and explicit `native_evidence_status=not-run` (historical v0.3.2 ref only).
  Native CLI install/activate remains a separate evidence layer.
- Installer CLI contract (#32 Option A): install/verify/uninstall/recover/
  matrix/quick-install/audit-host always emit versioned
  `portable-resume/install-result-v1` JSON on stdout with a uniform `results`
  array (no silent no-op `--json`). `verify` no longer accepts `--dry-run`.
  `hosts` remains human by default with optional `--json`. Docs/scripts updated.
- Project-scope control state split (#33 Option A): mutable installer control
  files (manifest, lock, journal, backups, stage) live under
  `.portable-resume/.state/` with mode `0700` where supported; shareable
  payload remains `.portable-resume/runtime|resources` plus deterministic
  `.portable-resume/.gitignore` that ignores only `.state/`. Legacy v1 control
  files migrate into `.state/` under lock; verify dual-reads legacy paths.
  Absolute claim roots stay machine-local (never in committed payload).
  Residual: portable relative claim identity still uses absolute root strings
  inside gitignored manifest only.
- Discovery duplicate/shadow scan (#34): each host has executable
  `DiscoveryRoot` policy (primary + known alternates); `install` fails closed
  with `E_INSTALL_SHADOW` when a higher-precedence root holds a divergent
  `resume-*` Skill; equal-tier / unknown-precedence copies warn; identical
  payloads and same-physical shared roots allow. New read-only
  `install-resume-skills audit-host`; `verify` attaches a discovery report;
  `hosts --json` emits `discovery_roots`. Foreign roots stay read-only;
  no automatic delete. Follow-up: global install without `--project` scans
  CWD project roots; alternate malformed manifests warn not abort; user
  primary roots honor host env homes (`KIMI_CODE_HOME`). Residual: plugin
  tree wildcards, host-native activation provenance, versioned precedence
  evidence (#27).
- Collect-free `stable_scan_lines` (#10 residual): verified attempts spool lines
  (RAM spill to disk) and replay after fingerprint checks instead of retaining a
  full `list[ScannedLine]`. Mid-attempt output is still never exposed. Zstd
  whole-decompress for compressed Codex rollouts remains residual under #8.
- Host-neutral Skill payloads (#25): direct `resume-*/SKILL.md` no longer embeds
  host activation prose; all destinations share `agent-skills-portable-v1`
  package bytes so Codex + Antigravity (and other shared-root pairs) can claim
  one physical Skill tree. Host grammar stays in catalog / `hosts` / docs.
- Multi-root install locking (#23): `--host all` / multi-target install
  acquires exclusive locks on every unique physical root in canonical order
  before checkpoint or mutation; replans and compensates while locks remain
  held. Compensation refuses foreign digests outside the transaction allowed
  set. Same-process compensation only — per-root journals remain the durable
  crash boundary (not a durable multi-root coordinator).
- Installer uninstall/verify transactions (#22): `uninstall` is a journaled
  recoverable transaction (`operation=uninstall`) that snapshots sole-claim
  owned files before unlink; `recover` finishes published uninstalls or rolls
  incomplete ones back to the previous generation. Post-snapshot digest drift
  is retained (not rolled back over concurrent user edits). `verify` takes the
  exclusive root lock on POSIX only when a support tree already exists so
  never-installed roots stay observationally pure (Windows residual remains
  #29). Pending journals report `E_RECOVERY_REQUIRED`, not false drift.
- Destination root resolution (#24): global install honors documented host
  env homes (Kimi `$KIMI_CODE_HOME/skills`); isolation `--home` ignores host
  env overrides; `hosts --json` reports `global_root_source` / `project_root_source`.
- Grok/Antigravity large histories (#15): Grok list is metadata-first
  (`summary.json` + mtime; no full updates parse for list); Antigravity exact
  show no longer depends on optional `brain/index.json` rediscovery (soft stale
  on corrupt/oversized index); list/show stream-reduce without retaining every
  outer record.
- Codex streaming show (#8): plain rollout `show` streams via
  `stable_scan_lines` + attempt-local history reduce (no whole-file
  `stable_read_bytes` / full outer-record list); `updated_at` pinned to the
  scanned inode. Compressed rollouts still use trusted-zstd decompress + line
  parse. Large synthetic (~20 MiB) regression included.
- Codex probe/list discovery (#7): capability from SQLite signature without
  walking `sessions/`; probe uses a soft-capped sample (not full tree walk);
  plain rollout discovery uses byte-bounded `stable_read_windows` heads;
  filesystem head fallback when schema missing, paths unresolved/stale, or the
  recognized DB is under-filled (sparse index).
- Hosts report commands (#66): recommend installed `install-resume-skills` entrypoint
  with argv arrays; label source-checkout forms separately; scope shared-root
  warnings to selected host sets.
- CI de-duplication (#67): `scripts/self_verify.py` exposes named stages and
  profiles; GitHub Actions matrix uses `ci-compat` (suite once per cell) while
  docs/secrets run once in `quality`; package job depends on both.
- Reader CLI option honesty (#65): `self-check` uses a closed parser (no silent
  ignore of unknown args); `--request-file` rejects `--within-min`; `--format`
  includes explicit `table` and show rejects table.
- Capability registries package axis (#36): `PACKAGE_SURFACES` registers native
  package builders; `build_host_packages` is driven by enabled destinations +
  package surfaces; public schema source enum matches enabled sources (adds `pi`);
  self-check reports `package_surfaces`.
- Exact snapshot parent siblings (#16): exact stable reads and file snapshots
  re-pin only the target basename through the parent dir_fd; a parent with more
  than `scanned_records` unrelated siblings no longer fails with
  `E_LIMIT_EXCEEDED`. SQLite family state tracks only main/WAL/SHM/journal.
- Shared JSONL scan migrations (#10): Grok `updates.jsonl` and Antigravity
  `transcript.jsonl` show paths stream via `stable_scan_lines` under
  `source_read_bytes` / `transcript_records` (with Pi, Kimi, Cursor CLI, Qwen).
  Codex streaming show remains #8; true collect-free yield remains residual.
- Installer control-document schemas (#28): closed bounded JSON loader rejects
  duplicate keys/non-finite values; strict `Manifest.loads` / journal parse before
  recovery or durable write; schema errors map to content-free diagnostics.
- Install lock replan (#35): `execute_install` rebuilds the action plan under
  `RootLock` from the exact current ownership manifest and trusted package
  materialize; preflight `ActionPlan` is advisory. Base manifest digest is
  recorded; caller-tampered `plan.files` cannot be committed; claim-aware
  classification is shared by plan and execute.
- Handoff serialized output budget (#63): `handoff_output_bytes` is separate from
  recovered `normalized_content_bytes`. Schema-valid sessions no longer fail
  handoff solely because Markdown framing exceeds the content ceiling; recovered
  quotes shrink with `W_TRUNCATED` while security banner and checklist remain.
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
