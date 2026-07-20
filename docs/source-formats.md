# Source-format evidence registry

Status: Adapters implemented against independently authored synthetic fixtures (deterministic bar green). Live host UI activation remains a separate gate — see `docs/STATUS.md`.

A provider may change from **planned** to **supported (fixture/parser)** only after public structural evidence, synthetic fixtures, probe/parser tests, and stable-read proofs exist in this repository.

| Source | Format ID(s) in code | Evidence baseline | Status | Known limitation |
|---|---|---|---|---|
| Claude Code | `claude-jsonl-v1` | Official Claude Code skills/session docs + synthetic fixtures | supported (fixture/parser) | List may include null titles; multi-slug collision uses recorded cwd |
| Codex | `codex-state-sqlite-v1`, `codex-rollout-jsonl-v1`, optional `codex-rollout-zstd-v1` | Public Codex/app-server docs + fixtures | supported (fixture/parser) | Missing zstd → partial capability; hot rollback journal fails closed |
| Cursor | `cursor-cli-chat-v1`, `cursor-desktop-vscdb-v1` | Official Cursor skills docs + fixtures | supported (fixture/parser) | Missing blobs warn without fabrication; native picker parity not claimed |
| OpenCode | `opencode-sqlite-v1`, `opencode-file-store-v1`, `opencode-export-file-v1` | Official OpenCode docs + fixtures | supported (fixture/parser) | Unknown schema fails closed; export is a separate provider |
| Antigravity | `antigravity-transcript-jsonl-v1` (index may be probed as hints) | Official Antigravity skills/CLI docs + fixtures | supported (fixture/parser) | Missing index degrades to exact id/path; optional index format is not a full content provider |
| Grok Build | `grok-updates-jsonl-v1` | Public Apache-2.0 Grok Build tree + fixtures | supported (fixture/parser) | Installed bundled reader is prohibited as an implementation source |

## Foundation-only anchor

`#foundation-only` is the provenance anchor used by tests of the reusable fixture-manifest validator. It represents synthetic contract data only and is not evidence for a source adapter.

## Provenance anchors

Fixture `provenance_ref` values should point at anchors in this file (for example `docs/source-formats.md#foundation-only`) or other **shipped** docs. Do not require gitignored private planning directories for builds or tests.

## Clean-room note

Implementation and fixtures must not copy `~/.grok/bundled/skills/**` or private transcripts. See `docs/provenance.md` and `NOTICE`.
