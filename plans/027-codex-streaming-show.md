# Plan 027: Codex stable streaming show + large-rollout regression (P1b)

> Related: [Issue #8](https://github.com/ImL1s/resume-skills/issues/8) (Codex streaming show), plan 026 / [Issue #7](https://github.com/ImL1s/resume-skills/issues/7), Issue #3 / PR #4 (P0 whole-file budget fix).
> Drift check: `git diff --stat origin/main -- src/portable_resume/snapshot.py src/portable_resume/adapters/codex.py tests/`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED–HIGH (correctness under concurrent writers)
- **Depends on**: plan 026 preferred first (probe/list no longer force full reads); PR #4 merged as `48746c4` (partial: readline + budget clamps landed; full reducer still this plan)
- **Category**: reliability / performance
- **Planned at**: 2026-07-25

## Why this matters

PR #4 correctly charges `source_read_bytes` and `transcript_records`, but still:

1. Loads up to 256 MiB into a single `bytes`
2. `splitlines(keepends=True)` → another large allocation
3. Parses **all** lines into `list[dict]` before normalizing turns

Peak memory can be several× file size. Fine for ~17–30 MiB; unsuitable as the long-term design near the 256 MiB cap. Claude adapter already has streaming-oriented tests; Codex should match that product shape while remaining **stdlib-only**, **no-follow**, **immutable source**.

## Product invariants (do not violate)

- Inert handoff only — never `codex resume` / app-server live attach
- Clean-room behavioral parity — do not copy vendor source
- Bounds: `record_bytes` 16 MiB/line, `source_read_bytes` 256 MiB total, `transcript_records` 50_000 lines, `normalized_turns` 2_000
- Fail closed on unsafe path, missing canonical `session_meta`, ID mismatch, oversize line/file/line-count
- Unknown outer types: skip + warning (existing)

## Scope

**In scope**

- `stable_scan_lines` (or equivalent) in `snapshot.py`: chunked read, line split, per-attempt fingerprint retry (max 3)
- Codex show path: feed records into a reducer; emit `Session` only after attempt succeeds
- Zstd: keep trusted binary allowlist; stream stdout into the same line splitter with compressed-size + decompressed-size caps
- Optional: track latest `turn_context` cwd/model metadata without rendering as a chat turn; prefer latest cwd for filtering when present
- Synthetic **17–30 MiB / 5k–10k line** regression (generated in test temp; not committed as a binary blob if avoidable)
- Docs/STATUS: “streaming show” only after tests green; still **not** live resume parity

**Out of scope**

- Raising default caps above `DEFAULT_BOUNDS`
- Writing ScanAndRepair into Codex state DB
- Cursor/OpenCode streaming refactors except shared snapshot helper reuse

## Steps

### Step 1: `stable_scan_lines` API

```text
each attempt:
  open no-follow → fstat fingerprint
  read 64 KiB chunks → line buffer
  for each complete line:
    enforce record_bytes, transcript_records, source_read_bytes
    callback(line_bytes) or yield parsed policy at adapter
  final fstat; mismatch → discard attempt state, retry
success → return reducer output + fingerprint
```

Do **not** yield partial `Session` to callers mid-attempt.

### Step 2: CodexHistoryReducer

- First matching `session_meta` (UUID == filename) is canonical
- `response_item` / `event_msg` → turns (existing normalize rules)
- `compacted` / rollback handling keep current fail-closed or warn behavior
- Skip unknown outers with `W_UNKNOWN_RECORD_SKIPPED`
- Apply `max_tool_chars` only at sanitize/normalize edge

### Step 3: Wire `show` (+ keep list on heads)

- `_read_rollout` becomes streaming or is replaced for show
- List continues to use head scan from plan 026 (must not call full show)

### Step 4: Zstd streaming

- writer thread → zstd stdin; read stdout chunks into line splitter
- caps: compressed file size, decompressed total, per-line, line count, process timeout
- reject when trusted binary missing (existing partial capability)

### Step 5: Tests

1. Synthetic 17–30 MiB plain rollout show succeeds under default bounds
2. Single line > 16 MiB → `E_LIMIT_EXCEEDED`
3. > 50_000 lines → `E_LIMIT_EXCEEDED`
4. File mutates mid-read → retry / busy, no mixed snapshot
5. Plain vs zstd equivalent handoff (fixture-sized + one larger if CI budget allows)
6. Source tree snapshot unchanged (existing pattern)
7. Four project gates green

## Done criteria

- [ ] Show path peak memory not proportional to full `list[dict]` of raw records for large files (document measurement method: fixture size vs process note or unit bounds)
- [ ] Large synthetic rollout test in CI
- [ ] Zstd path same line/byte caps
- [ ] STATUS: streaming show for Codex = done; live resume = not claimed
- [ ] Linked GitHub issue closed with evidence

## STOP conditions

- Stable fingerprint retries exhaust without clean read → `E_SOURCE_BUSY`, do not return partial turns
- Cannot stream zstd without third-party libs and trusted binary absent → keep capability partial, plain path still ships

## Maintenance notes

P0 whole-file reader may remain briefly behind a flag only if needed for bisect; default post-merge should be streaming. Remove whole-file show path once tests cover both plain and zstd.
