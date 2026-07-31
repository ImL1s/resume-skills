# Plan 043: Let `list` take the free-text filter that `show` already implements (`--match`)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/reader.py src/portable_resume/select.py src/portable_resume/resources/skill/SKILL.md.tmpl tests/`
> Written against `main` at `a4dc4d6`. On excerpt mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW–MED (envelope/schema surface — fenced below)
- **Depends on**: plans/029-reader-cli-help.md (same file; land 029 first)
- **Category**: direction (DIRECTION-03)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/143

## Why this matters

Searching sessions is currently a side effect of a failed selection: the
substring matcher (casefolded, over `session_id`/`title`/`cwd`/`branch`)
exists and is tested, but only `show` can reach it — `list` rejects any ref.
So "find the session about X" requires provoking `E_AMBIGUOUS` (exit 4) and
reading candidates off the error path, and a query matching exactly one
session silently becomes a full transcript dump instead of a one-row result.
The generated Skill even teaches host agents this workaround. `--match` on
`list` is pure wiring: matcher exists, ref validation exists, output shapes
exist.

## Current state

- `src/portable_resume/reader.py`:

  The gate that blocks it (`_resolve_invocation`, lines ~108–115):

```python
    if namespace.source not in SOURCE_KEYS or namespace.action not in {"list", "show"}:
        raise DiagnosticError.invalid()
    if namespace.action == "list" and namespace.ref is not None:
        raise DiagnosticError.invalid(source=namespace.source)
    if namespace.ref is not None:
        reject_controls(namespace.ref)
        if len(namespace.ref) > DEFAULT_BOUNDS.ref_chars:
            raise DiagnosticError.invalid(source=namespace.source)
```

  The list pipeline to filter (in `run()`, after
  `ordered_internal = ordered_internal_all[: DEFAULT_BOUNDS.listed_sessions]`):
  the `action == "list"` branch sanitizes summaries and emits an `Envelope`
  with `operation="list"`, sessions projected via `item.empty_session()`,
  formats `json` / `handoff` (`render_candidates`) / `table` (`_table`).

- `src/portable_resume/select.py` — the matcher to reuse (lines ~140–150,
  inside `select_session`):

```python
    needle = normalized_ref.casefold()
    matches: list[SessionSummary] = []
    for value in eligible:
        fields = (value.session_id, value.title or "", value.cwd or "", value.branch or "")
        if any(needle in field.casefold() for field in fields):
            matches.append(value)
```

- `src/portable_resume/resources/skill/SKILL.md.tmpl:66` — the workaround
  being taught:

```
- Free-text search may match `list` results; on ambiguity the reader exits with
```

  (read the surrounding lines for full context before editing).

- Envelope surface: `Envelope.create(operation="list", query=query, ...)` —
  `Query` already carries `ref` (it is `None` for list today). Decision made
  by this plan: pass the match text as `Query.ref` for list invocations so the
  echoed query in the envelope is truthful, IF the JSON schema
  (`src/portable_resume/resources/portable-resume-v1.schema.json`) and
  `validate_envelope` accept a non-null ref on list envelopes — check first
  (`grep -n "ref" src/portable_resume/resources/portable-resume-v1.schema.json`).
  If the schema constrains ref-on-list, keep `Query.ref = None` and do not
  echo the match text at all (bounded behavior change: filter only). Do NOT
  edit the schema in this plan.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Fixture smoke | `PYTHONPATH=src python3 scripts/portable-resume claude list --cwd /workspace/project --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root --format table` | exit 0, rows |
| With match (after) | same + `--match <text-from-fixture-title>` | exit 0, filtered rows |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | 0 |

## Scope

**In scope**: `src/portable_resume/reader.py`,
`src/portable_resume/select.py` (extract the shared predicate only),
`src/portable_resume/resources/skill/SKILL.md.tmpl` (teach `--match`),
reader/select test modules, `plans/README.md` row.

**Out of scope**:
- `portable-resume-v1.schema.json` and `contracts.py` — no schema changes; the
  ref-echo decision above bends to the existing schema, never the reverse.
- `show` selection semantics (`select_session` behavior unchanged).
- request-v1/v2 (`request.py`) — DIRECTION-04, separate decision.
- Positional ref on `list` — stays rejected (explicit `--match` only; keeps
  the argv grammar unambiguous).

## Git workflow

- Branch: `plan/043-list-match`
- Commit style: `feat(reader): list --match free-text filter`

## Steps

### Step 1: Extract the shared predicate

In `select.py`, extract the four-field casefold substring test into a
module-level function:

```python
def summary_matches(summary: SessionSummary, needle_casefold: str) -> bool:
    fields = (summary.session_id, summary.title or "", summary.cwd or "", summary.branch or "")
    return any(needle_casefold in field.casefold() for field in fields)
```

Use it inside `select_session` (behavior-identical refactor).

**Verify**: full suite OK (pure refactor gate).

### Step 2: Add `--match` to the reader

In `build_parser()`: `parser.add_argument("--match", help="filter list rows by case-insensitive substring over id/title/cwd/branch (list only)")`.
In `_resolve_invocation` / `run()`:
- Reject `--match` with `action == "show"` and with `--request-file`
  (`DiagnosticError.invalid()`), mirroring how other list/show-only flags are
  policed.
