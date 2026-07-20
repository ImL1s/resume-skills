# Remaining Sources Live Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make portable-resume **list/show** work on live local stores for **grok**, **antigravity**, and **opencode** (and document Cursor as deferred), matching the value users get from Claude/Codex partial-live.

**Architecture:** Fix false-negative discovery only—skip known co-located files, bounded brain scan, cwd-scoped OpenCode list—without widening safe roots, following symlinks, inventing content, or blind global bound raises. Cursor Desktop reverse stays out of scope.

**Tech Stack:** Python 3.11+ stdlib, unittest, existing adapters.

**Research (multi-agent 2026-07-20):**
- Grok: `E_UNSAFE_PATH` from `prompt_history.jsonl` / `session_search.sqlite` treated as unsafe during walk
- Antigravity: no `brain/index.json` → empty list; no directory scan
- OpenCode: list hard-fails when sessions > 2000 or WAL copy hit 16MiB `record_bytes`
- Cursor: live `store.db` / App Support vscdb ≠ synthetic fixtures → **defer**

---

### Task 1: Grok sessions walk — skip co-located files

**Files:** Modify `src/portable_resume/adapters/grok.py`; Test `tests/unit/test_grok_source_paths.py` or extend adapter tests

- [ ] **Step 1:** Failing test: sessions dir with `session_search.sqlite` + cwd bucket with `prompt_history.jsonl` + valid UUID/updates.jsonl → list succeeds
- [ ] **Step 2:** Skip regular files (not only `.DS_Store`); keep symlink → `E_UNSAFE_PATH`
- [ ] **Step 3:** Optional: prefer encoded cwd bucket for `query.cwd`
- [ ] **Step 4:** Live: `portable-resume grok list --cwd $PWD --json` not `E_UNSAFE_PATH`
- [ ] **Step 5:** Commit

### Task 2: Antigravity no-index transcript scan

**Files:** `src/portable_resume/adapters/antigravity.py`; fixture `tests/fixtures/antigravity/s-ant-07-no-index-scan/`

- [ ] **Step 1:** Failing test without index still lists `brain/<id>/.system_generated/logs/transcript.jsonl`
- [ ] **Step 2:** Bounded listdir + fixed transcript path; index preferred when valid
- [ ] **Step 3:** Commit (honest: live parse may still fail if format ≠ fixture)

### Task 3: OpenCode list bounds

**Files:** `src/portable_resume/adapters/opencode.py`; optionally `snapshot.py` WAL cap note

- [ ] **Step 1:** Failing test / live: list must not raise solely because session count > 2000
- [ ] **Step 2:** Cwd-scoped SELECT + `LIMIT listed_sessions`; no hard fail on overflow
- [ ] **Step 3:** Align WAL snapshot max with sqlite_snapshot_bytes if live WAL > 16MiB
- [ ] **Step 4:** Live smoke + commit

### Task 4: Docs honesty + Cursor defer

**Files:** `docs/STATUS.md`, `docs/source-formats.md` if needed

- [ ] Document partial-live for grok/opencode/agy; Cursor deferred
- [ ] Commit

### Task 5: Full gate

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

### Out of scope
- Cursor live store.db / Desktop vscdb reverse
- Copying Grok bundled skills
- Live host UI 36 cells
- Blind DEFAULT_BOUNDS increases
