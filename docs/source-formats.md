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

## Clean-room boundary

Do not copy real transcripts, credentials, developer home paths, or `~/.grok/bundled/skills/**`. See [`provenance.md`](provenance.md), [`clean-room-attestation.md`](clean-room-attestation.md), and `NOTICE`.
