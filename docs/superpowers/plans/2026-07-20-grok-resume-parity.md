# Grok resume-session live parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make portable-resume-skills pull real local sessions and hand them off the same way Grok Build’s bundled `resume-session` does (list/show + inert summary), without copying bundled source.

**Architecture:** Keep the clean-room stdlib adapters and skill-bound `run_reader.py`. Close live-read gaps proven by multi-agent research: Claude parent-chain bridging through non-conversation nodes; Codex skip-unknown outer types + compact/rollback/tool render; catalog/docs that still force request-v1; honest STATUS for Cursor/OpenCode/AGY/Grok live. Prefer behavioral parity over byte-identical transcripts.

**Tech Stack:** Python 3.11+ stdlib only, unittest, existing `portable_resume` package, synthetic fixtures under `tests/fixtures/`.

**Research basis (2026-07-20 multi-agent):**
- Claude sparse turns: attachment UUIDs break `_logical_lineage` mid-walk → `W_BROKEN_CHAIN`.
- Codex: outer-type fail-closed, no `compacted.replacement_history` / `thread_rolled_back`, tool calls incomplete; live smoke Grok list=1 vs portable `E_UNSUPPORTED_FORMAT`.
- Cursor: portable synthetic schema ≠ live `store.db` / App Support vscdb — out of V1 full parity (document).
- UX: `catalog.py` `arguments_note` still forces request-v1 into every skill body.

**Provenance:** Do not copy `~/.grok/bundled/skills/**` or `session_reader.py` text. Re-derive from observed on-disk shapes + public docs + fixtures.

---

## File map

| File | Responsibility |
|---|---|
| `src/portable_resume/adapters/claude.py` | Parent bridge through non-turn nodes; optional logicalParentUuid |
| `src/portable_resume/adapters/codex.py` | Skip unknown outer types; compact/rollback; tool_call turns |
| `src/portable_resume/install/catalog.py` | Fix `arguments_note` (request-v1 optional) |
| `src/portable_resume/resources/skill/SKILL.md.tmpl` | CORE-aligned safety bullets if still thin |
| `docs/install-hosts.md`, `docs/STATUS.md`, `docs/source-formats.md`, `README.md` | UX honesty + live evidence labels |
| `tests/fixtures/claude/s-cla-08-attachment-bridge/` | Synthetic attachment sandwich |
| `tests/fixtures/codex/s-cod-13-unknown-outer-and-compact/` | world_state + compacted + tools |
| `tests/adapters/test_claude_codex_cursor.py` or new unit modules | Lock behavior |

---

### Task 1: Catalog + docs — request-v1 is optional

**Files:**
- Modify: `src/portable_resume/install/catalog.py` (claude + grok `arguments_note`)
- Modify: `docs/install-hosts.md` (shared facts table ~line 20)
- Modify: `docs/STATUS.md` (add live-read note for claude list if accurate)
- Test: `tests/unit/test_hosts_catalog.py` or extend `tests/unit/test_grok_parity_cli.py`

- [ ] **Step 1: Write failing test** that rendered skill markdown for host claude must contain `show <ref>` / `run_reader.py show` as primary and must **not** say “Still write a request-v1 file before invoking the runner.”

```python
# tests/unit/test_grok_parity_cli.py — add:
def test_skill_template_argv_primary_not_request_file_required(self) -> None:
    from portable_resume.install.render import render_skill_markdown
    text = render_skill_markdown(host="claude", source="codex")
    self.assertIn("run_reader.py show", text)
    self.assertNotIn("Still write a request-v1 file before invoking the runner.", text)
    self.assertIn("Optional advanced path", text)  # or "optional" near request-v1
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd <repo>
PYTHONPATH=src python3 -m unittest tests.unit.test_grok_parity_cli.SkillBoundArgvTests.test_skill_template_argv_primary_not_request_file_required -v
```

- [ ] **Step 3: Fix catalog `arguments_note` for claude and grok**

Replace forced request-v1 language with:

```python
arguments_note=(
    "If this host expands `$ARGUMENTS` / invocation tail into the skill prompt, "
    "use that text as the session <ref> (or omit for latest). "
    "It is never process argv by itself. "
    "Optional advanced path: write portable-resume/request-v1 then "
    "`run_reader.py --request-file <path>`."
),
```

Update `docs/install-hosts.md` shared table: runtime contract = Grok-style `run_reader.py show|list`, request-v1 optional.

- [ ] **Step 4: Run tests PASS + commit**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_grok_parity_cli -q
git add src/portable_resume/install/catalog.py docs/install-hosts.md tests/unit/test_grok_parity_cli.py
git commit -m "docs: make request-v1 optional; argv path is primary like Grok"
```

---

### Task 2: Claude attachment-parent bridge

**Files:**
- Modify: `src/portable_resume/adapters/claude.py` (`_logical_lineage` and helpers)
- Create: `tests/fixtures/claude/s-cla-08-attachment-bridge/` (fixture.json + root jsonl)
- Modify: `tests/adapters/test_claude_codex_cursor.py` (or new `tests/unit/test_claude_bridge.py`)

- [ ] **Step 1: Write failing test** — user → attachment → assistant must yield user+assistant turns without `W_BROKEN_CHAIN`.

```python
def test_attachment_parent_bridge_recovers_main_line(self) -> None:
    # Build temp root: projects/<slug>/<uuid>.jsonl with:
    # user (uuid=u1, parent=None)
    # attachment (uuid=a1, parent=u1)
    # assistant (uuid=s1, parent=a1)  # parent is attachment
    # show latest → turns roles include user then assistant; no W_BROKEN_CHAIN
