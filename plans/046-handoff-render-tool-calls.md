# Plan 046: Render tool calls (name + input), correlated to their results

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/adapters/claude.py src/portable_resume/handoff.py src/portable_resume/model.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Status**: DONE
- **Priority**: P1 (highest-value in-session UX finding)
- **Effort**: M
- **Risk**: MED (turn ordinals and turn counts shift; envelope contract tests move with them)
- **Depends on**: **plans/045-claude-tool-fixture-real-schema.md** (its fixture is the only real-schema regression net)
- **Category**: bug (handoff content)
- **Planned at**: commit `2b4611c`, 2026-08-01
- **Issue**: https://github.com/ImL1s/resume-skills/issues/163

## Why this matters

The handoff systematically discards **what the previous agent actually did**.
For the flagship Claude source, every `tool_use` block — the tool's name and
its arguments — is dropped on the floor, and the surviving `tool_result` is
labelled by reading a `tool_name` key that the real Anthropic block never
emits, so it is always `None`. A resuming agent therefore sees:

```
> **[2 tool]**
> def test_login():
>     assert login('a','b') is True

> **[3 tool]**
> 1 failed, 0 passed
```

Which file was read? Which command produced "1 failed"? Both invisible. With
three file reads in a row it is three unlabelled blobs. This is the
highest-value evidence in a transcript and it is deleted before the renderer
ever sees it — while the product's entire purpose is telling a fresh session
what the last one did.

The `pi` adapter already renders a command-plus-output shape correctly, so the
renderer side can express this; Claude simply never populates it.

## Current state

- **The discard** — `src/portable_resume/adapters/claude.py` around lines
  1005–1022:

```python
        kind = item.get("type")
        if kind in {"thinking", "redacted_thinking", "signature", "tool_use"}:
            continue
        if kind in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
            values.append({"role": message_role, "content": item["text"], "timestamp": timestamp})
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

  Two defects in one place: `tool_use` is in the discard set (name + input
  lost), and `tool_result` is labelled from `item.get("tool_name")` — a key
  the real block does not carry (real keys: `content`, `tool_use_id`, `type`).
  `tool_use_id`, which is the *correct* correlation handle, is thrown away.

- **The renderer already supports a label** —
  `src/portable_resume/handoff.py` `_turn_block` around line 164:

```python
    label = f"[{turn.ordinal} {_value(turn.role)}{'/' + _value(turn.tool_name) if turn.tool_name else ''}]"
