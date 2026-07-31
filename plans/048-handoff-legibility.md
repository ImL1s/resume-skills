# Plan 048: Make truncation visible at the cut point and warnings self-explaining, above the evidence

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/handoff.py src/portable_resume/diagnostics.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (output-only)
- **Depends on**: none (composes with 046/047; order irrelevant)
- **Category**: dx (handoff legibility)
- **Planned at**: commit `2b4611c`, 2026-08-01

## Why this matters

Two output-only defects make the handoff harder to trust than it needs to be:

1. **Silent truncation.** When a transcript is too large, the renderer keeps
   the newest turns (correct) and drops the oldest — which is where the
   original goal and plan live. Nothing is written at the cut point. The agent
   sees the transcript begin at ordinal 53 and must *infer* from the ordinal
   alone that 53 turns are missing — an inference that requires knowing
   ordinals are dense and 0-based, which the document never states. The only
   signal is a `W_TRUNCATED` line in the footer, after the evidence.

2. **Unexplained warnings, in the wrong place.** Warnings render as bare
   codes (`> - \`W_BROKEN_CHAIN\``) *after* the transcript. The required
   response differs sharply per code and a weak agent cannot infer it:
   `W_BROKEN_CHAIN` means turn order may be wrong; `W_PARTIAL_TAIL` means the
   **newest** turns may be missing (which directly contradicts the renderer's
   newest-kept guarantee); `W_STALE_INDEX` means the metadata block may not
   describe the content below it. Placing them after the evidence means the
   agent has already read and trusted that evidence before learning it is
   unreliable.

## Current state

- **Warning rendering** — `src/portable_resume/handoff.py` around lines
  57–59:

```python
def _warning_lines(warnings: Iterable[str]) -> list[str]:
    stable = tuple(dict.fromkeys(warnings))
    return [f"> - `{_value(warning)}`" for warning in stable] if stable else ["> - none"]
```

- **Warning placement** — same file, around lines 155–159 (the block is
  appended *after* the transcript section built in `_assemble`):

```python
        values.append("W_TRUNCATED")
    lines = ["", "## Warnings", *_warning_lines(values)]
    if output_truncated:
        lines.append(_TRUNCATION_NOTICE)
    lines.extend(("", "## Required current checks (unchecked)", *CHECKLIST))
    return lines
```

- **The truncation notice** — around lines 27–29, naming no count and not
  distinguishing dropped turns from shortened bodies:

```python
_TRUNCATION_NOTICE = (
    "> `[W_TRUNCATED]` recovered display content was reduced to fit the handoff output budget."
)
```

- **Where turns are dropped** — around lines 229–248, a binary search keeping
  the newest K turns:

```python
    total = len(session.turns)
    lo, hi = 0, total
    best_turns: tuple[Turn, ...] = ()
    while lo <= hi:
        mid = (lo + hi) // 2
        kept = session.turns[total - mid :] if mid else ()
```

- **Where the section starts** — `_assemble` around lines 190–200, which
  opens `### Bounded transcript evidence` and immediately loops the survivors:

```python
    lines.append("### Bounded transcript evidence")
    if not turns:
        ...
    else:
        for turn in turns:
            lines.append("")
            lines.extend(_turn_block(turn))
```

- **The warning vocabulary** — `src/portable_resume/diagnostics.py`
  `WARNING_CODES` (14 codes) is the authoritative set; adapters raise them
  (e.g. `W_BROKEN_CHAIN` in `adapters/claude.py`, `W_STALE_INDEX` in
  `adapters/kimi.py`). No user-facing doc defines any of them today. **Plan
  032** (already merged as a plan) creates `docs/diagnostics.md` as the
  reference page — this plan does the in-handoff one-liners; keep the two
  consistent in wording if 032 has landed.
- **Markdown nit to fix while you are here**: `_TRUNCATION_NOTICE` is emitted
  as a bare `>` line directly after a `> - ` bullet, so CommonMark lazy
  continuation folds it into the `W_TRUNCATED` list item.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Render a fixture | `PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd /workspace/project --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root --format handoff` | exit 0 |
| Handoff tests | find with `grep -rln "render_handoff" tests/ \| head`, then run those modules | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**: `src/portable_resume/handoff.py`; handoff test modules;
`plans/README.md` row.

**Out of scope**:
- `diagnostics.py` `WARNING_CODES` itself — read it, do not change the set.
- Adding/removing warning *emission* in adapters.
- The security banner and the 6-item checklist — measured at ~926 B of fixed
  framing, judged worth keeping (the checklist is the only per-invocation
  statement of the safety contract). Do not trim them.
