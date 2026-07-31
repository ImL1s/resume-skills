# Plan 050: Return an empty result, not `E_LIMIT_EXCEEDED`, when `--cwd` matches no recorded project

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/adapters/claude.py src/portable_resume/bounds.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Priority**: P1 (highest-frequency hard failure in the in-session loop)
- **Effort**: M
- **Risk**: MED (the broad fallback is deliberate; narrowing it can regress relocated-bucket discovery)
- **Depends on**: none. **Coordinate with plan 014** (metadata-only list perf, already DONE) and **plan 006** (ReadBudget double-count, DONE) — both reduce the cost of this scan; neither fixes the semantics.
- **Category**: bug (in-session failure path)
- **Planned at**: commit `2b4611c`, 2026-08-01

## Why this matters

A host agent must pass the user's project directory as `--cwd`. Sessions were
recorded under possibly-different directories. The moment the two do not line
up on a store of any real size, the reader **hard-fails with exit 7,
`E_LIMIT_EXCEEDED`, and an empty stdout** — a code that means "a configured
resource bound was exceeded", pointing the agent at bounds and configuration
when the truth is simply "no sessions were recorded for this directory".

Observed on a real store (1.7 GB, 108 project buckets, 1056 session files):

```
run_reader.py list --cwd /usr/share      → exit 7, stdout 0 bytes,
  stderr {"code":"E_LIMIT_EXCEEDED","message":"A configured resource bound was exceeded.","source":"claude"}
```

Same for `--cwd /nonexistent/xyz`, and identically for `show latest`.
Quantified on synthetic stores (41 records/session, unmatched cwd): 10, 30 and
48 sessions → exit 0; 60 sessions (2460 records) → **exit 7**. The break is at
`scanned_records = 2000` store-wide, i.e. any store past roughly 50 modest
sessions.

This is the single most likely first failure an agent hits, it produces no
stdout at all, and it misdirects recovery.

## Current state

- **The fallback that causes the whole-store scan** —
  `src/portable_resume/adapters/claude.py` around lines 509–517:

```python
    if cwd_scoped and prefer_slugs:
        preferred_dirs = _project_dirs(root, prefer_slugs=prefer_slugs, prefer_only=True)
        if preferred_dirs:
            return _paths_under_projects(preferred_dirs, exact_uuid=None)
        # Preferred slug dir missing: preserve legacy broad list so sessions
        # whose project bucket name differs can still match recorded cwd.

    project_dirs = _project_dirs(root, prefer_slugs=prefer_slugs, prefer_only=False)
    return _paths_under_projects(project_dirs, exact_uuid=exact_uuid)
```

  The comment records the fallback as **intentional**: sessions whose bucket
  name differs from the cwd slug must still be discoverable by their recorded
  cwd. Do not delete that capability — bound it.

- **Where the budget is spent** — same file, around line 1295:

```python
        for path in paths:
            # List still needs recorded cwd/title for collision safety; show does lineage.
            item = _summary(path, root, query, budget)
```

  `_summary` charges `budget.consume_records()` per JSONL line against the
  single global ceiling.

- **The ceiling** — `src/portable_resume/bounds.py`: `scanned_records: 2_000`.

- **Captured raise path**: `reader.py` (list dispatch) → `claude.py:1295` →
  `_summary` → `_scan_metadata_chunk` → `bounds.py` `consume_records` →
  raise `E_LIMIT_EXCEEDED`.

- **Contrast — what "no sessions" should look like**: an empty `list`
  envelope with exit 0, and for `show`, the existing rendered
  `# Portable Resume No Match` document on stdout with exit 3
  (`E_NO_MATCH`) — that path already works and is what an agent can act on.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Reproduce (real store) | `PYTHONPATH=src python3 scripts/portable-resume claude list --cwd /usr/share` | before: exit 7 empty stdout; after: exit 0 empty listing |
| Reproduce (show) | `PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd /usr/share` | before: exit 7; after: exit 3 with the no-match document on stdout |
| Claude tests | `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor -v` | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

Note: the reproduce commands read the operator's real `~/.claude` store. They
are read-only. **Never quote recovered session content** in tests, fixtures,
or your report — exit codes, counts and timings only.

## Scope

**In scope**:
- `src/portable_resume/adapters/claude.py` — the cwd-scoped fallback and its
  budget accounting
- Claude adapter tests + synthetic fixtures large enough to cross the ceiling
- `plans/README.md` — status row

**Out of scope**:
- Raising `DEFAULT_BOUNDS.scanned_records` — the ceiling is a safety property,
  not the bug. Do not touch `bounds.py`.
- Other adapters — check whether any shares this shape and **report**; do not
  fix here.
- The reader's generic budget handling in `reader.py`.
- Adding a cross-cwd search flag — out of scope by design (see Maintenance).

## Git workflow

- Branch: `plan/050-unmatched-cwd`
- Commit style: `fix(claude): unmatched cwd yields an empty listing instead of E_LIMIT_EXCEEDED`

