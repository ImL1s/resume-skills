# Plan 045: Add a real-schema Claude tool fixture and assert through the handoff renderer

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/adapters/claude.py src/portable_resume/handoff.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (additive tests/fixtures)
- **Depends on**: none — **this is the prerequisite for plans 046 and 047**
- **Category**: tests
- **Planned at**: commit `2b4611c`, 2026-08-01
- **Issue**: https://github.com/ImL1s/resume-skills/issues/162

## Why this matters

Two real defects in the handoff pipeline (tool calls silently discarded; the
"latest assistant action" field skipping tool turns) survived review because
the only test covering the tool path **fabricates a message shape production
never emits**. It hand-builds a `tool_result` block carrying a `tool_name`
key; the real Anthropic block has no such key, so the adapter's
`item.get("tool_name")` is always `None` against real data while the test
passes green. No committed Claude fixture contains a tool block at all.

Until fixtures use the real schema, any fix to the tool-rendering path is
unverifiable — so this plan lands first and, on its own, should make the
latent defects visible as failing or plainly-wrong output.

## Current state

- **Zero** committed Claude fixtures contain tool blocks:

```bash
grep -rl "tool_use\|tool_result" tests/fixtures/claude/    # → no matches
```

- The only covering test fabricates the schema —
  `tests/adapters/test_claude_codex_cursor.py` around line 142:

```python
                [{"type": "tool_result", "content": "tool output", "tool_name": "Read"}],
```

- **The real block schema** (verified against a live transcript under
  `~/.claude/projects/`; do NOT copy any real content into fixtures — shape
  only):
  - assistant message content item: `{"type": "tool_use", "id": "<toolu_...>",
    "name": "<ToolName>", "input": {...}, "caller": ...}` — keys are exactly
    `caller`, `id`, `input`, `name`, `type`.
  - the following user message content item: `{"type": "tool_result",
    "tool_use_id": "<toolu_...>", "content": <str or list-of-blocks>}` —
    keys are exactly `content`, `tool_use_id`, `type`. **There is no
    `tool_name` key.**
- The adapter code this fixture will exercise —
  `src/portable_resume/adapters/claude.py` around lines 1005–1022:

```python
        kind = item.get("type")
        if kind in {"thinking", "redacted_thinking", "signature", "tool_use"}:
            continue
        ...
        elif kind == "tool_result":
            text = _flatten_text(item.get("content"))
            if text is not None:
                values.append(
                    {
                        "role": "tool",
                        "content": text,
                        "tool_name": item.get("tool_name") if isinstance(item.get("tool_name"), str) else None,
                        "timestamp": timestamp,
                    }
                )
```

- The renderer that consumes it — `src/portable_resume/handoff.py`
  `_turn_block` around line 164:

```python
    label = f"[{turn.ordinal} {_value(turn.role)}{'/' + _value(turn.tool_name) if turn.tool_name else ''}]"
```

- **Repo fixture rules** (`CONTRIBUTING.md`, "Code and fixture rules"): every
  fixture manifest must carry `"synthetic": true`, a registered `format_id`,
  and a `docs/source-formats.md` provenance anchor. Never commit real
  transcripts or absolute developer home paths. Model the new fixture on an
  existing one — read
  `tests/fixtures/claude/s-cla-01-ordered-parent-chain/` in full first
  (manifest + JSONL layout + the cwd it declares).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Adapter tests | `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor -v` | pass |
| Render the fixture | `PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd /workspace/project --source-root tests/fixtures/claude/<new-fixture>/root --format handoff` | exit 0, handoff markdown |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**:
- `tests/fixtures/claude/<new-fixture-id>/**` (create — follow the existing
  fixture id convention, e.g. `s-cla-NN-tool-use-result`)
- `tests/adapters/test_claude_codex_cursor.py` — fix the fabricated block; add
  handoff-level assertions
- `docs/source-formats.md` — provenance anchor for the new fixture if the
  existing anchor does not already cover this shape
- `plans/README.md` — status row

**Out of scope** (deliberately — later plans own these):
- `src/portable_resume/adapters/claude.py` — do NOT fix the discard of
  `tool_use` or the `tool_name` lookup here. **Plan 046 does that.** This plan
  only makes the gap visible and testable.
- `src/portable_resume/handoff.py` — plans 046–048.
- Any other adapter's fixtures.

## Git workflow

- Branch: `plan/045-claude-tool-fixture`
- Commit style (match `git log`): `test(claude): real-schema tool_use/tool_result fixture`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Read an existing fixture end to end

