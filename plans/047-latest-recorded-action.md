# Plan 047: Stop reporting stale intent as the "latest assistant action"

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/handoff.py src/portable_resume/adapters/ src/portable_resume/model.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Implementation status**: **DONE**
- **Implementation decision**: **Option A** — keep the public envelope field
  unchanged, render it as "Latest assistant message", and derive a separate
  "Latest recorded action" from the newest assistant/tool turn.
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW–MED (`last_assistant_action` is a public envelope field)
- **Depends on**: plans/045 (fixture) and **plans/046 — hard dependency, not a preference** (see below)
- **Category**: bug (handoff content)
- **Planned at**: commit `2b4611c`, 2026-08-01
- **Issue**: https://github.com/ImL1s/resume-skills/issues/164

### Implementation audit

- The prerequisite grep finds `tool_use` in Claude's handled record branch,
  not in its discard set; Plan 046 is present at this branch's base.
- The reversed assistant-only legacy derivation appears at **20** sites across
  the adapters. Option A intentionally leaves all 20 public-envelope
  derivations unchanged and computes the new presentation from
  `Session.turns` in the handoff renderer.
- Existing adapters that normalize tool evidence continue to retain those
  tool turns in `Session.turns`; adapters without a normalized tool-turn
  surface are not made to invent one here. No adapter restructuring or schema
  change was required.

## Why this matters

The handoff's most prominent state field — "Latest assistant action" — is
derived as *the last turn whose role is `assistant`*. Tool turns carry
`role == "tool"`, so they can never win. When a session is interrupted **mid
tool-loop** — the dominant real resume case — the field reports the last thing
the model *said*, not the last thing it *did*.

Observed against a realistic transcript where the session stopped right after
an `Edit`:

```
### Latest assistant action
> I'll start by mapping the call sites.

> **[2 tool]**
> Applied 1 edit to billing/charge.py
```

The real last action was a file edit applied eight minutes after that
sentence. A resuming agent reads "we were still planning" and may redo or
conflict with an edit that is already on disk. The only thing standing
between this and a duplicated edit is a generic checklist line.

**Why 046 is a hard prerequisite** (raised as P2 in review): until 046 lands,
Claude's turn assembly still discards `tool_use` blocks entirely. Running this
plan first would let the reversed scan pick up an *earlier* tool **result**
and label it the latest action, while a renderer-only fixture could still make
the new test pass — the interrupted-call defect would survive behind a green
test. Do not execute this plan before 046 unless you also surface pending
`tool_use` records here, which is 046's job.

## Current state

- **The renderer** — `src/portable_resume/handoff.py` `_assemble`, around
  lines 187–188:

```python
    lines.append("### Latest assistant action")
    lines.extend(assistant_lines if assistant_lines is not None else _quote(assistant_text))
```

  `assistant_text` is `session.last_assistant_action`.

- **The derivation, duplicated across adapters** — e.g.
  `src/portable_resume/adapters/claude.py` around lines 1396–1399:

```python
            last_assistant = next(
                (turn.content for turn in reversed(turns) if turn.role == "assistant"),
                None,
            )
```

  The identical idiom appears in `adapters/pi.py` (~line 161),
  `adapters/cursor.py` (~631), `adapters/grok.py` (~164),
  `adapters/kimi.py` (~291) and roughly a dozen more. Enumerate every site
  before editing:

```bash
grep -rn 'role == "assistant"' src/portable_resume/adapters/ | grep -n "reversed"
```

