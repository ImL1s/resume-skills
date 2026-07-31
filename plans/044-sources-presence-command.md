# Plan 044: `portable-resume sources` — report which agents have local stores for this machine/project

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/reader.py src/portable_resume/adapters/base.py src/portable_resume/registry.py tests/`
> Written against `main` at `a4dc4d6`. On excerpt mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: M (presence-only scope; cross-source `list` is explicitly deferred)
- **Risk**: MED (17-adapter fan-out must degrade gracefully)
- **Depends on**: plans/029-reader-cli-help.md (help/epilog integration).
  Pairs with plans/043-list-match.md as one product story.
- **Category**: direction (DIRECTION-02 / UX-09)
- **Planned at**: commit `a4dc4d6`, 2026-07-31

## Why this matters

The product's real entry question is "I was working in this repo yesterday in
*some* agent — which one, and can I resume from it?" Today that takes up to 17
guess-and-retry invocations, because every command requires naming a source up
front, and the only runtime enumeration of source keys is an unformatted
`--help` blob. Meanwhile destinations enjoy a full `hosts` report. Every
adapter already implements a cheap, fail-closed `probe()` returning a
capability state before any enumeration — a presence sweep is a loop over an
existing interface. **Scope fence: presence only.** A merged cross-source
`list` needs a multi-source envelope design (`Query`/`Envelope` are
single-source shaped) and is deferred; do not build it here.

## Current state

- `src/portable_resume/reader.py`:
  - `self-check` shows the pattern for a closed-parser subcommand dispatched
    before the main parser (string check on `argv_list[0]`, own
    `build_self_check_parser()`, always-JSON output, `ExitCode.CORRUPT_OR_LIMIT`
    on not-ok). `sources` should follow this exact pattern (second
    intercepted subcommand).
  - `self_check()` already loads all 17 adapters in a loop with per-adapter
    exception capture — the sweep skeleton to imitate:

```python
    for source in sorted(SOURCE_KEYS):
        try:
            adapter = _load_adapter(source)
            report["adapters"][source] = {"ok": True, "key": adapter.key}
        except Exception as error:
            report["ok"] = False
            report["adapters"][source] = {"ok": False, "error": type(error).__name__}
```

  - `run()`'s single-source flow shows the probe contract:

```python
        adapter = _load_adapter(source)
        capability = adapter.probe(query)
        if capability.state not in CAPABILITY_STATES or capability.source != source:
            raise DiagnosticError("E_INVARIANT", source=source)
