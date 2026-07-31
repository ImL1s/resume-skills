# Kilo Code CLI v7.4.17 source qualification

Qualification date: **2026-07-31**

## Decision

**NO-GO for Kilo source enablement at v7.4.17.** Keep the `kilo` source profile in
`research`, with no format ID and no adapter. The released tree identifies the database
location and schema, but it does not establish a safe, deterministic transcript authority
across the synchronized event log, `session_message` operational history, and legacy
`message` / `part` projections.

**GO only to a clean-room synthetic-fixture qualification follow-up.** That follow-up may
construct fixtures and prove read-only selection rules. It must not register or ship a Kilo
source adapter until every reversal blocker below is closed.

| Pin | Qualified value |
|---|---|
| Product release | [`v7.4.17`](https://github.com/Kilo-Org/kilocode/releases/tag/v7.4.17) |
| CLI package | [`@kilocode/cli` `7.4.17`](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/package.json#L1-L21) |
| Release commit | [`a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7`](https://github.com/Kilo-Org/kilocode/commit/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7) |
| Root package | [`@kilocode/kilo` `7.4.17`](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/package.json#L168-L175) |

On the qualification date, the npm `latest` dist-tag and package metadata both returned
`7.4.17`; GitHub's `refs/tags/v7.4.17` was a direct commit ref to the full SHA above, whose
commit message is `release: v7.4.17`. This establishes the release-to-source mapping used
here; it does not qualify a later npm dist-tag or release.

All vendor-code citations below use that full commit SHA. Mutable `main`, later releases,
design intent, and current website text are not evidence for this decision.

## Claim boundaries

This record is a source inspection, not a runtime qualification.

- It does not invoke Kilo, open a live Kilo database, run vendor migrations, or copy a real
  transcript.
- It does not add fixtures, a source adapter, a format ID, or a supported registry entry.
- It does not prove CLI, IDE, cloud, marketplace, natural-language, picker, or live-host
  activation. Those remain **not-run**.
- It does not treat Kilo as an OpenCode storage alias, even though internal packages retain
  `@opencode-ai/*` names.

## Track A destination reconciliation

Track A remains destination-only. Its shipped installer roots are intentionally narrower
than the vendor's discovery surface:

- project: `.kilocode/skills`
- global default: `$HOME/.config/kilo/skills`
- explicit global override: `$KILO_CONFIG_DIR/skills`

The portable-resume resolver does **not** consume `XDG_CONFIG_HOME`; a non-default XDG
config root therefore requires an explicit `KILO_CONFIG_DIR`. This is a documented Track A
limitation, not a claim that Kilo itself ignores XDG.

The release source sets the XDG application name to `kilo` and separates data and config
paths ([`global.ts` lines 12-25](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/global.ts#L12-L25)).
`KILO_CONFIG_DIR` replaces only the config service path
([`global.ts` lines 75-87](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/global.ts#L75-L87)).
CLI discovery also scans `.kilocode` and `.kilo` project/home directories plus an explicit
`KILO_CONFIG_DIR`
([`config/paths.ts` lines 23-40](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/config/paths.ts#L23-L40)),
then looks for `{skill,skills}/**/SKILL.md`
([`skill/index.ts` lines 24-31](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/skill/index.ts#L24-L31),
[`lines 240-253`](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/skill/index.ts#L240-L253)).

The same-release user guide instead describes `.kilo/skills` and a simplified
project-over-global rule
([`skills.md` lines 122-155](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/kilo-docs/pages/customize/skills.md#L122-L155),
[`lines 210-220`](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/kilo-docs/pages/customize/skills.md#L210-L220)).
The implementation actually overwrites duplicate names in discovery order
([`skill/index.ts` lines 140-153](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/skill/index.ts#L140-L153)).
Therefore Track A uses a conservative subset: `.kilocode/skills`, the fixed
`$HOME/.config/kilo/skills` default, and the explicit `KILO_CONFIG_DIR` override. It does
**not** claim XDG-default parity, the guide's complete discovery surface, or a universal
precedence rule.

Activation evidence is source-inspected only. No live Kilo session or host UI was used.
The pinned guide's deterministic request is natural language: `Use the <skill-name>
skill.`; it does not document a stable `/skill <name>` command
([`skills.md` lines 30-44](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/kilo-docs/pages/customize/skills.md#L30-L44)).
For any later isolated activation smoke, keep the `skill` permission at explicit `ask`:
the Skill tool checks permission before loading, and unmatched permission rules also
default to `ask`
([`tool/skill.ts` lines 65-99](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/tool/skill.ts#L65-L99),
[`permission.ts` lines 102-111](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/permission.ts#L102-L111)).
Installation never runs `kilo run --auto`: `--auto` is a permission auto-approval flag
([`run.ts` lines 247-257](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/cli/cmd/run.ts#L247-L257)),
not a safe activation or verification mechanism.

## Released storage inventory

| Area | v7.4.17 evidence | Qualification result |
|---|---|---|
| Data root | XDG data path joined with app `kilo`; config is a separate XDG path ([`global.ts` lines 12-25](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/global.ts#L12-L25)). | Proven for the default local root. `KILO_CONFIG_DIR` is not a data-root override. |
| Database path | Stable channels use `<data>/kilo.db`. `KILO_DB` accepts `:memory:`, an absolute path, or a path relative to the data root; development channels can fall back to a pre-existing `opencode-<channel>.db` ([`database.ts` lines 46-63](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/database.ts#L46-L63)). | Proven path selection, but the OpenCode-named fallback prevents brand/name-only detection. |
| Open behavior | Database construction sets WAL, checkpoints it, requires writable access, and applies migrations ([`database.ts` lines 24-43](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/database.ts#L24-L43)). | Vendor database services are forbidden to a reader. A private, stable main/WAL snapshot is required. |
| Migration behavior | Empty databases receive the generated schema; existing `session` databases receive migrations; the migration journal can be seeded from `__drizzle_migrations` ([`migration.ts` lines 18-79](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/migration.ts#L18-L79)). | Schema is versioned by applied migration IDs, not a single qualified integer. Migration execution is out of scope. |
| Schema inventory | The generated release schema contains `project`, `project_directory`, `workspace`, `session`, `message`, `part`, `session_message`, `session_input`, `session_context_epoch`, `event_sequence`, `event`, `permission`, `session_share`, account/credential, and other control-plane tables ([`schema.gen.ts` lines 27-258](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/schema.gen.ts#L27-L258)). | Proven table inventory only. A Kilo signature must require the exact safe subset plus migration IDs and reject partial/superset ambiguity. |
| Session identity | `session` includes `project_id`, optional `workspace_id` / `parent_id`, directory, path, share URL, revert state, permission/model metadata, compaction time, and archive time ([`session/sql.ts` lines 21-65](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/sql.ts#L21-L65)). | Columns are proven; public list policy for child, archived, moved, reverted, workspace, and cloud-derived sessions is not. |
| Legacy transcript projection | `message` and `part` store JSON data with time/ID indexes ([`session/sql.ts` lines 67-97](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/sql.ts#L67-L97)). | Present, but not proven to be complete or canonical for v7.4.17. |
| Operational history | `session_message` stores a typed JSON message and nullable `seq`, with sequence and timestamp indexes ([`session/sql.ts` lines 118-137](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/sql.ts#L118-L137)). Operational history reads only non-null `seq`, orders ascending, and applies compaction/context-epoch filters ([`history.ts` lines 14-63 and 77-110](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/history.ts#L14-L63)). | Strong candidate for runtime context, not yet a qualified portable public transcript reducer. |
| Event log | `event_sequence` and `event` enforce aggregate sequence uniqueness ([`event/sql.ts` lines 4-24](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/event/sql.ts#L4-L24)). Event publication runs projectors, operational commit, sequence update, and event insert in one immediate transaction ([`event.ts` lines 258-371](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/event.ts#L258-L371)). | Event order is proven. Whether event replay, `session_message`, or `message` / `part` is the recovery authority is unresolved. |
| Projection relationship | The current runtime reads sequenced `session_message` history; the projector writes synchronized messages there while separate v1 events update `message` and `part` ([`history.ts` lines 33-90](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/history.ts#L33-L90), [`projector.ts` lines 117-228](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/projector.ts#L117-L228), [`lines 283-343`](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/projector.ts#L283-L343)). | Runtime preference is proven, but completeness across legacy/partial migration and a portable public-turn reduction are not. Conflicting projections must fail closed until fixtures define a rule. |
| Archive/delete/share | Archive is a timestamp field, projector deletion removes the `session` row, and `session_share` stores an ID, URL, and secret ([`session/sql.ts` lines 21-65](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/sql.ts#L21-L65), [`projector.ts` lines 256-281](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/session/projector.ts#L256-L281), [`schema.gen.ts` lines 231-240](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/schema.gen.ts#L231-L240)). | Archived rows need an explicit list policy; deleted rows must not be reconstructed from stale events; share data is private and never emitted. |
| Privacy-bearing rows | The generated schema places account access/refresh tokens and credential values in the same database ([`schema.gen.ts` lines 27-69](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/schema.gen.ts#L27-L69)); `session_share` stores a share secret ([`lines 231-240`](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/schema.gen.ts#L231-L240)). | A reader must never emit these fields. Row-level allowlists and redaction tests are mandatory before enablement. |
| Cloud/sync surface | `--cloud-fork` imports a cloud session and returns a new local session ID, while event sequences can carry an owner ID ([`cloud-session.ts` lines 16-39](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/kilocode/cloud-session.ts#L16-L39), [`event/sql.ts` lines 4-8](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/event/sql.ts#L4-L8)). | A qualified local-row marker for local creation versus cloud import, remote placeholder, shared copy, or sync ownership was not found. No network fetch is allowed. |
| Legacy compatibility | Startup can create `<db>.json-migration`, initialize/migrate SQLite, and import legacy `${data}/storage` JSON; failures leave the marker for retry ([`json-migration.ts` lines 71-159](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/kilocode/storage/json-migration.ts#L71-L159)). A legacy session may also have an empty directory ([`database/path.ts` lines 43-59](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/core/src/database/path.ts#L43-L59)); `session_message.seq` is nullable for released-client compatibility. | A pending marker, empty directory, or null sequence must not be silently treated as a complete current transcript. CWD and migration/fallback policy remain unqualified. |

The release also contains a contradictory migration signal: the storage-removal spec says
`packages/opencode/src/storage/db.ts` was deleted
([`remove-opencode-db.md` lines 220-226](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/specs/storage/remove-opencode-db.md#L220-L226)),
but that file is present at the same commit and still implements Kilo/OpenCode path fallback
and migrations
([`storage/db.ts` lines 1-61](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/storage/db.ts#L1-L61)).
The shipped tree, not the spec status text, controls this qualification.

## OpenCode profile divergence

This comparison is against this repository's shipped OpenCode reader, not a generic claim
about all OpenCode versions.

| Contract | Repository OpenCode profile | Kilo v7.4.17 | Classification | Consequence |
|---|---|---|---|---|
| Profile identity | `opencode` owns `opencode-sqlite-v1`, `opencode-file-store-v1`, and `opencode-export-file-v1` in `src/portable_resume/registry.py`. | `kilo` remains `research` with no format IDs. | **Different** | Keep distinct source keys, provider identities, and format IDs. |
| Roots and overrides | Default OpenCode source root is the XDG `opencode` data directory; `--source-root` can explicitly contain discovery. | XDG app is `kilo`; `KILO_DB` changes the database candidate and `KILO_CONFIG_DIR` changes only Skill/config roots. | **Different** | Never search OpenCode roots for Kilo or confuse config and data overrides. |
| Database names | OpenCode accepts `opencode.db` / `opencode.sqlite`. | Stable Kilo uses `kilo.db`; a dev channel may reuse `opencode-<channel>.db`. | **Different** with an ambiguous compatibility fallback | Filename is neither sufficient acceptance nor rejection evidence. |
| SQLite signature | OpenCode requires the closed `session` / `message` / `part` relations. | Kilo adds `migration`, `event` / `event_sequence`, and sequenced `session_message` while retaining `message` / `part`. | **Different** | Never route Kilo through `opencode-sqlite-v1` by structural coincidence. |
| Schema version/migrations | The repo's OpenCode contract recognizes only its closed column signature; it does not run vendor migrations. | Kilo uses generated schema plus named migration rows and can bridge `__drizzle_migrations`. | **Different**; exact accepted Kilo migration set **unknown** | Add a profile-specific migration/signature gate. |
| Transcript authority | OpenCode reads fixture-pinned `message` / `part` JSON. | Current Kilo runtime reads `session_message`, with event and v1 projections coexisting. | **Different** | Do not share transcript reducers or authority rules. |
| Ordering | OpenCode orders messages by creation time/ID and parts by ID in its fixture-backed contract. | Current Kilo history orders non-null aggregate `seq` and applies compaction/context-epoch filters. | **Different** | Kilo needs its own reducer and overflow tests. |
| Selection/children | OpenCode's accepted schema does not require Kilo's workspace, parent, archive, sync-owner, review, or control-plane classifications. | Kilo stores `parent_id`, workspace, archive, agent/model, path, and other state. | **Different** fields; filtering policy **unknown** | Define root/child/review/worktree/cloud rules before `LIMIT`. |
| Cloud/sync | OpenCode reader has no cloud fetch and treats only its local fixture-backed families as authority. | Kilo can import a cloud session locally and stores synchronized owner/event state. | **Different**; local provenance **unknown** | Fail closed on unqualified cloud/sync states; never fetch. |
| Non-SQLite families | OpenCode has fixture-pinned file-store and explicit-export providers. | No Kilo-owned file-store or export authority is qualified here. | **Different** | Do not inherit OpenCode fallback discovery. |
| Skill discovery/activation | Repo destination profile uses OpenCode-specific roots and activation guidance. | Kilo uses the separately pinned `.kilocode`/XDG config roots, compatibility scans, named natural-language request, and `skill: ask`. | **Different** | Source or destination evidence never crosses profile names by assumption. |
| Fixtures | `tests/fixtures/opencode/` contains synthetic supported and drift fixtures. | No Kilo source fixture exists in this decision record. | **Different** | OpenCode fixtures are negative/divergence inputs only, not Kilo provenance. |
| Process boundary | The OpenCode reader never invokes OpenCode or opens the live database through vendor services. | Kilo bootstrap performs telemetry and legacy/auth migration ([`index.ts` lines 84-87](https://github.com/Kilo-Org/kilocode/blob/a0364858a6e1b69a2e2dc5434a82d5cefbe79ea7/packages/opencode/src/index.ts#L84-L87)). | Kilo implementation **unknown** because none exists | Reuse only the generic no-CLI/private-snapshot policy; invoking Kilo is prohibited. |

## Reversal blockers

Source enablement can change to GO only after an exact-version follow-up proves all of the
following without running vendor code:

1. **Authority:** choose `session_message`, `event`, or `message` / `part` as the source of
   public turns and define a fail-closed conflict rule for the other projections.
2. **Reduction:** fixture-pin message types, public text extraction, tool-name-only policy,
   compaction/context-epoch handling, revert/rewind behavior, incomplete turns, and stable
   sequence ordering.
3. **Selection:** define exact-ID, latest, CWD, project/workspace, root-vs-child, archived,
   shared, moved, and empty-directory behavior before applying limits.
4. **Local-only boundary:** distinguish a complete local session from remote, cloud-fork,
   shared, sync-owner, or placeholder state without network access.
5. **Privacy:** prove that account, credential, permission, model/provider, reasoning,
   system, share-secret, token, attachment, and sync metadata cannot enter summaries or
   handoffs.
6. **Immutable SQLite reads:** prove a stable no-follow private snapshot of the main/WAL
   family, including busy/race/size failures, without Kilo database initialization,
   checkpointing, migration, or source mutation.
7. **Version gate:** identify the migration IDs/schema signatures accepted for v7.4.17 and
   fail closed on older, newer, partial, and internally contradictory layouts.
8. **Adapter separation:** prove Kilo-only fixtures are rejected by OpenCode and
   OpenCode-only fixtures are rejected by Kilo.

## Clean-room fixture follow-up

The approved follow-up is documentation-and-fixture qualification, not source release:

1. Hand-author SQLite DDL from the immutable public schema links above. Do not run Kilo,
   import its runtime, or copy vendor/real databases.
2. Mark every fixture manifest `"synthetic": true` and reference a new Kilo provenance
   heading in `docs/source-formats.md`. Use invented IDs, paths, content, and secrets.
3. Create separate fixture families for:
   - consistent sequenced `session_message` plus event rows;
   - conflicting `session_message` versus `message` / `part` projections;
   - nullable sequence, compaction/context epoch, parent, archive, revert, share, and empty
     directory cases;
   - child/subagent, review, worktree, internal/control-plane, deleted, empty, cloud-import,
     sync-owner, and remote-placeholder rows with explicit fail-closed expectations;
   - ordered user/assistant/system/tool/reasoning/file/attachment variants, keeping only
     public text and bounded tool names under the eventual allowlist;
   - account/credential/share-secret decoys that must never appear;
   - main database plus WAL, busy/race, oversized, unknown-migration, and corrupt cases;
   - Kilo-only and OpenCode-only wrong-adapter rejection in both directions.
4. Before any adapter is registered, test probe/list/show, exact-ID-before-limit, ordering,
   CWD and child/archive filters, privacy allowlists, bounded snapshots, no-follow reads,
   source immutability, and the no-source-CLI-exec gate.
5. Re-run the registry-derived installed matrix only after a separate implementation PR.
   This research record does not change the current source count or claim a new cell.

Synthetic fixture conformance will prove only the pinned reader contract. It will not be
live-host, native activation, Cloud, IDE, marketplace, or future-version compatibility
evidence.

Generic SQLite snapshot, bounds, diagnostic, sanitization, and path-containment helpers may
be reused. OpenCode provider signatures, format IDs, discovery roots, transcript reducers,
and fixtures may not be reused as Kilo authority.
