# Plan 018: Add AGENTS.md and fix provenance / STATUS doc honesty

> Drift: `git diff --stat bc7baf0..HEAD -- AGENTS.md docs/STATUS.md docs/source-formats.md docs/superpowers/plans docs/evidence-summary.md`

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Agents (and humans) lack a single project instruction file: clean-room rules, verify commands, live UI claim discipline, and fixture synthetic requirements are scattered. Fixture `provenance_ref` fragments point at headings that do not exist in `source-formats.md`. STATUS upper table still reads “live 0” packaging-centric while 0.2.0 shipped partial source live. Superpowers plans still show open checkboxes for shipped work — agents re-do completed tasks.

## Current state

- No root `AGENTS.md` / `CLAUDE.md`
- Fixtures reference `docs/source-formats.md#claude-claude-jsonl-v1` etc.
- `docs/source-formats.md` has foundation/provenance sections without per-format `###` anchors; `#foundation-only` text may not match heading slug
- `docs/STATUS.md` dated 2026-07-20; CHANGELOG 0.2.0 is 2026-07-21
- `docs/superpowers/plans/2026-07-20-*.md` incomplete checkboxes

## Scope

**In scope**:
- Create `AGENTS.md` (and optionally one-line pointer from CONTRIBUTING)
- Fix `docs/source-formats.md` anchors + fixture refs or registry fragment validation
- Update `docs/STATUS.md` done table for source live partial
- Mark superpowers plans superseded / check completed tasks
- Optional: header on historical `docs/audit-*.md` “point-in-time”

**Out of scope**: Rewriting SECURITY threat model; implementing host UI

## Steps

### Step 1: Write AGENTS.md

Must include:

- Product: inert handoff, not live restore; stdlib-only runtime
- Verify: `python3 scripts/self_verify.py`, `check_secrets.py`, unittest with `PYTHONPATH=src`
- Never copy `~/.grok/bundled/skills/**` into this tree
- Honesty: Host UI / dual-OS release claims stay `not-run` / `not claimed` until evidence
- Fixtures: `synthetic: true`; no real home absolute paths
- Point to STATUS, SECURITY, install-hosts

### Step 2: Provenance anchors

Either:

- Add `### claude-claude-jsonl-v1` (etc.) for each format_id used in fixtures, **or**
- Point all fixtures at a single `#source-format-evidence-registry` and list format ids there

Strengthen `fixture_manifest.py` to resolve markdown headings if cheap.

Fix foundation-only anchor self-description mismatch.

### Step 3: STATUS + plans archive language

- Date STATUS to plan day; add row: source live list/show partial for six sources
- Keep host UI not-run clear
- Superpowers plans: top banner “Superseded by v0.2.0 — remaining: host UI, dual-OS claim, cursor bubbles”

### Step 4: Verify

```bash
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
# especially provenance / public policy tests
```

## Done criteria

- [ ] AGENTS.md present and accurate
- [ ] Fixture provenance fragments resolve
- [ ] STATUS reflects 0.2.0 source live without claiming host UI
- [ ] Suite green; README DONE

## STOP conditions

- Changing STATUS language would imply host UI live — do not

## Maintenance notes

Keep AGENTS.md short; link deep docs rather than duplicating install-hosts.
