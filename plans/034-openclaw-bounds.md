# Plan 034: Enforce openclaw read bounds in SQL and honor caller-lowered limits

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/adapters/openclaw.py tests/`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (plan 039 adds openclaw to the immutability suite; either order works)
- **Category**: security (bounded-read invariant)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/145

## Why this matters

The openclaw adapter is the one place in the newer adapter wave where the
bounded-read invariant is enforced *after* the allocation it exists to
prevent: `_list_nodes` fetches the entire `session_nodes` table — including
every `entry_json` blob — into Python before checking the record ceiling, and
this repeats once per agent database (up to 2000). The same file also drops
caller-lowered bounds: `_open_connection` uses `budget.limits` to choose
snapshot-vs-live but does not pass `bounds=limits` into
`private_sqlite_connection`, and several sites read `DEFAULT_BOUNDS` directly.
The documented contract in `src/portable_resume/bounds.py` ("Callers may
lower, but never raise, these defaults") does not hold for this adapter. The
sibling adapters merged in the same wave (goose, hermes, crush) all do this
correctly and serve as in-repo reference implementations.

## Current state

- `src/portable_resume/adapters/openclaw.py`:

  `_list_nodes` (function body around lines 394–425) — unbounded fetch,
  post-hoc check:

```python
    rows = connection.execute(
        """
        SELECT
          session_key,
          current_session_id,
          entry_json,
          ...
        FROM session_nodes
        ORDER BY COALESCE(last_interaction_at, updated_at, created_at) DESC, current_session_id ASC
        """
    ).fetchall()
    if len(rows) > DEFAULT_BOUNDS.scanned_records:
        raise DiagnosticError.limit_exceeded()
```

  `_open_connection` (around lines 220–228) — limits consulted for the branch,
  not passed to the snapshot:

```python
def _open_connection(database: str, root: str, budget: ReadBudget | None = None):
    limits = budget.limits if budget is not None else DEFAULT_BOUNDS
    ...
    if size > limits.sqlite_snapshot_bytes:
        return query_only_live_sqlite(database, root=root, provider=FORMAT_ID)
    return private_sqlite_connection(database, root=root, provider=FORMAT_ID)
```

  Direct `DEFAULT_BOUNDS` reads that ignore lowered budgets: around lines 456,
  863, 876 (`DEFAULT_BOUNDS.listed_sessions` in list assembly/truncation) —
  locate all with `grep -n "DEFAULT_BOUNDS\." src/portable_resume/adapters/openclaw.py`.

  Local byte accounting that checks but never debits the shared budget
  (around lines 684–689):

```python
        encoded = event_json.encode("utf-8")
        if len(encoded) > budget.limits.record_bytes:
            raise DiagnosticError.limit_exceeded()
        total_bytes += len(encoded)
        if total_bytes > budget.limits.source_read_bytes:
            raise DiagnosticError.limit_exceeded()
```

- Reference implementations (read them before editing):
  - `src/portable_resume/adapters/goose.py` — bounded SQL (`LIMIT ?` with a
    scan limit, around lines 316–331) and `bounds=limits` passed to
    `private_sqlite_connection` (around lines 160–162); budget debits via
    `budget.consume_records()` / `consume_bytes(...)` (around lines 279–280).
  - `src/portable_resume/adapters/hermes.py` (~line 166), `crush.py` (~151),
    `cline.py` (~229) — all pass `bounds=limits`.
- `src/portable_resume/snapshot.py` — `private_sqlite_connection(path, *, root,
  bounds=DEFAULT_BOUNDS, provider)` uses `bounds.sqlite_snapshot_bytes` for the
  snapshot copy cap.
- `src/portable_resume/bounds.py` — `ReadBudget` with `consume_records()` /
  `consume_bytes()`; the "Callers may lower, but never raise" contract comment.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Adapter tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q -k openclaw 2>/dev/null \|\| PYTHONPATH=src python3 -m unittest tests.unit.test_openclaw_adapter -v` | pass (find the exact module with `ls tests/unit/ tests/adapters/ \| grep -i openclaw`) |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**: `src/portable_resume/adapters/openclaw.py`; the openclaw test
module(s) under `tests/`; new fixture tree under
`tests/fixtures/openclaw/` if needed; `plans/README.md` row.

**Out of scope**:
- `snapshot.py`, `bounds.py` — the primitives are correct; only the adapter's
  use of them changes.
- Other adapters (goose/hermes/crush are the references, not targets).
- Output/selection semantics: the emitted summaries for stores *within*
  bounds must be byte-identical before/after (the existing `ORDER BY` already
  fixes deterministic order).

## Git workflow

