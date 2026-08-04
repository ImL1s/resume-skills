# Conversation storage and transcript authority matrix

Portable Resume does not treat every local coding-agent store as a generic chat log.
Each source has a different division of responsibility between discovery indexes,
transcript authority, branch or rollback controls, metadata, and provider-private state.

This document records the current adapter-oriented model for all enabled sources and
for Kilo, which is destination-only while its source authority remains under research.
It complements [`source-formats.md`](source-formats.md): that file pins format IDs and
provenance; this file explains how the stores behave as conversation histories.

## Core rule: locate, reduce, then normalize

A safe handoff follows this pipeline:

```text
bounded discovery
    -> select one session
    -> read the authoritative transcript surface
    -> apply branch / rewind / compaction semantics
    -> omit private and non-public records
    -> normalize user / assistant / tool turns
    -> emit inert, untrusted handoff context
```

Three concepts must remain separate:

- **Discovery index** locates and ranks sessions. It may be stale and may not contain
  the complete conversation.
- **Transcript authority** is the file, table, or event family from which public turns
  are recovered.
- **Timeline reducer** decides which physical records are still part of the active
  logical history after forks, rewinds, rollbacks, compactions, clears, or tombstones.

A matching filename, SQLite table name, or JSON role field is not enough to prove
transcript authority.

## Recovery classes

These classes describe current recovery behavior, not registry support status.

| Class | Meaning |
|---|---|
| **Active-lineage reducer** | The adapter has fixture-backed logic for selecting the active branch or applying supported timeline mutations. |
| **Authoritative projection** | The selected source is already a deterministic public-message projection; no separate branch reducer is currently required. |
| **Bounded public-text extraction** | Public text is safely extracted, but one or more timeline-control semantics are not yet qualified as full active-context parity. |
| **Partial graph recovery** | Metadata and some text are recoverable, but the complete graph or blob authority is explicitly not claimed. |
| **Research** | Store location or schema is known, but transcript authority is unresolved and no source format is enabled. |

## Matrix

