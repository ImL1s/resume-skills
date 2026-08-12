# Source-format evidence registry

Adapters are clean-room compatibility readers built from public documentation/source shapes and independently authored synthetic fixtures. Source stores remain immutable; parser coverage is not a claim that vendor formats will never change.

| Source | Format ID(s) | Public evidence baseline | Status | Main limitation |
|---|---|---|---|---|
| Claude Code | `claude-jsonl-v1` | public docs + synthetic fixtures | supported (fixture/parser) | bounded live list uses metadata windows; show streams a bounded lineage |
| Codex | `codex-state-sqlite-v1`, `codex-rollout-jsonl-v1`, optional zstd | public Codex code/docs + fixtures | supported (fixture/parser) | bounded live support; missing `zstd` is partial; invalid rollback state fails closed |
| Cursor | CLI/Desktop fixture and live families | official docs/public stores + fixtures | supported (fixture/parser) | bounded live support; Desktop full bubble graph is not claimed |
| OpenCode | SQLite, file-store, export families | official docs/public code + fixtures | supported (fixture/parser) | bounded live support; unknown schemas fail closed |
| Antigravity | `antigravity-transcript-jsonl-v1` | official docs + fixtures | supported (fixture/parser) | bounded live support; index is a hint and fallback scan is bounded |
| Grok Build | `grok-updates-jsonl-v1` | Apache-2.0 public tree + fixtures | supported (fixture/parser) | bounded live support; installed bundled Skills are excluded as implementation sources |
| Qwen Code | `qwen-chat-jsonl-v1` | Qwen Code public tree at `713a083aea24ccb7b80db3e11abf2155b854a78c` + fixtures | supported (fixture/parser) | bounded live support; thought/tool/file/binary payloads are not replayed |
| Kimi Code / legacy Kimi CLI | `kimi-code-wire-jsonl-v1`, `kimi-legacy-context-jsonl-v1` | Kimi Code `a2401cc1ed26e5758c081e657bcff6a75cb061bb`; legacy Kimi CLI `4a550effdfcb29a25a5d325bf935296cc50cd417`; fixtures | supported (fixture/parser) | bounded live support; tool execution is never replayed |
| Pi | `pi-session-jsonl-v3`, `pi-session-jsonl-v2` | Pi public session-format docs + synthetic fixtures | supported (fixture/parser) | v3 primary; v2 read-only compat; destination filesystem install supported; native UI activation not-run |
| OpenClaw | `openclaw-agent-sqlite-v1` | OpenClaw public schema/session docs + synthetic fixtures | supported (fixture/parser) | per-agent SQLite under `agents/<id>/agent/openclaw-agent.sqlite`; destination filesystem install supported; native UI activation not-run |
| goose | `goose-sessions-sqlite-v15` | aaif-goose `CURRENT_SCHEMA_VERSION=15` + synthetic fixtures | supported (fixture/parser) | SQLite authority only; default list prefers `user` sessions; legacy JSONL out of scope; dest filesystem install supported; native UI not-run |

## Provenance anchors

Fixture `provenance_ref` values point to headings below. Every fixture manifest must contain `"synthetic": true`.

### foundation-only

Synthetic contract data used to test the reusable fixture-manifest validator; not evidence for an adapter.

### claude-claude-jsonl-v1

Claude Code projects JSONL. Synthetic fixtures: `tests/fixtures/claude/`.
Tool-call coverage uses assistant `tool_use` blocks with `caller`, `id`,
`input`, `name`, and `type`, paired to user `tool_result` blocks by
`tool_use_id`; real transcript content is not included.

### codex-codex-state-sqlite-v1

Codex state SQLite and rollout JSONL/zstd families. Synthetic fixtures: `tests/fixtures/codex/`.

### cursor-cursor-cli-chat-v1

Cursor CLI chat and Desktop composer families. Synthetic fixtures: `tests/fixtures/cursor/`.

### opencode-opencode-sqlite-v1

OpenCode SQLite, file-store, and export providers. Synthetic fixtures: `tests/fixtures/opencode/`.

