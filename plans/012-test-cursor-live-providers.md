# Plan 012: Synthetic fixtures for Cursor live CLI + desktop providers

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/cursor.py tests/fixtures/cursor tests/adapters tests/unit/test_remaining_sources_live.py`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none; enables plans 002/010/023 tests
- **Category**: tests
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Live formats `cursor-cli-store-v1` / `cursor-desktop-composer-v1` power real user homes. Fixtures today cover synthetic CLI metadata + fixture `state.vscdb` (`DESKTOP_FORMAT`), not live `store.db` blobs or App Support `composerHeaders`/`cursorDiskKV`. Adapter tests never assert `LIVE_*` providers. Honesty claim `W_MISSING_BLOB` on desktop show is unlocked only by code comments.

## Current state

- LIVE constants in `cursor.py` (~26-28)
- `_list_live_cli_stores` / `_show_live_cli_store` / `_list_live_desktop` / `_show_live_desktop`
- Fixtures: `tests/fixtures/cursor/s-cur-01` … `s-cur-08`
- Format IDs must stay consistent with `docs/source-formats.md` / provenance policy

## Scope

**In scope**:
- New fixtures under `tests/fixtures/cursor/` (e.g. `s-cur-09-live-cli-store`, `s-cur-10-live-desktop-composer`)
- Adapter/unit tests exercising list/show with `--source-root` pointing at fixtures **or** isolated roots that force live code paths
- Note: live desktop probe skips when `source_root` is set — read `cursor.py` carefully; may need to call internal functions or structure fixture so live CLI store path runs under source_root

**Out of scope**: Real `~/Library/Application Support` smoke; full bubble graph implementation

## Steps

### Step 1: Build minimal store.db fixture

Use Python `sqlite3` in a build script or test setup:

- Table `blobs(id TEXT, data BLOB)` with 2–3 JSON messages `{role, content}` ordered for plan 010
- Sibling `meta.json` with cwd/title timestamps matching other fixtures’ synthetic paths (`/workspace/project` style — **no** real home paths; secret gate)

### Step 2: Build minimal composer desktop fixture

- `state.vscdb` with `composerHeaders` + optional `cursorDiskKV` key `composerData:{id}`
- Expect show includes `W_MISSING_BLOB` and at most best-effort text turns

### Step 3: Tests

- list returns session with provider live format id
- show returns turns / warnings as designed
- symlink meta rejected if plan 002 landed (or skip if ordered after)

### Step 4: Fixture manifest / synthetic flags

Follow existing `fixture.json` schema (`tests/helpers/fixture_manifest.py`): `synthetic: true`, provenance_ref string prefix ok.

**Verify**: full suite + check_secrets (no absolute homes).

## Done criteria

- [ ] At least one live CLI store fixture + tests green
- [ ] At least one live desktop composer fixture asserting `W_MISSING_BLOB`
- [ ] No real machine paths in fixtures
- [ ] README DONE

## STOP conditions

- Live code path impossible to reach under `source_root` without product change — then add a narrow test hook **only if** existing tests already use private hooks; prefer testing pure functions `_show_live_cli_store` with temp paths. Do not add debug env flags without operator approval.

## Maintenance notes

Keep fixtures tiny (<1MB). Document format ids in source-formats when anchors plan 018 lands.