## Steps

### Step 1: Reproduce and record the baseline

Run both reproduce commands and record exit codes and stdout byte counts.
Then build a synthetic store that crosses the ceiling with an unmatched cwd
(the audit used ~60 sessions × 41 records) under the scratchpad — **not** in
`tests/fixtures/` yet — and confirm it reproduces exit 7 without touching the
operator's real store.

**Verify**: your synthetic store reproduces exit 7 on `list --cwd <unmatched>`.

### Step 2: Choose the bounding strategy (record the choice)

Two candidates — pick ONE, state it, and justify it against the intentional
fallback comment:

**A. Separate budget for the fallback scan** (preferred): give the
broad-listing fallback its own `ReadBudget` (or a sub-budget derived from the
caller's limits) and, when that budget is exhausted, return the summaries
gathered so far plus a `W_TRUNCATED`-style warning — never raise. Preserves
relocated-bucket discovery, degrades honestly.

**B. Skip the fallback when the slug directory is absent**: cheapest, but
loses relocated-bucket discovery entirely. Only acceptable if you can show
that capability is already covered elsewhere (e.g. by the exact-UUID path) —
and if you take B, a fixture proving relocated buckets still resolve is
mandatory.

**Verify**: choice and justification recorded before code changes.

### Step 3: Implement

Apply the chosen strategy so that, for an unmatched cwd on a large store:
- `list` exits **0** with an empty (or partial + warned) session array;
- `show latest` exits **3** (`E_NO_MATCH`) with the existing rendered no-match
  document on **stdout**;
- a genuinely oversized *matched* scan still fails closed with
  `E_LIMIT_EXCEEDED` — the safety property must survive (test it).

**Verify**: both reproduce commands now behave as specified; the real-store
run no longer exits 7.

### Step 4: Fixtures and tests

Promote a trimmed version of your synthetic store into `tests/fixtures/claude/`
(synthetic manifest rules from `CONTRIBUTING.md` apply: `"synthetic": true`,
registered `format_id`, provenance anchor) — large enough to cross a
**lowered** budget rather than the full 2000-record default, so the test is
fast. Then assert:

1. Unmatched cwd + over-ceiling store → `list` exit 0, empty listing (plus
   the warning if you chose A).
2. Unmatched cwd → `show latest` exit 3 with the no-match document on stdout
   (assert stdout is non-empty).
3. **Relocated bucket still discoverable**: a session whose bucket name
   differs from its recorded cwd is still found when that cwd is passed —
   this pins the capability the fallback exists for.
4. A matched scan that genuinely exceeds the budget still raises
   `E_LIMIT_EXCEEDED` (safety property intact).

**Verify**: all four pass; full suite OK.

### Step 5: Cross-adapter check (report only)

`grep -n "prefer_only\|cwd_scoped" src/portable_resume/adapters/*.py` and note
which adapters use a similar scoped-then-broad fallback. Report the list; do
not change them.

**Verify**: report contains the list.

### Step 6: Full gates

**Verify**: full suite OK; `self_verify.py` → 0; `check_secrets.py` → 0;
`PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` → 0. Re-run the two
reproduce commands against the real store and record the new exit codes.

## Test plan

Step 4 (4 cases, all against synthetic fixtures with a lowered budget). The
relocated-bucket case is the regression guard for the capability being
bounded; the still-fails-closed case is the guard for the safety property.

## Done criteria

- [ ] `list --cwd <unmatched>` on a large store exits 0 with an empty listing
- [ ] `show latest --cwd <unmatched>` exits 3 with a non-empty stdout document
- [ ] Relocated-bucket discovery still works (test-pinned)
- [ ] Oversized *matched* scans still raise `E_LIMIT_EXCEEDED` (test-pinned)
- [ ] `bounds.py` unmodified (`git diff` empty)
- [ ] Cross-adapter list in the completion report
- [ ] Full suite + smoke matrix + gates green; `plans/README.md` updated

## STOP conditions

- You cannot preserve relocated-bucket discovery under any bounded strategy —
  report both options with their trade-offs; the maintainer decides.
- The fix would require raising `scanned_records` — that is not a fix; report
  instead.
- Existing tests assert exit 7 for unmatched-cwd scans (i.e. the behavior was
  pinned deliberately) — report the test names before changing them.
- The real-store reproduce commands behave differently on your machine (e.g.
  exit 0 because the store is small) — build the synthetic store first and
  work from that; note the discrepancy.

## Maintenance notes

- A "search across all recorded cwds" capability is deliberately **not** part
  of this plan — it is a product decision (and plan 044's `sources` command
  plus 043's `--match` are the adjacent surfaces). Do not smuggle it in.
- Reviewer: check that the safety ceiling still fires for genuinely oversized
  matched scans — the failure mode being fixed is the *unmatched* case only.
- If plan 014's metadata-only listing changes the per-path cost, this plan's
  fixture sizes may need adjusting; keep the lowered-budget approach so the
  test stays fast either way.