| Source | Default local layout | Transcript authority | Timeline model | Current recovery class |
|---|---|---|---|---|
| Claude Code | `~/.claude/projects/<cwd-slug>/<uuid>.jsonl` | Session JSONL | `uuid` / `parentUuid` tree, replay bridges, sidechains | Active-lineage reducer |
| Codex | `~/.codex/state_N.sqlite` plus `sessions/**/rollout-*.jsonl[.zst]` | Rollout JSONL or zstd JSONL; SQLite is the session index | Event stream with replacement history and rollback events | Active-lineage reducer |
| Cursor | `~/.cursor/chats/.../store.db`; Desktop `User/globalStorage/state.vscdb` | CLI `store.db`; Desktop composer blobs are only partially qualified | CLI projection; Desktop bubble/composer graph | Authoritative projection for CLI; partial graph recovery for Desktop |
| OpenCode | `~/.local/share/opencode/{opencode.db,opencode.sqlite}` or `storage/{session,message,part}` | Selected SQLite, file-store, or explicit export family | Ordered session/message/part projection | Authoritative projection |
| Antigravity | `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript.jsonl` | `transcript.jsonl`; `brain/index.json` is only a hint | Linear transcript or live step stream | Bounded public-text extraction |
| Grok Build | `~/.grok/sessions/<encoded-cwd>/<id>/updates.jsonl` | `updates.jsonl`; `summary.json` is metadata; optional `compaction_checkpoints/` | Chunked session updates; qualified compaction v1 (#238); rewind still fail-closed | Bounded public-text extraction with fail-closed timeline controls |
| Qwen Code | `~/.qwen/projects/<project>/chats/*.jsonl` and `chats/archive/*.jsonl` | Chat JSONL | Repeated-fragment aggregation plus `uuid` / `parentUuid` tree | Active-lineage reducer |
| Kimi Code / legacy Kimi CLI | `~/.kimi-code/session_index.jsonl` plus `sessions/.../agents/main/wire.jsonl`; legacy `~/.kimi/kimi.json` plus `context.jsonl` | Current `wire.jsonl`; legacy context/wire JSONL | Append-only current wire with control records; legacy message/event families | Bounded public-text extraction; active-control qualification tracked in #200 |
| Pi | `~/.pi/agent/sessions/--<cwd-slug>--/*.jsonl` | Versioned session JSONL | `id` / `parentId` tree with compaction nodes | Active-lineage reducer |
| OpenClaw | `~/.openclaw/agents/<agent>/agent/openclaw-agent.sqlite` | `transcript_events` for the selected session window | SQLite event graph with parent links, historical windows, and compaction | Active-lineage reducer |
| goose | `~/.local/share/goose/sessions/sessions.db` | `sessions` and `messages` tables | Ordered SQLite message projection | Authoritative projection |
| Crush | `<project>/.crush/crush.db` | `sessions` and `messages.parts` | Ordered project-local SQLite message projection | Authoritative projection |
| Cline | `~/.cline/data/db/sessions.db` plus `data/sessions/<id>/<id>.messages.json` | `<id>.messages.json`; SQLite is discovery only | Versioned message document | Authoritative projection |
| OpenHands CLI | `~/.openhands/conversations/<id>/events/event-*.json` | Ordered event JSON files | Linear event sequence; only public `MessageEvent` records become turns | Authoritative projection |
| Hermes Agent | `~/.hermes/state.db` | Active rows in `sessions` and `messages` | Ordered SQLite message projection | Authoritative projection |
| GitHub Copilot CLI | `~/.copilot/session-state/<uuid>/events.jsonl` | `events.jsonl`; `session-store.db` is Chronicle/search only | Session events with optional parent-linked active lineage | Active-lineage reducer |
| Gemini CLI | `~/.gemini/tmp/<projectHash>/chats/session-*.jsonl` | Session JSONL | Message map plus `$set` and `$rewindTo` state mutations | Active-lineage reducer |
| Kilo CLI | XDG `kilo` data root, normally `kilo.db`, with optional `KILO_DB` override | Unresolved across `event`, `session_message`, and `message` / `part` | Event sourcing plus synchronized and legacy projections | Research; Track B2 is #202 under #46 |

## Source details

### Claude Code

Claude Code stores one project-scoped JSONL file per session. Conversation records carry
stable node IDs and parent links, so physical file order alone is not the active
conversation. The adapter indexes the graph, skips sidechains, walks the selected leaf,
and permits non-rendered bridge nodes to connect public turns. Replayed nodes may replace
an earlier physical edge only when their semantic content remains consistent.

Tool calls are correlated through `tool_use` and `tool_result` identifiers. Thinking,
redacted thinking, signatures, system/control records, and binary content are omitted.

### Codex

Codex separates session discovery from transcript content. `state_N.sqlite` contains thread
metadata and a rollout path, while the rollout JSONL contains the actual event history.
Plain and optional zstd-compressed rollouts share the same logical model.

The reducer applies supported timeline mutations rather than emitting every physical row:

- compacted replacement history rebuilds the current history;
- rollback events remove the affected trailing user turns and their descendants;
- response items produce public message and bounded tool records;
- session metadata validates session identity, source, and CWD.

An unresolved or unsafe rollout path cannot be replaced by metadata-only fabricated turns.

### Cursor

Cursor currently spans several storage generations.

#### Cursor CLI

A current CLI session commonly uses:

```text
~/.cursor/chats/<md5-cwd>/<session-uuid>/
    meta.json
    store.db
```

`meta.json` supplies optional title, CWD, and timestamps. The `blobs` table in `store.db`
contains bounded JSON message records and is the transcript surface for this provider.

#### Cursor Desktop

Desktop stores composer metadata in platform-specific `User/globalStorage/state.vscdb`
files. Public text may be reachable through composer/KV blobs containing structures such
as `conversation`, `messages`, `bubbles`, maps, tabs, or nested state objects.

The current reader intentionally keeps `W_MISSING_BLOB`: recursive best-effort text
recovery is not proof of the complete bubble graph, active tip, or parent lineage. Exact
schema, blob-key, and branch qualification is tracked in #201.

### OpenCode

OpenCode supports three independently signed provider families:

- SQLite `session`, `message`, and `part` tables;
- the legacy `storage/session`, session-scoped `storage/message/<sessionID>`, and
  message-scoped `storage/part/<messageID>` tree;
- an explicit closed-shape export document.

The selected provider is authoritative for that invocation. Reasoning, control,
system, binary, file, image, audio, video, and attachment parts are omitted. Unknown
schemas are rejected rather than guessed from similar table names.

### Antigravity

Antigravity stores conversation transcripts below `brain/<conversation-id>` and may keep a
`brain/index.json` discovery hint. The transcript file remains authoritative when the
index is missing, stale, or corrupt.

The reader handles both normalized `session` / `message` / `tool` records and live step
streams such as user input, planner response, file/search/action, command, and subagent
steps. The live stream is normalized as bounded inert context; a complete vendor branch
model is not claimed.

### Grok Build

Grok Build groups sessions under percent-encoded CWD buckets. `summary.json` and `.cwd`
provide metadata or fallback path information, while `updates.jsonl` contains chunked
session updates.

Consecutive user or agent message chunks are coalesced. Public tool titles/results are
bounded, provider-private `rawOutput` is omitted, and encrypted-looking payloads are not
surfaced. Qualified **compaction v1** (`compaction_checkpoint` + session-local
`compaction_checkpoints/<file>` sidecar, `schema_version: 1`) replaces the active public
projection with allowlisted user/assistant history from `compacted_history`, then continues
reducing later `updates.jsonl` records (#238). System/developer/reasoning/tool sidecar roles
are omitted. Entries with a non-null `synthetic_reason`, including `compaction_meta`,
`project_instructions`, and `system_reminder`, are treated as synthetic control metadata:
their shape is validated but neither the reason nor their content is rendered. Only text
blocks from user/assistant entries with an absent or null reason enter the public projection;
known binary blocks are omitted. Missing, escaping, mismatched, or wrong-version sidecars
fail closed.
**`rewind_marker` remains unsupported** (fail closed).

### Qwen Code

Qwen Code chat JSONL can contain multiple physical fragments for one logical UUID.
The adapter first aggregates compatible repeated UUID records, rejects conflicting
fragments, then walks the latest complete parent-linked branch. Archived chats are a
separate bounded discovery surface.

Thoughts, function payloads, files, inline binary data, video metadata, code-execution
artifacts, and session-artifact control rows are omitted.

### Kimi Code and legacy Kimi CLI

Current Kimi Code uses an append-only `session_index.jsonl` as a discovery hint and reads
the selected session's `agents/main/wire.jsonl`. Index deletion tombstones must prevent
filesystem fallback from resurrecting deleted sessions. Legacy Kimi CLI uses `kimi.json`
for work-directory/session metadata and reads `context.jsonl` or legacy `wire.jsonl`.

Current extraction understands public append-message, loop content, and tool-result
families, plus preceding wire-event formats. Control records including compaction, clear,
and undo are recognized but are not yet qualified as a complete active-context reducer.
That focused work is #200.

### Pi

Pi stores a versioned session header followed by parent-linked entries. The adapter uses
the last persisted node as the candidate tip and walks `parentId` to the root. Compaction
nodes can redirect the walk to a retained entry and emit a bounded summary as assistant
context. Visible custom messages are marked so they do not incorrectly become the last
authored user request.

### OpenClaw

OpenClaw uses one SQLite database per agent. Session nodes identify the current session
window; historical windows remain reachable by exact ID. `transcript_events` is ordered by
sequence and can contain message, custom-message, compaction, and branch-summary nodes.

When stable IDs and parent IDs are present, the reader selects the latest graph leaf and
walks its ancestry. Branch summaries participate in lineage selection without becoming
public turns. Compaction can retarget ancestry through retained entry IDs or SQL sequence
positions.

### goose

goose stores schema-versioned sessions and messages in `sessions/sessions.db`. The SQLite
rows are the authority. Default listing prefers root user sessions and excludes scheduled,
sub-agent, hidden, gateway, ACP, and terminal sessions; exact IDs may still reach them.

`content_json` is decoded as bounded text parts. Malformed content cannot be silently
skipped when it would let an older session win `latest` selection.

### Crush

Crush stores a project-local `crush.db`. Root sessions are selected from `sessions`, and
`messages.parts` contains typed JSON wrappers. Public text, tool result, tool call name and
input, and shell command/output can become turns; reasoning, binary, image, and finish
parts are omitted.

CWD provenance comes from the `.crush` project layout, not from copying the caller's
requested CWD into output.

### Cline

Cline deliberately separates its session index from transcript authority:

```text
~/.cline/data/db/sessions.db
~/.cline/data/sessions/<id>/<id>.json
~/.cline/data/sessions/<id>/<id>.messages.json
```

The SQLite row and optional manifest support discovery and metadata. Only the versioned
messages document can produce turns. Synthetic user notices for compaction, reminders,
loop detection, and recovery are filtered rather than presented as authored requests.

### OpenHands CLI

OpenHands CLI stores one ordered JSON file per event. Only public `MessageEvent` records
whose source is user or agent/assistant are normalized. System prompts, actions,
observations, tool-control events, condensation, streaming/token events, hooks, errors,
and completion logs are omitted.

An unknown event that appears content-bearing fails closed because silently ignoring it
could drop part of the conversation.

### Hermes Agent

Hermes uses `state.db` as the sole current authority; legacy session JSONL and FTS tables
are outside this adapter. Default listing keeps non-archived root sessions with an active
public user turn. Message rows with user, assistant, tool, tool-result, or function roles
can become normalized turns.

System prompts, reasoning, account/platform identifiers, user/chat IDs, phone/channel
tokens, and other messaging-private fields are never session output.

### GitHub Copilot CLI

Copilot CLI stores complete local session events in
`session-state/<session-id>/events.jsonl`. `session-store.db` is a Chronicle/search index
and cannot fabricate turns.

Public message events contain user or assistant text. Tool-start events contribute only a
bounded tool name, not arguments or results. Session start/context-change events update
CWD and branch metadata. When event IDs and parent IDs are available, abandoned branches
are excluded by walking the active lineage.

### Gemini CLI

Gemini CLI groups chats by a project hash derived from the project-root string. Discovery
accounts for path spelling differences such as macOS `/tmp` and `/private/tmp` aliases.
Main sessions live directly in `chats`; subagents may live below a parent-session folder
and are hidden from default listing.

The JSONL reducer maintains an ordered message map:

- `$rewindTo` drops messages after the target;
- `$set.messages` replaces the current message collection;
- later records with an existing message ID update content without changing order.

Only user and Gemini public text become message turns; tool-only Gemini rows may contribute
bounded tool names.

### Kilo CLI

Kilo's database path and table inventory are known for the pinned qualification, but its
recoverable transcript authority is unresolved across:

- aggregate `event` / `event_sequence` history;
- sequenced operational `session_message` history;
- legacy or compatibility `message` / `part` projections.

The same database also contains privacy-bearing account, credential, share, permission,
worktree, review, and cloud/sync state. Kilo therefore remains a research source with no
format ID or adapter. Exact-version synthetic DB/WAL authority qualification is #202,
under the broader #46.

## Cross-source lessons

### Indexes cannot fabricate transcripts

Codex SQLite, Cline SQLite, Kimi's session index, Antigravity's brain index, Grok summaries,
and Copilot Chronicle data can help locate a session. They do not authorize inventing
turns when the selected transcript is missing or inconsistent.

### Physical order is not always logical history

Claude, Qwen, Pi, OpenClaw, Copilot, Codex, and Gemini all require some form of lineage or
state reduction. A generic `ORDER BY timestamp` or line-by-line renderer would include
abandoned, replaced, or rolled-back content.

### Similar SQLite tables do not imply compatible adapters

OpenCode, goose, Crush, Hermes, Cursor, OpenClaw, Codex, and Kilo all use SQLite somewhere,
but differ in authority, schemas, projections, branch semantics, privacy boundaries, and
selection rules. Adapter reuse must be limited to generic immutable snapshot and
sanitization primitives unless fixture equivalence is proven.

### Unknown timeline mutations must fail closed

A reader should not return a convincing stale transcript after encountering an unknown
rewind, compaction, clear, projection conflict, or content-bearing control record. The
safe result is an explicit unsupported/corrupt diagnostic or a precisely documented
partial capability.

## Checklist for adding or upgrading a source

Before claiming support for a new source family:

1. Pin an exact public version or schema family.
2. Identify the local root and every supported override.
3. Separate discovery data from transcript authority.
4. Define active-branch, rewind, rollback, compaction, delete, and archive semantics.
5. Hand-author synthetic fixtures, including conflict and wrong-adapter cases.
6. Read through stable no-follow file or immutable SQLite-family primitives.
7. Filter exact ID/CWD/root-session eligibility before bounded newest-session limits.
8. Normalize only public user, assistant, and bounded tool text.
9. Omit reasoning, system/developer prompts, credentials, binary/file payloads, and
   provider-private control state.
10. Fail closed when a content-bearing shape or timeline mutation is unknown.
11. Keep source CLIs, extension hosts, gateways, providers, and networks out of the
    reader path.
12. Document what is supported, partial, research, and explicitly not claimed.

## Open qualification work

- #200 — Kimi Code compaction, clear, and undo semantics
- #201 — Cursor Desktop bubble graph and active lineage
- #202 — Kilo event versus operational and legacy projection authority
- #46 — broader Kilo source/destination umbrella
