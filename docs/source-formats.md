# Source-format evidence registry

Status: Adapters implemented against independently authored synthetic fixtures (deterministic bar green). Live host UI activation and peer-OS release evidence remain separate gates — see `docs/STATUS.md` and `docs/host-support.md`.

A provider may change from **planned** to **supported** only after its public structural evidence, independently authored synthetic fixture, probe test, parser tests, stable-read proof, and limitations are recorded here.

| Source | Format ID(s) | Public/official evidence baseline | G002 status | Known limitation |
|---|---|---|---|---|
| Claude Code | `claude-jsonl-v1` | Official Claude Code session/skills documentation listed in the approved planning evidence | supported (fixture/parser) | Live multi-slug collision policy depends on recorded cwd metadata |
| Codex | `codex-rollout-jsonl-v1`, `codex-state-sqlite-v1`, optional `codex-rollout-zstd-v1` | Public OpenAI Codex repository/app-server documentation listed in the approved planning evidence | supported (fixture/parser) | Missing zstd is partial capability; hot rollback journal fails closed |
| Cursor | `cursor-cli-chat-v1`, `cursor-desktop-vscdb-v1` | Official Cursor skills documentation and public structural evidence recorded by planning | supported (fixture/parser) | Missing content blobs warn without fabrication; desktop picker parity is not claimed |
| OpenCode | `opencode-file-store-v1`, `opencode-sqlite-v1` | Official OpenCode skills/CLI documentation listed in the approved planning evidence | supported (fixture/parser) | Unknown SQLite schema fails closed; export provider is separate |
| Antigravity | `antigravity-transcript-jsonl-v1` | Official Google Antigravity skills/CLI documentation listed in the approved planning evidence | supported (fixture/parser) | Missing index degrades to exact ID/path selection |
| Grok Build | `grok-updates-jsonl-v1` | Public Apache-2.0 xAI Grok Build repository and changelog behavior | supported (fixture/parser) | Installed bundled reader remains prohibited as an implementation source |

## Foundation-only anchor

`#foundation-only` is the provenance anchor used by tests of the reusable fixture-manifest validator. It represents synthetic contract data only and is not evidence for a source adapter.

## Clean-room note

Implementation/test lanes used this specification, tracked public evidence under `.omx/context/`, and synthetic fixtures under `tests/fixtures/`. They must not inspect `~/.grok/bundled/skills/**`.
