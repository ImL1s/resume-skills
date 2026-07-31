# Plan 039: Drive the source-immutability and PATH-isolation suites from `SOURCE_KEYS`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- tests/security/`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (may surface real pre-existing violations — that is the point)
- **Depends on**: none. **Order note**: land before plans 034/035 if possible
  so their adapter changes run under the widened net; either order is
  acceptable.
- **Category**: tests (core safety guarantees)
- **Planned at**: commit `a4dc4d6`, 2026-07-31

## Why this matters

The project's two hardest safety promises — "readers never mutate the source
store" and "readers never invoke a source CLI" — are regression-tested for
only a fraction of the 17 sources, and both lists are hardcoded so they go
silently stale each time a source is added (which happened 11 times since the
lists were written):

- `tests/security/test_source_immutability.py` covers **3** sources (claude,
  grok, opencode). None of the recently added SQLite-backed adapters (goose,
  crush, cline, hermes, openclaw) is covered — precisely the family that can
  violate immutability silently (opening a DB can create `-wal`/`-shm`/journal
  files).
- `tests/security/test_isolation.py` plants PATH shims for **6** sources. The
  sibling test `test_no_source_cli_exec.py` already iterates
  `sorted(SOURCE_KEYS)` and is the pattern to copy.

After this plan, adding a source without immutability coverage fails closed.

## Current state

- `tests/security/test_source_immutability.py` (lines ~30–35):

```python
class SourceImmutabilityTests(unittest.TestCase):
    CASES = (
        ("claude", "tests/fixtures/claude/s-cla-01-ordered-parent-chain/root", "/workspace/project"),
        ("grok", "tests/fixtures/grok/s-gro-01/root", "/workspace/project"),
        ("opencode", "tests/fixtures/opencode/s-ope-01/root", "/workspace/project"),
    )
```

  Read the rest of the class to see what a case does (byte/mtime fingerprint of
  the fixture tree before/after `list` + `show`, asserting no change) — reuse
  its mechanism unchanged.

- `tests/security/test_isolation.py` (line ~53):

```python
            for source in ("claude", "codex", "cursor", "opencode", "antigravity", "grok"):
```

- The registry-driven pattern, `tests/security/test_no_source_cli_exec.py`
  (lines ~20–35):

```python
    def test_path_shim_binaries_never_run_during_list_show(self) -> None:
        fixture = Path("tests/fixtures/claude/s-cla-01-ordered-parent-chain/root")
        ...
            for name in sorted(SOURCE_KEYS):
                path = bin_dir / name
                path.write_text(f"#!/bin/sh\necho {name} >> '{marker}'\nexit 99\n", encoding="utf-8")
                path.chmod(0o755)
```

- Fixture inventory: every source has at least one fixture tree under
  `tests/fixtures/<source>/`. Enumerate candidates per source with
  `ls tests/fixtures/<source>/` and pick, for each, a fixture with a `root`
  directory that the adapter's tests already use for a successful
  `list`/`show` (find each adapter test's fixture paths via
  `grep -rn "tests/fixtures/<source>" tests/ | head -3`). The fixture's
  matching `--cwd` value comes from the same existing test.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Security suite | `PYTHONPATH=src python3 -m unittest discover -s tests/security -q` | OK |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Source count | `PYTHONPATH=src python3 -c "from portable_resume.model import SOURCE_KEYS; print(len(SOURCE_KEYS))"` | `17` |

## Scope

**In scope**: `tests/security/test_source_immutability.py`,
`tests/security/test_isolation.py`, `plans/README.md` row. (Adapters
themselves are OUT of scope — if the widened net catches a real mutation, that
is a STOP/report, not a fix-here.)

**Out of scope**:
- `tests/security/test_no_source_cli_exec.py` (already correct).
- Any `src/portable_resume/**` change.
- Adding new fixtures — reuse existing adapter-test fixtures; if a source
  genuinely has no usable fixture, that is a reportable gap, not something to
  invent here.

## Git workflow

- Branch: `plan/039-registry-driven-security-tests`
- Commit style: `test(security): drive immutability and isolation suites from SOURCE_KEYS`

## Steps

### Step 1: Build the per-source fixture map for immutability

Replace the 3-tuple `CASES` with a mapping derived from `SOURCE_KEYS`:

```python
FIXTURES: dict[str, tuple[str, str]] = {
    "claude": ("tests/fixtures/claude/s-cla-01-ordered-parent-chain/root", "/workspace/project"),
    "grok": ("tests/fixtures/grok/s-gro-01/root", "/workspace/project"),
    "opencode": ("tests/fixtures/opencode/s-ope-01/root", "/workspace/project"),
    # ... one entry per remaining source, taken from that adapter's own tests
}
```

Fill the 14 missing entries by reading each adapter test module's fixture
choice (the fixture it uses for a plain successful `list`). Then add the
fail-closed completeness test:

```python
    def test_every_source_has_an_immutability_case(self) -> None:
        self.assertEqual(sorted(FIXTURES), sorted(SOURCE_KEYS))
```

and iterate `for source, (root, cwd) in sorted(FIXTURES.items()):` with
`self.subTest(source=source)` through the existing fingerprint mechanism.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.security.test_source_immutability -v`
→ 17 subtests pass (or failures that are REAL findings — see STOP).

### Step 2: Widen the isolation shim loop

In `test_isolation.py` line ~53, replace the literal tuple with
`sorted(SOURCE_KEYS)` (import it the way `test_no_source_cli_exec.py` does).
Keep the extra "common launcher names" list that follows, if present, as-is.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.security.test_isolation -v` → pass.

### Step 3: Full gates

**Verify**: full suite OK; `python3 scripts/self_verify.py` → 0.

## Test plan

The plan IS tests. Expected new coverage: 14 additional immutability subtests,
11 additional shim names. The completeness assertion is the permanent guard.

## Done criteria

- [ ] `FIXTURES` keys == `SOURCE_KEYS` (asserted by a test)
- [ ] Immutability runs a fingerprint case per source; isolation shims cover every source key
- [ ] Full suite green — or documented STOP report of real violations
- [ ] No `src/` changes; `plans/README.md` updated

## STOP conditions

- **A widened case fails** (a source store mutates or a shim fires): do NOT
  patch the adapter here and do NOT weaken/skip the case. Report:
  source, failing assertion, and the observed side-effect (e.g. `-wal` file
  appeared). That report is the most valuable possible outcome of this plan.
- A source has no fixture with a working `list` (completeness assertion cannot
  be satisfied honestly) — report the source; do not fabricate a fixture.
- SQLite snapshot behavior makes mtime-based fingerprints flaky on some OS
  (nondeterministic failures) — report with the flake details; do not add
  retries.

## Maintenance notes

- New sources now fail `test_every_source_has_an_immutability_case` until an
  entry is added — that friction is intended; the entry costs one line.
- TEST-03 (bounds/truncation backfill for crush/hermes/openhands) remains
  open and would slot naturally beside this file as a shared conformance
  suite.
