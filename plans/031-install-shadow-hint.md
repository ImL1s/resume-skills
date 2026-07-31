# Plan 031: Give `E_INSTALL_SHADOW` a static remediation hint and document the upgrade path

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/diagnostics.py src/portable_resume/install/discovery.py docs/install-hosts.md schemas/ tests/`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW–MED (touches the diagnostic contract; additive only)
- **Depends on**: plans/030-installer-arg-validation.md (same files; land 030 first to avoid conflicts)
- **Category**: dx (CLI UX)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/135

## Why this matters

The README's headline command `install-resume-skills quick-install all` is a
dead end for anyone who upgraded the package with an older project-scope
install still on disk: it exits 6 with zero stdout and a stderr diagnostic that
names neither the conflicting root's location nor any remedy. The working
escape hatches (`audit-host` to locate the divergent root; then uninstall the
stale claim, or re-run with `--project`/`--root`) are undiscoverable. This plan
adds a **static, code-fixed hint string** to the diagnostic (preserving the
content-free invariant — the hint may reference command names and flag names,
never paths or user data) and documents the upgrade sequence.

## Current state

- `src/portable_resume/diagnostics.py`:
  - `DiagnosticError` is a `@dataclass(slots=True)` with fields
    `code`, `message`, `source`, `provider`, `attempts`, `family`.
  - `__post_init__` fixes the message from `_DEFAULT_MESSAGES[self.code]` with
    this load-bearing comment: "English prose is intentionally fixed by code.
    Adapter-supplied or recovered text can therefore never leak through an
    exception message."
  - `to_dict()` emits `schema_version: "portable-resume/diagnostic-v1"`, plus
    `code`, `message`, `exit_code`, `source`, `provider`, `attempts`, `family`.
  - `E_INSTALL_SHADOW` default message: "A higher-precedence discovery root
    already holds a divergent Portable Resume Skill."
- `src/portable_resume/install/discovery.py` `require_no_blocking_shadow`
  raises `DiagnosticError("E_INSTALL_SHADOW", family=...)` (lines ~1233–1239;
  after plan 030 the family is deduped).
- Reproduction (verified): from a checkout with an older `.grok/skills`
  project install (bundle 0.3.3 vs current dev), `quick-install all` → exit 6,
  stdout empty, stderr `{"code":"E_INSTALL_SHADOW",...}`. `audit-host --host
  grok --scope project` correctly reveals the stale root;
  `--project <other-dir>` clears the block.
- `docs/install-hosts.md` has no upgrade/conflict-resolution section (grep
  "E_INSTALL_SHADOW" in docs/ → no hits).
- Schema locations to check: `schemas/` at repo root and
  `src/portable_resume/resources/portable-resume-v1.schema.json`. Run
  `grep -rln "diagnostic-v1" schemas/ src/portable_resume/resources/ tests/`
  to find every schema/contract test that pins the diagnostic shape.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Contract search | `grep -rn "diagnostic-v1" src/ tests/ schemas/` | lists every pin |
| Full gate | `python3 scripts/self_verify.py` | exit 0 |
| Docs gate | `python3 scripts/check_docs.py` | exit 0 |

## Scope

**In scope**:
- `src/portable_resume/diagnostics.py` — add optional static `hint`
- `src/portable_resume/install/discovery.py` — pass the hint key (only if the
  design lands as per-raise rather than per-code; prefer per-code, below)
- Any JSON schema / contract test that must learn the optional field (found
  via the grep above)
- `docs/install-hosts.md` — new "Upgrading / resolving E_INSTALL_SHADOW"
  section
- `tests/unit/` — new/extended diagnostic tests
- `plans/README.md` — status row

**Out of scope**:
- Any dynamic content in diagnostics (paths, hostnames, versions) — forbidden
  by the invariant.
- Changing which conditions block vs warn (CORRECTNESS-03 design question —
  separate decision).
- Other error codes' hints beyond `E_INSTALL_SHADOW` (adding the *mechanism*
  is in scope; populating more hints is follow-up).

## Git workflow

- Branch: `plan/031-install-shadow-hint`
- Commit style: `feat(diagnostics): static remediation hint for E_INSTALL_SHADOW`

## Steps

### Step 1: Add a static hint map to diagnostics

In `diagnostics.py`, next to `_DEFAULT_MESSAGES`, add:

```python
_DEFAULT_HINTS: dict[str, str] = {
    "E_INSTALL_SHADOW": (
        "Run 'install-resume-skills audit-host --host <host> --scope <scope>' "
        "to locate the conflicting root; then uninstall the stale claim or "
        "re-run install with --project/--root."
    ),
}
```

Add a `hint: str | None = None` field to the dataclass (after `family` to keep
positional compatibility), and in `__post_init__` force it from the map:
`self.hint = _DEFAULT_HINTS.get(self.code)` — i.e. callers can NOT inject
hints; the map is the only source, mirroring how `message` works. Emit it in
`to_dict()` only when not None (or always with `null` — match whichever style
the contract tests expect; pick "always present, possibly null" only if the
schema requires fixed keys).

**Verify**: `PYTHONPATH=src python3 -c "from portable_resume.diagnostics import DiagnosticError; import json; print(DiagnosticError('E_INSTALL_SHADOW').to_json())"` → JSON contains the hint string; `DiagnosticError('E_NO_MATCH').to_json()` → no hint key (or null).

### Step 2: Update schemas and contract tests

For every pin found by `grep -rn "diagnostic-v1"`: if a JSON schema validates
diagnostics with `additionalProperties: false`, add the optional `hint`
property. Update contract tests that enumerate keys. Do NOT bump the schema
version for an optional additive field unless a contract test explicitly
asserts closed-set equality of keys in consumer-facing docs — if you find a
consumer contract that forbids additions, STOP and report (a `diagnostic-v2`
decision belongs to the maintainer).

**Verify**: `PYTHONPATH=src python3 -m unittest discover -s tests -q` → OK.

### Step 3: Document the upgrade path

In `docs/install-hosts.md`, add a short section "Upgrading and resolving
E_INSTALL_SHADOW":

1. Why it happens (older project/global install with a different bundle
   version is found at a higher-precedence root).
2. Diagnose: `install-resume-skills audit-host --host <key> --scope <scope> [--project <dir>]`.
3. Resolve: `install-resume-skills uninstall --host <key> --scope <scope> ...`
   the stale claim, or install to an explicit `--project`/`--root`.
4. Note the exit code is 6 and stdout is intentionally empty on this failure.

Then run the docs gate — `check_docs.py` enforces structure on some files;
keep the section ASCII and link-consistent.

**Verify**: `python3 scripts/check_docs.py` → exit 0; `grep -n "E_INSTALL_SHADOW" docs/install-hosts.md` → ≥ 3 hits.

### Step 4: Tests

- Unit: `E_INSTALL_SHADOW` diagnostic dict contains the exact static hint;
  a code without a hint entry has none; a constructed
  `DiagnosticError("E_INSTALL_SHADOW", message="attacker")` still emits the
  fixed message AND the fixed hint (injection-proof).
- Integration-ish: reuse plan 030's mocked `require_no_blocking_shadow` test
  to assert the emitted stderr JSON now includes the hint.

**Verify**: targeted test module passes; full suite OK.

## Test plan

As Step 4; model diagnostic tests after the existing tests that cover
`DiagnosticError.to_dict()` (find via `grep -rln "to_dict\|diagnostic-v1" tests/unit/`).

## Done criteria

- [ ] `E_INSTALL_SHADOW` stderr JSON includes the static hint; no other code gained unintended hints
- [ ] Hint is not caller-injectable (test proves it)
- [ ] All schema/contract pins updated; full suite green
- [ ] `docs/install-hosts.md` has the upgrade section; `check_docs.py` exits 0
- [ ] No files outside in-scope modified; `plans/README.md` updated

## STOP conditions

- A consumer-facing contract test asserts the diagnostic key set is closed
  (needs a versioning decision — report).
- The hint text cannot stay accurate without dynamic content — do not add
  dynamic content; report instead.
- `check_docs.py` fails for reasons unrelated to your edit (pre-existing
  drift — report, don't fix unrelated docs here; plans 033/042 own those).

## Maintenance notes

- The `_DEFAULT_HINTS` map is the sanctioned place for future per-code hints;
  reviewers must reject any hint containing formatting placeholders filled at
  raise time.
- If plan 042 (registry-generated docs) lands, the upgrade section's command
  examples should move into (or be checked by) the generated-docs gate.
