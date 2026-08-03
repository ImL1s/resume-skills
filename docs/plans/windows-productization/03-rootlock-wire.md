# Phase 3 — Wire RootLock to Win32 exclusive lock (#125)

**Primary issue:** [#125](https://github.com/ImL1s/resume-skills/issues/125)  
**Depends on:** Phase 1–2 on `main` (PR #216, #219). **Not** on Phase 4–7.  
**PR title pattern:** `feat(platform): #125 Phase 3 wire RootLock to Win32 exclusive lock`

---

## Agent brief (copy to low model)

```text
You are implementing ONLY Phase 3 of Windows #125 productization.

GOAL
- Make install.RootLock on Windows use the existing
  WindowsFilesystemBackend.acquire_exclusive_lock (CreateFileW+LockFileEx)
  for exclusive cross-process locking, instead of fcntl (POSIX-only).
- Product install/uninstall/recover CLI paths MUST STILL fail closed via
  require_mutating_install_platform() when os.name == "nt".

MUST DO
1. Read:
   - docs/plans/windows-productization/INDEX.md
   - src/portable_resume/install/transaction.py (class RootLock)
   - src/portable_resume/platform_fs/windows.py (acquire_exclusive_lock)
   - src/portable_resume/platform_fs/api.py / get_filesystem_backend()
2. On Windows only, RootLock must:
   - Resolve lock path under support state (same LOCK_NAME layout as POSIX).
   - Acquire exclusive OS lock via backend.acquire_exclusive_lock.
   - Release on __exit__ / context cancel; no leaked handles.
   - Map busy / conflict to existing diagnostics (E_INSTALL_BUSY / conflict)
     without inventing silent success.
3. Keep require_mutating_install_platform() raising E_INSTALL_UNSUPPORTED_PLATFORM
   for product entry points (execute install, uninstall, recover) on nt.
4. If RootLock is still gated by require_mutating_install_platform at __enter__,
   introduce a carefully named internal path used ONLY by tests / Phase 6 harness
   OR split "platform exclusive lock acquire" so product CLI still hits Policy B
   first — product user path must not create install trees on Windows yet.
5. Add Windows unit/integration tests that run only when os.name == "nt":
   - two processes or sequential exclusive: second acquire fails/busy
   - lock released after context exit
   - Policy B product install still raises E_INSTALL_UNSUPPORTED_PLATFORM
     and creates no destination root (reuse residual no-side-effect patterns
     from tests/unit/test_issue_125_residual_contract.py)

MUST NOT DO
- Do NOT remove Policy B for product install/uninstall/recover.
- Do NOT set relative_mutations=True.
- Do NOT implement mkdirs_beneath/unlink_beneath/replace_beneath for real.
- Do NOT close #125 or #209.
- Do NOT claim dual-OS mutating install complete.
- Do NOT use mock os.name as sole Windows evidence.

DoD
- [ ] RootLock exclusive lock path on real Windows uses Win32 primitive
- [ ] No fcntl import required on Windows success path
- [ ] Product Policy B still fails closed with zero install side effects
- [ ] pytest green on windows-latest for new tests
- [ ] docs/STATUS.md notes Phase 3 landed; #125 still OPEN
- [ ] PR body links windows-latest CI run URL

VERIFY ON WINDOWS (required)
python -c "import os; assert os.name=='nt'"
python -m pytest tests/unit/test_platform_fs.py tests/unit/test_install_windows_platform_gate.py tests/unit/test_issue_125_residual_contract.py -q
# plus new RootLock Windows tests file you add
python -m pytest tests/unit/test_rootlock_windows.py -q
```

---

## Must-do (detail)

| Item | Notes |
|------|--------|
| Backend selection | Use existing `get_filesystem_backend()` / Windows backend; no second ctypes stack |
| Lock path | Same control layout: `.portable-resume/.state/<lock>` under root |
| Hold duration | Lock held for full RootLock context (same as POSIX intent) |
| Alias contention | Case-insensitive path aliases should contend on same physical file when possible; document limits |
| Error mapping | Busy → `E_INSTALL_BUSY`; unsafe reparse leaf already fail-closed in Phase 2 |

## Must-not-do

- Lift `require_mutating_install_platform` for public CLI.  
- Enable relative mutations.  
- Parent-chain product traversal rewrite (Phase 5).  
- Full install transaction on Windows.

## Suggested file touches

- `src/portable_resume/install/transaction.py` — `RootLock` Windows branch  
- `src/portable_resume/platform_fs/windows.py` — only if small helpers needed for RootLock path creation under test hooks  
- `tests/unit/test_rootlock_windows.py` (new; skip if not `nt`)  
- `docs/STATUS.md` — Phase 3 note  

## Acceptance tests

1. **Real lock:** On Windows, acquiring exclusive RootLock (via internal/test API if product still gated) blocks a second concurrent exclusive attempt.  
2. **Release:** After context exit, second acquire succeeds.  
3. **Policy B product:** `require_mutating_install_platform()` still raises on `nt`; public install entry still no side effects.  
4. **No fcntl:** Windows success path must not depend on `import fcntl`.

## Windows verification commands

```powershell
python -c "import os,sys; print(os.name, sys.platform); assert os.name=='nt'"
python -m pytest tests/unit/test_rootlock_windows.py tests/unit/test_issue_125_residual_contract.py -v --tb=short
```

CI: ensure new tests run under existing `windows-latest` job (not skipped incorrectly).

## Done when

- [ ] Merged PR with windows-latest green  
- [ ] STATUS: Phase 3 landed, product install still fail-closed, #125 open  
- [ ] Next agent may start Phase 4 only after merge  

## STOP

If you cannot hold a real OS lock without lifting product Policy B, stop and ask maintainer — do not fake green with mocks.
