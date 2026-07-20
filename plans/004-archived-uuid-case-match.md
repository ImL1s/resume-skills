# Plan 004: Compare archived session gates with normalized UUIDs

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/codex.py src/portable_resume/adapters/cursor.py tests/`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Session IDs are stored as `str(uuid.UUID(...))` (canonical lowercase). Archived Codex rows (and Cursor archived/subagent gates) compare **raw** `query.ref` to that normalized id. Users pasting uppercase UUIDs get false `E_NO_MATCH` only for archived threads — fixtures use already-lowercase IDs so tests never catch it.

## Current state

```python
# codex.py ~720-731
identifier = str(uuid.UUID(identifier))
...
if archived_flag and query.ref != identifier:
    continue
```

Similar raw equality appears for Cursor archived/subagent gates (~340-341, ~463-464) and age bypass `query.ref == session_id` helpers (`codex.py:229`, `cursor.py:124`).

## Scope

**In scope**:
- `src/portable_resume/adapters/codex.py`
- `src/portable_resume/adapters/cursor.py`
- Tests (adapter or unit) covering uppercase UUID exact show for archived-shaped fixtures

**Out of scope**: Changing public session_id casing in envelopes (keep canonical lowercase)

## Steps

### Step 1: Normalize ref for comparisons

Introduce or reuse `_exact_uuid_ref(ref) -> str | None` (already exists in adapters for exact filter). For any gate that means “user named this session by id”:

```python
ref_id = _exact_uuid_ref(query.ref) or (query.ref.strip() if query.ref else None)
# for archived allow when ref_id == identifier (normalized)
if archived_flag and ref_id != identifier:
    continue
```

For age bypass “exact id ignores age”:

```python
if _exact_uuid_ref(query.ref) == session_id or query.ref == session_id:
    return True
```

Prefer comparing only normalized UUID forms when both parse as UUID.

### Step 2: Tests

- Codex: archived session fixture (or synthetic row) listed/shown when `ref` is uppercase of id
- Cursor: same if an archived fixture exists; otherwise unit-test the helper / gate function

**Verify**: full unittest + self_verify.

## Done criteria

- [ ] No archived gate uses bare `query.ref != identifier` without normalization
- [ ] Uppercase UUID show works for archived cases
- [ ] Suite green; README DONE

## STOP conditions

- Cursor archived semantics require non-UUID refs — keep non-UUID path separate; only normalize when UUID-shaped

## Maintenance notes

Reviewer: grep `query.ref ==` / `query.ref !=` in adapters after change.
