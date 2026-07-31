# Plan 040: Move whole-artifact builds out of the per-cell unit tier

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- tests/ scripts/self_verify.py .github/workflows/ci.yml`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`; note `.github/workflows/ci.yml` and `scripts/self_verify.py`
> carry in-flight #118 edits in the working tree). On excerpt mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW–MED (CI wiring; determinism evidence must not be lost)
- **Depends on**: none
- **Category**: perf (developer/CI feedback loop)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/140

## Why this matters

`tests/unit/test_host_package_builder.py` shells out to
`scripts/build_host_packages.py` **twice** (determinism check), each run
building all 18 host archives plus plugin surfaces. Measured: **26.2 s — 30.5%
of the unit tier** — sitting in the suite developers run most often, and CI
pays it in all 8 matrix cells (2 OS × 4 Python) before the `package` job
builds the same artifacts again (~17 builds per CI run). Moving it to a
packaging tier that runs once keeps the determinism evidence and returns ~26 s
to every inner-loop run and ~7 × 26 s to every CI run.

## Current state

- `tests/unit/test_host_package_builder.py` (lines ~21–46) — the double
  build:

```python
    def build(self, output: Path) -> dict:
        completed = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "build_host_packages.py"),
             "--output-dir", str(output), "--json"],
            cwd=REPO, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_builds_safe_complete_deterministic_host_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            report = self.build(first)
            repeated = self.build(second)
```

- `scripts/self_verify.py` — stage/profile registry (lines ~30–47):

```python
PROFILES: dict[str, tuple[str, ...]] = {
    "local": STAGE_NAMES,
    "ci-compat": (
        "compile",
        "unit",
        "reader_self_check",
        "installer_matrix",
        "fixture_list_show",
    ),
    "ci-quality": ("version_state", "docs", "secrets"),
}
```

  Read how the `unit` stage invokes unittest (grep `"unit"` in the file) —
  the split must exclude the packaging module from that stage's discovery.

- `.github/workflows/ci.yml`:
  - `test` job (8-cell matrix) runs `self_verify.py --profile ci-compat` then
    `smoke_installed_matrix.py`.
  - `package` job (`needs: [test, quality]`, single ubuntu runner) already
    builds wheel/sdist reproducibly (double `python -m build` + `cmp`) and
    then "Build deterministic host packages" (~line 125).
- Also relevant: `tests/unit/test_release_tooling.py` and
  `tests/unit/test_artifact_identity*.py` may shell to build scripts too —
  check with `grep -rln "build_host_packages\|subprocess" tests/unit/ | head`
  and include any other whole-artifact builder in the same move (measure
  first; only move modules whose cost is the artifact build).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Time the module | `time (PYTHONPATH=src python3 -m unittest tests.unit.test_host_package_builder -q)` | baseline ~26 s (machine-dependent) |
| Unit tier after | `time (PYTHONPATH=src python3 -m unittest discover -s tests -q)` | materially faster |
| Packaging tier | `PYTHONPATH=src python3 -m unittest discover -s tests/packaging -q` | OK |
| Self-verify | `python3 scripts/self_verify.py` (full local) | exit 0, still includes packaging |

## Scope

**In scope**:
- `tests/unit/test_host_package_builder.py` → move to
  `tests/packaging/test_host_package_builder.py` (new directory with
  `__init__.py`)
- `scripts/self_verify.py` — add a `packaging` stage; keep it in the `local`
  profile; exclude from `ci-compat`
- `.github/workflows/ci.yml` — run the packaging stage once (in the `package`
  job or the `quality` job — see Step 3 decision rule)
- `plans/README.md` row

**Out of scope**:
- `scripts/build_host_packages.py` itself (no behavior change).
- `smoke_distribution.py` / wheel-sdist reproducibility steps in the package
  job (already correct).
- Collapsing the 306-cell `smoke_installed_matrix` (PERF-02 — explicitly
  deferred; design-first).

## Git workflow

- Branch: `plan/040-packaging-tier-test-split`
- Commit style: `test(packaging): move whole-artifact builder tests to a once-per-CI packaging tier`

## Steps

### Step 1: Create the packaging tier

