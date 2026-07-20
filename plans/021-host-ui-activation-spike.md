# Plan 021: Spike — Host UI live activation evidence (design, not full 36-cell claim)

> Drift: `git diff --stat bc7baf0..HEAD -- docs/STATUS.md docs/host-support.md src/portable_resume/install/catalog.py src/portable_resume/install/transaction.py`

## Status

- **Priority**: P2 (product)
- **Effort**: L (spike S–M for design + first host; full matrix L)
- **Risk**: MED
- **Depends on**: none for spike; packaging already 36/36
- **Category**: direction
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

The product promise is 6×6 skill packages users invoke **inside** hosts. Today packaging is proven; STATUS/README maturity still **Host UI 0 / not-run**. Without a defined smoke protocol, “usable” cannot be claimed and matrix_report hardcodes `live_cells_supported: 0`.

This is a **design/spike plan**, not “implement all 36 cells in one PR”.

## Current state

- `docs/STATUS.md`: Live host UI activation **not-run**
- `matrix_report` in `transaction.py` ~597+: `live_supported: False`, `live_evidence: "not-run"`
- `docs/install-hosts.md` / `host-support.md`: per-host activation notes, live UI column not-run
- Catalog caveats state live UI not-run

## Scope

**In scope**:
- Write `docs/host-ui-smoke.md` (or section in STATUS) defining protocol
- Optionally split matrix report fields: `packaging` vs `source_live` vs `host_ui_live` (honest schema)
- Execute smoke for **1–2 priority hosts** only if operator provides the running host environment; record evidence table
- Do **not** flip global “live 36” without evidence rows

**Out of scope**: Automating all hosts in CI without display/TUI; claiming dual-OS release (plan 022)

## Steps

### Step 1: Define cell evidence schema

For each (host, source):

| Field | Values |
|-------|--------|
| host_version | string |
| activation | slash command / skill picker path used |
| result | pass / fail / blocked |
| notes | short |
| date | ISO date |

### Step 2: Document minimal human procedure

Per host from `docs/install-hosts.md`:

1. `install-resume-skills install --host X --scope project --project $PWD`
2. Open host, invoke `/resume-claude` (or host grammar)
3. Confirm host runs installed `run_reader.py` (not source CLI)
4. Confirm handoff banner appears; treat as untrusted

### Step 3: Schema honesty (code optional)

If touching `matrix_report`, introduce explicit fields rather than overloading `live_supported`. Keep packaging assertion in self_verify. **Do not** set host_ui live true without evidence file.

### Step 4: First evidence batch (operator-dependent)

Priority suggestion: Claude Code + Grok Build (skill dirs well documented). Record results in `docs/evidence-summary.md` or STATUS appendix.

**Verify** (docs only):

```bash
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest tests.unit.test_hosts_catalog tests.security.test_provenance_policy -q
```

## Done criteria

- [ ] Written smoke protocol exists
- [ ] Matrix/docs distinguish packaging vs host UI
- [ ] At least a template evidence table; 0+ filled rows if hosts available
- [ ] No false live claims
- [ ] README DONE (or BLOCKED if no host access — note reason)

## STOP conditions

- Operator forbids live host automation — deliver protocol doc only and mark DONE for spike portion
- Host requires network/login that cannot be documented offline — mark blocked for that host

## Maintenance notes

Full 36-cell completion is multi-session; re-run smoke when host major versions bump.