- `docs/diagnostics.md` — plan 032 owns it.

## Git workflow

- Branch: `plan/048-handoff-legibility`
- Commit style: `fix(handoff): count dropped turns at the cut point; explain and hoist warnings`

## Steps

### Step 1: Announce dropped turns at the cut point

In `_assemble`, when the rendered `turns` are fewer than `session.turns`,
emit a first line inside `### Bounded transcript evidence`, before the first
turn block, e.g.:

```
> _(N earlier turns omitted to fit the output budget; newest turns kept)_
```

`N = len(session.turns) - len(turns)`. `_assemble` already receives both, so
no signature change is needed — confirm that before adding parameters.

**Verify**: render a session large enough to truncate (either a many-turn
fixture or by lowering the budget through the existing seam — read how
`handoff_output_bytes` flows into the renderer and use the same knob the
tests use). The notice appears with a correct count.

### Step 2: Split the truncation notice wording

`_TRUNCATION_NOTICE` currently covers two distinct events. Emit
turn-drop wording when turns were dropped and body-shortened wording when
individual turn bodies were reduced; both may appear. Keep the `W_TRUNCATED`
code token in the text so existing assertions that grep for it still pass.

While here, fix the lazy-continuation nit: ensure the notice is not rendered
as a bare `>` line immediately after a `> - ` bullet (add the blank
quote-line separation the rest of the file uses).

**Verify**: rendered output shows the notice as its own block, not folded
into the warning bullet.

### Step 3: Explain warning codes

Add a code→one-line-meaning map in `handoff.py` (module-level constant,
static English strings only — same discipline as the content-free diagnostics
in `diagnostics.py`; no dynamic content) and render:

```
> - `W_BROKEN_CHAIN` — parent links were unresolvable; turn order may be wrong.
```

Cover every code in `WARNING_CODES` that can reach a handoff. Keep the code
token as the line prefix so existing tests asserting on the raw code still
match. An unknown/unmapped code must still render (code alone), never crash.

**Verify**: `PYTHONPATH=src python3 -c "from portable_resume.diagnostics import WARNING_CODES; from portable_resume.handoff import <YOUR_MAP>; print(sorted(set(WARNING_CODES) - set(<YOUR_MAP>)))"`
→ prints only codes that are install-side and cannot reach a handoff; list
them in your report.

### Step 4: Move `## Warnings` above the evidence

Reorder so the document reads: header/metadata → latest request → latest
action → **warnings** → bounded transcript evidence → required checks. The
agent learns the evidence is unreliable *before* reading it.

**Verify**: rendered output order matches; any test asserting on section
order updated deliberately (list them in the report).

### Step 5: Add a completeness test

Add a test asserting that **every** code in `WARNING_CODES` reachable from a
handoff has a one-line explanation, so a newly added code cannot ship
unexplained.

**Verify**: new test passes; deliberately remove one map entry → test fails;
restore.

### Step 6: Full gates

**Verify**: full suite OK; `self_verify.py` → 0; `check_secrets.py` → 0;
smoke matrix → 0.

## Test plan

- Truncated render shows an accurate dropped-turn count (Step 1).
- Both truncation wordings appear in their respective cases (Step 2).
- Each warning renders code + explanation; unknown code degrades gracefully
  (Step 3).
- Section order asserted (Step 4).
- Completeness guard (Step 5).

## Done criteria

- [ ] Truncated handoffs state how many turns were omitted, at the cut point
- [ ] Turn-drop and body-shorten notices are distinguishable; no lazy-continuation folding
- [ ] Every handoff-reachable `W_*` code renders with a static one-line meaning; a completeness test enforces it
- [ ] `## Warnings` precedes `### Bounded transcript evidence`
- [ ] Full suite + gates green; `plans/README.md` updated

## STOP conditions

- Reordering sections breaks many existing assertions (> ~5 test edits) —
  report the count before mass-editing.
- A warning's honest one-line meaning cannot be written without dynamic
  content — do not add dynamic content; report the code.
- You discover `W_PARTIAL_TAIL` semantics genuinely conflict with the
  newest-turns-kept guarantee in a way that makes both statements true —
  report it; that is a correctness question beyond this plan.

## Maintenance notes

- Keep the in-handoff one-liners and `docs/diagnostics.md` (plan 032) worded
  consistently; the completeness test here is what prevents drift on the
  handoff side.
- Reviewer: confirm all added strings are static and code-derived — the
  content-free discipline applies to the handoff framing too.
