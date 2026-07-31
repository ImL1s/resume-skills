# Plan 032: Publish the exit-code / diagnostic-code reference (`docs/diagnostics.md`)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/diagnostics.py scripts/check_docs.py docs/ README.md`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (if plan 031 lands first, include its `hint` field in the documented shape)
- **Category**: docs
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/136

## Why this matters

Every command in both CLIs fails by writing a structured JSON diagnostic to
stderr and returning one of eight stable exit codes — this *is* the product's
public API for scripts and host agents. Yet no document describes it:
`grep -rn "exit_code\|ExitCode" docs/ README.md CONTRIBUTING.md AGENTS.md`
finds nothing. Integrators must read `diagnostics.py`. A single reference page,
plus a docs-gate assertion that keeps it complete, closes the gap permanently.

## Current state

- `src/portable_resume/diagnostics.py` (source of truth to document — do not
  modify it in this plan):

```python
class ExitCode(IntEnum):
    OK = 0
    INVALID_INPUT = 2
    NO_MATCH = 3
    AMBIGUOUS = 4
    UNSUPPORTED = 5
    UNSAFE_OR_BUSY = 6
    CORRUPT_OR_LIMIT = 7
    INVARIANT = 8
```

  `ERROR_EXIT_CODES` maps 17 `E_*` codes onto these (E_INVALID_INPUT,
  E_NO_MATCH, E_AMBIGUOUS, E_UNSUPPORTED_FORMAT, E_CAPABILITY_UNAVAILABLE,
  E_UNSAFE_PATH, E_SOURCE_BUSY, E_SQLITE_HOT_JOURNAL, E_LIMIT_EXCEEDED,
  E_CORRUPT_RECORD, E_INVARIANT, E_INSTALL_BUSY, E_INSTALL_CONFLICT,
  E_INSTALL_SHADOW, E_INSTALL_UNSUPPORTED_PLATFORM, E_RECOVERY_REQUIRED,
  E_VERIFY_MISMATCH). `_DEFAULT_MESSAGES` holds each code's fixed prose.
  `WARNING_CODES` holds 14 `W_*` codes. `to_dict()` emits:
  `schema_version` ("portable-resume/diagnostic-v1"), `code`, `message`,
  `exit_code`, `source`, `provider`, `attempts`, `family` (+ `hint` if plan
  031 landed).
- `scripts/check_docs.py` — docs gate; contains hardcoded expectation lists
  (e.g. `REQUIRED_COMMANDS`, `REQUIRED_LINKS`) and checks README/i18n files.
  It imports nothing from `portable_resume` today — check with
  `grep -n "^import\|^from" scripts/check_docs.py`; other scripts set
  `sys.path` to import `src` (see `scripts/prepare_build_identity.py:14-16`
  pattern).
- `README.md` "Key documentation" section (lines ~180–189) lists docs pages —
  the new page must be added there.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Docs gate | `python3 scripts/check_docs.py` | exit 0 |
| Unit tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Coverage check | `PYTHONPATH=src python3 - <<'EOF'` (Step 3 snippet) `EOF` | prints OK |

## Scope

**In scope**:
- `docs/diagnostics.md` (create)
- `scripts/check_docs.py` (add the completeness assertion)
- `README.md` (one link line in Key documentation)
- `plans/README.md` — status row

**Out of scope**:
- `src/portable_resume/**` — no product code changes.
- Translating the page (i18n quick-starts are a different surface; do not
  touch `docs/i18n/`).

## Git workflow

- Branch: `plan/032-diagnostics-reference`
- Commit style: `docs: exit-code and diagnostic-code reference`

## Steps

### Step 1: Write `docs/diagnostics.md`

Structure:

1. **Diagnostic JSON shape** — one fenced example (take a real one:
   `PYTHONPATH=src python3 scripts/portable-resume nosuch list 2>&1 >/dev/null`)
   and a field table (`schema_version`, `code`, `message`, `exit_code`,
   `source`, `provider`, `attempts`, `family`, and `hint` if present in
   `to_dict()` at execution time). State the invariant: messages are fixed
   English prose chosen by code; no recovered text, paths, or user data ever
   appear.
2. **Exit codes** — a table of the 8 `ExitCode` values: number, name, meaning,
   what a caller should do (e.g. 3 NO_MATCH → treat as empty result; 4
   AMBIGUOUS → parse stdout candidates envelope; 6 UNSAFE_OR_BUSY → retry
   later / inspect store safety; 8 INVARIANT → file a bug).
3. **Error codes** — a table of all `ERROR_EXIT_CODES` entries: code → exit
   code → fixed message (copy from `_DEFAULT_MESSAGES`) → emitted by (reader /
   installer / both — determine with `grep -rn "<CODE>" src/portable_resume`).
4. **Warning codes** — list `WARNING_CODES` with one line each (warnings ride
   inside the stdout envelope's `warnings` array, not stderr).
5. Note where diagnostics are written (stderr, one line, JSON) vs envelopes
   (stdout), and that `verify`/`matrix`/`audit-host` also use exit codes 6/7
   from their result documents.

**Verify**: page exists; every code string from `ERROR_EXIT_CODES` and
`WARNING_CODES` appears in it (Step 3 automates this).

### Step 2: Link it

Add to README "Key documentation":
`- [docs/diagnostics.md](docs/diagnostics.md) — exit codes and machine diagnostics`

**Verify**: `grep -n "diagnostics.md" README.md` → 1 hit.

### Step 3: Gate completeness in `check_docs.py`

Add a check that imports the truth and fails on omission. Follow the
`sys.path` insertion pattern from `scripts/prepare_build_identity.py`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from portable_resume.diagnostics import ERROR_EXIT_CODES, WARNING_CODES
text = (ROOT / "docs" / "diagnostics.md").read_text(encoding="utf-8")
missing = [c for c in [*ERROR_EXIT_CODES, *sorted(WARNING_CODES)] if c not in text]
if missing:
    fail(f"docs/diagnostics.md missing codes: {missing}")
```

Adapt to the script's existing error-reporting helpers (read how existing
checks report failures and match that style exactly).

**Verify**: `python3 scripts/check_docs.py` → exit 0. Then temporarily delete
one code from the page, re-run → non-zero exit naming the code; restore.

### Step 4: Full gates

**Verify**: `python3 scripts/self_verify.py` → exit 0 (its docs stage runs
check_docs); full unittest suite OK; `python3 scripts/check_secrets.py` → 0.

## Test plan

The gate in Step 3 is the regression test (docs completeness is enforced by
`check_docs.py`, which `self_verify --profile ci-quality` runs in CI). No
product unit tests needed.

## Done criteria

- [ ] `docs/diagnostics.md` exists; all 17 `E_*` and 14 `W_*` codes appear in it
- [ ] `check_docs.py` fails if any code goes missing (spot-proved once)
- [ ] README links the page; `check_docs.py` and `self_verify.py` exit 0
- [ ] No product code modified (`git status` shows only the three in-scope files + plans/README.md)

## STOP conditions

- `check_docs.py`'s structure resists a clean import (e.g. it must stay
  stdlib-only-without-src by policy) — report; fallback design (hardcoding the
  code list in the gate) defeats the purpose and needs maintainer sign-off.
- You find additional exit-code semantics in `install/cli.py` that contradict
  `ERROR_EXIT_CODES` (e.g. bare `return 7`/`return 6` in matrix/audit-host
  paths) — document them as-is in the page; if they conflict with the enum,
  report the conflict rather than papering over it.

## Maintenance notes

- New error/warning codes now fail the docs gate until documented — that is
  the intended friction.
- If plan 031 adds `hint`, this page documents it; if plan 031 is not yet
  landed, leave hint out and note it in the plan-README row.
