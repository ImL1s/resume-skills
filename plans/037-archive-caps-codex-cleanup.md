# Plan 037: Bound all archive-member reads in package validation; delete the no-op codex affinity loop

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/install/package_contracts.py src/portable_resume/adapters/codex_sqlite.py tests/`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`; note `package_contracts.py` has in-flight #118 changes in
> the working tree — the excerpts reflect that tree). On excerpt mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security hardening (part A), tech-debt/clarity (part B)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/148

## Why this matters

**Part A** — `validate_archive_bytes` / `validate_archive_path` are exported
validation entry points whose stated purpose (module docstring) is checking
archives beyond bare ZIP shape. Inside one and the same function, the embedded
build-identity member is read with a size guard (`info.file_size >
MAX_BUILD_IDENTITY_BYTES` → failure, and a capped `handle.read(MAX_… + 1)`),
while the primary manifest and each `marketplace.json` are read with unguarded
`archive.read(...)` — a highly compressed member decompresses fully into
memory before any validation. `validate_archive_path` additionally slurps the
entire archive file with one unbounded `handle.read()`. Today the only
production caller validates archives this repo just built, so exposure is
low — this is hardening the API before it is pointed at third-party packages,
and the in-function asymmetry shows the guard was intended everywhere.

**Part B** — `codex_sqlite._table_signature` contains an eight-line loop of
nested `if`s whose every branch ends in `pass`: it reads as an affinity
validation gate for the `id`/`rollout_path`/`source`/`cwd` columns but
validates nothing, while the docstring implies enforcement. Misleading dead
code in a store-signature function is worth deleting.

## Current state

- `src/portable_resume/install/package_contracts.py`:

  Unguarded primary-manifest read (around lines 440–445):

```python
            if contract.primary_manifest:
                try:
                    raw = archive.read(contract.primary_manifest)
                    manifest = json.loads(raw.decode("utf-8"))
                except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
```

  Marketplace member reads (find with
  `grep -n "archive.read" src/portable_resume/install/package_contracts.py` —
  one reads each `marketplace.json` around line 371).

  The guarded identity read to imitate (around lines 482–487):

```python
                if info.is_dir() or info.file_size > MAX_BUILD_IDENTITY_BYTES:
                    ...append failure...
                    with archive.open(info) as handle:
                        raw_identity = handle.read(MAX_BUILD_IDENTITY_BYTES + 1)
                    if len(raw_identity) > MAX_BUILD_IDENTITY_BYTES:
```

  Unbounded whole-file read (lines 527–530):

```python
def validate_archive_path(path: str, *, package_type: str) -> dict[str, Any]:
    with open(path, "rb") as handle:
        data = handle.read()
    report = validate_archive_bytes(data, package_type=package_type)
```

- `src/portable_resume/adapters/codex_sqlite.py` — the no-op loop (lines
  ~56–62), with genuine enforcement for the timestamp column just above it
  (~50–53):

```python
    for name in ("id", "rollout_path", "source", "cwd"):
        if columns.get(name) not in {"TEXT", "VARCHAR", "CHAR", "NVARCHAR", "CLOB"}:
            # SQLite type affinity is loose; allow empty declared types.
            if columns.get(name) not in {"", "ANY"}:
                # Still accept common live TEXT-ish declarations only when present.
                if not str(columns.get(name, "")).startswith("TEXT"):
                    pass  # do not hard-fail on affinity; Grok only checks presence
    return True, updated
```

  Presence IS enforced earlier (`required = {...}` /
  `if not required.issubset(columns): return False, None`).

- Callers of the validators: `scripts/build_host_packages.py` (~line 275) and
  any tests — enumerate with `grep -rn "validate_archive" scripts/ tests/ src/`.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Contract tests | `PYTHONPATH=src python3 -m unittest tests.unit.test_package_contracts -v` | pass |
| Codex tests | find via `ls tests/unit tests/adapters \| grep -i codex`; run them | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Builder | `python3 scripts/build_host_packages.py --output-dir "$(mktemp -d)/hp" --json` | exit 0 |

## Scope

**In scope**: `src/portable_resume/install/package_contracts.py`,
`src/portable_resume/adapters/codex_sqlite.py`, their test modules,
`plans/README.md` row.

**Out of scope**:
- `MAX_BUILD_IDENTITY_BYTES`'s value and the identity-member logic (in-flight
  #118 work — do not restructure it; only reuse its pattern).
- Archive *extraction* (none exists; keep it that way).
- Any change to what constitutes a valid archive for legitimate packages —
  ceilings must be generous (manifests are small JSON).

