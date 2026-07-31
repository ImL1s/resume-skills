# Plan 036: Remove the symlink-following retry in the discovery reader and make `matches_expected` truthful

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/install/discovery.py tests/`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1 (part A) / P2 (part B)
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security (part A), correctness (part B)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/147

## Why this matters

**Part A** — `_read_regular_capped`, the sole content reader for `SKILL.md`,
`scripts/run_reader.py`, and every expected package file during `audit-host`,
`verify`, and the pre-install shadow scan, opens with `O_NOFOLLOW` but on
failure performs a non-atomic `islink` check and retries **without**
`O_NOFOLLOW`. That is a textbook time-of-check/time-of-use gap: between the
check and the second open the entry can be swapped for a symlink, and the
reader follows it — directly defeating the module's own documented rule that
symlinked skill files are reported unsafe and never content-hashed. Exposure
is bounded (post-open `fstat` enforces regular-file + size cap; contents are
hashed, not printed), but the invariant is broken. On Windows `O_NOFOLLOW`
resolves to 0, so the fallback is unreachable there; on POSIX the dominant
first-open failure is exactly "it's a symlink" — the fallback only exists to
follow links.

**Part B** — `inspect_skill_copy` accepts `expected_payload_digest` and every
call site passes a real digest, but the value is never compared: the emitted
`matches_expected` field is set purely from `payload_verified` and the
*presence* of the argument. Consumers of the `discovery-scan-v1` report
reasonably read `payload_verified` and `matches_expected` as two independent
checks; only one exists.

## Current state

- `src/portable_resume/install/discovery.py`:

  Part A — `_read_regular_capped` (around lines 713–730):

```python
    if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
        return None
    if st.st_size > max_bytes:
        return None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        if os.path.islink(path):
            return None
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        except OSError:
            return None
    try:
        st = os.fstat(fd)
        if not stat_mod.S_ISREG(st.st_mode):
            return None
```

  The no-follow discipline to match:
  `src/portable_resume/build_identity.py` (`load_identity_file`'s open) and
  `src/portable_resume/install/render.py` (~143–147) open with `O_NOFOLLOW`
  and treat failure as failure — no retry.

  Part B — `inspect_skill_copy` signature (around lines 770–776) and the
  no-op comparison (around lines 838–844):

```python
def inspect_skill_copy(
    skill_root: str,
    skill_name: str,
    *,
    host: str,
    expected_payload_digest: str | None = None,
    soft_manifest: bool = True,
) -> dict[str, Any]:
```

```python
    result["payload_verified"] = _on_disk_package_matches(skill_root, host)
    if result["payload_verified"] and expected_payload_digest is not None:
        result["matches_expected"] = True
    elif expected_payload_digest is not None:
        result["matches_expected"] = False
```

  The ownership metadata read just below (around lines 846–868) loads the
  on-disk manifest and, when owned, records
  `result["package_identity"] = manifest.package_identity`. **Do NOT use that
  as the comparison target** (Codex PR review): the manifest is informational
  metadata that can be stale or tampered independently of the payload — a
  byte-identical payload with stale metadata would read "not matching", and a
  stale caller-supplied digest could read "matching" merely because the
  manifest shares the stale value. The honest target is the *computed
  on-disk package identity* (hash of the actual installed bytes):

```python
    if manifest is not None and manifest.claims:
        result["owned"] = True
        result["bundle_version"] = manifest.bundle_version
        result["package_identity"] = manifest.package_identity
