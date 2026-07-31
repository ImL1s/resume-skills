# Plan 055: Rewrite the skill `description` so hosts route to it at the right moment

> **Executor instructions**: This plan contains a **wording decision** with
> release implications (installed bytes move). Do the investigation, propose
> the wording, and STOP for maintainer confirmation before committing unless
> the operator told you to pick. Then follow the steps. When done, update the
> status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/install/catalog.py src/portable_resume/install/render.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S (code) — the cost is coordination, not implementation
- **Risk**: LOW–MED — changes installed skill bytes, moving `package_identity`; needs a coordinated release
- **Depends on**: none. Pairs naturally with plan 053 (same file's frontmatter).
- **Category**: direction (needs a wording call)
- **Planned at**: commit `2b4611c`, 2026-08-01
- **Issue**: https://github.com/ImL1s/resume-skills/issues/172

## Why this matters

The `description` in each skill's frontmatter is what a host uses to decide
**whether to surface this skill at all**. Today every source renders the same
mechanism-first sentence:

> Import inert local {Title} session context into a fresh session using a
> validated request document.

Two problems. First, it contains none of the vocabulary a user actually uses
at the moment this skill should fire — "resume", "continue where I left off",
"what was I working on", "last session", "previous session", "pick up",
"handoff". "Import inert local … using a validated request document" reads
like an internal API summary, not a trigger. Second, it advertises the wrong
default path: "validated request document" is lane B, while the file's primary
lane (and what the tests assert) is plain argv.

The routing surface is real — the catalog itself documents hosts selecting the
skill *by description*.

## Current state

- **The generator** — `src/portable_resume/install/catalog.py`, around lines
  952–957:

```python
def description_for(source: str) -> str:
    title = SOURCE_TITLES[source]
    return (
        f"Import inert local {title} session context into a fresh session "
        "using a validated request document."
    )
```

- It feeds `${description}` in
  `src/portable_resume/resources/skill/SKILL.md.tmpl`'s frontmatter via
  `render_skill_markdown` (`src/portable_resume/install/render.py`).
- `SOURCE_TITLES` in the same module maps each source key to its product
  title (e.g. "Claude Code", "Codex", "Qwen Code").
- Any change moves installed bytes → `package_identity` changes → packaging
  and identity tests move with it (`tests/unit/test_runtime_package_allowlist.py`,
  `tests/unit/test_host_package_builder.py`,
  `tests/integration/test_matrix_and_installer.py` — confirm the exact set by
  running them).
- **Product constraints the wording must not violate**: this is context
  *migration*, never live session/process restoration; reads are local and
  offline; recovered text is inert and untrusted. A description that implies
  "restores your session" would misrepresent the product.
- Some hosts impose description length limits. **Check before writing**:
  `grep -rn "description" docs/install-hosts.md | head -20` and
  `grep -rn "description" src/portable_resume/install/package_contracts.py`
  for any validated bound.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Current output | `PYTHONPATH=src python3 -c "from portable_resume.install.catalog import description_for, SOURCE_TITLES; [print(k, '|', description_for(k)) for k in sorted(SOURCE_TITLES)]"` | 17 lines |
| Rendered frontmatter | `PYTHONPATH=src python3 -c "from portable_resume.install.render import materialize_plan; print(materialize_plan('claude')['SKILL.md'].decode().split('---')[1])"` | frontmatter block |
| Packaging tests | `PYTHONPATH=src python3 -m unittest tests.unit.test_host_package_builder tests.unit.test_runtime_package_allowlist -v` | pass after expectation updates |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Installed matrix | `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` | exit 0 |

## Scope

**In scope**:
- `src/portable_resume/install/catalog.py` — `description_for`
- Tests asserting the description string; packaging identity expectations
- `plans/README.md` — status row

**Out of scope**:
- The SKILL body — plan 053.
- Per-host description variants (the payload is shared across hosts by
  design).
- Marketplace catalog copy in the sibling `portable-resume-marketplace` repo —
  note if it duplicates this string, but do not edit another repo.

## Git workflow

- Branch: `plan/055-skill-description-triggers`
- Commit style: `feat(skill): trigger-first skill description`

## Steps

### Step 1: Check the constraints, then propose wording (STOP for confirmation)

1. Establish any host length limit (see "Current state") and record it.
2. Propose a trigger-first sentence. Starting point to refine:

   > Use when the user wants to resume, continue, or recover context from a
   > previous {Title} session — "what was I working on", "pick up where I left
   > off". Reads inert local session history and produces a summarized
   > handoff; never restores a live process.

   It must: lead with *when to use it*; contain the natural-language triggers;
   name the source product; and preserve the inert/not-live-restore boundary.
3. Note that the phrase "validated request document" disappears (it advertised
   the secondary lane).

**Verify**: the proposal, the length check for the longest `SOURCE_TITLES`
entry, and the constraint list are written up. **STOP for maintainer
confirmation** unless already authorized.

### Step 2: Implement

Update `description_for` to the confirmed wording. Keep it a pure function of
`source` — no per-host branching.

**Verify**: the "Current output" command prints 17 correct, in-bounds
descriptions; the rendered frontmatter is well-formed YAML (no unescaped `:`
or quoting hazards — check a title containing punctuation if one exists).

### Step 3: Update expectations and identity

Fix any test asserting the old string, then update packaging identity
expectations.

**Verify**: `PYTHONPATH=src python3 -m unittest discover -s tests -q` → OK;
`PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` → 0.

### Step 4: Add a guard test

Assert that every generated description (a) is within the recorded length
bound, (b) contains the source title, and (c) contains at least one trigger
word from a small list (`resume`, `continue`, `previous`).

For the product boundary, do **not** use a bare substring check against
"restore" — the proposed wording deliberately *contains* that word in a
negated statement ("never restores a live process"), so a naive guard would
reject the very sentence that preserves the boundary (raised as P2 in
review). Test the **affirmative claim** instead: assert the description does
not match an affirmative live-restore pattern (e.g. `restores your session`,
`resumes the live`, `restarts the process`) while explicitly permitting a
negated form. A small regex over the sentence containing the word — requiring
a preceding negation such as "never" or "not" — is the honest shape. Comment
the intent so a future editor understands what the guard protects.

**Verify**: the guard passes; deliberately break one condition → it fails;
restore.

### Step 5: Full gates and release note

**Verify**: full suite OK; smoke matrix → 0; `self_verify.py` → 0;
`check_secrets.py` → 0.

Add a CHANGELOG entry under Unreleased noting that installed skill bytes and
`package_identity` changed (users reinstalling will see a version-divergence
warning from the installer's discovery scan — expected).

## Test plan

Step 4's guard plus updated existing assertions. No behavioral tests are
needed: this is a metadata string, and its real effect (host routing) can only
be evaluated live — see Maintenance notes.

## Done criteria

- [ ] Wording proposal recorded with the host length constraint; confirmed before commit
- [ ] `description_for` emits trigger-first text for all 17 sources, within bounds
- [ ] Guard test enforces triggers, title, length, and rejects **affirmative** live-restore claims while permitting the negated boundary sentence (the proposed wording passes its own guard)
- [ ] Packaging identity expectations updated; installed matrix green
- [ ] CHANGELOG notes the identity change
- [ ] Full suite + gates green; `plans/README.md` updated

## STOP conditions

- A host's description limit is shorter than the proposed sentence — report
  the limit; the wording must shrink rather than be truncated at install time.
- Any packaging contract validates the description against a fixed string —
  report it before changing.
- The marketplace repo duplicates this copy — note it in the report as
  follow-up; do not edit another repository.

## Maintenance notes

- **Actual trigger rates are unmeasured.** The failure mode is clear from the
  text, but whether the new wording fires better is an empirical question. If
  a host-activation harness ever exists (deferred DIRECTION-05), a small eval
  across hosts is the honest way to settle wording — record this as the
  follow-up.
- Reviewer: check the description never implies live restoration and never
  promises cross-machine or network capability.
- Keep it a pure function of the source key so the payload stays shareable
  across hosts.
