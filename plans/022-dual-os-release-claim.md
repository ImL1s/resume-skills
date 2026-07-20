# Plan 022: Formal dual-OS release claim packet (CI ≠ claimed)

> Drift: `git diff --stat bc7baf0..HEAD -- docs/STATUS.md docs/evidence-summary.md .github/workflows README.md CHANGELOG.md`

## Status

- **Priority**: P3
- **Effort**: S–M
- **Risk**: LOW
- **Depends on**: none (CI already Ubuntu+macOS)
- **Category**: direction
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

CI already runs deterministic gates on Ubuntu and macOS, but STATUS honestly says dual-OS **release claim not claimed**. Marketing/README limitations still warn. A formal packet (workflow run URLs + self_verify artifacts + tag) closes the honesty gap without lying about host UI.

## Current state

- `.github/workflows/ci.yml` — dual OS
- STATUS: dual-OS release claim not claimed
- No release workflow / CD

## Scope

**In scope**: docs process + optional `workflow_dispatch` release checklist; STATUS language when criteria met  
**Out of scope**: Auto PyPI publish; host UI claims

## Steps

### Step 1: Define claim criteria in STATUS or RELEASE.md

Claim allowed only when:

1. Tag `vX.Y.Z` exists
2. CI green on ubuntu-latest **and** macos-latest for that commit SHA
3. `self_verify.py` + `check_secrets.py` outputs archived (gist/actions artifact/log link)
4. Explicit human sign-off line in evidence-summary

### Step 2: Add short RELEASE checklist doc

`docs/release-claim.md` with copy-paste commands.

### Step 3: Only after criteria: update STATUS

Change dual-OS row to claimed with links. Keep host UI not-run.

**Verify**: docs pass secrets gate; provenance tests still ok.

## Done criteria

- [ ] Written criteria + checklist
- [ ] STATUS only flips when links present (executor may leave TODO if no tag yet)
- [ ] README DONE or partial DONE with checklist only

## STOP conditions

- Do not claim dual-OS solely because workflow file exists

## Maintenance notes

Re-claim each release tag; do not inherit previous claim automatically.
