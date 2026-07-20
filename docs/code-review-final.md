# Code Review Final — portable-resume-skills (public V1)

**Date:** 2026-07-20  
**Reviewer role:** Senior Code Reviewer (independent pass)  
**Range:** root commit → current `main` (portable V1)  
**Focus:** residual real bugs, OSS safety, spec compliance, latest Codex zstd list degradation  

**Local re-verify note:** This pass is static/source-evidence based. Public readiness notes claim full unittest + `self_verify` green (~153 tests). Re-run before release:

```bash
cd /Users/iml1s/Documents/mine/resume-skills
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/check_secrets.py
python3 scripts/self_verify.py
```

---

## Stage 1 — Spec compliance

| Requirement | Status | Evidence |
|---|---|---|
| Deterministic V1 bar (adapters, core, installer, tests) | **Met** | Six adapters under `src/portable_resume/adapters/`, shared core, fixture + unit/integration/security suites |
| Linux + macOS CI | **Met** | `.github/workflows/ci.yml` matrix `ubuntu-latest` + `macos-latest`, compileall, secrets, unittest, self-check, matrix, self_verify |
| No secrets / home paths in public tree | **Met (gate present)** | `scripts/check_secrets.py`, `tests/security/test_public_tree_hygiene.py`, `.gitignore` excludes `.omc/research/` |
| Honest docs (packaging 36 / live 0) | **Met** | `matrix_report()` hard-codes `live_cells_supported: 0`; README / `docs/STATUS.md` / `docs/host-support.md` align |
| SECURITY / CONTRIBUTING / CI | **Met** | Root `SECURITY.md`, `CONTRIBUTING.md`, CoC, PR/issue templates, CODEOWNERS, dependabot (GHA) |
| Safe to remain PUBLIC | **Yes** | No hardcoded runtime secrets; threat model honest; redaction best-effort disclosed; no source-CLI exec |
| Latest fix: Codex zstd corrupt list degradation | **Partial** | Degrade path exists in `_rollout_summary`; incomplete for some post-decompress failures (see Issues) |

Would the requester recognize this as the requested portable OSS V1? **Yes**, with residual product/CI-hardening gaps below (not “wrong product”).

---

## Strengths

1. **Threat-aware reader design** — no-follow path walks (`paths.require_regular_no_symlinks`), stable double-read fingerprints (`snapshot.stable_read_bytes`), private SQLite copy + `query_only`, content-free diagnostics (`DiagnosticError` rewrites messages).
2. **Process isolation** — only intentional child process is optional Codex zstd via trusted absolute paths, fixed argv, `shell=False`, empty `PATH`, timeout/output caps (`adapters/codex.py`). Source agent CLIs are never invoked; security tests shim PATH binaries.
3. **Handoff safety** — inert banner, blockquote quoting of recovered text, checklist, role/key stripping, best-effort secret shapes (`handoff.py`, `sanitize.py`).
4. **Installer containment** — claim ownership, collision refuse, journal + rollback, `commonpath` destination checks, dry-run purity snapshot, force-with-backup sandboxed under `.portable-resume/backups/`.
5. **Honesty culture** — packaging 36 / live 0 is encoded in code and docs; dual-OS *release marketing* not claimed despite CI matrix; provenance/NOTICE clean-room language.
6. **Public hygiene** — secret/path gate + hygiene unittest; research logs ignored; community files (CoC, templates, SECURITY, CONTRIBUTING) present.
7. **Latest zstd list fix direction is correct** — optional compressed provider should not take down entire `list()` when decoder is missing or a single `.zst` is garbage (Ubuntu CI realism).

---

## Issues

### Critical

*None found at high confidence for public-tree secret leakage, RCE via shell=True, or intentional source-CLI invocation.*

---

### Important

#### 1. Codex zstd list degradation is incomplete after successful decompress

**File:** `src/portable_resume/adapters/codex.py` (`_rollout_summary`, ~414–435)  
**Confidence:** HIGH  

**Issue:**  
Only exceptions raised *inside* `_read_rollout` for `.zst` paths are degraded:

```python
except DiagnosticError as error:
    if path.endswith(".zst") and error.code in {
        "E_CORRUPT_RECORD",
        "E_CAPABILITY_UNAVAILABLE",
        "E_LIMIT_EXCEEDED",
    }:
        return None
    raise
metadata = _session_meta(records, identifier, provider)  # outside try
```

Gaps:

- `E_UNSUPPORTED_FORMAT` from `_parse_lines` / outer-type checks is **not** degraded → one bad `.zst` that decompresses to non-Codex JSON still fails the **entire** `list()`.
- `_session_meta` / `canonicalize_cwd` failures after a successful decompress are **outside** the degrade `try` → same whole-list failure.
- Swallowed `E_LIMIT_EXCEEDED` on a `.zst` leaves prior `ReadBudget` consumption in place; a flood of large optional archives can starve legitimate plain rollouts of budget and surface `E_LIMIT_EXCEEDED` on good sessions.

This is residual risk for the “Ubuntu CI corrupt zstd list degradation” fix: decoder-path absence and raw corrupt compressed bytes are covered; structural garbage after decompress is not.

**Fix:**

1. Treat all post-open failures for optional `.zst` during `list()` as session-local skip (at least `E_CORRUPT_RECORD`, `E_UNSUPPORTED_FORMAT`, `E_CAPABILITY_UNAVAILABLE`; decide explicitly whether limit exceed should fail closed globally).
2. Wrap from `_read_rollout` through `_session_meta` + cwd normalize in one degrade boundary for `.zst` only.
3. Prefer a nested budget snapshot/restore for degraded optional files, or fail closed on aggregate limit (do not silently skip limit and continue).
4. Add fixture/unit cases: decompress-ok / meta-bad `.zst` beside a good plain `.jsonl`; list must return the good session.

`show` must remain fail-closed for an explicit ref (current behavior is correct).

---

#### 2. Installer re-plan widens `--force-with-backup` to every path when any backup was planned

**File:** `src/portable_resume/install/transaction.py` (~302)  
**Confidence:** HIGH  

**Issue:**

```python
force_with_backup=force_with_backup or bool(plan.backups),
```

If the plan already listed *any* backup (one non-owned conflict under force), the under-lock reclassification enables force for **all** plan files. A concurrent or TOCTOU-introduced non-owned path can then be classified as `backup`/`replace` even though it was not in the original force set. The later per-path check (`safe in backups`, ~348) is tighter, but the first loop can still expand `backups` beyond the plan.

**Fix:**  
Only force paths that were already in `plan.backups` or that the caller explicitly requested:

```python
force_with_backup=force_with_backup or (rel in plan.backups)
```

Add a regression test where `plan.backups` is a singleton and a second non-owned file appears before execute → must `E_INSTALL_CONFLICT`, not silent force.

---

#### 3. Plain Codex JSONL corruption still fails whole `list()` (product consistency)

**File:** `src/portable_resume/adapters/codex.py` (`_rollout_summary` + `list`)  
**Tests:** `tests/adapters/test_claude_codex_cursor.py` (`test_common_corrupt_bounds_busy_and_injection`)  
**Confidence:** HIGH (intentional fail-closed, residual UX/ops risk)

**Issue:**  
Required rollout format is fail-closed: one truncated/corrupt plain `.jsonl` aborts listing of all other healthy sessions. That is defensible for integrity, but mixed stores (or hostile/partial writes under `sessions/`) make `list` brittle in the field. Optional zstd is now degraded; plain is not — intentional asymmetry should be documented if kept.

**Fix (product choice):**  
- Keep fail-closed and document clearly in `docs/source-formats.md` / SECURITY residual risks, **or**  
- Degrade plain corrupt rollouts to skip + warning when other sessions remain (with care for “silent omission”).

---

#### 4. Vulnerability reporting still process-light for a public repo

**File:** `SECURITY.md` (Reporting section)  
**Confidence:** MEDIUM  

**Issue:**  
Text says prefer Advisories “when enabled” and otherwise owner contact. No fixed response SLA, no `security@` alias, and private reporting is a **GitHub repo setting** not verifiable from the tree. Acceptable for early OSS, incomplete as “GH community security setup done.”

**Fix:**  
Enable private vulnerability reporting + Security Advisories on the public repo; add expected response window (e.g. 7/90 days); optional security contact in GitHub metadata.

---

### Minor

#### 5. README maturity line understates Linux CI

**Files:** `README.md` (status / maturity), vs `docs/STATUS.md`, `.github/workflows/ci.yml`  
**Confidence:** HIGH  

README still leads with “Deterministic V1 (**macOS**)” while CI already runs Ubuntu + macOS. STATUS is more accurate (“dual-OS release claim not claimed; CI yes”). Tighten wording so packaging maturity ≠ dual-OS *release archive* claim without implying Linux is untested.

---

#### 6. `check_secrets.py` does not scan git history

