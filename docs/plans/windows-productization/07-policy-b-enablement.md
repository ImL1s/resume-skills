# Phase 7 — Policy B enablement gate (final #125 product slice)

**Primary issue:** [#125](https://github.com/ImL1s/resume-skills/issues/125)  
**Depends on:** Phases 3–6 **all** merged with windows-latest evidence.  
**PR title pattern:** `feat(platform): #125 Phase 7 enable Windows mutating install (Policy B lift)`

---

## Agent brief (copy to low model)

```text
You are implementing ONLY Phase 7 — the ONLY slice allowed to lift Policy B.

GOAL
- Allow product install/uninstall/recover on Windows when the platform is ready,
  by changing require_mutating_install_platform() (or equivalent) so os.name=="nt"
  no longer unconditional fail-closed — ONLY if the checklist below is all true.
- If any checklist item fails, ABORT and leave Policy B in place.

CHECKLIST (all required before changing the gate)
[ ] Phase 3 RootLock uses Win32 exclusive lock on real Windows
[ ] Phase 4 relative_mutations True with reparse-safe mutations
[ ] Phase 5 parent-chain reparse defenses tested on windows-latest
[ ] Phase 6 adversarial product-path suite green on windows-latest (URL)
[ ] Public docs updated (host-support / STATUS) for Windows mutating support
[ ] No debug bypass left that weakens security
[ ] Maintainer explicitly OK in PR (human) — if no human, keep fail-closed

MUST DO
1. Paste checklist with links to PRs and CI runs in PR body.
2. Lift gate carefully; keep fail-closed for truly unsupported FS cases.
3. Enable windows-latest installed-runner / smoke paths previously skipped
   by design — only those that are now honest.
4. Full relevant pytest + smoke on windows-latest.
5. Close #125 ONLY after merge + evidence; never before.

MUST NOT DO
- Lift gate without Phase 6 evidence.
- Close #209 as a side effect.
- Claim WSL2/musl/BSD verified.
- Silent partial enablement.

DoD
- [ ] Product install works on windows-latest real nt
- [ ] Adversarial suite still green without test-only bypass as sole path
- [ ] STATUS: Windows mutating install verified (with run URL)
- [ ] #125 closed with implementation notes (not deferred)
```

---

## Must-do

1. **Evidence table in PR** linking Phase 3–6 PRs + CI.  
2. Change `require_mutating_install_platform` (and any “skip mutating smoke on Windows” CI flags).  
3. Regression: reparse attacks still fail closed.  
4. Update `docs/host-support.md`, `docs/STATUS.md`, `docs/evidence/*` as needed.  
5. Close #125 with comment listing evidence.

## Must-not-do

- Close #209.  
- Mark non-run families verified.  
- Skip residual contract tests — rewrite them for new expected behavior.

## Acceptance tests

1. On windows-latest: real product install → files + journal + lock behavior.  
2. Uninstall / recover smoke.  
3. Second concurrent install → busy.  
4. Junction escape still blocked.  
5. Ubuntu/macOS install paths still green (no regression).

## Windows verification

```powershell
python -c "import os; assert os.name=='nt'"
python -m pytest tests/unit tests/integration -q --tb=line
# plus project smoke / installed-runner commands used by CI for Windows
```

## Done when

- [ ] Policy B lifted with evidence  
- [ ] #125 closed as implemented  
- [ ] #209 remains open unless maintainer separately accepts umbrella criteria  

## STOP

If any Phase 3–6 evidence missing → **do not merge enablement**. Re-open incomplete phase instead.
