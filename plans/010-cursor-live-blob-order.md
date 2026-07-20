# Plan 010: Order Cursor live store.db blob turns deterministically

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/cursor.py tests/`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 012 recommended first (fixtures) or land tests in same PR
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Live CLI show runs `SELECT id, data FROM blobs LIMIT ?` with **no ORDER BY**. Turn order becomes SQLite row order → nondeterministic handoff “latest user/assistant”. Fixture CLI path uses ordered transcript links; live path does not.

## Current state

```python
# cursor.py ~738-741
rows = connection.execute(
    "SELECT id, data FROM blobs LIMIT ?",
    (DEFAULT_BOUNDS.scanned_records,),
).fetchall()
```

## Scope

**In scope**: `_show_live_cli_store` (and list if it reads blobs); synthetic `store.db` fixture; tests  
**Out of scope**: Desktop bubble graph (plan 023); changing LIMIT defaults

## Steps

### Step 1: Establish ordering strategy (in priority order)

1. If blobs table has a sequence/timestamp column (inspect real schema via fixture reverse or PRAGMA on sample): `ORDER BY that`.
2. Else `ORDER BY rowid ASC` (stable insertion order — best effort).
3. Else parse embedded timestamps from JSON payloads and sort (stable tie-break on id).
4. If none available: keep fetch but sort by id string **and** set an explicit warning code (prefer reusing existing warning if any; only add new code if diagnostics registry allows — check `diagnostics.py` WARNING_CODES). Do **not** invent silent random order.

Document chosen strategy in a short comment above the SQL.

### Step 2: Implement + fixture

Build minimal `store.db` with blobs inserted in known order / with known timestamps; assert show turns match expected ordinal roles.

### Step 3: Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
```

## Done criteria

- [ ] Live show turn order is deterministic for the fixture
- [ ] Strategy documented in code comment
- [ ] Suite green; README DONE

## STOP conditions

- Real Cursor store schema is opaque and rowid order is known wrong for multi-bubble — STOP and escalate to plan 023 rather than shipping false confidence without `W_MISSING_BLOB`-style honesty

## Maintenance notes

When Cursor changes store format, update fixture + ORDER BY together; keep partial honesty if graph incomplete.