**File:** `scripts/check_secrets.py`  
**Confidence:** HIGH  

Tracked-tree only. History rewrites are claimed in readiness docs; gate will not catch reintroduced historical blobs if force-pushed incorrectly later. Document one-time `gitleaks`/`git log -p` in CONTRIBUTING for maintainers.

---

#### 7. Static isolation test vs `getattr(subprocess, "Popen")`

**Files:** `tests/security/test_isolation.py` (~72–76), `src/portable_resume/adapters/codex.py` (~252)  
**Confidence:** HIGH  

Runtime forbids literal `subprocess.Popen(`; zstd uses `getattr` intentionally. Control is sound; test is string-level. Document as the sole allowed process site (SECURITY already nearly does).

---

#### 8. Windows install lock is non-exclusive

**File:** `src/portable_resume/install/transaction.py` (`RootLock`, `os.name == "nt"`)  
**Confidence:** HIGH  

Documented residual; Windows not V1 release OS. No change required for public Linux/macOS bar.

---

#### 9. Fixture metadata lag for s-cod-08

**File:** `tests/fixtures/codex/s-cod-08-malicious-zstd/fixture.json`  
**Confidence:** MEDIUM  

Manifest still `expected_operation: error` / `expected_code: 5` while unit tests expect **list** degradation to empty. Manifest is structural-only today (not execution oracle), but will confuse future harnesses. Align to list/0 or split list-vs-show fixtures.

---

#### 10. CI Python matrix is 3.12 only

**File:** `.github/workflows/ci.yml`  
**Confidence:** HIGH  

README claims 3.11+ recommended; CI only proves 3.12. Optional: add 3.11 job.

---

#### 11. Branch protection not verifiable from tree

**Confidence:** LOW (ops)  

CODEOWNERS and templates exist; actual required reviews / status checks need GitHub settings confirmation outside this repo snapshot.

---

## Recommendations

1. **Ship-blocker for “zstd list is sealed”:** complete Important #1 (degrade boundary + tests with mixed good plain + bad structural `.zst`).
2. **Ship-blocker for install force semantics:** fix Important #2 per-path force.
3. **Non-blocking OSS publish:** enable GH private vuln reporting; sync README macOS/Linux CI wording; refresh s-cod-08 fixture metadata.
4. **Keep marketing honesty:** packaging 36 / live 0 / no dual-OS release claim until archived evidence exists.
5. **Before any PyPI/CD:** add release workflow separately; do not auto-publish until live UI policy is explicit.
6. **Re-run** `self_verify.py` + `check_secrets.py` on the commit you tag.

---

## Assessment

| Question | Answer |
|---|---|
| **Safe to remain PUBLIC?** | **Yes** |
| **Ready to merge?** | **With fixes** |
| **Deterministic V1 bar (adapters/installer/docs honesty)?** | Substantially met |
| **Codex zstd CI degradation fully closed?** | **No** — partial (Important #1) |
| **Secrets/home paths in tree (static review)?** | No evidence of product leaks; gates present |

**Reasoning:**  
The public portable-resume-skills surface is thoughtfully security-scoped: local-only reads, fail-closed path/SQLite handling, inert handoff, installer ownership, dual-OS CI, and honest packaging-vs-live labeling. Nothing found that requires making the repo private.

Residual **Important** defects remain in (1) incomplete optional-zstd `list()` degradation after decompress, and (2) installer force-scope expansion under lock. Those should be fixed before treating the “latest Ubuntu CI zstd fix” and force-install semantics as fully correct. They do **not** undermine the public-safety case (no secret shipping, no source-CLI RCE path, threat model disclosed).

**Verdict mapping (reviewer checklist):** **REQUEST CHANGES** on Important #1 and #2; **COMMENT** otherwise; **APPROVE for remaining public** once those two are fixed or explicitly accepted as known limitations in STATUS.

---

## Positive reinforcement (keep doing this)

- Encoding honesty (`live_cells_supported = 0`) in code, not only markdown.
- Trusted-path zstd rather than PATH lookup.
- Content-free diagnostics that cannot leak recovered transcript text.
- Synthetic-only fixture policy + hygiene tests as merge gates.


## Follow-up fixes (after review)

- Codex `_rollout_summary`: compressed provider failures through meta/cwd now skip session only.
- Installer force: re-classify uses per-path planned backups, not global force expansion.

Re-verify: full unittest + `scripts/self_verify.py` + `scripts/check_secrets.py` green.
