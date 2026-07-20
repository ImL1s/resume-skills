# Plan 020: Split Cursor and Codex adapters by format module

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/cursor.py src/portable_resume/adapters/codex.py src/portable_resume/adapters/__init__.py tests/`

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans 002, 010, 012, 013 preferred (stabilize live paths first)
- **Category**: tech-debt
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

`cursor.py` is ~1.1k+ lines (fixture CLI, live store, desktop vscdb, live composer). `codex.py` is ~900+ (sqlite, rollout, zstd). Review cost and regression surface for any live fix is the whole file. Protocol entry `ADAPTER` must remain stable.

## Current state

- `adapters/__init__.py` / reader loads adapter by key
- Single `ADAPTER = CursorAdapter()` / Codex at file end

## Scope

**In scope**: file splits under `adapters/`; keep public `CursorAdapter`/`CodexAdapter` keys and probe/list/show behavior  
**Out of scope**: New features; changing format ids; install packaging of modules (ensure runtime package still includes new files via walk)

## Steps

### Step 1: Cursor split (suggested)

- `cursor_cli.py` — fixture + live store.db
- `cursor_desktop.py` — vscdb fixture + live composer
- `cursor.py` — thin `CursorAdapter` routing + shared constants

### Step 2: Codex split (suggested)

- `codex_sqlite.py` — state DB list/show
- `codex_rollout.py` — jsonl + zstd
- `codex.py` — thin adapter + probe routing

### Step 3: Ensure install materialize includes new modules

`install/render.py` walks package — new modules under `adapters/` should be picked automatically; verify with e2e installed runner.

### Step 4: Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
```

## Done criteria

- [ ] No behavior change (characterization: full suite)
- [ ] Main adapter files substantially smaller / readable
- [ ] Installed skill still runs reader e2e
- [ ] README DONE

## STOP conditions

- Circular imports force messy API — stop and report design; do not leave half-split modules

## Maintenance notes

Do this after live correctness plans so diffs are reviewable.
