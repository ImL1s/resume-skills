# Plan 009: Discover latest sessions beyond name-order early cap (Grok + Antigravity)

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/grok.py src/portable_resume/adapters/antigravity.py tests/`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (list output still truncated by reader to `listed_sessions`)
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Grok `_session_paths` stops when `len(output) >= listed_sessions` (50) while iterating **name-sorted** session dirs. Antigravity no-index discovery does the same. `select_session(..., ref="latest")` can only rank sessions the adapter returned — so with >50 sessions, true latest can be invisible. This is a silent wrong handoff, not a hard error.

## Current state

```python
# grok.py ~232-238
session_entries = sorted(os.scandir(cwd_entry.path), key=lambda entry: entry.name)
for session_entry in session_entries:
    if len(output) >= DEFAULT_BOUNDS.listed_sessions:
        return output
```

```python
# antigravity.py ~218-219 (no-index path) — early stop at listed_sessions
```

Reader already truncates display list (`reader.py:228-230`) and sorts by `summary_sort_key`.

## Scope

**In scope**:
- `adapters/grok.py` discovery
- `adapters/antigravity.py` no-index (and index path if it also early-caps before ranking)
- Tests with >50 synthetic sessions under a temp root

**Out of scope**:
- Claude/Codex list full-parse perf (plan 014)
- Raising `listed_sessions` default for stdout tables

## Steps

### Step 1: Separate scan cap from display cap

- Scan/collect candidates up to `DEFAULT_BOUNDS.scanned_records` (or a dedicated discovery cap ≤ scanned_records).
- Prefer preferred cwd buckets first (keep existing prefer_cwd behavior).
- Do **not** return after 50 names; finish preferred cwd scan (bounded) then rank.

### Step 2: Rank before truncating for list

For each candidate path, cheap ranking key:

1. Prefer `summary.json` / index timestamps if present without full transcript parse
2. Else `os.lstat(updates.jsonl|transcript).st_mtime`

Sort by updated desc, then id. Adapter `list` may still return up to `scanned_records` but should return at least enough for latest; reader already slices to 50 for list output. For `show latest`, returning top by mtime among scanned set is the fix — ensure the newest mtime sessions are included in the returned summaries.

Practical algorithm for Grok preferred cwd:

1. Enumerate all session dirs under preferred cwd (cap at scanned_records).
2. Attach mtime of updates.jsonl.
3. Sort by mtime desc; take first `listed_sessions` for list **or** return more for show path — simplest: return up to min(scanned_records, N) summaries sorted, let reader truncate list output.

Avoid full `stable_read_bytes` of every updates.jsonl during discovery if plan 014 not done — mtime-only ranking is enough for latest correctness.

### Step 3: Tests

- Create 60 temp session dirs with controlled mtimes; name-order first 50 are older; assert `show latest` / list top is the newest mtime session.
- Antigravity no-index equivalent.

**Verify**: full suite.

## Done criteria

- [ ] >50 sessions: latest by mtime (or summary time) is selectable
- [ ] Still hard-capped by scanned_records
- [ ] Tests prove name-order trap is gone
- [ ] Suite green; README DONE

## STOP conditions

- Prefer_cwd multi-bucket semantics make full scan too expensive without extra bounds — keep per-cwd scan cap and document; do not remove all caps
- Real Grok layout differs (sessions not under cwd buckets) — re-read `_session_paths` fully before inventing a new tree walk

## Maintenance notes

Reviewer: ensure early `return output` on listed_sessions is gone from discovery; keep fail-closed on symlinks.
