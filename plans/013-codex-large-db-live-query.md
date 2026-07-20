# Plan 013: Size-gate Codex SQLite list/probe onto query_only_live_sqlite

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/codex.py src/portable_resume/snapshot.py tests/`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 011 (characterization tests must exist first)
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

OpenCode/Cursor switch to live query-only when DB size > `sqlite_snapshot_bytes`. Codex always uses `private_sqlite_connection`. Homes with large `state_*.sqlite` fail list/probe with limit/busy instead of degraded live query — total unavailability.

## Current state

```python
# codex.py ~649-650 — always private_sqlite_connection for summaries
# codex.py ~768-769 — probe same
# opencode.py ~405-416 — exemplar size gate
```

## Scope

**In scope**: Codex adapter list/probe (and show if needed for consistency); tests with lowered bounds or mocked size  
**Out of scope**: Changing default 256MiB bound; zstd decoder

## Steps

### Step 1: Mirror OpenCode gate

```python
size = os.path.getsize(database)
if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes:
    with query_only_live_sqlite(database, root=root, provider=...) as connection:
        ...
else:
    with private_sqlite_connection(...) as connection:
        ...
```

Import `query_only_live_sqlite` from snapshot.

### Step 2: Prefer private snapshot for show when size allows

Product choice: list/probe may use live; show may keep private copy when under cap for stronger consistency. Match Cursor/OpenCode show behavior for large DBs (they use live when oversized).

### Step 3: Tests

- With Bounds injection or mock getsize > cap, assert code path uses live (no temp private dir / or spy)
- Hot journal still fails
- Existing codex fixtures still use private path (small DBs)

**Verify**: full suite + self_verify.

## Done criteria

- [ ] Large Codex DB list/probe does not require private multi-hundred-MB copy
- [ ] Small fixtures unchanged
- [ ] Plan 011 tests still pass
- [ ] README DONE

## STOP conditions

- Codex schema requires exclusive locks that break query_only — document and keep private-only with better error message; do not force live if probes show systematic corruption

## Maintenance notes

Document residual concurrent WAL races in SECURITY.md or source-formats (one sentence).
