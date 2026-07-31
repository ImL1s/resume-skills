# Plan 052: Fix the `cwd` asymmetry between the argv and request-file lanes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/request.py src/portable_resume/paths.py src/portable_resume/reader.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S (docs-only path) / M (if the validator is relaxed)
- **Risk**: MED — `validate_canonical_absolute` is a deliberate security boundary
- **Depends on**: none. Overlaps plan 053 (SKILL.md rewrite) — if 053 lands
  first, fold the doc half into it and keep only the code decision here.
- **Category**: bug (lane asymmetry) / docs
- **Planned at**: commit `2b4611c`, 2026-08-01

## Why this matters

The two request lanes accept **different `cwd` grammars under the same word**.
The argv lane silently canonicalizes whatever you pass; the request-file lane
rejects anything that is not already its own `realpath`. SKILL.md documents
lane B's `cwd` as a "canonical absolute working directory" and never defines
*canonical* as realpath-resolved — while lane A, two paragraphs earlier,
trains the agent to pass `"$PWD"`.

On macOS this is not an edge case: **every** path under `/tmp` and
`/var/folders` (exactly what `mktemp -d` returns, and a very common agent
workspace) is non-canonical, as is any symlinked worktree or home directory.

Reproduced with one fixture and one value:

| Lane | `cwd` value | Result |
|---|---|---|
| A (`--cwd`) | `/tmp/.../fx/proj` (symlink) | exit 0, handoff rendered |
| B (request file) | same string | **exit 2**, `E_INVALID_INPUT` |
| B (request file) | `/private/tmp/.../fx/proj` | exit 0 |

Direct probe of the validator: `/tmp` REJECT, `/var/folders` REJECT,
`/private/tmp` OK. Because the diagnostic is content-free it names no field,
so the agent cannot tell whether `cwd`, `resume_ref`, `source`, `action` or
the key set was wrong — it retries blind or abandons the lane that exists
specifically to keep free text out of a shell.

## Current state

- **Lane A canonicalizes** — `src/portable_resume/reader.py` around line 116:

```python
    cwd = canonicalize_cwd(namespace.cwd or os.getcwd())
```

- **Lane B rejects** — `src/portable_resume/request.py` around line 219:

```python
    cwd = validate_canonical_absolute(payload["cwd"])
```

  and `src/portable_resume/paths.py` around lines 38–44:

```python
    normalized = normalize_unicode(value)
    if value != normalized or not os.path.isabs(value):
        raise DiagnosticError.invalid()
    canonical = canonicalize_cwd(value)
    if canonical != value:
        raise DiagnosticError.invalid()
    return value
```

  Note it *computes* the canonical form and then throws it away — the
  information needed to accept the input is already in hand.

- **The security rationale**: `request.py`'s reader is the hardened lane
  (strict key set, duplicate-key rejection, `O_NOFOLLOW`, size bound, read
  stability). Whether "do not rewrite caller-supplied paths" is load-bearing
  *there* is the decision this plan must resolve — read the surrounding
  comments in `request.py` and `paths.py` before choosing.

- **SKILL.md's wording** —
  `src/portable_resume/resources/skill/SKILL.md.tmpl` describes the key as
  "canonical absolute working directory for selection scope".

- **Same-shaped trap, already noted**: `--request-file` is mutually exclusive
  with `--cwd`, positional `source`/`action`/`ref`, and `--within-min`
  (`reader.py` around lines 95–101) — five distinct causes, one identical
  `E_INVALID_INPUT`. Plan 053 documents that; this plan may fix the `cwd`
  case at the root.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Probe the validator | `PYTHONPATH=src python3 -c "from portable_resume.paths import validate_canonical_absolute as v; [print(p, (lambda: 'OK')() if not print else '') for p in []]"` — simpler: write a 3-line script trying `/tmp`, `/private/tmp`, `$PWD` | records which are accepted |
| Lane A | `PYTHONPATH=src python3 scripts/portable-resume claude show latest --cwd /tmp --source-root <fixture> --format handoff` | exit 0 |
| Lane B | write a request-v1 file with `"cwd":"/tmp"`, run `--request-file … --expected-source claude` | before: exit 2; after: per decision |
| Request tests | `grep -rln "request-v1\|load_request" tests/ \| head`, run those modules | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**:
- **Decision + exactly one of**: (a) `src/portable_resume/request.py` /
  `src/portable_resume/paths.py` to canonicalize on read, or (b)
  `src/portable_resume/resources/skill/SKILL.md.tmpl` wording only
- Request-lane tests
- `plans/README.md` — status row

