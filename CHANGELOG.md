# Changelog

## Unreleased

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
