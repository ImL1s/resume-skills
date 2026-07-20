# Plan 008: Align check_secrets / hygiene gates with runtime secret shapes

> Drift: `git diff --stat bc7baf0..HEAD -- scripts/check_secrets.py tests/security/test_public_tree_hygiene.py src/portable_resume/sanitize.py`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

CI secret gate uses a **narrower** `sk-` pattern than runtime sanitize (`sk-[A-Za-z0-9]{20,}` vs `sk-[A-Za-z0-9_-]{20,}`), so `sk-proj-…` shapes can land in tracked docs/code. Entire `tests/` tree skips `SENSITIVE_SHAPES`. Hygiene tests mirror the narrow pattern. Public forks inherit the gap.

## Current state

```python
# scripts/check_secrets.py:28-31
(re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-like secret shape"),
...
if under_tests:
    continue  # skips SENSITIVE_SHAPES for all tests/
```

```python
# sanitize.py:18
re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
```

## Scope

**In scope**:
- `scripts/check_secrets.py`
- `tests/security/test_public_tree_hygiene.py` (patterns must stay consistent)
- Optional short note in `SECURITY.md` or `CONTRIBUTING.md` that history is not scanned

**Out of scope**: Expanding runtime redaction catalog (plan 016); gitleaks CI install (optional mention only)

## Steps

### Step 1: Align sk- pattern

Use the same class as sanitize: `sk-[A-Za-z0-9_-]{20,}` (word-boundary if needed).

### Step 2: Tighten tests/ policy

For `tests/`:

- Still allow synthetic redaction fixtures under known paths (e.g. `tests/unit/test_sanitize_handoff.py`) via allowlist of relative paths **or** require markers like `SYNTHETIC_SECRET_SHAPE` comments.
- Still **forbid** `PRODUCT_FORBIDDEN` everywhere (already true).
- For non-allowlisted tests files, run SENSITIVE_SHAPES.

Minimal approach: allowlist only files that already embed synthetic keys for redaction tests; everything else under tests scanned.

### Step 3: Document residual

One line in SECURITY.md or CONTRIBUTING: gate scans `git ls-files` only, not git history; release checklist may run gitleaks optionally.

### Step 4: Verify

```bash
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

If gate fails on existing synthetic keys, expand allowlist carefully (paths only, no secret values in plan/commits).

## Done criteria

- [ ] sk- pattern matches sanitize breadth
- [ ] tests/ not a free-for-all for SENSITIVE_SHAPES
- [ ] Gate clean + suite green; README DONE

## STOP conditions

- Existing fixture JSONL contains shapes that are real product content — scrub or quarantine; never weaken PRODUCT_FORBIDDEN

## Maintenance notes

When adding redaction tests with synthetic keys, add the file to the allowlist in the same PR.