**Out of scope**:
- Adding field names to diagnostics (content-free contract; plan 031 owns
  hint mechanisms).
- The other mutual-exclusion traps — plan 053 documents them.
- Lane A's behavior — it is correct.
- `request-v2` / adding a `list` action — deferred (DIRECTION-04).

## Git workflow

- Branch: `plan/052-request-lane-cwd-parity`
- Commit style: `fix(request): accept non-canonical cwd like the argv lane` (or `docs(skill): …` for the docs-only path)

## Steps

### Step 1: Establish the security question, then decide

Read `request.py`'s module docstring and the comments around
`validate_canonical_absolute` in `paths.py`, and answer explicitly in your
report: **does anything downstream depend on the request file's `cwd` being
byte-identical to its realpath?** Trace where the returned `cwd` flows
(`Query.cwd` → adapter `prefer_slugs` / cwd matching) and check whether
rewriting it could widen access to any path the caller did not name.

Then pick ONE:

**A. Canonicalize on read** (preferred if the trace comes back clean): make
`load_request` call `canonicalize_cwd` exactly like lane A, so both lanes
accept the same inputs. The hardened file-reading (strict keys, no-follow,
size, stability) is untouched — only the path-normalization asymmetry goes
away.

**B. Keep strict, document precisely**: leave the validator alone and make
SKILL.md state that `cwd` must be realpath-resolved, with an explicit macOS
example (`/tmp` is not canonical; `/private/tmp` is) and a one-line
canonicalizing snippet the agent can run before writing the file.

**Verify**: the decision and its justification are written down before any
code change.

### Step 2A (if A): Canonicalize in the request lane

Replace the strict validation of `cwd` with the same canonicalization lane A
uses, keeping every other validation in `load_request` exactly as-is
(`normalize_unicode`, `isabs`, control rejection, strict key set). Do **not**
loosen `resume_ref` handling.

**Verify**: the same request file with `"cwd":"/tmp"` now exits 0 and selects
the same session as lane A's `--cwd /tmp`; a relative `cwd` (`"./x"`) and a
non-absolute/unicode-tricky value still exit 2.

### Step 2B (if B): Document precisely

In `SKILL.md.tmpl`'s lane B `cwd` bullet, state the realpath requirement,
give the macOS example, and note that lane A's `--cwd` does *not* have this
requirement. Keep it to a few lines; plan 053 restructures this file, so flag
the edit in your report.

**Verify**: `grep -n "realpath" src/portable_resume/resources/skill/SKILL.md.tmpl` → your lines.

### Step 3: Tests

Whichever path you took:
1. Lane A and lane B accept the **same** `cwd` value and select the same
   session (path A), or a test pins the rejection with a comment naming the
   documented requirement (path B).
2. Symlinked-directory case explicitly covered (create a symlink in a temp
   dir; do not depend on macOS-specific `/tmp` behavior in the assertion —
   build the symlink yourself so the test is portable).
3. Relative and non-absolute `cwd` values still rejected in lane B.
4. The strict key set, duplicate-key rejection, and no-follow behavior of
   `load_request` still hold (run the existing request tests untouched).

**Verify**: new tests pass; full suite OK.

### Step 4: Full gates

**Verify**: full suite OK; `self_verify.py` → 0; `check_secrets.py` → 0;
smoke matrix → 0.

## Test plan

Step 3 (4 cases). Build symlinks inside the test's own temp directory so the
suite behaves identically on Linux and macOS.

## Done criteria

- [ ] The decision (A or B) and its security justification are recorded in the completion report
- [ ] Lanes A and B accept the same `cwd` inputs (A) **or** SKILL.md states the realpath requirement with a worked example (B)
- [ ] Symlinked-directory case test-pinned
- [ ] `load_request`'s strict key set / no-follow / duplicate-key behavior unchanged (existing tests green untouched)
- [ ] Full suite + gates green; `plans/README.md` updated

## STOP conditions

- The trace in Step 1 shows that rewriting `cwd` could widen path access in
  any adapter — take path B and report the finding; do not relax the
  validator.
- Path A makes any existing request-lane security test fail — STOP; that test
  encodes the boundary you are moving.
- You find yourself adding the offending field name to a diagnostic message —
  out of scope (content-free contract).

## Maintenance notes

- Reviewer: if path A was taken, confirm the *only* behavioral change is
  path normalization — the strict-key, no-follow, size, and stability checks
  must be byte-identical.
- If `request-v2` (DIRECTION-04) is later built, it should inherit whichever
  grammar this plan settles on, and the SKILL.md wording must move with it.
