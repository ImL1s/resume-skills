# Windows mutating install — Phase 1 decision (#125 residual / #209 honesty)

**Date:** 2026-08-03  
**Status:** Decision recorded. **#125 remains OPEN** (not product-complete). **#209 remains OPEN**.

## Context

Windows **read-only** product surfaces (17-source list+show fixtures, `platform_fs` backend paths, CI on `windows-latest`) are already evidenced. Product **mutating** install/uninstall/recover still fail closed under **Policy B** (`require_mutating_install_platform` → `E_INSTALL_UNSUPPORTED_PLATFORM` on `os.name == "nt"`) before support/lock creation. That gate must not be removed early.

Related: [Issue #125](https://github.com/ImL1s/resume-skills/issues/125), [Issue #29](https://github.com/ImL1s/resume-skills/issues/29) (Policy B gate **done**), [Issue #209](https://github.com/ImL1s/resume-skills/issues/209) (platform-family umbrella).

## Options for #125

| ID | Approach | Pros | Cons |
|----|----------|------|------|
| **A** | **Full implement now** — wire `RootLock` + full transaction mutation on Windows (reparse-safe handles, atomic replace, crash recovery, ACL policy) in one go | Matches full “done” criteria | XL multi-PR security surface; high risk of incomplete unlock / ambient path races; issue forbids dropping fail-closed without a real complete path |
| **B** | **Phased foundation (chosen)** — implement a Win32 **exclusive lock primitive** (`LockFileEx`) under `platform_fs`; keep product install/uninstall/recover **fail-closed** until RootLock/transaction fully use the primitive and pass `windows-latest` adversarial tests | Microsoft-recommended exclusive lock; stdlib/`ctypes` only; honest capabilities; does not weaken product gate; unblocks later wiring | #125 stays **open**; users still cannot mutate-install on Windows |
| **C** | **Honesty-only** — STATUS/tests wording only, no new Win32 primitive | Lowest risk | No engineering progress toward #125 |

## Decision (chosen: **B**)

**Phase 1 — exclusive-lock primitive under a fail-closed product gate.**

1. Implement `WindowsFilesystemBackend.acquire_exclusive_lock` via `CreateFileW` + `LockFileEx` / `UnlockFileEx` (ctypes, stdlib-only). Prefer non-blocking exclusive flags (`LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY`). A lock *file’s existence* alone is not a lock.
2. Advertise `exclusive_locking` / `handle_locking` capabilities **only when** the lock path is implemented and tested; do not claim product install support from capability bits alone.
3. **Do not** change `require_mutating_install_platform()` — install/uninstall/recover remain Policy B fail-closed.
4. **Phase 2 (future, not this decision’s ship):** wire `RootLock` / transaction paths to the primitive; reparse-safe relative mutation; evaluate `ReplaceFileW` / same-volume replace; adversarial tests on real `windows-latest`. Only then may product fail-closed be reconsidered.

Until Phase 2 lands with evidence, **do not claim** dual-OS mutating install complete, and **do not** close #125.

## #209 — platform family honesty

| Family | Claim posture |
|--------|----------------|
| Ubuntu (GitHub `ubuntu-latest`) | Readers + CI **verified** (read-only / suite surfaces) |
| macOS (GitHub `macos-latest`) | Readers + CI **verified** |
| Windows native (`windows-latest` / real `nt`) | Readers + CI **verified** for **read-only** surfaces; mutating install **fail-closed** residual (#125) |
| WSL2 | **not-run** (no dedicated runner evidence; no fake green) |
| musl-only | **not-run** |
| FreeBSD / BSD | **not-run** |

**Reject** inventing green CI for unavailable families. **Reject** closing #209 while #125 and unavailable families remain open / not-run.

## Out of scope (this phase)

Full Windows `RootLock` product path, install transaction enablement, `ReplaceFileW` durability claims, ACL ownership model, live resume / host UI / marketplace, inventing WSL2/musl/BSD runners.

## Citations

- Microsoft Learn — [`LockFileEx`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex) (`fileapi.h`)
- Project **Policy B** — `require_mutating_install_platform` in `src/portable_resume/install/transaction.py`; product docs in `docs/host-support.md` and `docs/evidence/native-activation-policy-v1.md`
- Existing Windows read path / reparse checks — `src/portable_resume/platform_fs/windows.py` (`CreateFileW` + reparse-aware opens)
- Read-only Windows tip evidence (unchanged claim): [Actions run 30753320460](https://github.com/ImL1s/resume-skills/actions/runs/30753320460)

## Disposition

| Item | Posture |
|------|---------|
| #29 Policy B gate | **Done** (fail-closed before support/lock) |
| #125 productization | **OPEN** — Phase 1 = lock primitive only; product install still unsupported |
| #209 umbrella | **OPEN** — verified families documented; WSL2/musl/BSD **not-run** |
