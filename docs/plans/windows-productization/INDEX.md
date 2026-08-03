# Windows productization plan pack — low-model handoff

**Audience:** lower-tier coding agents running on **real Windows** (`os.name == "nt"`, preferably GitHub `windows-latest`) or preparing PRs that must be proven on Windows CI.

**Primary issues:** [#125](https://github.com/ImL1s/resume-skills/issues/125) (mutating install productization), [#209](https://github.com/ImL1s/resume-skills/issues/209) (platform-family honesty umbrella).

**Baseline (do not re-implement):**

| Landed | What | Evidence |
|--------|------|----------|
| Phase 1 | Win32 exclusive lock primitive (`CreateFileW` + `LockFileEx`) | PR [#216](https://github.com/ImL1s/resume-skills/pull/216) |
| Residual honesty | Zero side-effect gates + STATUS closed/open clarity | PR [#218](https://github.com/ImL1s/resume-skills/pull/218) |
| Phase 2 | Lock-leaf metadata fail-closed + full-width `INVALID_HANDLE_VALUE` | PR [#219](https://github.com/ImL1s/resume-skills/pull/219) |

Product `install` / `uninstall` / `recover` on Windows still raise **`E_INSTALL_UNSUPPORTED_PLATFORM`** (Policy B / #29).  
`FilesystemCapabilities.relative_mutations` remains **`False`** on the Windows backend.

Decision docs:

- [`docs/research/2026-08-03-windows-mutating-install-phase1-decision.md`](../../research/2026-08-03-windows-mutating-install-phase1-decision.md)
- [`docs/research/2026-08-03-windows-mutating-install-phase2-lock-metadata-decision.md`](../../research/2026-08-03-windows-mutating-install-phase2-lock-metadata-decision.md)

---

## Pick order (strict)

Do **one** slice → one PR → one primary issue. Do not combine enablement with foundation.

| Order | Slice file | Phase label | Primary issue | Product Policy B |
|------:|------------|-------------|---------------|------------------|
| **1 (start here)** | [`03-rootlock-wire.md`](03-rootlock-wire.md) | Phase 3 | **#125** | **MUST keep fail-closed** |
| 2 | [`04-relative-mutations.md`](04-relative-mutations.md) | Phase 4 | **#125** | **MUST keep fail-closed** |
| 3 | [`05-parent-chain-reparse.md`](05-parent-chain-reparse.md) | Phase 5 | **#125** | **MUST keep fail-closed** |
| 4 | [`06-adversarial-product-path.md`](06-adversarial-product-path.md) | Phase 6 | **#125** | **MUST keep fail-closed** (tests may use a **test-only** hook; product CLI still blocked) |
| 5 (last #125) | [`07-policy-b-enablement.md`](07-policy-b-enablement.md) | Phase 7 | **#125** | **Only slice allowed to lift** after checklist |
| Parallel (docs only) | [`209-platform-honesty.md`](209-platform-honesty.md) | #209 honesty | **#209** | N/A — **never** invent WSL2/musl/BSD green |

Also read once: [`00-baseline-and-global-rules.md`](00-baseline-and-global-rules.md).

```text
First PR for a low model on Windows:
  → docs/plans/windows-productization/03-rootlock-wire.md
```

---

## Global must-not-do (every pre-final slice)

1. **Do not** remove or weaken `require_mutating_install_platform()` on `os.name == "nt"` until **Phase 7** and its evidence checklist pass.
2. **Do not** claim dual-OS **mutating** install complete from lock primitives, capability bits, or read-only CI.
3. **Do not** close **#125** until Phase 7 acceptance is met with `windows-latest` product-path evidence.
4. **Do not** close **#209** while #125 productization is open or while WSL2 / musl / BSD remain **not-run** without an explicit maintainer decision.
5. **Do not** use Ubuntu/macOS mocks as Windows evidence; **do not** monkeypatch `os.name` to `"nt"` as sole proof.
6. **Do not** set `relative_mutations=True` until Phase 4 DoD is green **and** parent-chain (Phase 5) is either done or explicitly fail-closed for unproven chains.
7. **Do not** invent CI runners or “verified” rows for WSL2, musl-only, FreeBSD/BSD without real host evidence.
8. One PR names **exactly one** primary issue (`#125` or `#209`) and the **phase** from this pack.

---

## PR title pattern

```text
feat(platform): #125 Phase N <short-slug>
fix(platform): #125 Phase N <short-slug>
docs(platform): #209 honesty <short-slug>
```

Examples:

- `feat(platform): #125 Phase 3 wire RootLock to Win32 exclusive lock`
- `feat(platform): #125 Phase 4 reparse-safe relative mutations`
- `docs(platform): #209 refresh not-run family checklist`

### GitHub auto-close guard (critical)

For **Phases 3–6** and **docs-only** PRs (including plan-pack PRs):

```text
PR body MUST use:  Relates to #125   or   Refs #125
PR body MUST NOT use: Closes / Close / Fixes / Fix / Resolves #125
Merge commit subject: avoid implying product completion of #125
```

**Only Phase 7** (after checklist + product evidence) may use `Closes #125`.  
**Never** auto-close #209 from a single Windows phase PR.

If #125 is closed without Phase 7 product evidence, **reopen immediately** and comment that only the plan/partial phase landed.

---

## How a low model should work

1. Open **only** the next incomplete slice file in order.
2. Copy the **Agent brief** into the agent system prompt.
3. Implement on a branch from current `main`.
4. Run the **Windows verification** commands on real `nt` (local Windows or `windows-latest` job).
5. Capture CI / pytest logs in the PR body with run URLs.
6. Do not start the next slice until the previous PR is merged (or maintainer explicitly parallelizes #209 docs).

---

## Out of scope for this entire pack

- Host UI / marketplace / live resume activation claims  
- ACL ownership model completeness  
- Claiming `ReplaceFileW` durability without measured limits  
- reinframe or other repos  
- Re-doing Phase 1–2 primitives already on `main`
