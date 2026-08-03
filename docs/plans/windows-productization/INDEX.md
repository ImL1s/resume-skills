# Windows productization plan pack — handoff (post #125)

**Audience:** agents / maintainers reading residual platform work after Windows mutating install landed.

**Primary issues:**
- [#125](https://github.com/ImL1s/resume-skills/issues/125) — **CLOSED** (Phase 1–7 on main; Policy B lifted on real Windows).
- [#209](https://github.com/ImL1s/resume-skills/issues/209) — **V1 desktop dual-OS (Windows native + macOS) CLOSED**; WSL2 / musl / BSD remain **not-run** (out of V1 scope).

## Landed baseline (do not re-implement)

| Phase | What | Evidence |
|------:|------|----------|
| 1 | Win32 exclusive lock (`LockFileEx`) | PR #216 |
| 2 | Lock-metadata fail-closed | PR #219 |
| 3 | `RootLock` Win32 wire | main |
| 4 | reparse-safe relative mutations | PR #224 |
| 5 | parent-chain reparse defenses | PR #226 |
| 6 | adversarial product-path suite | PR #227 |
| 7 | Policy B lift + focused product install smoke | PR #228 → `949180a` · [run 30800595796](https://github.com/ImL1s/resume-skills/actions/runs/30800595796) |

Product `install` / `uninstall` / `recover` on **real** Windows (`os.name == "nt"` and `sys.platform.startswith("win")`) are **enabled**. Spoofed `nt` on non-Windows still fail-closed.

## Windows CI honesty (win+mac V1)

| Gate | OS | Claim |
|------|-----|--------|
| `smoke_installed_matrix` full **306/306** | **Ubuntu only** | hard gate |
| `smoke_windows_product_install.py` (claude/cursor/codex) | **windows-latest** | hard gate; **not** 306/306 |
| macOS suite | **macos-latest** | CI verified (readers + mutating POSIX path) |

Do **not** write STATUS language that claims Windows installed-runner **306/306** unless a real green run measures every cell.

## Remaining plan files (historical / residual)

| File | Status |
|------|--------|
| `03`–`07` phase briefs | Historical — #125 complete |
| [`209-platform-honesty.md`](209-platform-honesty.md) | V1 dual-OS closed; residual families stay not-run |

## Global must-not-do

1. Do not re-open Policy B fail-closed on real Windows without a security regression.
2. Do not mark WSL2 / musl-only / FreeBSD–BSD **verified** without real host evidence.
3. Do not invent green for host UI / marketplace / picker (separate not-run track).
4. Do not claim dual-OS *release* complete solely from docs without packaging/release jobs.

## Out of scope for this pack

- Host UI / marketplace / live resume activation  
- ACL ownership completeness  
- reinframe or other repos  
- Re-doing Phase 1–7 primitives already on `main`
