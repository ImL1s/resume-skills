# Plan 028: Kimi stream index/wire + metadata list + FS fallback (Issue #14)

> Related: [Issue #14](https://github.com/ImL1s/resume-skills/issues/14), umbrella [Issue #18](https://github.com/ImL1s/resume-skills/issues/18), shared `#10` `stable_scan_lines`.

## Status

**DONE** on `main` via [PR #58](https://github.com/ImL1s/resume-skills/pull/58) → `79d32ae`
([Issue #14](https://github.com/ImL1s/resume-skills/issues/14) closed COMPLETED).
Post-merge CI: [run 30267866248](https://github.com/ImL1s/resume-skills/actions/runs/30267866248).

## Summary

Stop treating whole Kimi `session_index.jsonl` / `wire.jsonl` as a single 16 MiB `stable_read_bytes` record. Use aggregate `source_read_bytes`, per-line `record_bytes`, append-only index reduce, metadata-only list, exact-path show with `W_STALE_INDEX`, and read-only `sessions/` FS fallback.

## Done criteria checklist

- [x] Append-only index reduced without retaining all raw entries
- [x] `list` no longer full-parses wire/context
- [x] Exact safe path show not blocked by optional stale index
- [x] Read-only current-store filesystem fallback bounded + tested
- [x] Full histories use `source_read_bytes` + per-line `record_bytes` + `transcript_records`
- [x] Uses `#10` `stable_scan_lines`
- [x] Four canonical project gates (self_verify, secrets, 375 unittest, 81/81 smoke)
- [x] STATUS/CHANGELOG distinguish Kimi #14 vs other adapters
- [x] Merged to `main` (`79d32ae`); issue closed; post-merge CI green

## Out of scope

- Raising global bounds
- Live process restore / invoking Kimi CLI
- Silent tail-only “~15 MiB” partial resume
- Codex/Cursor/other adapter migrations
