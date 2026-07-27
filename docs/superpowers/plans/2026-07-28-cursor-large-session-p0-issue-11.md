# Cursor Large-Session P0 (#11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate silent Cursor transcript/SQL truncation and align JSONL/SQL budgeting with the shared #10 contract so `show` never returns a plausible incomplete handoff.

**Architecture:** Reuse `stable_scan_lines` (source_read_bytes + record_bytes per line + transcript_records when parsing full show) for CLI JSONL; live CLI SQLite uses LIMIT n+1 overflow fail-closed; synthetic Desktop filters archived/subagent in SQL before ORDER/LIMIT; live Desktop `composerData` length-gated and charged before JSON decode. Full bubble graph remains not claimed.

**Tech Stack:** Python 3 stdlib, existing `ReadBudget`/`Bounds`, `stable_scan_lines`/`stable_read_bytes`, unittest + synthetic fixtures only.

**Spec:** GitHub issue #11; prior Kimi pattern in `adapters/kimi.py` (`_iter_jsonl` + `stable_scan_lines`).

---

## File map

| Path | Responsibility |
|---|---|
| `src/portable_resume/adapters/cursor.py` | CLI JSONL `_parse_transcript`; synthetic `_desktop_summaries` SQL filters; optional list title metadata path |
| `src/portable_resume/adapters/cursor_live.py` | Live CLI `store.db` overflow; live Desktop composerData budget |
| `tests/unit/test_cursor_large_session.py` | New P0 regressions (JSONL budgets, 2001 blobs, filter-before-LIMIT, composerData size) |
| `tests/unit/test_cursor_live_store.py` | Extend live store overflow if needed |
| `CHANGELOG.md`, `docs/STATUS.md` | Honest done providers |

---

### Task 1: CLI JSONL streaming parse (#11 step 1)

**Files:**
- Modify: `src/portable_resume/adapters/cursor.py` (`_parse_transcript`, list title fallback if it full-parses)
- Create: `tests/unit/test_cursor_large_session.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_cursor_large_session.py — synthetic CLI session under temp root
# 1) show with > record_bytes whole-file must still work if lines are small
#    (file size between record_bytes and source_read_bytes)
# 2) line count > transcript_records raises E_LIMIT_EXCEEDED (no partial Session)
# 3) list with metadata title does not require full transcript open
```

- [ ] **Step 2: Implement `_parse_transcript` via `stable_scan_lines`**

- Use `stable_scan_lines(..., charge_transcript=True)` so aggregate file charges `source_read_bytes` and lines charge `transcript_records` / per-line `record_bytes`.
- Keep blob content via `stable_read_bytes` with `record_bytes` when `content_blob` present.
- Preserve `W_PARTIAL_TAIL` / corrupt / unsupported behaviors.
- Prefer not using `consume_records()` for transcript lines (use transcript path).

- [ ] **Step 3: Run targeted tests green; commit**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_cursor_large_session tests.adapters.test_claude_codex_cursor -q
```

---

### Task 2: Live CLI SQLite overflow (#11 step 2)

**Files:**
- Modify: `src/portable_resume/adapters/cursor_live.py` (`_show_live_cli_store`)
- Modify: `tests/unit/test_cursor_live_store.py` and/or `tests/unit/test_cursor_large_session.py`

- [ ] **Step 1: Write failing test** — insert 2001 blobs; show must raise `E_LIMIT_EXCEEDED` (or equivalent explicit fail), not return only first 2000 silently; last user text after row 2000 must not be omitted as success.

- [ ] **Step 2: Implement**

```sql
SELECT id, data FROM blobs ORDER BY rowid ASC, id ASC LIMIT ?
-- bind transcript_records + 1 (clamped)
```

- If `len(rows) > transcript_records`: `raise DiagnosticError.limit_exceeded()` before building Session.
- Charge each admitted blob with `consume_transcript_records` and length vs `record_bytes` / remaining `source_read_bytes` before decode.
- Prefer `length(data)` in SQL if portable; else `len(bytes)` after fetch with reject before decode for oversized.

- [ ] **Step 3: Tests green; commit**

---

### Task 3: Synthetic Desktop filter-before-LIMIT + exact ID (#11 step 3)

**Files:**
- Modify: `src/portable_resume/adapters/cursor.py` (`_desktop_summaries`)
- Test in `tests/unit/test_cursor_large_session.py`

- [ ] **Step 1: Failing test** — many newer archived/subagent rows + one older eligible project composer; list window must still surface eligible parent; exact-ID for archived still works.

- [ ] **Step 2: SQL**

Normal list:

```sql
... FROM cursor_composers
WHERE archived=0 AND composer_kind='project'
  [AND cwd predicates if safe]
ORDER BY updated_at DESC, id ASC
LIMIT ?
```

Exact ID path: `WHERE id=?` (or UUID-normalized equality) without crowding filters that hide archived when ref matches.

- [ ] **Step 3: Tests green; commit**

---

### Task 4: Live Desktop composerData bounds (#11 step 4)

**Files:**
- Modify: `src/portable_resume/adapters/cursor_live.py` (`_show_live_desktop`)
- Test: synthetic oversized value fails before successful partial Session claiming full content.

- [ ] Select `length(CAST(value AS BLOB))` with value (or length of fetched bytes).
- [ ] Reject when over remaining `source_read_bytes` / `record_bytes` policy consistent with other adapters.
- [ ] `budget.consume_bytes` before `json.loads`.
- [ ] Tests green; commit

---

### Task 5: Docs + full gates + PR merge

- [ ] STATUS/CHANGELOG: Cursor CLI JSONL + live CLI store + synthetic Desktop filter-before-LIMIT + live Desktop blob bound; **full bubble graph still not claimed**.
- [ ] Full project gates → `{SCRATCH}/gates.log`
- [ ] PR + CI + AI review + squash-merge; close #11 with evidence in `{SCRATCH}/ship-evidence.md`

---

## Self-review

1. Spec coverage: issue steps 1–4 map to Tasks 1–4; step 5 provider separation preserved.
2. No placeholders: concrete SQL and stable_scan_lines usage.
3. Residual honesty: bubble graph not claimed; true streaming yield of stable_scan_lines may still collect then yield (existing #10 residual).
