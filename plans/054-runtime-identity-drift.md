# Plan 054: Detect at runtime that the agent is running a stale or foreign skill copy

> **Executor instructions**: This plan contains a **design decision** the
> maintainer must confirm before implementation (Step 1). Do the investigation,
> write up the options, and STOP for confirmation unless the operator told you
> to pick. Then follow the steps, running every verification command. When
> done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/reader.py src/portable_resume/resources/skill/run_reader.py.tmpl src/portable_resume/install/ tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Decision (implemented)**: A + C. A temp Claude install exposed the bounded
  ownership manifest at `.portable-resume/.state/manifest.json`, with one
  recorded root and 75 payload files. On the implementation machine, 200
  iterations averaged **0.06 ms** for the manifest read/parse and **1.35 ms**
  for reading and hashing all 75 payload files. The runtime therefore performs
  only the recorded-root check on the hot path and reports actual root,
  recorded root, agreement, and package identity through `--version`; it does
  not claim to detect an intact older install at its original root.
- **Priority**: P2
- **Effort**: M
- **Risk**: MED — adds I/O to every invocation; must warn, never block
- **Depends on**: none. Distinct from plan 031, which addresses **install-time**
  `E_INSTALL_SHADOW` only.
- **Category**: direction / correctness (needs a design call)
- **Planned at**: commit `2b4611c`, 2026-08-01
- **Issue**: https://github.com/ImL1s/resume-skills/issues/171

## Why this matters

The installer knows about drift; the runtime forgets it at the moment it
matters. Verified on the audit machine: `install --dry-run` discovery flagged
all eight owned skills at `$HOME/.claude/skills` as
`duplicate_different_version` (`bundle_version` 0.3.3 vs expected 0.4.0.dev0,
`matches_expected: false`, `payload_verified: false`) under a warn policy —
yet copying an entire `resume-claude/` tree plus its sibling
`.portable-resume/` to an unrelated directory and running it produced **exit
0, correct-looking output, and no warning of any kind**. `--version` reported
the same string from both the installed copy and the relocated one, so version
output cannot distinguish them either.

`SKILL.md` tells the agent to resolve "the directory containing **this**
`SKILL.md`", which makes running a stale copy entirely possible when two
skill roots are on the host's discovery path. When that happens the agent
silently executes old adapter code while everything looks current.

### What is and is not detectable from inside the loaded tree

This distinction was raised as a **P1 in review** and is the load-bearing
constraint on the whole plan — an earlier draft proposed comparing the
sibling manifest's `bundle_version` against the runtime's `__version__`,
which **cannot work**: a complete old installation contains an old manifest
*and* an old runtime whose versions agree, and relocating both trees together
preserves that agreement. Self-comparison of a consistent tree provides false
assurance.

| Failure | Detectable from inside the tree? | How |
|---|---|---|
| Tree was copied/moved away from where it was installed | **Yes** | `build_manifest` records `"root": os.path.realpath(root)` per claim (`src/portable_resume/install/manifest.py`, around line 145). Compare it to the tree's actual realpath at runtime. This is exactly the audit's reproduction. |
| Payload no longer matches its own manifest (tampering, partial sync, hand-edited files) | **Yes** | Recompute the loaded tree's identity and compare with the manifest's `package_identity`. Costs I/O. |
| An intact **older** install shadowing a newer one elsewhere | **No** | An internally consistent 0.3.3 tree at its original root knows nothing about 0.4.0. Only a cross-root comparison sees this — which is what the installer's `audit-host` discovery already does. The runtime's honest contribution is to *report* its identity so a human, an agent, or `audit-host` can compare. |

Design accordingly: the runtime can **detect** relocation and
self-inconsistency, and can **report** identity for external comparison. It
cannot detect staleness on its own, and no done criterion in this plan may
assume otherwise.

## Current state

- **No runtime identity check exists.** Both greps return zero:

```bash
grep -c "package_identity\|manifest" src/portable_resume/reader.py                       # → 0
grep -c "package_identity\|manifest" src/portable_resume/resources/skill/run_reader.py.tmpl  # → 0
```

- **The runner loads whatever sits beside it** —
  `src/portable_resume/resources/skill/run_reader.py.tmpl` around lines
  12–19 computes `_RUNTIME` from `realpath(__file__)` and prepends it to
  `sys.path`; nothing validates that tree.
