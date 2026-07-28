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
| OpenClaw | `openclaw-agent-sqlite-v1` | OpenClaw public schema/session docs + synthetic fixtures | planned (fixtures-only) | no adapter; per-agent SQLite under `agents/<id>/agent/openclaw-agent.sqlite` |
| goose | `goose-sessions-sqlite-v15` | aaif-goose `CURRENT_SCHEMA_VERSION=15` + synthetic fixtures | planned (fixtures-only) | SQLite authority only; legacy JSONL out of scope; adapter not landed (#39) |

## Provenance anchors

Fixture `provenance_ref` values point to headings below. Every fixture manifest must contain `"synthetic": true`.

### foundation-only

Synthetic contract data used to test the reusable fixture-manifest validator; not evidence for an adapter.

### claude-claude-jsonl-v1

Claude Code projects JSONL. Synthetic fixtures: `tests/fixtures/claude/`.

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

### antigravity-antigravity-transcript-jsonl-v1

Antigravity transcript JSONL with optional index hints. Synthetic fixtures: `tests/fixtures/antigravity/`.

### grok-grok-updates-jsonl-v1

Grok Build session `updates.jsonl`. Synthetic fixtures: `tests/fixtures/grok/`.

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
(`synthetic: true`); no adapter is registered yet. See `tests/fixtures/openclaw/`.

### goose-goose-sessions-sqlite-v15

Goose `sessions/sessions.db` SQLite store at schema version 15 (`schema_version`,
`sessions`, `messages`, `usage_ledger`). Upstream `session_type` values are snake_case
(`sub_agent`, `gateway`, `acp`, …). Synthetic fixtures: `tests/fixtures/goose/`.
Legacy JSONL session files are not fixture-covered. Future adapter `list` should prefer
`user` sessions and exclude `scheduled`, `sub_agent`, `hidden`, `gateway`, and `acp` by
default unless explicitly requested.

## Clean-room boundary

Do not copy real transcripts, credentials, developer home paths, or `~/.grok/bundled/skills/**`. See [`provenance.md`](provenance.md), [`clean-room-attestation.md`](clean-room-attestation.md), and `NOTICE`.
