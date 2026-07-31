# Plan 029: Make `portable-resume --help` teach the CLI (option help strings + self-check visibility)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/reader.py tests/unit/`
> This plan was written against the working tree of branch
> `fix/issue-118-embedded-identity` (base commit `a4dc4d6`, with uncommitted
> changes present in `reader.py`). Compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx (CLI UX)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/133

## Why this matters

`portable-resume` is the end-user half of the product, and its `--help` page
teaches nothing: 8 of its 9 options are registered with no `help=` text, so the
rendered help shows bare metavars. Because the parser deliberately replaces
argparse's specific error messages with a uniform content-free diagnostic
(security invariant — see below), `--help` is the *only* place a user can learn
the per-action `--format` defaults, the closed option sets, and the numeric
bounds. Additionally, the `self-check` subcommand — the first thing anyone runs
when an install misbehaves, and one the README explicitly documents — is
dispatched by a string comparison before the parser is built, so `--help` denies
it exists.

## Current state

- `src/portable_resume/reader.py` — the only file to modify. `build_parser()`
  (around lines 30–52) registers options with no help text:

```python
    parser.add_argument("--cwd")
    parser.add_argument("--within-min", type=int)
    parser.add_argument("--format", choices=("json", "handoff", "table"))
    parser.add_argument("--json", action="store_true", dest="json_alias")
    parser.add_argument("--max-tool-chars", type=int, default=DEFAULT_BOUNDS.tool_output_chars)
    parser.add_argument("--source-root")
    parser.add_argument("--request-file")
    parser.add_argument("--expected-source", choices=tuple(sorted(SOURCE_KEYS)))
```

- The undocumented semantics these help strings must convey (all verified in
  the same file):
  - `_format()` (around lines 120–136): default format is `handoff` for `show`
    and `table` for `list`; `show` rejects `table`; `--json` conflicts with an
    explicit non-json `--format`.
  - `run()` (around lines 259–262): `--within-min` must be 0 ≤ n ≤ 5256000
    (ten years in minutes; only negatives are rejected, and `<= 0` is defined
    by `adapters/common.within_age` as disabling the age filter);
    `--max-tool-chars` must be within `0..DEFAULT_BOUNDS.tool_output_chars`.
  - `--request-file` is mutually exclusive with positional
    `source`/`action`/`ref` and `--cwd`, and requires `--expected-source`
    (`_resolve_invocation`, lines 93–103).
- `self-check` interception in `run()` (around lines 244–251):

```python
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if argv_list and argv_list[0] == "self-check":
        # Real closed parser: unknown options / positionals fail (no silent ignore).
        self_parser = build_self_check_parser()
```

- The `action` positional help currently reads `"list|show"` (line 42) and does
  not mention `self-check`.
- **Design constraint you must honor** (documented in
  `src/portable_resume/diagnostics.py`, comment in `DiagnosticError.__post_init__`):
  "English prose is intentionally fixed by code. Adapter-supplied or recovered
  text can therefore never leak through an exception message." Do NOT change
  `DiagnosticArgumentParser.error` or any diagnostic message. This plan changes
  help text only.
- Repo conventions: stdlib-only runtime, four-space indent, type hints,
  `snake_case` (see `CONTRIBUTING.md` "Code and fixture rules"). The installer
  CLI is the in-repo exemplar for good help strings — see
  `src/portable_resume/install/cli.py:53-62`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Render help | `PYTHONPATH=src python3 scripts/portable-resume --help` | exit 0, help text |