Read `tests/fixtures/claude/s-cla-01-ordered-parent-chain/` completely — the
manifest file, the JSONL record shape, the parent-chain linkage, and the cwd
it declares. Your new fixture must match that structure exactly except for the
added tool blocks.

**Verify**: you can state (in your report) which file is the manifest, what
`format_id` it declares, and what `--cwd` value renders it.

### Step 2: Create the tool fixture

Create `tests/fixtures/claude/<id>/root/...` with a synthetic session of at
least 4 messages in the real schema:

1. user: plain text (the request).
2. assistant: content array containing a `text` block AND a `tool_use` block
   with `id`, `name` (e.g. `"Read"`), and a small `input` object (e.g.
   `{"file_path": "/workspace/project/app.py"}`).
3. user: content array containing a `tool_result` block with the **matching**
   `tool_use_id` and a short `content` string. **No `tool_name` key.**
4. assistant: a second `tool_use` (e.g. `name: "Bash"`, `input:
   {"command": "pytest -x"}`) so the fixture covers *two* calls — this is what
   makes the "which result belongs to which call" problem visible.

Manifest carries `"synthetic": true` and the registered `format_id`. All
content is invented; no real paths (`/workspace/project` style only).

**Verify**: `PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd /workspace/project --source-root tests/fixtures/claude/<id>/root --format handoff`
→ exit 0. **Expect the known-bad output**: tool turns render as bare
`[N tool]` with no tool name, and the `tool_use` blocks (the `Read` and the
`pytest` command) do not appear at all. Record this output verbatim in your
completion report — it is the baseline plan 046 must change.

### Step 3: Fix the fabricated block in the existing test

In `tests/adapters/test_claude_codex_cursor.py` (~line 142), remove the
non-existent `"tool_name": "Read"` key from the hand-built `tool_result` and
add `"tool_use_id"` matching a `tool_use` id, so the test data matches
production shape.

If that removal makes an existing assertion fail, the assertion was pinning
the fabricated behavior: **do not weaken the fixture to keep it green** —
adjust the assertion to describe today's real behavior (tool name absent) and
note in your report that plan 046 will change it.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor -v` → pass.

### Step 4: Add handoff-level assertions

Add a test that renders the new fixture **through the handoff renderer**
(not just the adapter) and asserts on the rendered text. Find the pattern with
`grep -rln "render_handoff\|--format handoff" tests/ | head`.

Assert today's truth explicitly, so the test documents the gap:
- the tool result content appears;
- the turn label for tool turns is `[N tool]` (no `/ToolName` suffix);
- the strings from the `tool_use` inputs (the file path, the command) do
  **not** appear.

Name the test so its intent is obvious, e.g.
`test_tool_use_input_is_currently_not_rendered_see_plan_046`.

**Verify**: new test passes; full suite OK.

### Step 5: Full gates

**Verify**:
- `PYTHONPATH=src python3 -m unittest discover -s tests -q` → OK
- `python3 scripts/self_verify.py` → exit 0
- `python3 scripts/check_secrets.py` → exit 0

## Test plan

- New fixture rendered through both adapter and handoff layers.
- Assertions pin **current** behavior (tool identity lost), so plan 046 has a
  failing target to flip rather than a vacuum.
- Pattern to follow: the existing Claude adapter tests plus whichever test
  module already asserts on rendered handoff text.

## Done criteria

- [ ] A Claude fixture exists containing `tool_use` (with `id`, `name`, `input`) and a matching `tool_result` (with `tool_use_id`, no `tool_name`)
- [ ] `grep -rl "tool_use" tests/fixtures/claude/` returns at least one path
- [ ] `grep -rn '"tool_name"' tests/adapters/test_claude_codex_cursor.py` returns no fabricated-block hit
- [ ] A test asserts on rendered handoff text for that fixture
- [ ] Baseline output recorded in the completion report
- [ ] Full suite + `self_verify.py` + `check_secrets.py` green
- [ ] `plans/README.md` status row updated

## STOP conditions

- The real block schema in your environment differs from the keys listed in
  "Current state" — report the actual keys; do not invent a third shape.
- Removing the fabricated `tool_name` breaks more than the single test module
  — report the blast radius before proceeding.
- You find yourself editing `adapters/claude.py` or `handoff.py` — out of
  scope by definition; that is plan 046.

## Maintenance notes

- This fixture is the regression net for plans 046 and 047; its assertions
  flip from "not rendered" to "rendered" when 046 lands. Keep the fixture
  itself unchanged in that plan so the diff is purely renderer behavior.
- The other 16 adapters likely have the same fixture gap for tool evidence —
  audited but not planned this round; worth a follow-up sweep.