`mkdir tests/packaging`, add empty `__init__.py`, `git mv`
`tests/unit/test_host_package_builder.py` into it. Fix any relative
`REPO = Path(__file__).resolve().parents[2]` depth if the directory depth
changed (it does not: `tests/packaging/` is the same depth as `tests/unit/`).
Check for and move any other whole-artifact builder module identified in
"Current state" (report which you moved).

**Verify**: `PYTHONPATH=src python3 -m unittest discover -s tests/packaging -q`
→ OK. `PYTHONPATH=src python3 -m unittest discover -s tests -q` still
discovers it (top-level discovery includes the new dir) — confirm the count
did NOT drop vs before the move.

### Step 2: Stage it in `self_verify.py`

Read how stages are defined/executed in the file, then:
- If the `unit` stage discovers `tests` wholesale, split: `unit` discovers with
  a pattern or start-dir set that excludes `tests/packaging`, and a new
  `packaging` stage runs `tests/packaging` discovery. Follow the existing
  stage-definition style exactly.
- Profiles: `local` includes `packaging` (pre-PR runs stay comprehensive);
  `ci-compat` excludes it; `ci-quality` unchanged.

CAUTION: the top-level `PYTHONPATH=src python3 -m unittest discover -s tests
-q` documented in CONTRIBUTING/README still runs everything — that is fine
(comprehensive local command stays comprehensive). The tier split only changes
what the 8-cell CI profile pays.

**Verify**: `python3 scripts/self_verify.py --only packaging` → runs just the
packaging tests, exit 0. `python3 scripts/self_verify.py --profile ci-compat`
→ excludes them (confirm via its stage output listing).

### Step 3: Run it once in CI

Add the packaging stage where artifacts are already built once per run — the
`package` job (preferred: it `needs: [test, quality]`, runs on one ubuntu
runner, and already invokes `build_host_packages.py`, so the determinism test
lands beside the real build). Insert a step before/after "Build deterministic
host packages":

```yaml
      - name: Packaging determinism tests
        env:
          PYTHONPATH: src
        run: python scripts/self_verify.py --only packaging
```

Match the workflow's existing step style (pinned actions untouched; plain
`run:` steps need no new actions).

**Verify**: `python3 - <<'EOF'` YAML-parse the workflow (`import yaml` is not
stdlib — instead use `ruby -ryaml` if present or simply push to a branch and
let CI validate; minimum local check: `git diff` shows only the one step
added and indentation matches siblings). Then run the full local gate:
`python3 scripts/self_verify.py` → 0.

## Test plan

No new test logic — the moved module's assertions are unchanged. The
verification is structural: unit-tier wall time drops by roughly the module's
cost (time it before and after; record both numbers in the report), and the
packaging stage passes standalone.

## Done criteria

- [ ] `tests/packaging/` exists; builder test lives there; total discovered test count unchanged
- [ ] `self_verify --profile ci-compat` no longer runs it; `--only packaging` runs it; `local` profile still includes it
- [ ] ci.yml runs the packaging stage exactly once per workflow run
- [ ] Recorded before/after unit-tier timings show the expected drop
- [ ] Full local gate + full unittest discovery green
- [ ] `plans/README.md` updated

## STOP conditions

- `self_verify.py`'s stage machinery cannot exclude a directory without
  restructuring (its `unit` stage may hardcode `-s tests`) — if the change
  grows beyond ~30 lines in that file, report with the observed structure
  instead of refactoring the verifier.
- The in-flight #118 edits to `ci.yml`/`self_verify.py` conflict — report,
  don't merge-fix.
- Any evidence doc (`docs/release-claim.md`, `docs/evidence-summary.md`)
  hardcodes "unit suite includes packaging determinism" semantics — report the
  doc line; claims-vs-gates honesty is a maintainer call.

## Maintenance notes

- The `package` job is now the sole CI home of artifact determinism evidence —
  release workflow (`release.yml`) re-runs its own gates and is untouched.
- If PERF-02 (matrix collapse) is picked up later, it composes with this tier:
  the 306-cell sweep could similarly become single-cell + per-host identity
  assertions.
