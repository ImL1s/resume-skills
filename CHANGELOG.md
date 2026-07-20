# Changelog

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
