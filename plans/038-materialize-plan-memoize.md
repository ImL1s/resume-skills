# Plan 038: Memoize `materialize_plan` and hoist it out of the verify claim loop

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/install/render.py src/portable_resume/install/transaction.py tests/`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`; `render.py` has in-flight #118 identity changes in the
> working tree — excerpts reflect that tree). On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW–MED (cache correctness; mutation aliasing)
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/138

## Why this matters

`materialize_plan(host)` re-reads ~40 allowlisted runtime files (~1 MB total)
and re-renders ~34 templates on every call, yet its output is host-invariant:
all 18 hosts produce one identical `package_identity` (the `host` argument is
only validated, never baked into content — by design, #25). Measured during
the audit: `verify --host all` makes **648 calls — 9.7 s of a 15.1 s wall
(65%)**; `install --host all --dry-run` spends 76% of its wall in it. The
worst call site sits inside `_verify_root_locked`'s per-claim loop, ~3,300
lines into `transaction.py`. A cache keyed on the resolved identity removes
almost all of it without touching semantics.

## Current state

- `src/portable_resume/install/render.py` (lines ~101–112):

```python
def materialize_plan(
    host: str,
    *,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, bytes]:
    """Return relative path -> file bytes for one complete skill root."""
    if host not in HOST_PROFILES:
        raise KeyError(host)
    selected_identity = runtime_identity() if identity is None else identity
    assert_identity_matches_package(selected_identity, package_root=_PACKAGE_ROOT)
    files: dict[str, bytes] = {}
```

  Note the optional `identity` mapping (in-flight #118 surface): the cache key
  must derive from the *resolved* identity content, not just `host`.

- `src/portable_resume/install/transaction.py` — the hot loop (lines
  ~3321–3330):

```python
        for claim_id, meta in manifest.claims.items():
            if claim is not None and claim_id != claim:
                continue
            host = meta.get("host")
            if host not in HOST_PROFILES or meta.get("bundle_version") != BUNDLE_VERSION:
                raise DiagnosticError("E_VERIFY_MISMATCH")
            expected_files = materialize_plan(host)
            expected_identity = package_identity(expected_files)
```

- Other call sites (all benefit automatically once cached):
  `install/cli.py` (`_reject_divergent_shared_roots`), `transaction.py`
  (~341, ~2708), `discovery.py` (~753, ~871 via
  `_expected_package_identity`), `scripts/build_host_packages.py` (~57).
  Enumerate current state with
  `grep -rn "materialize_plan(" src/ scripts/`.
- Mutation-safety survey (verified during audit): existing callers build new
  dicts rather than mutating the return value — but a cache makes aliasing a
  permanent hazard, so the cache must return a defensive copy.
- `runtime_identity()` in `src/portable_resume/build_identity.py` — check
  whether it is itself cached (`grep -n "lru_cache\|_cache" src/portable_resume/build_identity.py`);
  the identity is stable within a process run.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Baseline timing | `time (PYTHONPATH=src python3 scripts/install-resume-skills verify --host all --scope global --home "$(mktemp -d)")` | records a "before" wall (verify will fail-fast on empty home — see Step 4 for the honest benchmark) |
| Render tests | `PYTHONPATH=src python3 -m unittest tests.unit.test_runtime_package_allowlist -v` and the render/identity modules (`ls tests/unit \| grep -iE "render\|identity\|package"`) | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Smoke | `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` | 0 |

## Scope

**In scope**: `src/portable_resume/install/render.py`,
`src/portable_resume/install/transaction.py` (hoist only), render-related test
module, `plans/README.md` row.

**Out of scope**:
- `build_identity.py` (in-flight #118) — read-only; if `runtime_identity()`
  needs its own cache, note it in the report instead of editing.
- `scripts/build_host_packages.py` — its profile showed only 9% of time in
  `materialize_plan`; no changes there.
- Any change to rendered bytes, file sets, or `package_identity` values.

## Git workflow

- Branch: `plan/038-materialize-plan-memoize`
- Commit style: `perf(render): cache materialized plan by identity digest; hoist out of verify claim loop`

## Steps

### Step 1: Add the identity-keyed cache in `render.py`

Because the `identity` argument is an unhashable `Mapping` and the payload is
identity-determined, key the cache on a canonical serialization:

```python
_PLAN_CACHE: dict[str, dict[str, bytes]] = {}

def _identity_cache_key(identity: Mapping[str, Any]) -> str:
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

In `materialize_plan`, after the `host` validation and identity resolution
(keep both OUTSIDE the cache so bad hosts still raise and
`assert_identity_matches_package` still runs — unless profiling shows the
assert is the cost; it is not: file reads/rendering are):

```python
    key = _identity_cache_key(selected_identity)
    cached = _PLAN_CACHE.get(key)
    if cached is None:
        ... existing rendering ...
        _PLAN_CACHE[key] = files
        cached = files
    return dict(cached)
```

The `dict(cached)` shallow copy prevents caller mutation of the shared dict;
values are immutable `bytes`, so a shallow copy is sufficient. Keep the cache
module-private; add a `_reset_plan_cache()` helper for tests.

Decision to honor: `assert_identity_matches_package` must still run on every
call (it guards against the package tree changing under an embedded identity
— an in-flight #118 invariant). Only the file-read/render work is cached.

**Verify**:
`PYTHONPATH=src python3 -c "from portable_resume.install.render import materialize_plan, package_identity; a=materialize_plan('claude'); b=materialize_plan('qwen'); print(package_identity(a)==package_identity(b), a is not b)"`
→ `True True`.

### Step 2: Hoist per-host dedupe in the verify loop

In `_verify_root_locked` (~3321), claims may span hosts on a shared root;
compute per-host expectations once:

```python
        expected_by_host: dict[str, tuple[dict[str, bytes], str]] = {}
        for claim_id, meta in manifest.claims.items():
            ...
            if host not in expected_by_host:
                files = materialize_plan(host)
                expected_by_host[host] = (files, package_identity(files))
            expected_files, expected_identity = expected_by_host[host]
```

(With Step 1's cache this is belt-and-braces; it also avoids re-hashing
`package_identity` per claim, which the cache does not cover.)

**Verify**: full suite OK (verify-path tests live in
`tests/integration/test_matrix_and_installer.py` and the transaction test
modules — all must pass unchanged).

### Step 3: Cache-correctness tests

New tests in the render test module:

1. Two calls return equal content but distinct top-level dicts (mutation
   safety): mutate the first result, assert the second is unaffected.
2. Different identities produce different cache entries: call with an
   explicit synthetic `identity=` mapping (build a valid one the way existing
   identity tests do — find with `grep -rln "runtime_identity\|build-identity" tests/unit | head`),
   assert the returned bytes differ where identity is embedded.
3. `_reset_plan_cache()` between tests in `setUp` for any module that builds
   identities, to keep isolation.

**Verify**: new tests pass; full suite OK.

### Step 4: Honest before/after measurement

Build a real multi-host install in a temp home, then time verify:

```bash
H=$(mktemp -d)
PYTHONPATH=src python3 scripts/install-resume-skills quick-install all --home "$H" >/dev/null
time PYTHONPATH=src python3 scripts/install-resume-skills verify --host all --scope global --home "$H" >/dev/null
```

Record both times in your completion report. Expected: verify wall drops by
roughly half or more (the audit measured 65% of 15.1 s in materialization on
one machine; exact numbers vary).

**Verify**: the after-time is materially lower and the verify output JSON is
identical in content (diff the two runs' stdout with the timestamps/paths that
legitimately differ accounted for).

### Step 5: Full gates

**Verify**: full suite OK; smoke matrix 0; `self_verify.py` 0;
`check_secrets.py` 0.

## Test plan

Step 3's three tests plus the measurement in Step 4. Existing determinism
tests (`test_host_package_builder` builds twice and compares) are the
strongest regression net — they must stay green.

## Done criteria

- [ ] Repeat `materialize_plan` calls hit the cache (content-equal, not
      same-object results; tests prove mutation safety)
- [ ] `assert_identity_matches_package` still runs per call (grep: it is
      outside the cached block)
- [ ] Verify loop computes one expectation per host per run
- [ ] Before/after timing recorded; full suite + smoke + gates green
- [ ] `plans/README.md` updated

## STOP conditions

- `materialize_plan` output turns out NOT host-invariant at execution time
  (e.g. #118 added host-specific content): the one-identity assumption is
  dead — the cache key must become (identity, host); verify with
  `python3 - <<'EOF'` comparing `package_identity` across all 18 hosts before
  proceeding, and report the change.
- Any test depends on call-count/side-effects of materialization (e.g. mocks
  counting reads) — report which.
- The in-flight #118 edits to `render.py` conflict with the cache placement —
  report rather than rebase-fix.

## Maintenance notes

- The cache is process-lifetime; if a long-lived embedder ever mutates the
  package tree mid-process, `assert_identity_matches_package` (still per-call)
  is the guard — do not remove it when "optimizing" further.
- Reviewer: check no caller mutates the returned dict in new code; the
  defensive copy protects the cache, not the caller's own aliasing.
