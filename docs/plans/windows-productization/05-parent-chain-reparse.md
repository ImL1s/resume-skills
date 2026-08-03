# Phase 5 — Parent-chain reparse defenses (#125)

> **HISTORICAL (archive):** #125 Phases 1–7 are **COMPLETE** on main (Policy B lifted; PR #228). Do **not** re-implement this slice or treat Policy B fail-closed product install as current residual work. See [`INDEX.md`](INDEX.md).

**Primary issue:** [#125](https://github.com/ImL1s/resume-skills/issues/125)  
**Depends on:** Phase 4 (relative mutations exist) **or** explicit coordination if hardening must land with Phase 4 — prefer **after** Phase 4 merge.  
**PR title pattern:** `feat(platform): #125 Phase 5 parent-chain reparse defenses`

---

## Agent brief (copy to low model)

```text
You are implementing ONLY Phase 5 of Windows #125 productization.

GOAL
- Harden path acceptance so every component from volume root (or skill root)
  down to the leaf is checked for reparse/junction/symlink policy before
  mutation or lock under product-adjacent paths.
- Leaf-only checks from Phase 2 are NOT enough for product honesty.

MUST DO
1. Inventory existing _check_reparse_components / path validators.
2. Ensure parent chain of lock path, support dirs, stage dirs, and mutation
   targets is validated without silently following reparse out of root.
3. Adversarial tests: reparse in middle of path; mount-point style redirections
   where creatable in CI; expect fail-closed + no write outside root.
4. Product Policy B remains fail-closed for public install.

MUST NOT DO
- Lift Policy B.
- Close #125.
- Soften Phase 2 leaf fail-closed.

DoD
- [ ] Documented parent-chain algorithm in code comments or short research note
- [ ] Tests on windows-latest covering mid-path reparse rejection
- [ ] Product install still fail-closed
```

---

## Must-do

- Walk components from accepted skill root to target; each component type allowed only if policy says so (typically: no unexpected reparse that escapes root).  
- Shared helper used by lock path setup, mkdirs, unlink, replace.  
- Fail closed with stable diagnostics (`unsafe_path` / `E_INSTALL_UNSUPPORTED_PLATFORM` as appropriate).

## Must-not-do

- Product enablement.  
- Claiming all reparse tags “supported” without tests.

## Suggested files

- `src/portable_resume/platform_fs/windows.py`  
- `tests/unit/test_windows_parent_chain_reparse.py`  
- Optional: `docs/research/2026-*-windows-parent-chain-reparse.md` (short)

## Acceptance tests

1. Mid-path junction → reject before write.  
2. Clean path under root → still works with Phase 4 mutations.  
3. Outside root unchanged after rejection.  
4. Policy B residual contract still green.

## Windows verification

```powershell
python -c "import os; assert os.name=='nt'"
python -m pytest tests/unit/test_windows_parent_chain_reparse.py tests/unit/test_windows_relative_mutations.py -v --tb=short
```

## Done when

- [ ] Merged; STATUS Phase 5; #125 open; product fail-closed  

## STOP

If Windows CI cannot create junctions in the sandbox, document limitation and use the strongest available adversarial fixture; do not mark “fully proven” without evidence.
