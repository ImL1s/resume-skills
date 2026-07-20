# Source-format evidence registry

Status: Adapters implemented against independently authored synthetic fixtures (deterministic bar green). Live host UI activation remains a separate gate — see `docs/STATUS.md`.

A provider may change from **planned** to **supported (fixture/parser)** only after public structural evidence, synthetic fixtures, probe/parser tests, and stable-read proofs exist in this repository.

| Source | Format ID(s) in code | Evidence baseline | Status | Known limitation |
|---|---|---|---|---|
| Claude Code | `claude-jsonl-v1` | Official Claude Code skills/session docs + synthetic fixtures | supported (fixture/parser) | List may include null titles; multi-slug collision uses recorded cwd |
| Codex | `codex-state-sqlite-v1`, `codex-rollout-jsonl-v1`, optional `codex-rollout-zstd-v1` | Public Codex/app-server docs + fixtures | supported (fixture/parser) | Missing zstd → partial capability; hot rollback journal fails closed |
| Cursor | `cursor-cli-chat-v1`, `cursor-desktop-vscdb-v1`, live `cursor-cli-store-v1`, `cursor-desktop-composer-v1` | Official Cursor skills docs + fixtures + live store shapes | supported (fixture/parser) | Live CLI `store.db`/`meta.json` + Desktop composerHeaders partial; full bubble graph not claimed; missing blobs warn without fabrication |
| OpenCode | `opencode-sqlite-v1`, `opencode-file-store-v1`, `opencode-export-file-v1` | Official OpenCode docs + fixtures | supported (fixture/parser) | Unknown schema fails closed; export is a separate provider |
| Antigravity | `antigravity-transcript-jsonl-v1` (index may be probed as hints) | Official Antigravity skills/CLI docs + fixtures | supported (fixture/parser) | Index preferred when valid; missing index uses bounded `brain/<id>/…/transcript.jsonl` scan. Live AGY JSONL schema often differs from fixtures (list may skip unreadable files). Exact id/path still works when parseable. |
| Grok Build | `grok-updates-jsonl-v1` | Public Apache-2.0 Grok Build tree + fixtures | supported (fixture/parser) | Installed bundled reader is prohibited as an implementation source |

## foundation-only

`#foundation-only` is the provenance anchor used by tests of the reusable fixture-manifest validator. It represents synthetic contract data only and is not evidence for a source adapter.

## Provenance anchors

Fixture `provenance_ref` values should point at anchors in this file (for example `docs/source-formats.md#foundation-only`) or the per-format headings below. Do not require gitignored private planning directories for builds or tests.

### claude-claude-jsonl-v1

Claude Code projects JSONL (`claude-jsonl-v1`). Synthetic fixtures under `tests/fixtures/claude/`.

### codex-codex-state-sqlite-v1

Codex state SQLite + rollout JSONL/zstd families. Synthetic fixtures under `tests/fixtures/codex/`.

### cursor-cursor-cli-chat-v1

Cursor CLI chats metadata/transcript fixtures and live `store.db` / desktop composer families. Synthetic fixtures under `tests/fixtures/cursor/`.

### opencode-opencode-sqlite-v1

OpenCode SQLite / file-store / export providers. Synthetic fixtures under `tests/fixtures/opencode/`.

### antigravity-antigravity-transcript-jsonl-v1

Antigravity transcript JSONL (+ optional index). Synthetic fixtures under `tests/fixtures/antigravity/`.

### grok-grok-updates-jsonl-v1

Grok Build session `updates.jsonl`. Synthetic fixtures under `tests/fixtures/grok/`.

## Clean-room note

Implementation and fixtures must not copy `~/.grok/bundled/skills/**` or private transcripts. See `docs/provenance.md` and `NOTICE`.
