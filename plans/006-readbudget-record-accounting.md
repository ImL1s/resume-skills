# Plan 006: Fix ReadBudget double-counting of file + line records

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/snapshot.py src/portable_resume/adapters src/portable_resume/bounds.py tests/`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW–MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

`stable_read_bytes` charges `budget.consume_records()` once per successful file read. JSONL adapters also charge once **per line**. A 2000-line transcript costs 2001 units against `scanned_records=2000` and fails `E_LIMIT_EXCEEDED` while still within the documented line bound. Bounds become untrustworthy on the core path.

## Current state

```python
# snapshot.py ~218-220
if budget is not None:
    budget.consume_records()
    budget.consume_bytes(len(data))
```

Adapters (claude/codex/cursor/grok/antigravity) call `budget.consume_records()` per line when parsing.

`bounds.py`: `scanned_records: int = 2_000`.

## Scope

**In scope**:
- `src/portable_resume/snapshot.py` and/or adapters’ parse loops
- Docstring / comment in `bounds.py` defining what a “record” means
- Tests that set tiny `scanned_records` may need retune

**Out of scope**: Changing numeric defaults of bounds; snapshot multi-pass I/O redesign (perf plan 014)

## Steps

### Step 1: Pick one definition (recommended)

**Recommended**: A “record” is one logical source row (JSONL line / SQLite row). File open is **not** a record — only charge `consume_bytes` in `stable_read_bytes`, not `consume_records`.

Alternative (if tests rely on file-level): charge file-level only for list metadata paths that do not line-parse — more invasive.

Implement recommended: remove `budget.consume_records()` from successful path in `stable_read_bytes`; keep `consume_bytes`.

### Step 2: Audit adapters

Ensure every parse loop still charges per line/row. SQLite path list already charges appropriately — do not double-remove.

### Step 3: Fix tests

Any test expecting `scanned_records=1` to fail on first file open may need updating to fail on second line or use byte budget.

Document in `bounds.py` module docstring: `scanned_records` counts logical records after open, not open() calls.

### Step 4: Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
```

## Done criteria

- [ ] Single 2000-line file can parse under default bounds (add synthetic test if feasible)
- [ ] No double charge on file+line path
- [ ] Suite green; README DONE

## STOP conditions

- Removing file-level charge breaks a security test that intentionally limits opens — adjust that test to use `source_read_bytes` or membership limits instead of inventing a second counter

## Maintenance notes

Reviewer: confirm private SQLite snapshot still has *some* budget story (plan 014 may charge snapshot bytes separately).