```

  Call sites pass `_expected_package_identity(host)` (=
  `package_identity(materialize_plan(host))`) — find both with
  `grep -n "expected_payload_digest" src/portable_resume/install/discovery.py`.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Discovery tests | find via `grep -rln "inspect_skill_copy\|audit_host" tests/ \| head`; run those modules | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Smoke | `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` | 0 |

## Scope

**In scope**: `src/portable_resume/install/discovery.py`; discovery/audit-host
test modules; `plans/README.md` row.

**Out of scope**:
- The symlinked-*root* policy branch (`higher_precedence_symlink_root`,
  ~lines 984–1030) — that is CORRECTNESS-03, a separate design decision,
  deliberately NOT in this plan.
- `_on_disk_package_matches` (the byte comparison is genuine — keep).
- `render.py` / `build_identity.py` (references only).

## Git workflow

- Branch: `plan/036-discovery-nofollow-matches`
- Commit style: `fix(discovery): drop symlink-following retry; compare expected payload digest for real`

## Steps

### Step 1 (Part A): Delete the fallback open

Replace the `except OSError:` block so any first-open failure returns `None`:

```python
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
```

Delete the `islink` check and the second `os.open`. Everything after
(`fstat`, regular-file re-check, capped read) stays.

**Verify**: `grep -n "islink" src/portable_resume/install/discovery.py` → the
hit inside `_read_regular_capped` is gone; discovery tests pass.

### Step 2 (Part A): Test the no-follow contract

Add a test: build a valid installed-skill tree in a temp root, replace its
`SKILL.md` with a symlink to a regular file containing the same bytes, run the
inspection path (`inspect_skill_copy` or the audit-host report against that
root), assert the copy is NOT reported `payload_verified` and the scan does
not hash through the link (the finding's status reflects a mismatch/unsafe,
not a verified copy). Model on existing discovery tests that build temp skill
trees (find via the grep in "Commands").

**Verify**: new test passes; on the pre-fix code it must fail (run once
against stash if convenient — optional but recommended).

### Step 3 (Part B): Compare the digest against the computed on-disk identity

Replace the presence-based block with a comparison against the **computed**
on-disk package identity — never the manifest's recorded one (see Current
state). First read `_on_disk_package_matches` (discovery.py, ~lines 746–767):
it already walks the expected file set and byte-compares each file via the
no-follow capped reader. Extend that walk (or add a sibling helper reusing
`_read_regular_capped`) to also collect the on-disk bytes per relative path
and compute `package_identity(collected)` — the same function the expected
digest was produced with (`from .render import package_identity`). Then:

```python
    if expected_payload_digest is not None:
        result["matches_expected"] = (
            on_disk_identity is not None
            and on_disk_identity == expected_payload_digest
        )
```

`manifest.package_identity` stays an informational field, untouched and
uncompared. Keep the early-return path for unreadable manifests
(`manifest_unreadable`) setting `matches_expected = False` as it already
does. Preserve the field's presence semantics exactly as today (emitted
whenever `expected_payload_digest` was passed) so `discovery-scan-v1`
consumers see the same keys. Avoid reading every file twice: collect bytes in
the same pass `_on_disk_package_matches` already makes.

**Verify**: full suite OK.

### Step 4 (Part B): Test the field's independence in both directions

1. Intact installed copy, expected digest = current materialization →
   `payload_verified` true AND `matches_expected` true.
2. **Metadata-independence (the review's case)**: intact payload, ownership
   manifest hand-edited to a stale/wrong `package_identity` →
   `matches_expected` **true** (payload bytes are what count; stale metadata
   must not flip it).
3. Payload file modified on disk → `payload_verified` false and
   `matches_expected` false.
4. Intact payload but caller passes a *different* expected digest →
   `payload_verified` true, `matches_expected` **false** — the two fields now
   measure different things; assert both values.

**Verify**: all four pass; full suite + smoke matrix + gates green.

## Test plan

Steps 2 and 4 (≥ 3 new tests). Pattern: existing audit-host/discovery tests
with temp skill roots.

## Done criteria

- [ ] `_read_regular_capped` has no second `os.open`; symlinked SKILL.md test proves fail-closed
- [ ] `matches_expected` compares the computed on-disk identity (never `manifest.package_identity`); the metadata-independence and divergent-expected tests prove the field is independent of both the manifest and `payload_verified`
- [ ] `discovery-scan-v1` key set unchanged (same fields emitted)
- [ ] Full suite, smoke matrix, `self_verify.py`, `check_secrets.py` all green
- [ ] `plans/README.md` updated

## STOP conditions

- A fixture or test legitimately reads through a symlink via
  `_read_regular_capped` (would mean something depends on the fallback) —
  report it; that dependency is itself a finding.
- `_on_disk_package_matches`'s walk cannot be extended to collect bytes
  without double-reading every file or restructuring beyond ~40 lines —
  report the observed structure instead of forcing it.
- Windows CI (if any appears) behaves differently — note it; `O_NOFOLLOW`=0
  there means Part A's change is a no-op on Windows, which is acceptable and
  documented here.

## Maintenance notes

- Reviewer: confirm no other `os.open` in discovery.py lacks `O_NOFOLLOW`
  (`grep -n "os.open" discovery.py`).
- The symlinked-root install-blocking policy (CORRECTNESS-03) remains open; if
  it is later relaxed to inspect link targets, that code must use this
  now-hardened reader.