- **Roles in play**: `assistant`, `user`, `tool` (see the turn construction in
  any adapter and `src/portable_resume/model.py`'s `Turn`).
- `last_assistant_action` is a field on the public envelope — check
  `src/portable_resume/resources/portable-resume-v1.schema.json` and
  `src/portable_resume/contracts.py` before renaming anything.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Render 045's fixture | `PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd /workspace/project --source-root tests/fixtures/claude/s-cla-08-tool-use-result/root --format handoff` | exit 0; action field reflects the tool call |
| Contract tests | `PYTHONPATH=src python3 -m unittest tests.unit.test_contract_equivalence -v` | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**:
- `src/portable_resume/handoff.py` — the rendered headings
- The `last_assistant_action` derivation in every adapter that uses the
  reversed-scan idiom
- Adapter + handoff tests
- `plans/README.md` — status row

**Out of scope**:
- Renaming or adding envelope fields (see STOP conditions).
- `last_user_request` semantics for `pi` — that is plan 049.
- Tool-call *content* rendering — plan 046.

## Git workflow

- Branch: `plan/047-latest-recorded-action`
- Commit style: `fix(handoff): latest recorded action includes tool turns`

## Steps

### Step 1: Choose the presentation (record the choice)

Two options — pick ONE and state it in your report:

**A. Two labelled lines** (preferred): keep the existing prose field but
rename its heading to "Latest assistant message", and add a new rendered line
"Latest recorded action" derived from the last turn whose role is `assistant`
**or** `tool`. Intent and action are then both visible and never conflated.
No envelope field is renamed; the new line is rendered from data already in
`session.turns`, so it needs no schema change.

**B. Redefine the existing field** to mean last assistant-or-tool turn. One
line, but it silently changes the meaning of a public envelope field for
existing consumers.

Prefer **A**.

**Verify**: the choice is written down before code changes.

### Step 2: Implement

For option A, compute the action line inside `handoff.py` from
`session.turns` (do not add an envelope field):

```python
    last_action = next(
        (turn for turn in reversed(session.turns) if turn.role in {"assistant", "tool"}),
        None,
    )
```

Render it with the same `_quote`/`_turn_block` conventions used nearby, and
when the last action is a tool turn, include its identity (post-046 the turn
carries `tool_name`) so the line reads like "tool/Edit — Applied 1 edit to …"
rather than an anonymous blob. When there are no turns, render the existing
`_(not persisted)_` form.

**Verify**: 045's fixture shows the tool call as the latest recorded action
while the message line still shows the prose.

### Step 3: Cover the interrupted-session case with a fixture

Add (or extend) a fixture whose final turn is a **tool** turn following an
assistant text turn — i.e. the interrupted-mid-tool-loop shape. Assert on
rendered handoff text that:
1. "Latest recorded action" reflects the tool turn, and
2. the assistant prose is still present under its own heading, and
3. the two are not the same string.

**Verify**: new test passes.

### Step 4: Adapter sweep for the derivation

If you chose A, adapters need no change — the new line is renderer-derived.
Confirm that with the grep from "Current state" and state it in the report.
If any adapter *filters tool turns out of `session.turns` entirely* (so the
renderer cannot see them), that adapter needs a fix here; list any such
adapter and handle it, or report if the list is long.

**Verify**: `grep -rn 'role == "assistant"' src/portable_resume/adapters/ | wc -l` recorded in the report, with a one-line statement of why each site is or is not affected.

### Step 5: Full gates

**Verify**: full suite OK; `self_verify.py` → 0; `check_secrets.py` → 0;
`PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` → 0.

## Test plan

- Interrupted-mid-tool-loop fixture asserted through rendered handoff text
  (Step 3).
- A session ending on an assistant text turn still renders both lines
  identically-sourced (no regression for the simple case).
- A session with zero turns renders the not-persisted form.
- Existing contract tests must pass untouched (option A adds no envelope
  field).

## Done criteria

- [x] Rendered handoff distinguishes "latest assistant message" from "latest recorded action"
- [x] An interrupted-mid-tool-loop fixture proves the action line reflects the tool turn
- [x] No envelope/schema field added or renamed (`git diff` on `resources/portable-resume-v1.schema.json` is empty)
- [x] Full suite + smoke matrix + gates green
- [x] `plans/README.md` updated

## STOP conditions

- **Plan 046 has not landed** — check with
  `grep -n '"tool_use"' src/portable_resume/adapters/claude.py`; if it still
  appears in the discard set, STOP. Executing this plan first yields a green
  test over a still-broken path (the scan would label an earlier tool result
  as the latest action).
- Option A turns out to need a schema change after all — STOP and report;
  do not edit the schema on your own initiative.
- Some adapter drops tool turns from `session.turns` before the renderer sees
  them, and fixing it requires restructuring that adapter's turn assembly —
  report rather than refactoring broadly.
- Existing tests assert the exact heading string "Latest assistant action" in
  a way that makes renaming it a large sweep — report the count; keeping the
  old heading and adding the new line is an acceptable fallback.

## Maintenance notes

- Reviewer: confirm the action line cannot leak unsanitized content — it
  reads the same `Turn` objects the transcript section already renders.
- If plan 046 lands first, the action line gains the tool name for free; if
  it does not, the line still fixes the *staleness* (it will just say "tool"
  without identity).