```

  So populating `tool_name` alone already yields `[3 tool/Bash]`.

- **The in-repo reference implementation** —
  `src/portable_resume/adapters/pi.py` around lines 661–673 renders a
  `$ <command>` line followed by its output. Read it before designing your
  content shape and stay close to it.

- **Sanitization boundary**: everything that reaches output goes through
  `sanitize_session` (`src/portable_resume/sanitize.py`) and the bounds in
  `src/portable_resume/bounds.py`. The `input` object you newly surface is
  recovered untrusted content and MUST take the same path as message text —
  it is not exempt because it is structured.

- **`--max-tool-chars`** (`src/portable_resume/reader.py`, default from
  `DEFAULT_BOUNDS.tool_output_chars`) caps tool *output*. Whatever rendering
  you choose for `input` must be bounded by the same knob (or a documented
  sibling), never unbounded.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Render 045's fixture | `PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd /workspace/project --source-root tests/fixtures/claude/<045-fixture>/root --format handoff` | exit 0; tool name + input now visible |
| Claude tests | `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor -v` | pass |
| Contract tests | `PYTHONPATH=src python3 -m unittest tests.unit.test_contract_equivalence -v` | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**:
- `src/portable_resume/adapters/claude.py` — stop discarding `tool_use`;
  correlate `tool_result` via `tool_use_id`
- `src/portable_resume/handoff.py` — only if the label/---content shape needs
  a small rendering change (prefer populating existing fields)
- `src/portable_resume/model.py` — only if a `Turn` field must be added
  (see STOP conditions first)
- Claude adapter + handoff tests, including flipping 045's
  "currently not rendered" assertions
- `plans/README.md` — status row

**Out of scope**:
- The other 16 adapters — **audit them and report**, but do not change them
  here; a sweep is a separate plan.
- `last_assistant_action` semantics — that is plan 047.
- The JSON envelope schema (`src/portable_resume/resources/portable-resume-v1.schema.json`)
  — if your change requires a schema edit, STOP (see conditions).
- Redaction policy changes.

## Git workflow

- Branch: `plan/046-handoff-tool-calls`
- Commit style: `fix(claude): render tool calls with name and bounded input`

## Steps

### Step 1: Decide the turn shape (and write it down)

**Decision: Shape A.** A matched Claude `tool_use` enriches the existing
`tool_result` turn with the correlated name and deterministic JSON input. The
correlation map lives for the selected lineage, across physical JSONL records,
and is capped by the effective `scanned_records` ceiling. Input is sanitized
and redacted before it is truncated to at most one quarter of
`--max-tool-chars`; framing plus the result use the remaining allowance, so an
oversized input cannot evict its result. An unresolved pending call is emitted
at the end as the same tool-turn shape with `[missing tool result]`.

Two viable shapes — pick ONE and state the choice in your report:

**A. Enrich the existing tool turn** (preferred; smallest blast radius):
carry the paired call's `name` into the existing `tool_name` field and prefix
the content with a bounded rendering of `input`. Turn count is unchanged, so
ordinals do not shift.

**B. Emit a separate turn for the call**: an extra turn per `tool_use`. More
faithful, but every turn ordinal after it shifts — which moves envelope
contract tests, bounded-transcript counts, and any snapshot assertions.

Prefer **A** unless you find a concrete reason B is required; if you take B,
budget for the ordinal churn and say so.

**Verify**: the choice is recorded in your report before any code changes.

### Step 2: Correlate calls to results in the Claude adapter

Within the message-item loop:

1. Remove `"tool_use"` from the discard set.
2. When you see a `tool_use` item, record `{id: (name, input)}` in a
   per-session mapping (bounded — cap the map at
   `min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)`
   entries and stop recording beyond it; do not let an adversarial transcript
   grow it unbounded).
3. When you see a `tool_result`, look up `item.get("tool_use_id")` in that
   mapping to obtain the real tool name. **Delete the `item.get("tool_name")`
   lookup entirely** — it can never match production data.
4. Render `input` bounded — **order matters, and so does the split**:

   **a. Sanitize before truncating (P2 from review).** Serialize with sorted
   keys, then run the existing sanitize/redact path, and only then apply the
   output bound — or let the sanitizer perform the truncation itself.
   Truncating first can cut a secret-shaped value below the redactor's
   minimum match length (e.g. slicing a `ghp_…` token mid-string), turning a
   value that *would* have been redacted into an unrecognized prefix that
   ships. Read `sanitize_text` in `src/portable_resume/sanitize.py` and match
   the order it already uses for message content.

   **b. Do not let the input evict the result (P2 from review).** Under shape
   A the input is prefixed to the existing tool-result turn, and
   `sanitize_turn_record` then applies the same `--max-tool-chars` allowance
   to the *combined* content — so an oversized input can consume the entire
   budget and delete the correlated result, recreating exactly the
   missing-evidence problem this plan exists to fix. Either bound the combined
   representation once with a guaranteed share for the result, or give the
   input its own smaller sub-budget (e.g. a fixed fraction of the allowance).
   State which you chose.

   A tool call whose result never arrives (interrupted session — the common
   resume case) must still surface: emit its call with the result shown as
   missing rather than dropping it.

**Verify**: 045's fixture now renders the tool name and the file path /
command from `input`; `[N tool]` becomes `[N tool/Read]`.

### Step 3: Flip plan 045's assertions

045 pinned "the input strings do NOT appear" and "no `/ToolName` suffix".
Invert those assertions to the new truth, keeping the fixture bytes unchanged
so the diff is purely renderer behavior.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor -v` → pass.

### Step 4: Bounds and hostile-input tests

Add tests for:
1. A `tool_use` whose `input` is very large → truncated at the tool-chars
   budget, `W_TRUNCATED`-style signalling consistent with existing behavior,
   **and the correlated result is still visible** (assert its text appears —
   this pins the sub-budget/reserved-share decision from Step 2b).
1b. A `tool_use` whose `input` contains a secret-shaped value positioned so
   that a naive truncation would cut it mid-token → the value is redacted,
   not shipped as a prefix (pins the sanitize-before-truncate order from
   Step 2a). Build the case by placing the token so the cutoff falls inside
   it.
2. A `tool_result` whose `tool_use_id` matches **no** call → renders as
   today (unlabelled), no crash.
3. A `tool_use` with **no** following result (interrupted) → the call is
   still visible.