- Branch: `plan/034-openclaw-bounds`
- Commit style: `fix(openclaw): bound session_nodes listing in SQL and thread caller limits`

## Steps

### Step 1: Thread the budget into `_list_nodes` and bound the query

Change `_list_nodes` to accept `budget: ReadBudget`, compute
`scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)`,
append `LIMIT ?` to the SQL with `scan_limit + 1` (the +1 preserves the
fail-closed behavior: if a full `scan_limit + 1` rows come back, raise
`DiagnosticError.limit_exceeded()` exactly as today, instead of silently
truncating). Keep the existing post-check as defense in depth. Charge the
budget per admitted row: `budget.consume_records()` and
`budget.consume_bytes(len(entry_json.encode("utf-8")))` following the goose
pattern. Update both call sites (around lines 833/849 — find with
`grep -n "_list_nodes(" src/portable_resume/adapters/openclaw.py`).

**Verify**: openclaw test module passes; full suite OK.

### Step 2: Pass lowered bounds into the snapshot

In `_open_connection`, change the final call to
`private_sqlite_connection(database, root=root, bounds=limits, provider=FORMAT_ID)`.

**Verify**: full suite OK.

### Step 3: Replace direct `DEFAULT_BOUNDS` reads on budget-relevant limits

For each hit of `grep -n "DEFAULT_BOUNDS\." adapters/openclaw.py` that
represents a *per-query* limit (listed_sessions, scanned_records,
record_bytes, source_read_bytes): replace with
`min(budget.limits.X, DEFAULT_BOUNDS.X)` where a budget is in scope. Leave
hits that are structural constants (if any) unchanged and list them in your
report. In the show-path byte loop (~684–689), replace the local
`total_bytes` accumulation with `budget.consume_bytes(len(encoded))` (which
enforces `source_read_bytes` centrally) while keeping the per-record
`record_bytes` check.

**Verify**: full suite OK; behavior with default bounds unchanged (existing
fixtures pass untouched).

### Step 4: Tests

Add to the openclaw test module (model after the goose adapter tests' bounds
cases — find them via `grep -rn "limit_exceeded\|scanned_records" tests/ | grep -i goose`):

1. **Over-ceiling listing**: a synthetic store whose `session_nodes` row count
   exceeds a lowered `scanned_records` → `E_LIMIT_EXCEEDED` raised, and (key
   assertion) the query itself was bounded — assert via a lowered budget of
   e.g. 5 records against a 50-row fixture, not via a 2001-row fixture.
2. **Lowered `sqlite_snapshot_bytes` honored**: budget with
   `sqlite_snapshot_bytes` smaller than the store size takes the
   `query_only_live_sqlite` branch (or errors per that path's contract) —
   assert the branch, not just absence of crash.
3. **Budget debit**: after a `list`, the shared `ReadBudget` shows consumed
   records/bytes > 0.
4. Fixture manifests must carry `"synthetic": true` and a registered
   `format_id` (repo rule — `CONTRIBUTING.md` "Code and fixture rules").

**Verify**: new tests pass; full suite OK.

### Step 5: Full gates

**Verify**: `self_verify.py` 0; `check_secrets.py` 0;
`PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` 0.

## Test plan

As Step 4. Structural pattern: the existing openclaw adapter tests plus goose's
bounds tests. All fixtures synthetic, no absolute home paths.

## Done criteria

- [ ] `_list_nodes` SQL contains `LIMIT ?`; post-check retained
- [ ] `_open_connection` passes `bounds=limits`
- [ ] No budget-relevant bare `DEFAULT_BOUNDS.` reads remain in openclaw.py (grep proves; structural exceptions listed in report)
- [ ] New bounds tests pass; full suite + smoke matrix + gates green
- [ ] Existing fixture outputs unchanged (no golden-output diffs)
- [ ] `plans/README.md` updated

## STOP conditions

- The openclaw schema in fixtures lacks `session_nodes` columns the excerpt
  shows (adapter was refactored) — re-map, and STOP if the listing no longer
  goes through a single query.
- Charging `consume_bytes` in the show path makes existing fixtures exceed the
  default budget (would mean real double-counting — report; do not raise
  limits to compensate).
- Any output ordering change appears in golden tests — the `LIMIT` must not
  change ordering (it is applied after `ORDER BY`); if it does, report.

## Maintenance notes

- Reviewer: confirm the `LIMIT` parameter is bound (`?`), not interpolated.
- Future adapters must copy the goose pattern; plan 039's registry-driven
  security tests will catch missing immutability coverage but not missing
  bounds threading — consider a shared bounds-conformance suite later
  (TEST-03, unplanned this round).
