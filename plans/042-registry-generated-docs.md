# Plan 042: Generate host/matrix documentation from the registry (root-cause fix for count drift)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- scripts/check_docs.py docs/ README.md src/portable_resume/registry.py src/portable_resume/install/catalog.py`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1 (highest-leverage direction finding)
- **Effort**: M–L
- **Risk**: MED (touches the docs gate and 12 locales; scope is fenced below)
- **Depends on**: plans/033-readme-quickstart-counts.md (immediate corrections
  land first; this plan prevents recurrence). Coordinate: any line 033 already
  fixed simply becomes generated/checked here.
- **Category**: direction / docs infrastructure
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/142

## Why this matters

The product's value proposition is a registry-derived 17×18 matrix, but the
documentation describing that matrix is hand-written and the docs gate
enforces a stale snapshot of it: `docs/host-support.md` still claims
"9×9=81", all 12 localized quick-starts tell readers there are "nine
destinations", `docs/install-hosts.md` says "thirteen", and
`scripts/check_docs.py` hardcodes the 9 host names of last July — so every one
of these drifts passed CI. Meanwhile `install-resume-skills hosts --json`
already emits every field the host tables need. Deriving the tables and counts
from the registry makes the next nine hosts cost zero doc edits and makes this
entire drift class structurally impossible. `docs/STATUS.md` itself lists
"auto-generated docs tables / planned-profile release gates still manual" as a
known residual (issue #36).

## Current state

- Source of truth (read-only for this plan):
  - `src/portable_resume/registry.py` — `enabled_source_keys()` (17),
    `enabled_destination_keys()` (18), `matrix_dimensions()`.
  - `src/portable_resume/install/catalog.py` — `HOST_KEYS`, `hosts_report()`
    with per-host `display_name`, `installer_defaults`, `official_layouts`,
    `alternate_*_roots`, `install_methods`, `installer_commands`,
    `activation_help`, `activation_examples`, `arguments_note`, `caveats`,
    `official_docs`, `evidence_level`, `live_ui` (see `_print_hosts_human` in
    `src/portable_resume/install/cli.py` for the full field walk).
- Drifted targets (verified):
  - `docs/host-support.md:3` — "matrix dimensions are **derived from
    registries** (currently **9×9=81** cells)".
  - `docs/i18n/en.md:17` "all nine destination profiles" and `:29` a
    hand-written 9-host list; the same in all 12 locales (`ja` `9 個の宛先`,
    `pt-BR` `nove`, `hi` `नौ`, `ru` `девять`, `ar` `تسعة`, zh-CN/zh-TW/de/es/fr
    equivalents).
  - `scripts/check_docs.py:32-46` — `HOST_NAMES` tuple of 9 names;
    `REQUIRED_EVIDENCE_MARKERS = ("8/8", "7/7", "6/6")` and an
    `EVIDENCE_SCOPE_MARKER` comment string pin v0.3.2-era evidence.
- Layout conventions: docs are plain Markdown; `check_docs.py` is stdlib-only
  and run by `self_verify --profile ci-quality` in CI.
- Honesty rule that fences this plan: evidence claims ("8/8", "not-run") are
  NOT derivable from the registry — they are human-recorded truth in
  `docs/STATUS.md` / `docs/host-ui-smoke.md`. Generation covers **structure
  and counts only**; evidence markers stay hand-written and gate-checked as
  today.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Truth dump | `PYTHONPATH=src python3 scripts/install-resume-skills hosts --json` | JSON with 18 hosts |
| Docs gate | `python3 scripts/check_docs.py` | exit 0 |
| Generator (new) | `python3 scripts/render_docs.py --check` | exit 0 when in sync |
| Full gate | `python3 scripts/self_verify.py` | exit 0 |

## Scope

**In scope**:
- `scripts/render_docs.py` (create)
- `docs/host-support.md`, `docs/install-hosts.md` — add generated regions
- `README.md` — the "17 sources × 18 hosts" line becomes checked (not
  necessarily generated)
- `docs/i18n/*.md` (12 files) — one-time count reconciliation + marker-based
  count check (NOT prose regeneration)
- `scripts/check_docs.py` — derive from registry; add `--check` integration
- `plans/README.md` row

**Out of scope**:
- Translating or rewriting locale prose — counts and host-list lines only;
  the executor must NOT attempt to re-translate sentences. Where a locale
  sentence hardcodes a number-word ("nove", "девять"), replace the *number
  claim* minimally using the locale's existing sentence with the digit form
  (e.g. "18") — digits are locale-neutral; do not touch surrounding wording.
- Evidence claims / STATUS / host-ui-smoke — human-recorded; only their
  *checking* stays as-is.
- `src/portable_resume/**` — read-only truth.

## Git workflow

- Branch: `plan/042-registry-generated-docs`
- Commit per step (generator; en-docs regions; locale reconciliation; gate
  rewire). Style: `docs(gen): registry-derived host tables and counts (#36 residual)`

## Steps

### Step 1: Write `scripts/render_docs.py`

Stdlib-only script with two modes:
- `--write`: renders generated regions in place.
- `--check`: renders to memory and exits non-zero with a unified diff if any
  target file's generated region differs (this is what the gate calls).

Region protocol (HTML comments survive Markdown rendering):

```markdown
<!-- generated:hosts-table:begin (run scripts/render_docs.py --write) -->
| Host | Project root | Global root | Install methods | Evidence |
|------|--------------|-------------|-----------------|----------|
... one row per catalog.HOST_KEYS entry, from hosts_report() ...
<!-- generated:hosts-table:end -->
```

Implementation notes:
- Import truth directly (insert `src` on `sys.path` like
  `scripts/prepare_build_identity.py` does) — do not shell out to the CLI.
- Deterministic output (sorted keys, no timestamps) so `--check` is a stable
  byte diff.
- Also expose `counts` (sources, destinations, cells) for the count checks.

**Verify**: `python3 scripts/render_docs.py --check` after Step 2 → exit 0;
corrupt one generated row by hand → non-zero with a diff naming the file;
restore via `--write`.

### Step 2: Convert `docs/host-support.md` and `docs/install-hosts.md`

- Replace the hand-written host table(s) in `docs/host-support.md` with the
  generated region; rewrite line 3 to state the *current* dimensions using
  digits sourced at render time ("currently 17×18=306 cells" inside a
  generated inline region, or drop the count and reference the generated
  table).
- In `docs/install-hosts.md`, wrap the per-host root/commands listings that
  duplicate `hosts` output in generated regions; keep the hand-written
  narrative (activation grammar explanations, marketplace walkthroughs)
  untouched around them. If a section is too intertwined to fence cleanly,
  leave it hand-written and add it to the count-check instead — fence what is
  mechanical, don't force it.

**Verify**: `python3 scripts/render_docs.py --check` → 0; page renders sanely
(eyeball); `git diff` shows tables match `hosts --json` truth.

### Step 3: One-time locale count reconciliation

For each of the 12 `docs/i18n/*.md`: update the destination-count claims and
the hand-written host lists to current truth, using digits for counts and the
canonical English host display names for list items (the files already use
English product names like "Claude Code" — verified in `en.md:29`; keep that
convention). Add a hidden marker line each file must carry:

```markdown
<!-- portable-resume-counts: sources=17 destinations=18 -->
```

(The marker's numbers are what `check_docs.py` verifies against the registry;
prose stays human.)

**Verify**: `grep -c "portable-resume-counts" docs/i18n/*.md` → 1 per file
(12 total, excluding `README.md` index unless it also claims counts — check).

### Step 4: Rewire `check_docs.py`

- Delete the hardcoded `HOST_NAMES` 9-tuple; derive the required host names
  from `catalog`'s display names (import via `sys.path` insertion).
- Verify each i18n file's `portable-resume-counts` marker matches
  `len(enabled_source_keys())` / `len(enabled_destination_keys())`.
- Add a check that shells (or imports) `render_docs --check` so generated
  regions cannot drift.
- Keep `REQUIRED_EVIDENCE_MARKERS` and `EVIDENCE_SCOPE_MARKER` exactly as they
  are (human-recorded evidence; out of scope) — but add a comment pointing to
  this plan explaining the split.

**Verify**: `python3 scripts/check_docs.py` → 0. Mutation tests: (a) edit a
generated row → gate fails; (b) change one locale marker number → gate fails;
restore both.

### Step 5: Full gates

**Verify**: `python3 scripts/self_verify.py` → 0 (ci-quality profile runs
docs); full unittest suite unaffected → OK.

## Test plan

The gate mutations in Steps 1/4 are the tests (docs infra is enforced by
`check_docs.py`, which CI runs). Record each mutation test's observed failure
message in the completion report.

## Done criteria

- [ ] `render_docs.py --check` exists, deterministic, wired into `check_docs.py`
- [ ] `docs/host-support.md` shows 17×18=306-consistent content inside generated regions; no "9×9" remains (`grep -rn "9×9\|81 cells" docs/` → none)
- [ ] All 12 locales carry a registry-checked counts marker; no "nine/nove/девять/九/तेरह…"-style destination-count claim remains (`grep` per locale for its number word — list the greps run)
- [ ] `check_docs.py` derives host names from the catalog (no hardcoded host tuple)
- [ ] Evidence markers ("8/8" etc.) untouched
- [ ] All gates green; `plans/README.md` updated

## STOP conditions

- `hosts_report()` lacks a field a table needs (would tempt adding fields to
  `catalog.py` — that is a src/ change, out of scope; report the gap).
- A locale's count sentence cannot be edited without translating new prose —
  leave that file, report it (partial reconciliation is acceptable; the
  marker still gates the counts).
- `check_docs.py`'s structure makes the registry import circular or
  policy-forbidden (stdlib-only-without-src) — report; a frozen JSON snapshot
  committed by `render_docs --write` and diffed by the gate is the fallback
  design, but needs maintainer sign-off.
- Generated-region fencing in `install-hosts.md` would swallow hand-written
  caveats — fence less, report what stayed manual.

## Maintenance notes

- Adding a host now means: registry/catalog entry → `render_docs.py --write`
  → commit; docs gate fails until run. Update `CONTRIBUTING.md`'s docs note if
  reviewers ask where the tables come from (one line, allowed).
- The evidence-claims split (generated structure vs human evidence) is the
  load-bearing honesty boundary — reviewers must reject any attempt to
  "generate" an evidence marker.
- Follow-up (not this plan): host-ui-smoke automation (DIRECTION-05) would
  eventually let evidence rows be machine-appended; the marker split here is
  forward-compatible with that.
