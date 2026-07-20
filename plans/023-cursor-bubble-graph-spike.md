# Plan 023: Spike — Cursor full bubble / composer graph restore

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/cursor.py docs/STATUS.md CHANGELOG.md tests/fixtures/cursor`

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans 010, 012
- **Category**: direction
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Among six sources, Cursor Desktop/CLI restore depth is the shortest board: live show sets `W_MISSING_BLOB` and best-effort `composerData` text only. CHANGELOG explicitly **not claimed** full bubble graph. Users care about multi-turn Cursor threads; this is the main quality asymmetry once host UI exists.

This plan is a **spike + incremental deepen**, not a guarantee of full graph in one pass.

## Current state

```python
# cursor.py ~898-915
def _show_live_desktop(...):
    """List-level metadata + optional composerData text; bubble graph not fully restored."""
    warnings: list[str] = ["W_MISSING_BLOB"]  # full bubble chain not claimed
```

## Scope

**In scope**:
- Research pinned Cursor version store schema (local machine sample under operator consent only; scrub secrets)
- Synthetic fixtures for discovered bubble structures
- Implement **bounded** multi-turn restore if schema is stable enough
- Keep partial warnings until complete

**Out of scope**: Claiming picker parity; reverse-engineering with network; shipping without fixtures

## Steps

### Step 1: Schema spike document

Write `docs/research/cursor-bubble-schema.md` (or under plans notes) with:

- Tables/keys observed
- Ordering fields
- What can be restored vs permanently missing
- Cursor version stamp

Never paste real conversation secrets.

### Step 2: Fixtures

Extend plan 012 fixtures with multi-bubble synthetic data.

### Step 3: Implement incrementally

Only if ordering + roles are clear:

- Restore N turns with stable order
- Map roles to user/assistant/tool safely
- Drop thinking/system via sanitize pipeline
- Remove blanket `W_MISSING_BLOB` **only** when bubbles actually restored; otherwise keep honesty

### Step 4: Verify

Full suite + self_verify + secrets gate.

## Done criteria

- [ ] Spike doc exists with version pin
- [ ] Either: deeper restore + tests, **or** documented “not feasible / unstable” with STATUS unchanged
- [ ] No honesty regression (no claiming full graph without evidence)
- [ ] README DONE

## STOP conditions

- Schema encrypted/opaque — stop, document unavailable, do not fake turns from headers
- Requires following symlinks or writing source stores — absolute STOP

## Maintenance notes

Cursor updates may break fixtures; pin version in docs; re-spike on major Cursor releases.
