# Plan 051: Make the installed runner safe to probe — bare invocation lists, missing runtime diagnoses

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/resources/skill/run_reader.py.tmpl src/portable_resume/diagnostics.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW–MED (part A changes a documented convenience default)
- **Depends on**: none
- **Category**: bug / dx (in-session failure paths)
- **Planned at**: commit `2b4611c`, 2026-08-01
- **Issue**: https://github.com/ImL1s/resume-skills/issues/168

## Why this matters

**Part A — a bare invocation detonates the caller's context.** The first thing
an agent does with an unfamiliar script is run it with no arguments to see
what it does. Here, no arguments means `show latest`: measured against a real
store, that emitted **157,446 bytes** of handoff markdown to stdout (roughly
40K tokens) unprompted, against whatever directory the host happened to be in.
There is no size guard the agent can set first — `--max-tool-chars` only caps
tool blocks (at 8000 / 500 / 0 the same session rendered 161,857 / 76,774 /
42,158 bytes), and the output ceiling is 10 MB.

**Part B — a missing runtime returns a Python traceback.** The runner imports
the bundled runtime at module scope with no guard. Copy `scripts/run_reader.py`
without its sibling `.portable-resume/runtime` — precisely what a partially
synced or hand-copied skill directory looks like, and SKILL.md tells the agent
to resolve paths relative to "the directory containing this SKILL.md" — and it
exits **1** with a raw `ModuleNotFoundError` traceback on stderr and nothing
on stdout. This is the one path in the whole flow that breaks the product's
diagnostic contract: no `portable-resume/diagnostic-v1` envelope, and exit 1
is not one of the eight stable exit codes.

## Current state

- **Part A — the no-argument default** —
  `src/portable_resume/resources/skill/run_reader.py.tmpl` around lines
  75–92:

```python
    # Drop a leading source token (bound or hostile) so we re-bind exactly once.
    if cleaned and cleaned[0] in _KNOWN_SOURCES:
        cleaned = cleaned[1:]

    if not cleaned:
        # No action: default to show latest (same as bare Grok-style invocation).
        return [_BOUND_SOURCE, "show", "latest", "--expected-source", _BOUND_SOURCE]

    if cleaned[0] in {"list", "show"}:
        return [_BOUND_SOURCE, *cleaned, "--expected-source", _BOUND_SOURCE]

    if cleaned[0].startswith("-"):
        # Options without action — leave to the reader (invalid unless request-file).
        return [_BOUND_SOURCE, *cleaned, "--expected-source", _BOUND_SOURCE]

    # Bare ref without action → show <ref> (Grok resume-session style).
    # Leading "-" refs are options, not refs (handled above).
    return [_BOUND_SOURCE, "show", *cleaned, "--expected-source", _BOUND_SOURCE]
```

  Note the bare-ref shorthand on the last branch is a separate, valued
  ergonomic — **keep it**.

- **Part B — the unguarded import** — same file, around lines 10–21:

```python
# Skill package root is the parent of scripts/; the installer places the
# stdlib runtime next to the skill tree under <skill-root>/.portable-resume/runtime.
_SKILL_PACKAGE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_ROOT = os.path.dirname(_SKILL_PACKAGE)
_RUNTIME = os.path.join(_ROOT, ".portable-resume", "runtime")
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)

from portable_resume.reader import main  # noqa: E402
from portable_resume.model import SOURCE_KEYS  # noqa: E402
```

  `_KNOWN_SOURCES = frozenset(SOURCE_KEYS)` immediately below means the
  argv-shaping logic itself depends on the import succeeding — so a fallback
  must not assume `SOURCE_KEYS` is available.

- **The diagnostic contract to honor** —
  `src/portable_resume/diagnostics.py`: `ExitCode` (0/2/3/4/5/6/7/8),
  `ERROR_EXIT_CODES`, and the JSON shape
  `{"schema_version":"portable-resume/diagnostic-v1","code":…,"message":…,"exit_code":…,…}`.
  Messages are **fixed English prose chosen by code** — no dynamic content,
  no paths. A fallback emitter must reproduce that shape *without* importing
  the runtime (it is missing, by definition), so it writes a small literal
  JSON document itself.