```

- [ ] **Step 2: Run test — expect FAIL** (current code stops at attachment parent)

- [ ] **Step 3: Implement bridge**

In `_logical_lineage` (or new helper):

1. Build `parent_of: dict[str, str | None]` for **every** record that has `uuid` + optional `parentUuid` (all types that carry those fields).
2. Conversation nodes remain only user/assistant/system (non-sidechain) for **emission**.
3. When walking `parentUuid`, if parent is missing from conversation nodes but present in `parent_of`, hop: `cur = parent_of.get(cur)` without emitting until a conversation node or missing UUID.
4. Emit `W_BROKEN_CHAIN` only when parent UUID is **nowhere** in the file.
5. Optional: if `parentUuid` missing but `logicalParentUuid` is a str and present, try that after primary hop fails.

Do **not** emit attachment/hook payloads as turns.

- [ ] **Step 4: Run adapter + full suite**

```bash
PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor tests.unit.test_claude_bridge -q
# optional live:
PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd <project> --format handoff | head -40
```

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(claude): bridge parent chain through non-conversation nodes"
```

---

### Task 3: Codex skip unknown outer types + compact/rollback

**Files:**
- Modify: `src/portable_resume/adapters/codex.py`
- Create: `tests/fixtures/codex/s-cod-13-outer-skip-compact/`
- Test: `tests/adapters/test_claude_codex_cursor.py` or `tests/unit/test_codex_parity.py`

- [ ] **Step 1: Failing tests**

1. Rollout line with `"type":"world_state"` between valid `session_meta` and `response_item` → **show succeeds**, warning `W_UNKNOWN_RECORD_SKIPPED` (or codex-specific code already in WARNING_CODES — add `W_UNKNOWN_RECORD_SKIPPED` if used).
2. `compacted` with `replacement_history` list of message items, then new `response_item` → turns reflect post-compact view.
3. `event_msg` with `thread_rolled_back` / num_turns → last N user-side turns dropped from normalized view.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Minimal implementation**

- In parse loop: if outer `type` not in safe set, skip + warning (do not abort entire file).
- Safe set include current types + treat `world_state`, `inter_agent_communication*`, `turn_context` as skippable.
- On `compacted`: if `payload.replacement_history` is a list of items, replace base turn buffer with those items (then continue).
- On `event_msg` rolled back: drop last N user turns from buffer (match product intent: inert history).

- [ ] **Step 4: Live smoke**

```bash
PYTHONPATH=src python3 scripts/portable-resume codex list --cwd <project> --within-min 0 --json
# should not be E_UNSUPPORTED_FORMAT solely due to unknown outer types
```

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(codex): skip unknown outer types; apply compact and rollback"
```

---

### Task 4: Codex tool_call inert turns (function/local_shell)

**Files:**
- Modify: `src/portable_resume/adapters/codex.py` (`_raw_turn` / render)
- Test: extend Task 3 fixture or new case

- [ ] **Step 1: Failing test** — `response_item` with `function_call` name + string/dict output produces assistant/tool turn text (inert), not empty.

- [ ] **Step 2–4: Implement minimal inert tool summary** (name + truncated args/output via existing sanitize bounds). No execution.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(codex): surface inert function/shell tool calls in handoff turns"
```

---

### Task 5: Antigravity list without brain index

**Files:**
- Modify: `src/portable_resume/adapters/antigravity.py`
- Fixture: `tests/fixtures/antigravity/s-ant-07-no-index-scan/`
- Test: `tests/adapters/test_opencode_antigravity_grok.py`

- [ ] **Step 1: Failing test** — store with `brain/<id>/…/transcript.jsonl` but **no** `brain/index.json` still lists session for matching cwd (or lists by path) so `show latest` works.

- [ ] **Step 2–4: Bounded directory scan** under approved root for `transcript.jsonl` (depth/count limits via DEFAULT_BOUNDS). Index remains preferred hint when present. No content invention.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(antigravity): discover transcripts when brain index missing"
```

---

### Task 6: STATUS + source-formats honesty + optional within-min note

**Files:**
- Modify: `docs/STATUS.md`, `docs/source-formats.md`, `docs/host-support.md` if needed
- Modify: `README.md` Limitations if needed

- [ ] **Step 1: Document** what is live-proven vs fixture-only after Tasks 1–5:
  - Claude: live list/show metadata proven; turns improved by bridge (not full restore)
  - Codex: unknown-type + compact fixed; live list depends on machine stores
  - Cursor: still fixture/synthetic — **not** live Grok-desktop parity
  - OpenCode/Grok adapters: fixture-ready; compaction/rewind policies documented

- [ ] **Step 2: Commit**

```bash
git commit -m "docs: record Grok-parity live evidence and remaining limits"
```

---

### Task 7: Full gate + self_verify

- [ ] **Step 1: Run full suite**

```bash
cd <repo>
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

Expected: OVERALL_SELF_VERIFY PASS, SECRET CLEAN, all tests OK.

- [ ] **Step 2: Push if green**

```bash
git push origin main
```

---

## Out of scope (this plan)

- Full Cursor live Desktop vscdb / `store.db` reverse (separate plan; schema mismatch is large).
- Copying Grok `session_reader.py` or skill bodies.
- Claiming live host UI activation (still not-run).
- Raising fail-closed SQLite hot-journal / trusted zstd path policy.

## Self-review

| Spec need | Task |
|---|---|
| Grok-like skill UX | Task 1 |
| Actually pull Claude conversation main-line | Task 2 |
| Codex live list/show not die on modern records | Task 3–4 |
| AGY latest without index | Task 5 |
| Honest docs | Task 6–7 |
| No Cursor overclaim | Out of scope + Task 6 |

No TBD placeholders in task steps.
