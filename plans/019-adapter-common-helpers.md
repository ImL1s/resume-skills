# Plan 019: Extract shared adapter JSON / time / within helpers

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/`

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans 003–004 ideally landed first (behavior freeze)
- **Category**: tech-debt
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

`_DuplicateKey`, strict `object_pairs_hook`, `_rfc3339`, `_within`, and root helpers are copy-pasted across claude/codex/cursor/grok/antigravity (and partially opencode). Semantics already drifted once (`within_min<=0`). Future security fixes must not be applied to 5 files by hand.

## Current state

Duplicate class patterns at approx:

- `claude.py:69-73`, `codex.py:66-70`, `cursor.py:60-64`, `grok.py:53-57`, `antigravity.py:43-47`

`_within` signatures differ (minutes vs Query).

## Scope

**In scope**: new `src/portable_resume/adapters/common.py` (or `_jsonutil.py`); re-exports from adapters; tests still green  
**Out of scope**: Splitting cursor/codex god modules (plan 020); behavior changes beyond centralizing already-fixed semantics

## Steps

### Step 1: Create common module

Move pure helpers:

- `DuplicateKey` error + `object_pairs_hook`
- `rfc3339` parsers used in multiple adapters
- `within_age(updated_at, minutes, *, default=...)` with `<=0` means unlimited
- Optional `exact_uuid_ref`

Keep adapter-specific DiagnosticError source/provider wrapping at call sites.

### Step 2: Replace duplicates

Import from common; delete local copies. Grep for leftover `_DuplicateKey` definitions.

### Step 3: Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
```

No public API change for `portable_resume.reader`.

## Done criteria

- [ ] Single definition of strict JSON object hook and within-age
- [ ] All adapters import common helpers
- [ ] Suite green; README DONE

## STOP conditions

- An adapter’s `_within` intentionally differs after plans 003/004 — document exception, do not silently unify wrong

## Maintenance notes

New adapters must use common helpers; code review checklist item.