- Validate exactly like ref: `reject_controls(match)`, length ≤
  `DEFAULT_BOUNDS.ref_chars`.
- **Two truncation layers exist — define v1 semantics honestly (Codex PR
  review).** Adapters internally cap their own listings at
  `DEFAULT_BOUNDS.listed_sessions` before the reader ever sees them (e.g.
  openclaw returns only its newest page), so a reader-side filter can only
  search the bounded window plain `list` shows — a matching session older
  than the adapter's page is invisible to both. v1 semantics of this plan:
  `--match` filters that same visible window; it is NOT a full-history
  search. Requirements that make this honest:
  - Apply `summary_matches` to `internal` before `ordered_internal_all` /
    the reader-side cap, so the reader cap applies to matches ("top N of the
    visible window that match").
  - Help text must say: "searches the most recent bounded listing window per
    source, not full store history".
  - If the pre-filter listing already hit a cap (`W_TRUNCATED` computed, or
    `len(internal) >= DEFAULT_BOUNDS.listed_sessions`), the envelope MUST
    carry `W_TRUNCATED` even when the filtered result is small or empty —
    consumers must be able to tell "no match exists in the window" from "no
    match found, window was clipped".
  - An empty result is a valid empty list envelope (exit 0), NOT
    `E_NO_MATCH` — list semantics, not selection.
  Threading the predicate into adapter discovery (true full-history match) is
  explicitly out of scope — see Maintenance notes.
- Query echo per the schema decision in "Current state".

**Verify**: fixture smoke with `--match` returns the subset; `--match` with
`show` exits 2; empty match → exit 0 with zero rows.

### Step 3: Teach the Skill

Update `SKILL.md.tmpl` (line ~66 region): replace the ambiguity-as-search
guidance with `list --match <text>` as the discovery path, keeping the
ambiguity fallback documented for `show`. Then regenerate/verify whatever
consumes the template (`grep -rn "SKILL.md.tmpl" src/ scripts/ tests/` — the
render pipeline embeds it; `test_runtime_package_allowlist` and render tests
must stay green; installed-skill golden tests may need their expected text
updated — that is in scope, listed here).

**Verify**: full suite OK; `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` → 0.

### Step 4: Tests

Reader tests (model after existing list-format tests, found via
`grep -rln "operation.*list\|render_candidates" tests/unit | head`):

1. `--match` filters across each of the four fields (one case each).
2. Case-insensitivity (`--match TITLE` vs title-cased fixture).
3. `--match` + `show` → exit 2; `--match` + `--request-file` → exit 2.
4. Control chars / over-length match string → exit 2.
5. Zero matches → exit 0, empty sessions array, no `E_NO_MATCH`.
6. Truncation honesty: with a listing that hits the cap (build via a lowered
   `DEFAULT_BOUNDS`-style budget or a many-session synthetic fixture),
   `--match` results — including an EMPTY result — carry `W_TRUNCATED`, so
   "not in window" is distinguishable from "not anywhere". (If constructing
   an over-cap fixture is genuinely expensive, lower the effective cap via
   the budget/limits seam instead; only skip with a note if neither works.)
7. Select refactor equivalence: existing `select_session` tests untouched and
   green.

**Verify**: new tests pass; full suite OK.

### Step 5: Full gates

**Verify**: suite, smoke matrix, `self_verify.py`, `check_secrets.py` all 0.

## Test plan

As Step 4 (≥ 6 new cases). The Skill-text change is covered by the render
golden tests it forces you to update.

## Done criteria

- [ ] `list --match` filters; `show`/request-file reject it; validation matches ref rules
- [ ] Empty result is exit 0 (test-pinned)
- [ ] Skill template teaches `--match`; smoke matrix green
- [ ] No schema file modified (`git status` proves)
- [ ] Full suite + gates green; `plans/README.md` updated

## STOP conditions

- The envelope schema rejects any shape you produce (validation error from
  `validate_envelope` in the list branch) — do not edit the schema; report the
  exact validation failure.
- The Skill template text is embedded in per-host golden fixtures whose
  update fans out beyond ~20 files — report the blast radius first.
- `select_session`'s matcher turns out to have selection-specific coupling
  (e.g. exact-ID fast path interleaved) making the extraction non-trivial —
  report; do not duplicate the predicate instead.

## Maintenance notes

- **Deferred by design**: threading the match predicate into adapter
  discovery (so adapters scan a larger bounded window than their output page
  when a filter is active) — that is what would upgrade `--match` from
  "filters the visible window" to true bounded history search. It touches all
  17 adapters and belongs with the request-v2 work. Until then the
  `W_TRUNCATED` contract above is the honesty mechanism.
- DIRECTION-04 (request-v2 with `list` + `match`) builds directly on this;
  the predicate extracted in Step 1 is the piece it will reuse.
- Reviewer: confirm `--match` text can never reach a shell or a diagnostic
  message (it flows only into in-process comparison and, per schema decision,
  possibly the stdout envelope's query echo).
