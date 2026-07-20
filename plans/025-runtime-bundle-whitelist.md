# Plan 025: Whitelist installed runtime package (exclude install/ from skill roots)

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/install/render.py tests/e2e/`

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (e2e installed runner is the guardrail)
- **Category**: tech-debt
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

`materialize_plan` copies the entire `portable_resume` package into each skill root’s `.portable-resume/runtime/`, including `install/` (transaction, catalog, CLI). Installed skills only need reader + adapters + core. Extra code grows attack surface narrative, package_identity churn, and install size.

## Current state

`install/render.py` ~50-62 walks `_PACKAGE_ROOT` for runtime files. E2E `tests/e2e/test_installed_runner_and_relocation.py` proves Claude host installed runner works.

## Scope

**In scope**: `render.py` whitelist/blacklist; e2e + matrix identity tests  
**Out of scope**: Changing skill markdown templates semantics

## Steps

### Step 1: Define allowlist

Include:

- `portable_resume/*.py` core modules needed by reader
- `portable_resume/adapters/**`
- `portable_resume/resources/**` if any
- Exclude: `portable_resume/install/**` (except if any module is imported by reader — **verify with grep**)

### Step 2: Grep runtime imports

```bash
rg -n 'portable_resume\.install|from \.\.install|from \.install' src/portable_resume --glob '!** /install/**'
```

Reader path must not import install. If something does, either keep that module or break the dependency first.

### Step 3: E2E

Run installed runner list/show after whitelist; matrix packaging 36 still ok; package_identity stable when only install/ changes (optional assert).

**Verify**:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
```

## Done criteria

- [ ] Installed runtime tree has no `install/` package (or only documented exceptions)
- [ ] E2E installed runner green for at least Claude host
- [ ] README DONE

## STOP conditions

- Hidden import from adapters into install — fix import graph before whitelist

## Maintenance notes

When adding core modules, ensure allowlist patterns include them; e2e will catch missing files.