4. `input` containing control characters / a secret-shaped string → same
   sanitization/redaction as message content (find the existing redaction test
   with `grep -rln "redact" tests/ | head` and mirror it).

**Verify**: new tests pass; full suite OK.

### Step 5: Audit the other adapters (report only)

Run `grep -n "tool_use\|tool_name\|tool_result" src/portable_resume/adapters/*.py`
and record, per adapter, whether it drops tool-call identity the same way.
**Do not fix them here.** The list goes in your completion report and becomes
the follow-up plan's scope.

**Verify**: the report contains one line per adapter.

#### Adapter inventory (2026-08-01)

| Source | Current tool identity behavior |
|---|---|
| `codex` | Emits call names and bounded argument previews; outputs use a persisted name only when present, with no call-ID correlation. |
| `cursor` | Preserves a persisted `tool_name` on CLI/desktop tool rows; does not correlate separate calls and results. |
| `openhands` | Normalizes public message events only; tool-event identity is not surfaced. |
| `openclaw` | Keeps command/output text for tool-like roles but does not populate `tool_name` or correlate calls. |
| `goose` | Flattens tool request/response text and drops tool identity/correlation. |
| `hermes` | Reads `tool_name` only as fallback content when tool content is absent; labels do not retain it. |
| `grok` | Emits tool labels from titles/kinds/tool-call IDs, but does not correlate a call payload to its result. |
| `gemini` | Emits tool-call names as tool content; inputs/results are not correlated. |
| `cline` | Flattens tool-use names and tool-result content into message text without labels or correlation. |
| `claude` | Correlates `tool_use.id` to `tool_result.tool_use_id`, preserving bounded input, name, result, and interrupted calls. |
| `kimi` | Preserves available tool names; some wire results receive the generic `tool_result` label, with no ID correlation. |
| `opencode` | Preserves a tool/name field on result parts; no separate call/result correlation is performed. |
| `qwen` | Labels every tool row generically as `tool_result`; concrete identity is not preserved. |
| `antigravity` | Labels known tool steps by step kind or persisted name; no call-ID correlation is performed. |
| `pi` | Preserves `toolName` on results and renders bash command plus output; no separate call-ID correlation is needed by the pinned shape. |
| `github-copilot` | Emits execution-start tool names only; arguments and results are intentionally omitted by the pinned adapter contract. |
| `crush` | Flattens call name/input and result text into message content without a correlated tool label. |

### Step 6: Full gates

**Verify**: full suite OK; `python3 scripts/self_verify.py` → 0;
`python3 scripts/check_secrets.py` → 0;
`PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` → 0.

## Test plan

Steps 3–4 (≥ 5 assertions). The structural pattern is 045's handoff-level
test. Every new rendering path must be exercised through the **rendered
handoff text**, not just the adapter's Python objects — the bug being fixed
was invisible at the adapter layer.

## Done criteria

- [x] `grep -n 'item.get("tool_name")' src/portable_resume/adapters/claude.py` → no matches
- [x] `"tool_use"` no longer in the discard set
- [x] 045's fixture renders tool name + bounded input; assertions flipped
- [x] Unmatched-id, missing-result, oversized-input, and hostile-input cases tested
- [x] Sanitization runs before the output bound (test-pinned with a token straddling the cutoff)
- [x] An oversized input never evicts its correlated result (test-pinned)
- [x] Per-adapter audit list recorded in this plan
- [x] Full suite + smoke matrix + gates green
- [x] `plans/README.md` updated

## STOP conditions

- The change requires editing `portable-resume-v1.schema.json` or
  `contracts.py` (e.g. `Turn` needs a new public field) — STOP and report; a
  schema version decision belongs to the maintainer.
- Turn-ordinal shifts break more than a handful of tests (shape B) — report
  the count and switch to shape A instead of mass-updating expectations.
- Rendering `input` would surface content that bypasses `sanitize_session` —
  STOP; the sanitize path is non-negotiable.
- The live schema in your environment lacks `tool_use_id` on `tool_result` —
  report the actual keys.

## Maintenance notes

- Reviewer should scrutinize: the call→result map is bounded; `input`
  rendering goes through sanitize + the tool-chars budget; an interrupted
  call still renders.
- The other 16 adapters likely share this defect — Step 5's list is the
  scope of the follow-up.
- Plan 047 (latest recorded action) touches the same turn stream; land 046
  first so 047 can rely on tool turns carrying identity.
