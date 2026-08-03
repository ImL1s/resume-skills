# #209 — Platform-family honesty plan (not “implement all OS”)

**Primary issue:** [#209](https://github.com/ImL1s/resume-skills/issues/209)  
**Type:** documentation / checklist / evidence hygiene  
**PR title pattern:** `docs(platform): #209 honesty <short-slug>`

---

## Agent brief (copy to low model)

```text
You are working on #209 umbrella honesty ONLY.

GOAL
- Keep the platform contract honest: verified vs not-run families.
- Never implement “all OS support” in one PR.
- Never mark WSL2 / musl-only / FreeBSD-BSD as verified without real runners.

MUST DO
1. Read docs/STATUS.md platform table and issue #209 body rules.
2. Update checklist only when merged code + current evidence exist.
3. When #125 Phase 7 lands, update Windows native mutating row to verified
   with CI URL — still leave WSL2/musl/BSD as not-run unless evidence exists.
4. Forbid STATUS language that groups #205–#209 as all closed.

MUST NOT DO
- Fake green CI for missing runners.
- Close #209 while #125 open (unless maintainer redefines #209 scope in writing).
- Close #209 while WSL2/musl/BSD remain required-and-not-run under current
  issue definition.
- Implement Windows install here (that is #125 phases).

DoD for a honesty-only PR
- [ ] STATUS/table accurate
- [ ] not-run families remain not-run without runners
- [ ] #209 stays open unless explicit maintainer close criteria met
```

---

## Current family posture (template — refresh from STATUS when editing)

| Family | Typical posture |
|--------|-----------------|
| Ubuntu (`ubuntu-latest`) | verified (suite / readers) |
| macOS (`macos-latest`) | verified (suite / readers) |
| Windows native (`windows-latest`) | read-only verified; mutating fail-closed until #125 Phase 7 |
| WSL2 | **not-run** |
| musl-only | **not-run** |
| FreeBSD / BSD | **not-run** |

## Allowed #209 PR units (atomic)

1. **Refresh STATUS table** after a real CI change (links only).  
2. **Document how to add a runner** (WSL2/musl/BSD) without claiming verified.  
3. **Fix overclaim wording** found in README/host-support.  
4. **After #125 Phase 7:** update Windows mutating row only.

## Forbidden

```text
❌ "Full cross-platform support complete"
❌ Closing #209 because Windows lock primitive landed
❌ Closing #209 because Ubuntu+macOS+Windows read-only CI is green
❌ Marking WSL2 verified from ordinary Linux CI
```

## Verification (docs PR)

```bash
# any OS
rg -n "not-run|verified|#125|#209" docs/STATUS.md
# ensure no "#205–#209" bulk-closed language
rg -n "205–#209|#205-#209" docs/STATUS.md && exit 1 || true
```

## Relationship to #125

- #125 owns Windows **mutating install productization**.  
- #209 owns **umbrella honesty** across families.  
- Completing #125 Phase 7 is **necessary but not sufficient** to close #209 under the current issue text (WSL2/musl/BSD still not-run).

## Done when (honesty PR)

- [ ] Docs accurate; no fake verified rows  
- [ ] Issue #209 comment summarizing still-open residuals  

## Close #209 only if

Maintainer rewrites scope **or** every required family has real evidence — not by agent assumption.