## Git workflow

- Branch: `plan/037-archive-caps-codex-cleanup`
- Commit style: `fix(packages): bound manifest member reads; drop no-op codex affinity loop`

## Steps

### Step 1: Add a bounded member reader

In `package_contracts.py`, add near the top constants:

```python
MAX_MANIFEST_MEMBER_BYTES = 1_048_576  # 1 MiB; manifests are small JSON documents
MAX_ARCHIVE_BYTES = 268_435_456  # 256 MiB; whole-archive ceiling for path validation
```

and a helper:

```python
def _read_bounded_member(archive: zipfile.ZipFile, name: str, max_bytes: int) -> bytes:
    info = archive.getinfo(name)
    if info.is_dir() or info.file_size > max_bytes:
        raise KeyError(name)  # caller already treats KeyError as a failure
    with archive.open(info) as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise KeyError(name)
    return data
```

(If the callers' except clauses distinguish KeyError semantics in their failure
messages, raise a dedicated internal exception instead and append an explicit
"member exceeds size bound: <name>" failure — inspect each caller's except
list first and keep failure strings in the established style.)

Route the primary-manifest read and each `marketplace.json` read through it
with `MAX_MANIFEST_MEMBER_BYTES`.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.unit.test_package_contracts -v` → pass.

### Step 2: Cap `validate_archive_path`

```python
    size = os.stat(path).st_size
    if size > MAX_ARCHIVE_BYTES:
        return {"ok": False, "failures": [f"archive exceeds size bound"], "path": path, ...}
```

Match the exact report shape `validate_archive_bytes` returns for failures
(read it and mirror the keys) so consumers see a uniform document.

**Verify**: builder command exits 0 (real archives are far under the cap).

### Step 3: Tests for the caps

In `tests/unit/test_package_contracts.py` (model after its existing
failure-case tests):

1. A crafted in-memory ZIP whose `marketplace.json` (or primary manifest)
   declares `file_size` beyond `MAX_MANIFEST_MEMBER_BYTES` (write a real
   oversized member — a few MiB of spaces compresses tiny, which is exactly
   the decompression-bomb shape) → validation fails with the size-bound
   failure, without materializing the full member.
2. `validate_archive_path` on a file larger than a temporarily-monkeypatched
   small `MAX_ARCHIVE_BYTES` → fails closed.

**Verify**: new tests pass.

### Step 4: Delete the codex no-op loop

Remove lines ~56–62 in `codex_sqlite.py` (the whole `for name in (...)` loop)
and amend `_table_signature`'s docstring to state: presence is required for
`id`/`rollout_path`/`source`/`cwd`; declared type affinity is NOT checked for
them (SQLite affinity is loose in live stores); integer affinity IS required
for the chosen `updated_at` column.

**Verify**: codex adapter tests pass; full suite OK;
`grep -n "do not hard-fail on affinity" src/portable_resume/adapters/codex_sqlite.py` → no matches.

### Step 5: Full gates

**Verify**: full suite OK; `python3 scripts/self_verify.py` → 0;
`python3 scripts/check_secrets.py` → 0; builder → 0.

## Test plan

Steps 3 (2 new bound tests) and the pinned-behavior guarantee that Step 4
changes nothing observable (existing codex signature tests keep passing
untouched — if any asserted the loop's presence, see STOP).

## Done criteria

- [ ] No `archive.read(` call on manifest members without a size pre-check (grep proves)
- [ ] `validate_archive_path` refuses oversized archives (test proves)
- [ ] Codex no-op loop deleted; docstring truthful; zero behavior diff in codex tests
- [ ] Full suite + gates + builder green
- [ ] `plans/README.md` updated

## STOP conditions

- The in-flight #118 changes restructured the identity-member code such that
  the excerpt anchors are gone — re-locate; if `package_contracts.py` is
  mid-refactor (conflicting edits), report rather than merge-fix.
- Any caller feeds archives near 1 MiB manifests legitimately (would need a
  bigger ceiling — report the observed size instead of guessing one).
- A codex test asserts on the affinity loop's (non-)behavior — report; the
  alternative fix (actually enforcing affinity) risks rejecting live stores
  and needs a maintainer decision.

## Maintenance notes

- Reviewer: check the bomb test writes a genuinely compressed-small,
  decompressed-large member (compare `compress_size` vs `file_size` in the
  test) — that is the scenario the cap exists for.
- If these validators are ever exposed to downloaded third-party archives,
  revisit `MAX_ARCHIVE_BYTES` and add a members-count ceiling too.
