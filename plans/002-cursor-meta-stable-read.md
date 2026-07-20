# Plan 002: Read Cursor live meta.json via stable no-follow I/O

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/cursor.py tests/adapters/test_claude_codex_cursor.py tests/unit/test_remaining_sources_live.py`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (pairs well with plans 010–012)
- **Category**: security
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Source reads are supposed to use `stable_read_bytes` / descriptor walks with `O_NOFOLLOW`. Cursor’s **live** CLI path still does `open(meta_path, "rb")` after a TOCTOU-prone `isfile`/`islink` check. Between check and open, a symlink swap can make the reader follow into an arbitrary readable file; metadata (title/cwd) then enters list/show/handoff. Fixture CLI paths already use `stable_read_bytes` — live must match.

## Current state

- `src/portable_resume/adapters/cursor.py` — Cursor adapter (CLI fixture, live store.db, desktop)

Vulnerable sites:

```python
# cursor.py ~657-660 (list live)
raw = open(meta_path, "rb").read(DEFAULT_BOUNDS.record_bytes)
# cursor.py ~722-724 (show live)
meta = json.loads(open(meta_path, "rb").read(...).decode("utf-8"))
```

Good pattern already in same file for fixture metadata (~205):

```python
observation = stable_read_bytes(path, root=root, max_bytes=DEFAULT_BOUNDS.request_bytes, budget=budget)
```

Import already present: `from ..snapshot import StableRead, private_sqlite_connection, query_only_live_sqlite, stable_read_bytes`.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | exit 0 |
| Self verify | `python3 scripts/self_verify.py` | exit 0 |

## Scope

**In scope**:
- `src/portable_resume/adapters/cursor.py`
- Tests under `tests/adapters/` and/or `tests/security/` proving symlink meta is rejected

**Out of scope**:
- Full bubble graph restore (direction plan 023)
- Blob ORDER BY (plan 010)
- Changing bounds defaults

## Git workflow

- Branch: `advisor/002-cursor-meta-stable-read`
- Commit: `fix: read cursor live meta.json with stable_read_bytes`

## Steps

### Step 1: Replace bare opens

In `_list_live_cli_stores` and `_show_live_cli_store`:

1. Ensure `meta_path` is under the approved chats/`source_root` (use existing `is_within` / `canonical_root`).
2. Replace bare `open` with:

```python
read = stable_read_bytes(
    meta_path,
    root=root,  # the approved cursor root for this session bucket
    max_bytes=min(DEFAULT_BOUNDS.record_bytes, 256 * 1024),  # meta is small; keep tight if reasonable
    budget=budget,  # pass the active ReadBudget in list/show
    attempts=DEFAULT_BOUNDS.snapshot_attempts,
)
meta = json.loads(read.data.decode("utf-8"))
```

3. On `DiagnosticError` / JSON errors, keep current degrade behavior (`pass` on list, `W_STALE_INDEX` on show).

**Verify**: `rg -n 'open\(meta_path' src/portable_resume/adapters/cursor.py` → no matches.

### Step 2: Symlink regression test

Create a temp root with `chats/<hash>/<uuid>/store.db` (minimal empty sqlite or touch regular file as needed for listing) and `meta.json` as a symlink to a file outside root. Assert list/show either skips meta or raises `E_UNSAFE_PATH` / omits cwd without following.

If live list requires real sqlite blobs, reuse fixture helpers or create a tiny store.db with `sqlite3` in the test.

**Verify**: new test fails before fix, passes after.

### Step 3: Full suite

**Verify**: `PYTHONPATH=src python3 -m unittest discover -s tests -q` → exit 0.

## Test plan

- Symlink `meta.json` is not followed
- Regular meta still supplies title/cwd
- Existing cursor fixture tests (s-cur-*) remain green

## Done criteria

- [ ] No bare `open(meta_path` in cursor adapter
- [ ] Symlink regression test exists and passes
- [ ] Full unittest exit 0
- [ ] Scope clean; README status DONE

## STOP conditions

- Live list requires a different root identity than `store` parent and `is_within` cannot be satisfied without redesigning approved roots — report with stack; do not disable no-follow
- Discovering more bare `open`s on untrusted store paths in other adapters — file follow-up, only fix cursor here unless trivial same pattern (do not expand to full adapter rewrite)

## Maintenance notes

- Reviewer: every new live side-car file must use `stable_read_bytes`.
- Plan 012 will add broader live fixtures; keep this test independent and fast.