| Unit tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK (all pass; 757 at planning time) |
| Full local gate | `python3 scripts/self_verify.py` | exit 0 |
| Secrets gate | `python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope** (the only files you should modify):
- `src/portable_resume/reader.py` — help text, epilog, description only
- `tests/unit/test_reader_help.py` (create)
- `plans/README.md` — status row

**Out of scope** (do NOT touch, even though they look related):
- `DiagnosticArgumentParser.error` and anything in `diagnostics.py` — the
  content-free error contract is a deliberate security invariant.
- `_format()`, `_resolve_invocation()`, `run()` dispatch logic — no behavior
  change of any kind; parsing semantics must remain byte-identical.
- `src/portable_resume/install/cli.py` — covered by plan 030.

## Git workflow

- Branch: `plan/029-reader-cli-help` from current `main` (or the operator's
  instruction).
- Commit style (match `git log`): `fix(reader): teach --help the option semantics and self-check`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add help strings to all reader options

In `build_parser()`, add a `help=` to each of the 8 undocumented options.
Required content (wording may be tightened, facts may not be dropped):

- `--cwd`: "project directory used for session matching (default: current directory)"
- `--within-min`: "only consider sessions updated within this many minutes (0..5256000; 0 disables the age filter; default: adapter listing window)"
- `--format`: "output format; default: handoff for show, table for list; show rejects table"
- `--json`: "alias for --format json (conflicts with an explicit non-json --format)"
- `--max-tool-chars`: f"per-tool-output character cap, 0..{DEFAULT_BOUNDS.tool_output_chars} (default: {DEFAULT_BOUNDS.tool_output_chars})"
- `--source-root`: "override the approved source store root (file or directory pinned by the adapter)"
- `--request-file`: "read a portable-resume/request-v1 JSON file instead of positional args; requires --expected-source; excludes source/action/ref/--cwd/--within-min"
- `--expected-source`: "assert the source key this invocation must resolve to (required with --request-file)"

Use dynamic values from `DEFAULT_BOUNDS` where shown so help never drifts from
the enforced bounds.

**Verify**: `PYTHONPATH=src python3 scripts/portable-resume --help` → every
option line shows a help sentence; exit 0.

### Step 2: Surface `self-check` in the main help

1. Change the `action` positional help from `"list|show"` to
   `"list|show (health report: run 'portable-resume self-check')"`.
2. Add an `epilog` to `build_parser()`'s `ArgumentParser` with two worked
   examples and the self-check pointer, e.g.:

```
examples:
  portable-resume claude list --cwd "$PWD"
  portable-resume claude show latest --cwd "$PWD" --format handoff
  portable-resume self-check        # packaging/runtime health (always JSON)
```

Pass `formatter_class=argparse.RawDescriptionHelpFormatter` so the epilog keeps
its line breaks. Do NOT move `self-check` into the parser as a real
subcommand — the string-dispatch at the top of `run()` is load-bearing (its
closed parser rejects unknown options) and stays as-is.

**Verify**: `PYTHONPATH=src python3 scripts/portable-resume --help | grep -c "self-check"` → `2` (action help + epilog).

### Step 3: Add help-content regression tests

Create `tests/unit/test_reader_help.py` (unittest, model after any
`tests/unit/test_reader_*.py` module's structure). Capture help via:

```python
import contextlib, io, unittest
from portable_resume.reader import build_parser

class ReaderHelpTests(unittest.TestCase):
    def render_help(self) -> str:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), self.assertRaises(SystemExit) as ctx:
            build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        return stream.getvalue()
```

Assert: (a) "self-check" appears; (b) each of the 8 option strings has a
non-empty help (grep for one distinctive keyword per option, e.g. "handoff for
show", "request-v1", "5256000" or the rendered bound); (c) `--help` exits 0.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.unit.test_reader_help -v` → all pass.

### Step 4: Full gates

**Verify**:
- `PYTHONPATH=src python3 -m unittest discover -s tests -q` → OK
- `python3 scripts/self_verify.py` → exit 0
- `python3 scripts/check_secrets.py` → exit 0

## Test plan

- New file `tests/unit/test_reader_help.py`: help renders, exits 0, contains
  self-check pointer and per-option help keywords (≥ 9 assertions).
- No existing test should change: parsing behavior is untouched.
- Verification: `PYTHONPATH=src python3 -m unittest discover -s tests -q` → all pass.

## Done criteria

- [ ] `PYTHONPATH=src python3 scripts/portable-resume --help` exits 0 and every option line has help text
- [ ] `--help` output mentions `self-check` at least twice
- [ ] `tests/unit/test_reader_help.py` exists and passes
- [ ] Full unittest suite passes; `self_verify.py` and `check_secrets.py` exit 0
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts above don't match `reader.py` (branch #118 landed and moved
  things) — re-locate, and if `build_parser` semantics changed, report.
- Any existing test fails after adding help text (would mean a test asserts on
  exact help output — report which).
- You find yourself editing `DiagnosticArgumentParser`, `_format`, or
  `_resolve_invocation` — that is out of scope by definition.

## Maintenance notes

- If a new option is added to the reader, the help-content test will not force
  a help string automatically; consider asserting "every option in
  `parser._actions` has non-empty help" as a stronger invariant (allowed as an
  extra test assertion in Step 3).
- Reviewer should check: no wording leaks dynamic/user content into help
  (static strings + `DEFAULT_BOUNDS` constants only).
- Deferred: exposing `self-check` as a true subparser (would change the
  closed-parser dispatch; not worth the risk for help visibility alone).
