# Plan 016: Expand runtime secret redaction shapes (best-effort, tested)

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/sanitize.py tests/unit/test_sanitize_handoff.py SECURITY.md`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 008 optional (keep CI/runtime patterns coherent)
- **Category**: security
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

This tool **reads** conversation stores that often contain credentials and prints them into handoff/json. Current patterns cover AKIA, GitHub tokens, `sk-…`, Bearer, and label=value secrets. High-value shapes (PEM private keys, Slack `xox*`, common cloud API key prefixes, optional JWT) still pass through. SECURITY.md already says best-effort — this plan narrows residual, not “complete DLP”.

## Current state

```python
# sanitize.py:15-21
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*"),
    re.compile(r"(?i)(\b(?:password|passwd|api[_-]?key|access[_-]?token|token|secret)\s*[:=]\s*)[^\s,;]+"),
)
```

Never put real secrets in tests — use synthetic shapes only.

## Scope

**In scope**: `sanitize.py`, `tests/unit/test_sanitize_handoff.py`, brief SECURITY.md residual list update  
**Out of scope**: ML-based DLP; encrypting handoff; changing banner text

## Steps

### Step 1: Add patterns (high precision first)

Add with unit tests for each:

1. PEM private key header/footer blocks → redact interior
2. Slack token shape `xox[baprs]-…` (synthetic)
3. Google-like `AIza…` long keys if precision OK
4. Optional JWT: three base64url segments — **only if** false-positive rate acceptable on sample fixture transcripts; otherwise document skip

Align with `scripts/check_secrets.py` PRODUCT_FORBIDDEN / SENSITIVE where sensible.

### Step 2: Preserve warning code

Continue emitting `W_METADATA_REDACTED` on any substitution.

### Step 3: False-positive guard

Run sanitize over existing fixtures’ expected non-secret technical strings; fix over-redaction.

**Verify**:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_sanitize_handoff -q
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/check_secrets.py
```

## Done criteria

- [ ] At least PEM + Slack shapes redacted in unit tests
- [ ] SECURITY.md residual list updated honestly
- [ ] Suite + secrets gate green; README DONE

## STOP conditions

- Pattern would redact common git SHAs or UUIDs — refine or drop that pattern
- Never commit live credential material

## Maintenance notes

Reviewer: watch for redaction of intentional `sk-` documentation examples in docs — docs should use obviously fake placeholders.
