# #209 — Platform-family honesty (V1 desktop dual-OS)

**Primary issue:** [#209](https://github.com/ImL1s/resume-skills/issues/209)  
**Type:** documentation / checklist / evidence hygiene  
**V1 close criteria (maintainer, 2026-08-03):** Windows native + macOS product surfaces with real CI evidence; WSL2 / musl / BSD **not-run** and **out of V1 scope**.

---

## Agent brief (copy to low model)

```text
You are working on #209 platform honesty ONLY (or residual not-run family docs).

GOAL
- Keep the platform contract honest: verified vs not-run families.
- V1 desktop dual-OS = Windows native + macOS (Ubuntu remains a CI host).
- Never mark WSL2 / musl-only / FreeBSD-BSD as verified without real runners.

MUST DO
1. Read docs/STATUS.md platform table.
2. Update checklist only when merged code + current evidence exist.
3. Windows mutating install is CLOSED via #125 Phase 7 — do not re-open.
4. Windows installed-runner: focused smoke only; full 306 is Ubuntu-only unless measured.

MUST NOT DO
- Fake green CI for missing runners.
- Require WSL2/musl/BSD verified before documenting V1 dual-OS done.
- Implement new OS runners in a honesty-only PR unless assigned.

DoD for honesty-only PR
- [ ] STATUS/table accurate for win+mac V1
- [ ] not-run families remain not-run without runners
- [ ] no claim of Windows 306/306 installed-runner without evidence
```

---

## V1 scope (closed)

| Family | Readers + CI | Mutating install |
|--------|--------------|------------------|
| Windows native | verified | supported (#125) |
| macOS | verified | supported |
| Ubuntu (CI host) | verified | supported (POSIX) |
| WSL2 | not-run | not-run |
| musl-only | not-run | not-run |
| FreeBSD / BSD | not-run | not-run |

Closing #209 under V1 means **desktop dual-OS product honesty is complete**, not “every Unix-like is verified.”
