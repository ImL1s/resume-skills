# Phase 4 — Reparse-safe relative mutations (#125)

**Primary issue:** [#125](https://github.com/ImL1s/resume-skills/issues/125)  
**Depends on:** Phase 3 merged (RootLock can hold Win32 exclusive lock).  
**PR title pattern:** `feat(platform): #125 Phase 4 reparse-safe relative mutations`

---

## Agent brief (copy to low model)

```text
You are implementing ONLY Phase 4 of Windows #125 productization.

GOAL
- Implement reparse-safe relative mutation primitives on WindowsFilesystemBackend:
  mkdirs_beneath, unlink_beneath, replace_beneath
  so install transaction code can mutate under a skill root without following
  junctions/symlinks out of the root.
- Product CLI install/uninstall/recover MUST STILL fail closed (Policy B)
  until Phase 7.

MUST DO
1. Read INDEX.md, Phase 3 result, windows.py mutation stubs (currently raise
   E_INSTALL_UNSUPPORTED_PLATFORM), and POSIX backend for behavioral parity intent.
2. Implement mkdirs_beneath / unlink_beneath / replace_beneath with:
   - path under accepted root only
   - no following reparse points into foreign trees
   - reject ADS, reserved device names, drive-relative junk per existing
     _validate_win32_path / reparse helpers
   - same-volume constraints for replace where required
3. Capabilities: set relative_mutations=True ONLY if all three methods are real
   and tested on Windows. If partially done, keep False and fail closed.
4. Keep require_mutating_install_platform() product gate intact.
5. Tests on real nt:
   - happy path under temp root
   - junction/symlink escape attempt fails closed
   - product install still E_INSTALL_UNSUPPORTED_PLATFORM with no side effects

MUST NOT DO
- Lift Policy B product gate.
- Close #125/#209.
- Skip parent-chain work by claiming Phase 5 done (do minimal leaf+component
  checks; full parent-chain product defenses are Phase 5).
- Use Ubuntu as Windows evidence.

DoD
- [ ] Three mutation methods work on real Windows under a temp skill root
- [ ] Escape via reparse rejected
- [ ] Product Policy B still on
- [ ] windows-latest CI green
- [ ] STATUS updated; #125 still OPEN
```

---

## Must-do

| Method | Behavior |
|--------|----------|
| `mkdirs_beneath` | Create dirs under root; fail if any component is unsafe reparse escaping root |
| `unlink_beneath` | Remove file/dir under root without following reparse out |
| `replace_beneath` | Atomic-as-possible replace within root/volume; document limits |

Prefer existing Win32 open flags already used for reads (`FILE_FLAG_OPEN_REPARSE_POINT` patterns). Stdlib/`ctypes` only.

## Must-not-do

- Enable public product install.  
- Claim crash-proof `ReplaceFileW` durability without tests.  
- Parent-chain comprehensive product path (Phase 5 owns hardening pass).

## Suggested files

- `src/portable_resume/platform_fs/windows.py`  
- `tests/unit/test_windows_relative_mutations.py` (skip if not `nt`)  
- `docs/STATUS.md`

## Acceptance tests

1. Create nested dirs under root; files visible; outside root rejected.  
2. Junction pointing outside root: mutation that would escape → diagnostic error; outside tree unchanged.  
3. `capabilities.relative_mutations is True` only with full implementation.  
4. Residual product gate tests still pass (no install side effects).

## Windows verification

```powershell
python -c "import os; assert os.name=='nt'"
python -m pytest tests/unit/test_windows_relative_mutations.py tests/unit/test_issue_125_residual_contract.py -v --tb=short
```

## Done when

- [ ] PR merged; STATUS: Phase 4 landed; product still fail-closed; #125 open  

## STOP

If reparse escape cannot be proven fail-closed, leave methods raising and `relative_mutations=False` — do not advertise True.