```

- `src/portable_resume/adapters/base.py` — `SourceAdapter.probe(query) ->
  CapabilityReport`; `CAPABILITY_STATES` (read the file for the exact state
  set: includes `supported`, `partial`, `unavailable`, `unsafe`, plus any
  others — enumerate before coding). `CapabilityReport` carries `source`,
  `format_id`, `state`, `warnings`.
- Probes are cheap by contract: e.g. the claude adapter returns
  `CapabilityReport(self.key, FORMAT_ID, "unavailable")` when no root exists,
  before any enumeration.
- `src/portable_resume/registry.py` — `SOURCE_PROFILES` /
  `enabled_source_keys()`; `SourceProfile` carries `key`, `format_ids`,
  `status`, `supports_list`, `supports_show` — static columns for the report.
- Output conventions: machine JSON is compact (`_json` in reader.py:
  `sort_keys`, `separators=(",", ":")`), schema-versioned
  (`"portable-resume/self-check-v1"` precedent → use
  `"portable-resume/sources-v1"`). Human table format precedent: `_table()`
  (tab-separated, header row).
- Safety invariants that bind the sweep: never invoke a source CLI; per-source
  `ReadBudget()` fresh per probe; one broken store must not kill the sweep.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| After build | `PYTHONPATH=src python3 scripts/portable-resume sources` | exit 0, one row per enabled source |
| JSON | `PYTHONPATH=src python3 scripts/portable-resume sources --json` | one-line JSON, schema sources-v1 |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Isolation | `PYTHONPATH=src python3 -m unittest discover -s tests/security -q` | OK (sweep must pass the PATH-shim tests) |

## Scope

**In scope**: `src/portable_resume/reader.py` (new `sources` dispatch +
parser + report builder), new test module `tests/unit/test_reader_sources.py`,
`plans/README.md` row. Optionally one line in `README.md` quick start.

**Out of scope**:
- Cross-source merged `list`/`show` — deferred by design (envelope shape
  decision pending).
- Any adapter change. If a probe turns out expensive or crashy, that is a
  STOP/report, not a fix-here.
- The envelope JSON schema file — `sources` output is a new standalone
  document like self-check, not an envelope.
- Installer CLI (`hosts` stays where it is).

## Git workflow

- Branch: `plan/044-sources-presence-command`
- Commit style: `feat(reader): sources presence report across enabled adapters`

## Steps

### Step 1: Parser + dispatch

Mirror self-check exactly: intercept `argv_list[0] == "sources"` in `run()`
before the main parser; closed parser `build_sources_parser()` accepting
`--cwd` (optional; canonicalized like the main path), `--json` (accepted;
output is table by default, JSON with the flag — note this differs from
self-check's always-JSON because humans are a primary audience; keep the flag
semantics simple: no `--format`).

**Verify**: `PYTHONPATH=src python3 scripts/portable-resume sources --nope`
→ exit 2, JSON diagnostic (closed parser, no silent ignore).

### Step 2: The sweep

Report builder `sources_report(cwd: str | None) -> dict`:

```python
{
  "schema_version": "portable-resume/sources-v1",
  "ok": True,                    # False only on invariant-level failures
  "cwd": <canonicalized cwd or None>,
  "sources": {
     "<key>": {
        "state": "supported" | "partial" | "unavailable" | "unsafe" | "error",
        "format_id": <str or None>,
        "warnings": [...],       # from CapabilityReport, W_* validated
        "supports_list": bool, "supports_show": bool,   # from SourceProfile
     }, ...
  }
}
```

Per source: fresh `Query(source=key, ref=None, cwd=cwd or os.getcwd(), ...)`
with defaults, `_load_adapter`, `adapter.probe(query)` under
`try/except DiagnosticError` → state `"error"` with the diagnostic `code`
(content-free by construction) instead of aborting; `except Exception` →
state `"error"`, `"exception": type(e).__name__`. Do NOT call `list()` —
presence only, no store enumeration beyond what probe does. Validate probe
results the way `run()` does (state in `CAPABILITY_STATES`, key match) and
downgrade violations to `"error"` rows rather than raising.

Human table (default): reuse the `_table` style —
`SOURCE\tSTATE\tFORMAT\tWARNINGS` rows, sorted by key.

Exit code: 0 always when the sweep itself ran (individual `unavailable`/
`error` rows are data, not failures) — mirrors `hosts`. Document in the
epilog from plan 029.

**Verify**: `sources` on this dev machine → exit 0, 17 rows, plausible states;
`sources --json | python3 -m json.tool` parses.

### Step 3: Tests

`tests/unit/test_reader_sources.py`:

1. Sweep over fixtures: point one source at a real fixture via env-free
   means — probes use default roots, so instead patch: use
   `unittest.mock.patch` on one adapter's module `ADAPTER.probe` to return a
   crafted `CapabilityReport` (supported) and another to raise
   `DiagnosticError("E_UNSAFE_PATH")`; assert rows: supported, error-with-code,
   and the untouched majority `unavailable`-or-real (assert presence of all 17
   keys, not specific states for unpatched ones — the dev machine may have
   real stores).
2. One adapter raising bare `Exception` → its row is `"error"`, sweep exit
   still 0, other rows intact.
3. Closed parser: unknown flag → exit 2.
4. JSON schema shape: keys exactly as specced (sorted, compact).
5. Security: the sweep run passes under the PATH-shim isolation harness —
   extend nothing; just confirm `tests/security` still passes (the shims are
   global; if plan 039 landed, the widened net covers this free).

**Verify**: new module passes; full suite + security suite OK.

### Step 4: README one-liner (optional)

Add `portable-resume sources` to the README quick-start installed block ("see
which local agents have resumable context"). Skip if plan 033's structure
hasn't landed; note the skip.

### Step 5: Full gates

**Verify**: suite, smoke matrix, `self_verify.py`, `check_secrets.py` all 0.

## Test plan

As Step 3 (≥ 5 cases). Pattern: self-check's existing tests (find via
`grep -rln "self-check\|self_check" tests/unit | head`).

## Done criteria

- [ ] `sources` lists all enabled sources with per-source state; one broken adapter cannot abort the sweep (test-pinned)
- [ ] Closed parser semantics (unknown args → exit 2 diagnostic)
- [ ] No adapter files modified; no source CLI invoked (security suite green)
- [ ] Schema `portable-resume/sources-v1` stable-sorted compact JSON
- [ ] Full suite + gates green; `plans/README.md` updated

## STOP conditions

- A real probe on the dev machine takes > ~2 s or reads unbounded data
  (probe contract violated by some adapter) — report the adapter; do not add
  timeouts/threads here.
- `CAPABILITY_STATES` contains states not listed in Step 2's schema — extend
  the schema enum to the real set (that is fine), but if states carry
  path-like content anywhere in `CapabilityReport.warnings`/`format_id`,
  STOP: nothing path-like may reach output.
- Test 1's patching approach fights the adapter loading mechanism
  (`_load_adapter` re-imports modules) — report the observed structure; a
  registry-level injection point would be a src/ change needing sign-off.

## Maintenance notes

- This is the foundation for the deferred cross-source `list` (needs a
  multi-source envelope decision) and for request-v2 discovery
  (DIRECTION-04) — both consume `sources_report`'s sweep loop.
- Reviewer: confirm no output field can carry recovered text or local paths;
  states/format-ids/warning-codes only.
- New sources inherit coverage automatically (sweep iterates
  `enabled_source_keys()`).
