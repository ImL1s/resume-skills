# Windows mutating install — Phase 2 lock-metadata fail-closed (#125 residual)

**Date:** 2026-08-03  
**Status:** Decision recorded for a **minimal Phase-2 safety slice**. **#125 remains OPEN** (not product-complete). **#209 remains OPEN**. Product `require_mutating_install_platform` stays **fail-closed** on `os.name == "nt"`.

## Context

After:

| Milestone | Evidence / scope |
|-----------|------------------|
| **PR [#216](https://github.com/ImL1s/resume-skills/pull/216) Phase 1** | Win32 exclusive-lock primitive (`CreateFileW` + `LockFileEx` / `UnlockFileEx`) under `platform_fs`; CI evidence [Actions run 30757382272](https://github.com/ImL1s/resume-skills/actions/runs/30757382272) |
| **PR [#218](https://github.com/ImL1s/resume-skills/pull/218) residual hardening** | Side-effect / document honesty for residual Windows work; CI evidence [Actions run 30758747880](https://github.com/ImL1s/resume-skills/actions/runs/30758747880) |

Phase 1 already chose **not** to enable product install/uninstall/recover on Windows (Policy B). That posture is unchanged. See [`2026-08-03-windows-mutating-install-phase1-decision.md`](2026-08-03-windows-mutating-install-phase1-decision.md).

Related: [Issue #125](https://github.com/ImL1s/resume-skills/issues/125), [Issue #29](https://github.com/ImL1s/resume-skills/issues/29) (Policy B gate **done**), [Issue #209](https://github.com/ImL1s/resume-skills/issues/209) (platform-family umbrella).

## Options for this increment

| ID | Approach | Pros | Cons |
|----|----------|------|------|
| **A** | **Full #125 product close now** — `RootLock` wire, relative mutations, parent-chain reparse, adversarial product install path, then lift Policy B | Would match “#125 done” | XL security surface; out of scope for a safety-only residual; product gate must not open without evidence |
| **B** | **Minimal Phase-2 safety slice (chosen)** — harden lock-leaf metadata + handle validity checks on the existing primitive; **no** product install enablement | Reduces mis-lock / mis-classify risk before any product wire; keeps Policy B; stdlib/`ctypes` only | #125 stays **OPEN**; users still cannot mutate-install on Windows |
| **C** | **Docs-only** — STATUS wording without code hardening | Lowest code risk | Leaves known handle/metadata edge cases unaddressed on the primitive |

## Decision (chosen: **B**)

**Phase 2 (this slice) — lock-metadata fail-closed only; product install still unsupported.**

When the code lands under `src/portable_resume/platform_fs/windows.py`:

1. **`GetFileInformationByHandle` before `LockFileEx`** — After a successful `CreateFileW` open of the lock leaf (with reparse-aware open flags already used in Phase 1), require handle metadata that **proves** a non-reparse, non-directory leaf **before** calling `LockFileEx`.  
   - If metadata cannot be read → **fail closed** (`E_INSTALL_UNSUPPORTED_PLATFORM`).  
   - If attributes show reparse point or directory → **fail closed** (`unsafe_path` / reject).  
   - Do **not** proceed to exclusive lock on unproven leaf type.
2. **`_handle_is_invalid` pointer-width only** — Treat invalid handles by comparison against full pointer-width `INVALID_HANDLE_VALUE` (`ctypes.c_void_p(-1)`), plus explicit `None` / `0` / `-1`. Do **not** use a low-32-bit `0xFFFFFFFF` mask alone as decisive (on 64-bit Windows a truncated comparison can mis-classify handles).

### Explicit non-goals (this slice)

- **Do not** change `require_mutating_install_platform()` — install/uninstall/recover remain Policy B fail-closed (`E_INSTALL_UNSUPPORTED_PLATFORM` on `nt` before support/lock creation).
- **Do not** set `relative_mutations` true; `mkdirs_beneath` / `unlink_beneath` / `replace_beneath` stay fail-closed on the Windows backend.
- **Do not** wire `RootLock` / transaction paths to the exclusive-lock primitive for product use.
- **Do not** claim dual-OS mutating install complete; **do not** close #125 or #209.

## Still remaining for full #125 close

These remain **out of scope** for this minimal Phase-2 safety slice (and block any honest “#125 done” claim):

| Residual | Why it still blocks product enablement |
|----------|----------------------------------------|
| **RootLock wire** | Product install must hold the exclusive lock through the same control path as POSIX; primitive alone is not product install |
| **Relative mutations** | Windows backend must implement reparse-safe relative mkdirs/unlink/replace (or equivalent) before mutation under a skill root is honest |
| **Parent-chain reparse** | Leaf-only reparse/directory checks are insufficient; parent chain defenses needed when wiring product paths |
| **Adversarial `windows-latest` product install path** | Real CI evidence for product install/uninstall/recover (not only lock-unit gates) before reconsidering Policy B |

Until those land with evidence, **do not claim** dual-OS mutating install complete, and **do not** close #125.

## #209 — platform family honesty (unchanged)

| Family | Claim posture |
|--------|----------------|
| Ubuntu (GitHub `ubuntu-latest`) | Readers + CI **verified** (read-only / suite surfaces) |
| macOS (GitHub `macos-latest`) | Readers + CI **verified** |
| Windows native (`windows-latest` / real `nt`) | Readers + CI **verified** for **read-only** surfaces; Phase‑1 lock primitive + Phase‑2 lock-metadata fail-closed (when code lands); mutating **product** install **fail-closed** residual (#125 **OPEN**) |
| WSL2 | **not-run** (no dedicated runner evidence; no fake green) |
| musl-only | **not-run** |
| FreeBSD / BSD | **not-run** |

**Reject** inventing green CI for unavailable families. **Reject** closing #209 while #125 and unavailable families remain open / not-run.

## Out of scope (this phase)

Full Windows `RootLock` product path, install transaction enablement, relative mutation enablement, parent-chain reparse product defenses, `ReplaceFileW` durability claims, ACL ownership model, live resume / host UI / marketplace, inventing WSL2/musl/BSD runners.

## Citations

- Microsoft Learn — [`LockFileEx`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex), [`GetFileInformationByHandle`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- Project **Policy B** — `require_mutating_install_platform` in `src/portable_resume/install/transaction.py`
- Implementation surface — `src/portable_resume/platform_fs/windows.py` (`acquire_exclusive_lock`, `_handle_is_invalid`, `_invalid_handle_value`)
- Prior decision — [`2026-08-03-windows-mutating-install-phase1-decision.md`](2026-08-03-windows-mutating-install-phase1-decision.md)
- Phase‑1 lock evidence: [Actions run 30757382272](https://github.com/ImL1s/resume-skills/actions/runs/30757382272) @ PR [#216](https://github.com/ImL1s/resume-skills/pull/216)
- Residual honesty evidence: [Actions run 30758747880](https://github.com/ImL1s/resume-skills/actions/runs/30758747880) @ PR [#218](https://github.com/ImL1s/resume-skills/pull/218)
- Read-only Windows tip evidence (unchanged claim): [Actions run 30753320460](https://github.com/ImL1s/resume-skills/actions/runs/30753320460)

## Disposition

| Item | Posture |
|------|---------|
| #29 Policy B gate | **Done** (fail-closed before support/lock) |
| #125 Phase 1 | **Landed** — exclusive-lock primitive only |
| #125 Phase 2 (this slice) | **Lock-metadata fail-closed increment** (handle validity + proven non-reparse non-directory leaf before `LockFileEx`) — **not** product install enablement |
| #125 productization | **OPEN** — still need RootLock wire, relative mutations, parent-chain reparse, adversarial product install path |
| #209 umbrella | **OPEN** — verified families documented; WSL2/musl/BSD **not-run** |
