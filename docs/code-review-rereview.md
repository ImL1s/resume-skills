# Code Review Re-Review

**HEAD (claimed):** `0bdbb36` / current main  
**Scope:** Verify Important #1 (Codex zstd list degrade) + Important #2 (installer per-path force)  
**Date:** 2026-07-20  
**Mode:** Read-only verification of source; parent reported tests 153 green / check_secrets CLEAN / self_verify PASS

---

## Assessment

**Ready to merge?** **Yes**

Both previously blocking Important defects are fixed in source with correct semantics. Residual items are product-choice / process / test-gap, not ship-blockers for the claimed fixes.

---

## Claimed fixes — verification

### 1. Codex zstd list degrade (meta/cwd wrap) — **FIXED**

**File:** `src/portable_resume/adapters/codex.py` `_rollout_summary` (~414–430)

```python
compressed = path.endswith(".zst")
try:
    observation, records, warnings, provider = _read_rollout(path, root, budget)
    metadata = _session_meta(records, identifier, provider)
    cwd = canonicalize_cwd(metadata["cwd"])
except DiagnosticError as error:
    # Optional compressed provider: any structural/decode failure skips only this session
    if compressed:
        return None
    raise
```

| Prior gap | Status |
|-----------|--------|
| `_session_meta` / `canonicalize_cwd` outside degrade try | **Closed** — same try |
| `E_UNSUPPORTED_FORMAT` after decompress not degraded | **Closed** — any `DiagnosticError` on `.zst` → `None` |
| Early absence of trusted zstd | Still early-return `None` (~418–419) |
| `show()` fail-closed | Unchanged (correct) |

**Confidence:** HIGH

### 2. Installer force re-classify per-path — **FIXED**

**File:** `src/portable_resume/install/transaction.py` `execute_install` (~293–305, ~344–353)

```python
planned_backups = set(plan.backups)
...
force_with_backup=force_with_backup or rel in planned_backups,
```

| Prior gap | Status |
|-----------|--------|
| `force_with_backup or bool(plan.backups)` global widen | **Gone** — no `bool(plan.backups)` in tree |
| TOCTOU non-owned path outside plan force set | First-loop `_classify_dest` raises `E_INSTALL_CONFLICT` when not in `planned_backups` and caller flag false |
| Commit loop | Uses `planned_backups` + runtime `backups`; conflict guard retained |

**Confidence:** HIGH

---

## Remaining Critical / Important

### Critical

*None.*

### Important (non-blocking residual from prior review)

| # | Item | Severity | Blocking merge? |
|---|------|----------|-----------------|
| A | Plain Codex `.jsonl` corruption still aborts whole `list()` (intentional fail-closed asymmetry vs zstd) | Important / product | **No** — document if kept |
| B | Optional `.zst` skip still leaves `ReadBudget` consumption (flood of large/corrupt archives can starve later plain sessions) | Medium–Important edge | **No** for claimed fix; optional harden later |
| C | SECURITY process (private reporting SLA / Advisories enablement) | Process | **No** for code merge |

No new CRITICAL/HIGH confidence logic regressions introduced by these two fixes.

---

## Minor / test gaps (optional)

1. **No dedicated TOCTOU regression** for singleton `plan.backups` + second non-owned path → `E_INSTALL_CONFLICT`. Code path is correct; test would lock the invariant.
2. **No explicit decompress-ok / meta-bad `.zst` fixture** next to a good plain rollout (existing tests cover absence + corrupt payload). Code path is correct.
3. Unused `error` binding in `_rollout_summary` except clause (style only).

---

## Reasoning

- Spec for both Important items matches implementation: optional compressed list is session-local degrade through meta/cwd; installer under-lock force is per planned backup path, not global.
- Parent evidence (153 tests, secrets clean, self_verify PASS) is consistent with a non-regressing change set; this pass did not re-run the suite.
- Prior Important #3 (plain fail-closed) and process/docs items remain residual product debt, not regressions of this fix round.
- Public-safety posture unchanged: no new secret surface, no shell=True / PATH zstd, force still sandboxed under `.portable-resume/backups/`.

---

## Recommendation

**APPROVE** for merge of the Important #1 / #2 fix round.

Optional follow-ups (non-blocking): budget snapshot for degraded zstd, TOCTOU force regression test, meta-bad zstd list fixture, document plain-JSONL fail-closed asymmetry.
