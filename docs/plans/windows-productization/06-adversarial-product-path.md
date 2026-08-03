# Phase 6 — Adversarial product install path evidence (#125)

> **HISTORICAL (archive):** #125 Phases 1–7 are **COMPLETE** on main (Policy B lifted; PR #228). Do **not** re-implement this slice or treat Policy B fail-closed product install as current residual work. See [`INDEX.md`](INDEX.md).

**Primary issue:** [#125](https://github.com/ImL1s/resume-skills/issues/125)  
**Depends on:** Phases 3–5 merged.  
**PR title pattern:** `test(platform): #125 Phase 6 adversarial Windows product-path evidence`

---

## Agent brief (copy to low model)

```text
You are implementing ONLY Phase 6 of Windows #125 productization.

GOAL
- Prove on real windows-latest that the *transaction body* (install / uninstall /
  recover) can run under RootLock + relative mutations correctly when the
  platform gate is bypassed ONLY in a controlled test harness —
  OR implement a documented internal entry used solely by tests/CI.
- Public product CLI must STILL fail closed with Policy B until Phase 7.

MUST DO
1. Build adversarial tests on windows-latest covering:
   - successful dry-run (no mutation)
   - successful locked install into temp root via harness (if gate bypass is test-only)
   - uninstall / recover paths with journal
   - crash/busy/conflict diagnostics where feasible
   - reparse attack attempts during install
2. Explicitly assert public CLI / require_mutating_install_platform still blocks
   product entry without harness.
3. Wire CI job so these tests run on windows-latest (not skipped).
4. Capture run URL in PR and STATUS.

MUST NOT DO
- Flip Policy B for production users (that is Phase 7).
- Close #125.
- Call Ubuntu logs Windows evidence.
- Skip side-effect assertions.

DoD
- [ ] windows-latest adversarial product-path suite green
- [ ] Public Policy B still fails closed with zero side effects
- [ ] Evidence URLs in PR + STATUS
- [ ] #125 remains OPEN until Phase 7
```

---

## Must-do

| Track | Content |
|-------|---------|
| Public gate | Still `E_INSTALL_UNSUPPORTED_PLATFORM` for normal install API on `nt` |
| Harness | Test-only bypass **or** inject fake platform allow-list used only in tests — never default True in production |
| Matrix | Prefer small deterministic skill payload, not full 306 matrix on every PR if too slow; document |
| Side effects | Before/after tree hashes for fail paths |

## Must-not-do

- Shipping Phase 7 early “because tests pass with bypass always on”.  
- Leaving a debug env var that end users can set to unlock install without docs/review.

## Suggested files

- `tests/integration/test_windows_install_adversarial.py` (or under `tests/unit` if lighter)  
- `.github/workflows/ci.yml` — ensure job includes new tests  
- `docs/STATUS.md` / evidence notes  

## Acceptance tests

1. Public install on Windows → unsupported + no root created.  
2. Harness install under temp root → payload + control files as designed; lock held.  
3. Concurrent second install → busy/conflict.  
4. Recover after incomplete journal (if fixtures exist for POSIX, port carefully).

## Windows verification

```powershell
python -c "import os; assert os.name=='nt'"
python -m pytest tests/integration/test_windows_install_adversarial.py -v --tb=short
python -m pytest tests/unit/test_issue_125_residual_contract.py -q
```

## Done when

- [ ] CI windows-latest URL recorded  
- [ ] Maintainer can decide Phase 7 with evidence in hand  
- [ ] #125 still OPEN  

## STOP

If harness requires permanent production unlock, stop — redesign. Phase 6 is evidence, not enablement.
