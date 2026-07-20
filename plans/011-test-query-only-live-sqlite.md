# Plan 011: Characterization tests for query_only_live_sqlite

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/snapshot.py tests/security/test_snapshot.py src/portable_resume/adapters/opencode.py src/portable_resume/adapters/cursor.py`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (blocks safe execution of plan 013)
- **Category**: tests
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

When main DB size exceeds `sqlite_snapshot_bytes` (256MiB), OpenCode/Cursor use `query_only_live_sqlite` instead of private copy. That path is production-critical for multi-GiB OpenCode homes and is **untested**. Existing OpenCode tests assert private URI only and would not catch regressions that reintroduce full GiB copies.

## Current state

```python
# snapshot.py ~411-449
def query_only_live_sqlite(...):
    safe, _base = require_regular_no_symlinks(database, root)
    if os.path.exists(f"{safe}-journal") or os.path.lexists(...):
        raise DiagnosticError("E_SQLITE_HOT_JOURNAL", ...)
    for suffix in ("-wal", "-shm"):
        ...  # reject symlinks / non-regular
    uri = f"file:{quote(safe)}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
```

`tests/security/test_snapshot.py` covers private snapshot / stable_read only.

## Scope

**In scope**:
- `tests/security/test_snapshot.py` (or new `tests/security/test_query_only_live.py`)
- Possibly tiny helper to lower bounds via `Bounds(...)` injection if API allows; **do not** create real 256MiB files in CI

**Out of scope**: Changing live query behavior; Codex live path (plan 013)

## Steps

### Step 1: Unit-test live path without 256MiB file

Options (pick simplest that works with current APIs):

A. Call `query_only_live_sqlite` directly on a small temp DB (function does not check size — size gate is in adapters). Assert:
   - Can SELECT
   - `PRAGMA query_only` is on
   - Hot `-journal` raises `E_SQLITE_HOT_JOURNAL`
   - Symlink `-wal` raises unsafe path
   - URI is mode=ro (inspect via connection or source)

B. For adapter size gate: construct Bounds with tiny `sqlite_snapshot_bytes` if adapters accept bounds override; else unit-test adapter branch by mocking `os.path.getsize` (prefer real Bounds if pluggable).

Prefer A for snapshot module; add B only if adapters hardcode DEFAULT_BOUNDS without injection — then either inject Bounds in adapter signatures (small API change, in scope) or mock getsize in test.

### Step 2: Cases

1. Happy query_only read
2. Hot journal fail-closed
3. WAL symlink rejected
4. Does **not** create tempfile private directory (no `portable-resume-sqlite-` leak) — assert no new temp dirs or spy TemporaryDirectory

### Step 3: Verify

```bash
PYTHONPATH=src python3 -m unittest tests.security.test_snapshot -q
# or new module
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
```

## Done criteria

- [ ] query_only_live_sqlite covered by automated tests
- [ ] Hot journal + wal symlink covered
- [ ] Suite green; README DONE

## STOP conditions

- Cannot observe query_only without executing SQL writes that fail differently on platforms — use PRAGMA query_only fetchone assertion

## Maintenance notes

Plan 013 must keep these tests green when Codex gains the same gate.