- **SQLite list:** exact `query.ref` session IDs use `WHERE id = ?` before any
  newest-session `LIMIT` (issue #13).
- **SQLite show:** joined message/part rows use `transcript_records` with a
  `LIMIT n+1` overflow fail-closed path; discovery `scanned_records` is not the
  transcript ceiling.
- **File-store show:** supported layout is session-scoped
  `storage/message/<sessionID>/` and message-scoped `storage/part/<messageID>/`;
  show does not enumerate unrelated sessions.
- **Export:** an explicit export JSON document is bounded by
  `source_read_bytes` (one source document), not the single-record
  `record_bytes` ceiling.
- **Oversized live WAL (#263):** regular main/WAL/SHM members are pinned and
  validated before use. Darwin may recover through a real same-volume APFS
  `fclonefileat` of the pinned main descriptor plus a bounded checksum-valid
  current-generation WAL prefix in private `0700` scratch. The prefix is
  materialized through its last commit into the private clone; SQLite,
  integrity, schema, list, and show then access that exact private vnode through
  Darwin `/.vol`, never a replaceable pathname. Source SHM is validated but
  never copied, the private immutable open creates no SHM, and cleanup rejects
  the first unknown scratch entry without an unbounded listing. Unsupported
  hosts/capabilities return
  `E_SQLITE_LIVE_WAL` (`attempts: 0`). A qualified independent file-store or
  explicit export may still be listed/shown with `W_SOURCE_PROVIDER_SKIPPED`;
  its provider and source path remain authoritative. After quiescing, retry
  once; a persistent-WAL-mode main may remain unavailable on an unsupported
  host even after sidecars disappear, so use an eligible persisted fallback
  rather than deleting or checkpointing WAL manually.

### antigravity-antigravity-transcript-jsonl-v1

Antigravity transcript JSONL with optional index hints. Synthetic fixtures: `tests/fixtures/antigravity/`.

**CLI multi-lane (#248):** live Antigravity CLI under `~/.gemini/antigravity-cli` often leaves
`brain/<id>/.system_generated/logs/transcript.jsonl` as a zero-byte placeholder. When the
transcript has no records, the adapter falls back to:

1. `history.jsonl` — workspace + user display prompts + `conversationId`
2. `brain/<id>/.system_generated/messages/*.json` — visible agent messages (`hideFromUser` skipped)

Recovery sets warning `W_CLI_MESSAGES_LANE`. Legacy non-empty transcripts remain authoritative.
Fixture `s-ant-07` covers empty-transcript + history + messages.

### grok-grok-updates-jsonl-v1

Grok Build session `updates.jsonl`. Synthetic fixtures: `tests/fixtures/grok/`.
Show streams byte-bounded physical records and normalizes only allowlisted
update fields. Provider-private `rawOutput` stays omitted and does not borrow
the discovery `scanned_records` cardinality ceiling; duplicate keys, depth,
map width, and public-list cardinality still fail closed. **Qualified compaction
v1** (`compaction_checkpoint` + session-local sidecar, `schema_version: 1`) is
supported for public projection (#238). **`rewind_marker` and unqualified
compaction still fail closed.**

### qwen-qwen-chat-jsonl-v1

Qwen Code project `chats/*.jsonl` and bounded `chats/archive/*.jsonl` discovery, using current `{role, parts}` message envelopes. Synthetic fixtures: `tests/fixtures/qwen/`.

### kimi-kimi-code-wire-jsonl-v1

Current Kimi Code `$KIMI_CODE_HOME/session_index.jsonl` plus contained `sessions/.../agents/main/wire.jsonl`. Synthetic fixture: `tests/fixtures/kimi/s-kim-01/`.

### kimi-kimi-legacy-context-jsonl-v1

Legacy Python Kimi CLI `kimi.json` session metadata plus `sessions/<workdir-key>/<session>/context.jsonl`. Synthetic fixture: `tests/fixtures/kimi/s-kim-02/`.

### pi-pi-session-jsonl-v3

Pi agent session JSONL (version 3 tree with `id`/`parentId`). Default on-disk layout:
`agent/sessions/--<cwd-slug>--/<timestamp>_<uuid>.jsonl`. Synthetic fixtures:
`tests/fixtures/pi/`. A v2 tree compatibility fixture exists (`pi-session-jsonl-v2`);
v1 linear sessions are not fixture-covered yet. Destination filesystem install
to `.pi/skills` / `~/.pi/agent/skills` is supported on `main`; native Pi host
UI / picker activation evidence remains not-run (PR D).
`list` is metadata-lenient on interior corrupt lines (`W_BROKEN_CHAIN`); `show` fails closed with `E_CORRUPT_RECORD`.

### pi-pi-session-jsonl-v2

Pi session JSONL version 2 tree (`id`/`parentId` linking). Version 1 linear sessions may
auto-migrate on load upstream; fixtures here pin v2 only for compatibility testing.
Synthetic fixture: `tests/fixtures/pi/s-pi-05-v2-compat/`.

### openclaw-openclaw-agent-sqlite-v1

OpenClaw per-agent data-plane SQLite (`agents/<agent-id>/agent/openclaw-agent.sqlite`).
Public upstream references:

- Schema SQL: [openclaw-agent-schema.sql](https://github.com/openclaw/openclaw/blob/main/src/state/openclaw-agent-schema.sql)
- Session storage docs: [database-schemas](https://docs2.openclaw.ai/reference/database-schemas)

Fixtures pin `openclaw-agent-sqlite-v1` with `PRAGMA user_version = 11` and a minimal
subset of tables (`schema_meta`, `session_nodes`, `session_windows`, `conversations`,
`session_conversations`, `transcript_events`). All fixture payloads are synthetic
(`synthetic: true`). Adapter `openclaw` lists composite ids `agentId:sessionId`,
filters `internal`/`cron`/`spawn`/`run`/`plugin` by default, and shows message
events from the selected window only. Destination filesystem install uses
workspace `skills/` and `~/.openclaw/skills`. See `tests/fixtures/openclaw/`.

### goose-goose-sessions-sqlite-v15

Goose `sessions/sessions.db` SQLite store at schema version 15 (`schema_version`,
`sessions`, `messages`, `usage_ledger`). Upstream `session_type` values are snake_case
(`sub_agent`, `gateway`, `acp`, …). Synthetic fixtures: `tests/fixtures/goose/`.
Legacy JSONL session files are not fixture-covered. Adapter `goose` list prefers
`user` sessions and excludes `scheduled`, `sub_agent`, `hidden`, `gateway`, and `acp`
by default (exact id can still select them). Destination filesystem install uses
`.goose/skills` and `~/.config/goose/skills`.

## Clean-room boundary

Do not copy real transcripts, credentials, developer home paths, or `~/.grok/bundled/skills/**`. See [`provenance.md`](provenance.md), [`clean-room-attestation.md`](clean-room-attestation.md), and `NOTICE`.

## crush-sqlite-v1

- **Store:** per-project data directory `crush.db` (default `.crush/crush.db`)
- **Schema pin:** `goose_db_version.version_id` max = **7** (migrations through
  `20260127000000_add_read_files_table` upstream charmbracelet/crush)
- **Tables:** `sessions`, `messages` required; `files` / `read_files` optional and not loaded for handoff
- **Messages:** `parts` is a JSON array of `{type, data}` wrappers (`text`, `tool_call`,
  `tool_result`, `shell_command` admitted; reasoning/binary/image/finish skipped)
- **List policy:** root sessions only (`parent_session_id` empty); require extractable public turns
- **Roots:** `--source-root` as data dir, project root, or exact `crush.db`; without root, only `<cwd>/.crush`
- **Out of scope:** Crush CLI/serve/migrations/MCP; recursive home multi-project scan; parent session merge

## cline-session-json-v1

- **Store:** `~/.cline/data/db/sessions.db` (index) + `~/.cline/data/sessions/<id>/`
- **Authority:** `<id>.messages.json` (`version: 1`) is the transcript source of truth;
  SQLite is discovery/list only and never fabricates turns
- **List policy:** root sessions only (`parent_session_id` empty, `is_subagent=0`);
  require non-empty prompt or extractable public messages
- **Messages:** public `user`/`assistant`/`tool` text; skip synthetic user kinds
- **Roots:** `CLINE_DIR` / `~/.cline`, or `--source-root` as cline/data/db/sessions layout
- **Out of scope:** Cline hub/CLI/SDK, team merge, connectors, cloud fetch

## openhands-cli-events-v1

- **Store:** `~/.openhands/conversations/<id>/events/event-*.json` (OpenHands CLI LocalFileStore)
- **Authority:** ordered event JSON files; no SQLite transcript
- **Public turns:** `MessageEvent` with `source` user/agent and `llm_message.content` text
- **Omit:** system prompts, tools/actions/observations, condensations, token/stream/control events
- **Fail closed:** unknown content-bearing `kind` values
- **Roots:** `OPENHANDS_CONVERSATIONS_DIR` / `OPENHANDS_PERSISTENCE_DIR/conversations` / `~/.openhands/conversations`
- **Out of scope:** Cloud, GUI, ACP, SDK tool registration, organization skills

## hermes-state-sqlite-v1

- **Store:** `$HERMES_HOME/state.db` or `~/.hermes/state.db` (WAL SQLite)
- **Schema:** `schema_version` max = **23**; tables `sessions`, `messages` (+ optional FTS unused)
- **Authority:** SQLite only; legacy JSONL under `sessions/` is out of scope
- **List:** root sessions (`parent_session_id` empty, not archived); hide child/subagent by default
- **Show:** public `user`/`assistant`/`tool` message `content`; omit system_prompt, reasoning*, platform IDs
- **Privacy:** never surface `user_id`, `chat_id`, phone/channel tokens in summaries
- **Roots:** `HERMES_HOME` (absolute), `~/.hermes`, exact `state.db`, or `--source-root`
- **Out of scope:** Hermes CLI/gateway, Skill hub/taps, messaging retrieval, FTS search, migrations

## copilot-cli-events-jsonl-v1

- **Store:** `$COPILOT_HOME/session-state/<session-id>/events.jsonl` (default `~/.copilot/…`)
- **Authority:** local `events.jsonl` only; `session-store.db` is Chronicle/search index, not list/show authority
- **Public turns:** `user.message` / `assistant.message` string `data.content`; `tool.execution_start` tool names only
- **Omit:** `reasoningText`, tool args/results, hooks, subagent payloads, system/compaction/control events
- **cwd:** from `session.start` / `session.context_changed` context; filter when query.cwd set
- **Roots:** `COPILOT_HOME`, `~/.copilot`, `session-state/`, exact session dir, or exact `events.jsonl` (CLI `--source-root` accepts file or directory)
- **Destination:** supported as `github-copilot` (`.github/skills`, `$COPILOT_HOME/skills`)
- **Out of scope:** copilot CLI process, Chronicle reindex, cloud session sync, plugins

## kilo (research — not enabled)

- **Status:** research / not in enabled sources (#46 Track B); [v7.4.17 qualification](research/kilo-cli-v7.4.17-qualification.md) is **NO-GO for source enablement**
- **Pinned store:** Kilo v7.4.17 uses the XDG-derived `kilo` data root and normally `kilo.db` (`KILO_DB` may override); opening vendor services can create directories, checkpoint WAL, and migrate, so readers must never invoke them
- **Authority risk:** current CLI reads `session_message` by aggregate `seq`, while `event`/projectors and legacy `message`/`part` projections coexist; cloud import, legacy migration, and exact local provenance are not yet fixture-qualified
- **Blocker:** independently generate exact-version synthetic DB/WAL fixtures and prove a Kilo-specific signature, reduction, filtering, and wrong-adapter rejection; never assume OpenCode `opencode-sqlite-v1` authority
- **Destination:** supported as `kilo` (`.kilocode/skills`, `~/.config/kilo/skills`, `$KILO_CONFIG_DIR/skills`)
- **Out of scope until qualification:** source probe/list/show, marketplace remote skills, IDE/cloud surfaces

## gemini-cli-session-jsonl-v1

- **Store:** `~/.gemini/tmp/<projectHash>/chats/session-*.jsonl` (or `$GEMINI_CLI_HOME/.gemini/tmp/...`)
- **projectHash:** legacy pin is `sha256(projectRoot)` (hex); when `cwd` is provided, list/show restrict to matching hash(es) so `latest` cannot pick another project's session
- **Authority:** JSONL session log (chatRecordingService); metadata line + MessageRecord lines; `$set` / `$rewindTo` control
- **Public turns:** `type=user` and `type=gemini` text parts; tool names only when content empty
- **Omit:** `info`/`error`/`warning`, nested `thoughts`, account/OAuth files, Antigravity roots
- **List:** main sessions only (`kind!=subagent`); require a public user turn; cwd→hash filter when cwd set
- **Distinct from:** `antigravity-transcript-jsonl-v1` — never aliased
- **Lifecycle note:** consumer Login-with-Google for Gemini CLI ended 2026-06-18; Standard/Enterprise/API remain
- **Out of scope:** gemini CLI process, Google APIs, MCP, Antigravity stores
