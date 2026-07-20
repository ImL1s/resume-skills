# Plan 014: Metadata-first list for Claude and Codex (avoid full JSONL parse)

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/claude.py src/portable_resume/adapters/codex.py src/portable_resume/adapters/grok.py src/portable_resume/adapters/antigravity.py tests/`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 006 helpful; plan 009 for Grok/AGY discovery order
- **Category**: perf
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Claude `list` full-parses every session JSONL via triple `stable_read_bytes` (up to 2000 files × 16MiB × 3). Codex rollout fallback full-reads and `_normalized_turns` just for titles. Reader truncates output to 50 **after** that cost. Real homes become unusable while show correctness stays fine.

## Current state

- Claude: `list` → `_summary` → `_read` → full file (`claude.py:588-604`, `515-527`)
- Codex rollout: `_rollout_summary` normalizes turns for title (`codex.py` ~540-564, ~837-842)
- Grok/AGY: list still full-parses transcripts even with `include_turns=False` for updates (perf audit PERF-07)

## Scope

**In scope**: list/probe paths for claude, codex (rollout fallback), optionally grok/antigravity metadata-only list  
**Out of scope**: Changing show lineage correctness; lowering security of stable_read for show

## Steps

### Step 1: Claude list metadata strategy

For list only:

1. Enumerate paths as today (cwd_scoped / exact uuid).
2. For each path, use `lstat` mtime for `updated_at` and session id from filename UUID **without** full parse when possible.
3. Optionally read only first N KB / first few JSONL lines for cwd/title if required for cwd filter — must still enforce no-follow (`stable_read_bytes` with small max_bytes).
4. Full `_logical_lineage` / turn parse **only** in `show`.

Preserve fail-closed on unsafe paths. If cwd filter requires record cwd and first lines lack it, either include file (bounded) or skip with documented behavior.

### Step 2: Codex rollout list

Stop calling `_normalized_turns` for list titles; use `session_meta` / first user line skim / filename.

### Step 3: Grok/AGY list (if cheap)

Prefer `summary.json` / index / mtime for list; open updates/transcript only on show or missing summary.

### Step 4: Tests

- Existing fixture list/show still pass (titles may be slightly poorer — update expectations only if necessary and document)
- New test: many large-ish JSONL files; list completes under a small `source_read_bytes` budget that would fail today’s full parse (if budget charged correctly after plan 006)

**Verify**: full suite + self_verify.

## Done criteria

- [ ] List path does not full-parse every JSONL by default
- [ ] Show still full correctness for fixtures
- [ ] Suite green; README DONE

## STOP conditions

- Cwd filtering becomes wrong without full parse — keep full parse when `query.cwd` set **or** implement bounded header scan; do not drop cwd safety
- Any change causes source store writes — absolute STOP

## Maintenance notes

Reviewer: measure that `stable_read_bytes` still used for any content read; no bare open regression.