- **The installer's knowledge already exists**: `install/manifest.py` writes
  an ownership manifest recording `bundle_version` and `package_identity`;
  `install/discovery.py` `inspect_skill_copy` compares on-disk payload bytes
  and reports `payload_verified` / `matches_expected`;
  `install/render.py` `package_identity(materialize_plan(host))` computes the
  expected digest. Read all three before designing.
- **Constraint**: the installed runtime deliberately does **not** ship
  `portable_resume/install/**` (plan 025's allowlist), so the runtime cannot
  import `install.discovery` to do the comparison. Whatever check you add must
  work from what the runtime *does* ship — read
  `_iter_runtime_files` in `render.py` and the allowlist test
  (`tests/unit/test_runtime_package_allowlist.py`) to see exactly what is
  available.
- **Version reporting today**: `--version` prints
  `runtime_identity()['version']` (`src/portable_resume/build_identity.py`),
  which describes the *package build*, not the installed tree.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Temp install | `PYTHONPATH=src python3 scripts/install-resume-skills quick-install claude --root "$(mktemp -d)/skills"` | exit 0 |
| Relocate | copy `<root>/resume-claude` **and** `<root>/.portable-resume` to another temp dir; run its `run_reader.py list --cwd /tmp` | today: exit 0 silently; after: a warning |
| Allowlist test | `PYTHONPATH=src python3 -m unittest tests.unit.test_runtime_package_allowlist -v` | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Installed matrix | `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` | exit 0 |

**Temp roots only. Never install into `$HOME` or a real host root.**

## Scope

**In scope** (after the decision):
- `src/portable_resume/resources/skill/run_reader.py.tmpl` and/or
  `src/portable_resume/reader.py` — the check and its reporting
- Possibly `src/portable_resume/build_identity.py` — only to surface the
  *installed tree's* identity alongside the build version
- Tests for matched / mismatched / missing-manifest cases
- `plans/README.md` — status row

**Out of scope**:
- Blocking execution on mismatch — the check must never fail closed (a
  hand-relocated install is legitimate).
- Install-time shadow policy — plan 031.
- Shipping `install/**` into the runtime — plan 025's allowlist stands.
- Network or telemetry of any kind.

## Git workflow

- Branch: `plan/054-runtime-identity-drift`
- Commit style: `feat(runner): warn when the loaded skill tree diverges from its manifest`

## Steps

### Step 1: Investigate and present the options (STOP for confirmation)

Determine, and write up:

1. **What the runtime can actually read.** Does the installed tree contain the
   ownership manifest, and is it inside the runtime's reach without importing
   `install/**`? Check a real temp install's file list.
2. **Cost.** Time the candidate check (read manifest + hash the payload) on a
   real install. Hashing ~75 files on every invocation may be unacceptable for
   an in-session tool; a cheap variant (compare recorded `bundle_version` and
   `package_identity` from the manifest against the runtime's own
   `__version__`, without re-hashing) may be enough to catch the realistic
   failure — a *stale* copy — even though it cannot catch a tampered one.

Then present the options with their trade-offs. Only these three are sound
given the detectability table above (a `bundle_version`-vs-`__version__`
self-comparison is **not** among them — it cannot fail on a consistent tree):

- **A. Recorded-root check** on every run: compare the manifest claim's
  recorded `root` against the tree's actual realpath; warn on mismatch.
  Catches relocation — the audit's reproduction — at the cost of one small
  file read, no hashing. Must stay silent when no manifest exists.
- **B. Full payload verification** on every run: recompute the loaded tree's
  identity and compare with the manifest's `package_identity`. Additionally
  catches tampering and partial syncs; costs I/O proportional to the payload
  (~75 files) on every invocation — measure it before recommending.
- **C. Report-only**: surface the loaded tree's identity and recorded root in
  `--version` (and/or `self-check`) and do nothing on normal runs. Zero
  hot-path cost. This is the **only** mechanism that helps with the
  shadowing-an-older-install case, since that comparison must happen outside
  the tree.

**Recommendation to present**: **A + C** — A catches the failure the audit
actually reproduced, C makes the undetectable case diagnosable by
`audit-host` or by an agent that asks. Take B only if the measured cost is
negligible on a real install; per-invocation hashing inside a session is hard
to justify otherwise.

**Verify**: the write-up exists, with measured timings for B. **STOP here for
maintainer confirmation** unless already authorized.

### Step 2: Implement the chosen option

Whatever is chosen:
- The check must **never** raise or change the exit code on mismatch.
- The signal must reach the agent through an existing channel: prefer a
  `W_*` warning in the handoff/envelope warnings array over ad-hoc stderr
  text. If you need a new warning code, add it to
  `diagnostics.WARNING_CODES` and mirror the wording work of plan 048
  (explanations) and plan 032 (`docs/diagnostics.md`).
- The check must degrade silently when the manifest is absent (direct-ZIP and
  hand-copied installs are supported paths) — absence is not drift.
- No path, hostname, or user data in the warning payload (content-free
  discipline).

**Verify**: the relocate command produces the warning; a pristine install
produces none; a manifest-less tree produces none.

### Step 3: Surface identity in `--version`

Extend `--version` (and, if cheap, `self-check`) to report enough to tell two
copies apart. **Payload identity and the manifest's recorded root are not
enough** (raised as P2 in review): an exact relocated copy has a byte-identical
payload digest *and* carries the original recorded root in its copied
manifest, so both fields match the pristine install and the comparison cannot
distinguish them.

Report, in addition to the build version:
- the **actual** runtime root the process resolved and loaded (i.e. the
  realpath derived from `__file__` at load time), and
- an explicit recorded-root-vs-actual-root agreement flag (the same signal
  Step 2's option A computes).

Those two are what differ between a pristine tree and its relocated copy.
Keep the first line's existing format stable if any test or doc depends on it
— check with `grep -rn "\-\-version" tests/ docs/ | head`.

**Verify**: run `--version` on the pristine install and on the relocated copy
and diff the two outputs — they must differ, and the difference must identify
which tree ran. If the outputs are identical, the plan's premise is unmet:
STOP and report.

### Step 4: Tests

1. Pristine temp install → no warning; exit unchanged.
2. **Relocated tree** (copy `resume-<source>/` **and** `.portable-resume/` to
   another directory, run from there) → warning present, exit code unchanged,
   stdout otherwise identical. This is the audit's reproduction and the
   primary regression guard.
3. No manifest → no warning, no error (direct-ZIP and hand-copied installs
   are supported).
4. (If option B) a payload byte modified in place → warning present.
5. **Negative control**: an intact tree whose recorded root matches, but which
   is "old" relative to some other install, produces **no** warning — assert
   this explicitly so nobody later mistakes the check for staleness detection
   (see the detectability table).
6. Hot-path cost: assert the check does not read more than N files (prefer
   counting reads over timing, which is flaky in CI).

**Verify**: all pass; full suite OK.

### Step 5: Full gates

**Verify**: full suite OK; `smoke_installed_matrix.py` → 0; `self_verify.py`
→ 0; `check_secrets.py` → 0. Re-run the relocate scenario on a fresh temp
install.

## Test plan

Step 4 (4–5 cases). Every case runs the **installed** runner as a subprocess
from a temp root — this defect is invisible when testing the source tree
in-process.

## Done criteria

- [ ] Options written up with measured cost; decision recorded
- [ ] A **relocated** copy produces a warning through an existing channel (test-pinned)
- [ ] An intact tree at its recorded root produces no warning, even when older than another install elsewhere (negative control, test-pinned)
- [ ] Exit codes and stdout content are unchanged by the check (test-pinned)
- [ ] Missing manifest is silent (test-pinned)
- [ ] `--version` reports the **actual loaded runtime root** plus a recorded-root agreement flag (not just payload identity and the copied manifest's root, which are identical across an exact relocated copy), and diffing the two outputs identifies which tree ran (test-pinned)
- [ ] Runtime still does not import `install/**` (allowlist test green)
- [ ] Full suite + smoke matrix + gates green; `plans/README.md` updated

## STOP conditions

- The installed tree does not contain a manifest the runtime can read, or the
  manifest does not record an install root — report it; options A and B both
  collapse and C is the only viable one.
- You find yourself designing a check that compares the tree only against
  itself (e.g. manifest `bundle_version` vs runtime `__version__`) — STOP:
  that cannot fail on a consistent tree and is the flaw this plan exists to
  avoid.
- Implementing the check requires importing anything from
  `portable_resume.install` — STOP; that breaks the runtime allowlist (plan
  025) deliberately.
- Adding a `W_*` code cascades into schema/contract tests beyond a handful of
  edits — report the count first.
- Any design you consider would block execution on mismatch — reject it; warn
  only.

## Maintenance notes

- Reviewer: confirm the check is bounded, silent-on-absence, and cannot change
  an exit code; and that no path or user data reaches the warning.
- If plan 048 has landed, the new warning gets an explanation line for free —
  make sure it is added there too.
- The realistic drift scenario is a stale *user-global* copy shadowing a newer
  project install; the install-time counterpart is plan 031.
