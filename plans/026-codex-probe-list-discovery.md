# Plan 026: Codex probe head-only + list FS fallback (P1a)

> Related: [Issue #7](https://github.com/ImL1s/resume-skills/issues/7) (Codex discovery reliability), Issue #3 / PR #4 (P0 budget + SQL pre-filter).
> Drift check: `git diff --stat origin/main -- src/portable_resume/adapters/codex.py src/portable_resume/adapters/codex_sqlite.py src/portable_resume/snapshot.py tests/adapters/test_claude_codex_cursor.py`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: PR #4 merged as `48746c4` (Issue #3 P0: `source_read_bytes` + `transcript_records` + SQL parent pre-filter) — **satisfied on main**
- **Category**: bug / reliability
- **Planned at**: 2026-07-25 (post PR #4 review)

## Why this matters

After P0, large rollouts can be *shown* with correct budgets, but capability and discovery still misbehave on real homes:

1. **`probe()`** may full-read a rollout and/or walk the entire `sessions/` tree (e.g. `_zstd_warnings` → `_rollout_paths`). On multi-GB stores this yields false `E_UNSUPPORTED_FORMAT` / `unsupported` even when SQLite schema is fine.
2. **`list()`** treats a recognized SQLite schema as **authoritative with no filesystem fallback**. Stale or missing rows produce false negatives that Codex-style discovery would still recover via head scan.

Product rule: **inert, read-only** context migration. Do **not** write back into `~/.codex` (no Codex `ScanAndRepair` mutation). Approximate list reliability with **verify + optional FS head scan only**.

## Current state (after P0)

- SQL list filters `source IN ('cli','vscode')` and default `archived = 0` before `LIMIT` (good).
- `show` / `_read_rollout` uses `source_read_bytes` + `consume_transcript_records` (good) but still whole-file load (P1b).
- `probe` still can call full `_read_rollout` on fallback path and still walks rollouts for zstd warnings.
- List comment: recognized DB is authoritative; rollout scan only when schema unrecognized.

## Scope

**In scope**

- `CodexAdapter.probe`: head-only validation (≤10 records, extend ≤200 for meta/preview if needed); never full transcript parse.
- Stop full-tree walks from probe (zstd availability: check trusted binary path only, or sample bounded set — not all sessions).
- `list`: after SQLite candidates, verify rollout path + session_meta head; if under-filled / stale, **read-only** filesystem head scan under `sessions/` (+ archived only for exact-id paths as today).
- Tests: synthetic large session count; stale SQLite row; probe does not open full multi-MB body beyond head bound.

**Out of scope**

- Streaming full show / reducer (plan 027).
- Invoking `codex` CLI or app-server `thread/resume`.
- Mutating Codex SQLite or rewriting rollout paths.
- Claiming Codex-native resume parity.

## Steps

### Step 1: Head reader helper

Add a bounded head scan (adapter-local or `snapshot` helper) that:

- no-follow open, fingerprint before/after attempt
- parse at most N JSONL lines (default 10, cap 200)
- charge `scanned_records` / small byte budget, **not** full `transcript_records`
- returns session_meta fields needed for capability + list summary

### Step 2: Rewrite `probe`

```text
root exists?
  → state_*.sqlite table signature OK → supported/partial (no full rollout read)
  → else head-scan one plain rollout → supported if canonical session_meta
  → else zstd binary policy only → partial/supported
  → else unavailable/unsupported
```

Never map `E_LIMIT_EXCEEDED` from a full-file walk to “no format supported” without trying DB signature alone.

### Step 3: List verify + FS fallback

```text
SQLite query (parent filter) → candidates
  → drop rows whose rollout missing / UUID mismatch / head meta fails
  → if cwd filter and fewer than listed_sessions, page or FS head scan newest rollouts
  → merge/dedupe by session_id; sort by updated_at
```

FS path remains **compatibility fallback when rows are wrong or sparse**, not a second full index rebuild written to disk.

### Step 4: Tests

- Probe with huge synthetic sessions tree does not raise/limit from full walk.
- List recovers parent when SQLite row points at missing path but file exists under `sessions/YYYY/MM/DD` (or opposite: row present file gone → omit).
- Existing fixture list/show still pass.
- Four gates: self_verify, secrets, unittest, installed matrix.

## Done criteria

- [ ] `probe` never full-parses a multi-MB rollout
- [ ] Large live `~/.codex` no longer reports false unsupported solely due to tree scan
- [ ] Stale/missing SQLite rows can still surface sessions via head FS scan (documented as best-effort)
- [ ] Source store byte-for-byte unchanged
- [ ] `docs/STATUS.md` updated honestly
- [ ] Linked GitHub issue closed only with evidence

## STOP conditions

- Cannot verify path safely without follow/symlink escape → fail closed that row
- FS scan would exceed scanned_records → stop with partial list + warning, do not raise unsupported for whole source

## Maintenance notes

Keep Issue #3 closed after P0; this plan is **new work**, not a reopen of budget accounting.
