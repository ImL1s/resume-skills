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

Then present two or three options with their trade-offs:

- **A. Cheap version cross-check** on every run: compare the sibling
  manifest's `bundle_version` against the loaded runtime's `__version__`;
  warn on mismatch. Catches stale copies; no hashing; near-zero cost.
- **B. Full payload verification** on every run: recompute the identity of the
  loaded tree and compare to the manifest. Catches tampering too; costs I/O
  per invocation.
- **C. Opt-in only**: report identity in `--version` (and/or a `self-check`
  addition) but do nothing on normal runs. Zero hot-path cost; relies on the
  agent to ask.

**Recommendation to present**: A as the default with C's richer reporting in
`--version` — the realistic failure is a stale copy, and per-invocation
hashing on a tool that runs inside a session is hard to justify.

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

Extend `--version` (and, if cheap, `self-check`) to report the identity of the
**loaded tree** in addition to the build version, so an agent or human can
tell two copies apart. Keep the first line's existing format stable if any
test or doc depends on it — check with
`grep -rn "\-\-version" tests/ docs/ | head`.

**Verify**: the pristine install and the relocated copy print
distinguishable identity information.

### Step 4: Tests

1. Pristine temp install → no drift warning; exit unchanged.
2. Manifest edited to a different `bundle_version` → warning present, exit
   code unchanged, output otherwise identical.
3. No manifest → no warning, no error.
4. (If option B) payload byte modified → warning present.
5. Hot-path cost: assert the check does not read more than N files (or assert
   a timing bound loose enough not to be flaky — prefer counting reads).

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
- [ ] A stale/foreign copy produces a warning through an existing channel
- [ ] Exit codes and stdout content are unchanged by the check (test-pinned)
- [ ] Missing manifest is silent (test-pinned)
- [ ] `--version` distinguishes two copies
- [ ] Runtime still does not import `install/**` (allowlist test green)
- [ ] Full suite + smoke matrix + gates green; `plans/README.md` updated

## STOP conditions

- The installed tree does not contain a manifest the runtime can read — report
  it; the plan's premise fails and option C is the only viable one.
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