- **Verified passing behavior — do not regress it**: hostile source override
  is genuinely ignored (`run_reader.py list --expected-source qwen` and
  `run_reader.py qwen list` both return the bound source's rows, exit 0).
- **Template rendering**: this file is a `string.Template` rendered per source
  (`render_run_reader` in `src/portable_resume/install/render.py`), so
  `${source_key}` substitution rules apply — **any literal `$` you add must be
  escaped as `$$`**.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Temp install | `PYTHONPATH=src python3 scripts/install-resume-skills quick-install claude --root "$(mktemp -d)/skills"` | exit 0 |
| Bare invocation | `python3 <root>/resume-claude/scripts/run_reader.py` | after: a bounded listing, not a full transcript |
| Missing runtime | copy only `scripts/run_reader.py` elsewhere, run `list --cwd /tmp` | after: diagnostic JSON on stderr, stable exit code |
| Runner tests | find with `grep -rln "run_reader" tests/ \| head`, run those modules | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Installed matrix | `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` | exit 0 |

**Install into `$(mktemp -d)` roots only. Never into `$HOME` or a real host
root.**

## Scope

**In scope**:
- `src/portable_resume/resources/skill/run_reader.py.tmpl`
- Runner/argv-shaping tests; a new test for the missing-runtime path
- `src/portable_resume/resources/skill/SKILL.md.tmpl` — **only** the one line
  documenting what a bare invocation does (the full rewrite is plan 053; keep
  this edit to a single sentence and note it so 053 does not conflict)
- `plans/README.md` — status row

**Out of scope**:
- The bare-**ref** shorthand (`run_reader.py <uuid>` → `show <uuid>`) — keep.
- `reader.py` argument handling — plan 029 owns `--help` text.
- Adding a new error code to `diagnostics.py` unless STOP conditions say
  otherwise (prefer reusing `E_CAPABILITY_UNAVAILABLE`).
- Runtime identity/drift detection — plan 054.

## Git workflow

- Branch: `plan/051-runner-hardening`
- Commit style: `fix(runner): bare invocation lists; missing runtime emits a diagnostic`

## Steps

### Step 1 (Part A): Default no-args to `list`

Change the `if not cleaned:` branch to
`return [_BOUND_SOURCE, "list", "--expected-source", _BOUND_SOURCE]`.
Update the adjacent comment to say the bare invocation is the cheap discovery
step. Leave every other branch untouched — in particular the bare-ref
shorthand.

**Verify**: on a temp install, `python3 <root>/resume-claude/scripts/run_reader.py`
emits a bounded listing (record the byte count — should be orders of
magnitude below the 157,446-byte baseline), exit 0. `run_reader.py show latest`
still renders the full handoff. `run_reader.py <a-session-id>` still works.

### Step 2 (Part A): Document the new default in one line

In `SKILL.md.tmpl`, state that a bare invocation lists sessions and that
`show latest` is the explicit full-transcript form. **One sentence** — plan
053 restructures this file, so keep the edit minimal and flag it in your
report so 053's author expects it.

**Verify**: `grep -n "bare" src/portable_resume/resources/skill/SKILL.md.tmpl` → your line.

### Step 3 (Part B): Guard the runtime import

Wrap the two imports in `try/except ImportError`. In the failure path, write a
literal diagnostic document to **stderr** and exit with a stable code — do not
re-raise, do not print a traceback:

```python
try:
    from portable_resume.reader import main  # noqa: E402
    from portable_resume.model import SOURCE_KEYS  # noqa: E402
except ImportError:
    sys.stderr.write(
        '{"schema_version":"portable-resume/diagnostic-v1",'
        '"code":"E_CAPABILITY_UNAVAILABLE",'
        '"message":"The requested source capability is unavailable.",'
        '"exit_code":5,"source":null,"provider":null,"attempts":null,"family":[]}\n'
    )
    raise SystemExit(5)
```

Match the exact key set and message string that `diagnostics.py` would
produce for the code you choose — read `_DEFAULT_MESSAGES` and `to_dict()` and
mirror them byte-for-byte. Keep the payload static (no paths, no exception
text): the content-free discipline applies here too. Note that everything
below this point (including `_KNOWN_SOURCES`) must not execute in the failure
path.

**Verify**: copy only `scripts/run_reader.py` to an empty temp dir and run
`list --cwd /tmp` → stderr is a single parseable JSON line, stdout empty,
exit code is the one you chose (not 1), and `python3 -c "import json,sys; json.load(sys.stdin)"` accepts the stderr text.

### Step 4: Tests

1. Argv shaping: no args → `["<source>", "list", "--expected-source", "<source>"]`;
   `show latest` unchanged; bare ref unchanged; hostile leading source token
   still dropped exactly once.
2. Missing runtime: render the template to a temp dir **without** the runtime,
   run it as a subprocess, assert the exit code, empty stdout, and that stderr
   parses as JSON with the expected `code`/`exit_code`.
3. Regression: `--expected-source qwen` against a claude-bound runner still
   returns claude rows (the passing behavior above).

Find the existing runner test module first
(`grep -rln "run_reader" tests/ | head`) and follow its structure.

**Verify**: new tests pass; full suite OK.

### Step 5: Full gates

**Verify**: full suite OK; `smoke_installed_matrix.py` → 0; `self_verify.py`
→ 0; `check_secrets.py` → 0. Re-run the Step 1 and Step 3 verifications on a
**fresh** temp install to confirm the shipped bytes carry both changes.

## Test plan

Step 4 (≥ 5 assertions). The missing-runtime test must run the script as a
subprocess — importing it in-process cannot exercise a module-scope import
failure.

## Done criteria

- [ ] Bare `run_reader.py` produces a bounded listing (byte count recorded, ≪ 157 KB)
- [ ] `show latest` and bare-ref shorthand unchanged
- [ ] Missing runtime → parseable `diagnostic-v1` JSON on stderr, empty stdout, stable exit code (never 1, never a traceback)
- [ ] Hostile `--expected-source` override still ignored
- [ ] Template `$` escaping intact (`smoke_installed_matrix.py` green proves rendering)
- [ ] Full suite + gates green; `plans/README.md` updated

## STOP conditions

- Reusing `E_CAPABILITY_UNAVAILABLE` is judged wrong for "runtime missing" and
  a **new** code is needed — STOP and report; adding to `ERROR_EXIT_CODES` is
  a contract change (and plan 032's reference page would need it too).
- Changing the no-args default breaks a documented host integration (some
  host invokes the runner bare and expects a transcript) — search
  `docs/install-hosts.md` and `docs/host-ui-smoke.md` for bare invocations
  first; report if you find one.
- The literal JSON cannot be made byte-identical to `diagnostics.py`'s output
  for the chosen code — report the difference rather than shipping a
  near-miss shape.

## Maintenance notes

- Reviewer: check the fallback emitter imports nothing from the runtime and
  contains no dynamic content; and that `$` in any added literal is escaped
  for `string.Template`.
- Plan 053 rewrites `SKILL.md.tmpl` wholesale — the one-line edit here must
  survive that rewrite (or be folded into it).
- Plan 032's `docs/diagnostics.md` should mention that the runner can emit
  this code before the runtime loads.
