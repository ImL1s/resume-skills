# Plan 003: Align Claude `within_min <= 0` with other sources

> **Executor instructions**: Follow step by step; STOP if excerpts drift.
> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/claude.py tests/adapters/test_claude_codex_cursor.py tests/unit/`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

CLI allows `--within-min 0`. Codex/Cursor/OpenCode/Grok/Antigravity treat `minutes <= 0` as **no age filter**. Claude’s `_within` only special-cases `None` → default window; with `0` it computes `stamp >= now - 0`, so only future timestamps pass. Cross-source scripts and live tests that pass `within_min=0` silently empty Claude results.

## Current state

```python
# claude.py:267-276
def _within(updated_at: str | None, minutes: int | None) -> bool:
    if minutes is None:
        minutes = DEFAULT_BOUNDS.listing_age_minutes
    if updated_at is None:
        return False
    ...
    return stamp >= time.time() - minutes * 60
```

```python
# codex.py:231-234 (exemplar)
if minutes is not None and minutes <= 0:
    return True
```

## Commands

| Purpose | Command | Expected |
|---------|---------|----------|
| Tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | exit 0 |

## Scope

**In scope**: `src/portable_resume/adapters/claude.py`; unit/adapter test for age filter  
**Out of scope**: Changing default `listing_age_minutes`; rewriting `_within` signatures across adapters (that is plan 019)

## Steps

### Step 1: Fix `_within`

After resolving default for `None`, add:

```python
if minutes is not None and minutes <= 0:
    return True
```

before timestamp parse / comparison. Keep `updated_at is None → False` unless product decision says otherwise (do not change null handling).

**Verify**: small unit test: old mtime summary listed when `Query(..., within_min=0)`.

### Step 2: Test

Add case in `tests/adapters/test_claude_codex_cursor.py` or `tests/unit/`: fixture session older than default window; with `within_min=0` list non-empty; with small positive window empty (if fixture age can be controlled via mtime or mock).

**Verify**: targeted unittest pass + full discover pass.

## Done criteria

- [ ] Claude matches codex semantics for `within_min <= 0`
- [ ] Regression test exists
- [ ] Full suite green; README DONE

## STOP conditions

- Product docs claim Claude intentionally rejects `0` — none known; if found in STATUS/SECURITY, STOP and report contradiction

## Maintenance notes

Plan 019 should eventually unify `_within` helpers so this cannot drift again.
