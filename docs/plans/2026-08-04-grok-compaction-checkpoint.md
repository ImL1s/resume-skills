# Grok compaction_checkpoint show support (#238) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven-development to implement this plan task-by-task.

**Goal:** Make Grok `show` (exact id and `latest`) reconstruct public conversation across qualified `compaction_checkpoint` + sidecar events without weakening rewind fail-closed or privacy.

**Architecture:** Checkpoint-aware reducer inside `GrokAdapter._parse_updates`: allowlist-validate the checkpoint event, resolve `checkpoint_file` strictly under the session’s `compaction_checkpoints/`, `stable_read_bytes` the sidecar, project only public user/assistant history, replace the active turn projection, then continue reducing later JSONL records. Multi-checkpoint applies sequentially. `rewind_marker` stays in `_ESSENTIAL_UNSUPPORTED`. List path (`include_turns=False`) recognizes checkpoints without loading sidecars.

**Tech Stack:** Python 3 stdlib; existing `stable_read_bytes` / `stable_scan_lines` / `is_within` / `ReadBudget` / unittest fixtures under `tests/fixtures/grok/`.

---

### Task 1: Synthetic success fixture

**Files:**
- Create: `tests/fixtures/grok/s-gro-07/fixture.json`
- Create: `tests/fixtures/grok/s-gro-07/root/sessions/%2Fworkspace%2Fproject/grok-compact/summary.json`
- Create: `tests/fixtures/grok/s-gro-07/root/sessions/%2Fworkspace%2Fproject/grok-compact/updates.jsonl`
- Create: `tests/fixtures/grok/s-gro-07/root/sessions/%2Fworkspace%2Fproject/grok-compact/compaction_checkpoints/cp-001.json`

**Step 1:** Write synthetic public pre-turns, `auto_compact_*`, one checkpoint + sidecar (`schema_version: 1`, public `compacted_history`, private roles present to prove omission), post-turns.

**Step 2:** Validate tree: `python3 -c "from tests.helpers.fixture_manifest import validate_fixture_tree; from pathlib import Path; validate_fixture_tree(Path('tests/fixtures/grok/s-gro-07'))"`

---

### Task 2: RED tests

**Files:**
- Modify: `tests/adapters/test_opencode_antigravity_grok.py` (or create focused `tests/adapters/test_grok_compaction.py`)

**Cases:**
1. Success: show s-gro-07 includes compacted public + post public exactly once; no system/reasoning.
2. Multi-checkpoint sequential replace without duplicates.
3. Fail-closed: missing sidecar, path escape, wrong schema, id mismatch, symlink if portable, rewind still fails.
4. Existing `test_interior_corruption_and_essential_timeline_event_fail_closed` still fails rewind; checkpoint case updates to success fixture path OR remains fail for bare checkpoint without sidecar.

**Verify (expect RED before GREEN):**
```bash
PYTHONPATH=src python3 -m unittest tests.adapters.test_grok_compaction -v
```

---

### Task 3: GREEN implementation

**Files:**
- Modify: `src/portable_resume/adapters/grok.py`

**Behavior:**
- `_ESSENTIAL_UNSUPPORTED = {"rewind_marker"}` only
- Filter `auto_compact_started` / `auto_compact_completed`
- On `compaction_checkpoint` + `include_turns`: validate allowlist, resolve sidecar, project public history, replace turns
- On `include_turns=False`: count recognized, do not read sidecar

**Verify:**
```bash
PYTHONPATH=src python3 -m unittest tests.adapters.test_grok_compaction tests.adapters.test_opencode_antigravity_grok.GrokAdapterTests -v
```

---

### Task 4: Docs + CHANGELOG

**Files:**
- Modify: `docs/conversation-storage-matrix.md` (Grok section)
- Modify: `CHANGELOG.md` Unreleased
- Optional: STATUS one-line if Open work needs it

**Verify:**
```bash
python3 scripts/check_secrets.py
python3 scripts/check_docs.py
```

---

### Task 5: CLI + dual verify captures

```bash
PYTHONPATH=src python3 -m portable_resume.reader grok show latest --cwd /workspace/project --source-root <fixture-root> --format json
# fail-closed rewind fixture
```

Capture under scratch; re-run unittest twice.

---

### Task 6: Review + PR + CI + merge

requesting-code-review → fix → `gh pr create` closes #238 → CI green → `@codex review` on HEAD → merge.
