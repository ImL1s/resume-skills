# Plan 035: Stop the cline adapter from swallowing unsafe/busy/budget diagnostics

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/adapters/cline.py tests/`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (fail-silent → fail-loud only)
- **Depends on**: none
- **Category**: bug (honest-diagnostics contract)
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/146

## Why this matters

Two handlers in the cline adapter convert fail-closed safety diagnostics into
silent degradation:

1. `_session_has_extractable` catches `DiagnosticError` and, even on explicit
   selection (`raise_on_bad=True`), converts `E_UNSAFE_PATH` /
   `E_SOURCE_BUSY` (and, for the non-selection path, `E_LIMIT_EXCEEDED`) into
   `return False` — the user asking for that exact session gets
   `E_NO_MATCH` ("no such session") instead of learning that its messages file
   is a symlink or mid-write. The function's own docstring ("Explicit
   selection / show still full-loads and raises") contradicts the code.
2. The optional session-manifest read swallows the same codes with a bare
   `pass`, so when the shared `ReadBudget` runs out mid-listing, `list`
   returns a partial, metadata-stripped result set (titles/cwd/timestamps
   lost — which changes recency ordering and `latest` selection) with exit 0
   and no warning; a symlinked manifest reads as "no metadata" instead of
   unsafe.

The hermes adapter handles the identical situation correctly and is the
pattern to copy.

## Current state

- `src/portable_resume/adapters/cline.py`:

  `_session_has_extractable` docstring (around lines 486–491):

```python
    """Require a safe authoritative messages payload (prompt alone is insufficient).

    During ordinary listing (``raise_on_bad=False``):
    - corrupt / unsupported candidates are skipped so older valid rows can win
    - multi-MB files use a soft bounded check (no full JSON decode, no role-in-window)
    Explicit selection / show still full-loads and raises.
    """
```

  The offending handler (around lines 527–534):

```python
    except DiagnosticError as error:
        if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
            if raise_on_bad:
                raise
            return False
        if error.code == "E_LIMIT_EXCEEDED" and not raise_on_bad:
            return False
        return False
```

  Note the final `return False` catches `E_UNSAFE_PATH`, `E_SOURCE_BUSY`, and
  (when `raise_on_bad=True`) `E_LIMIT_EXCEEDED`.

  The manifest handler (around lines 638–665, inside the listing loop):

```python
        if _regular_file(manifest_path, root):
            try:
                read = stable_read_bytes(
                    manifest_path,
                    root=root,
                    max_bytes=min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes),
                    budget=budget,
                )
                manifest = json.loads(read.data.decode("utf-8"), object_pairs_hook=_object)
                ...
            except (DiagnosticError, json.JSONDecodeError, _DuplicateKey, UnicodeDecodeError):
                pass
```

- The reference pattern, `src/portable_resume/adapters/hermes.py` (around
  lines 379–387):

```python
            except DiagnosticError as error:
                if error.code in {
                    "E_LIMIT_EXCEEDED",
                    "E_SOURCE_BUSY",
                    "E_UNSAFE_PATH",
                    "E_CORRUPT_RECORD",
                }:
                    raise
                continue
```

  (Hermes re-raises the fail-closed set unconditionally during listing and
  skips only the rest.)

- Semantics decision, already made by the codebase's conventions — implement
  exactly this:
  - `E_UNSAFE_PATH`, `E_SOURCE_BUSY`: **always** re-raise (both listing and
    selection). An unsafe store is never a "skip".
  - `E_LIMIT_EXCEEDED`: re-raise **always** (matches hermes; a blown budget
    invalidates the whole listing, partial silent results are the bug).
  - `E_CORRUPT_RECORD` / `E_UNSUPPORTED_FORMAT`: keep current behavior —
    raise on selection, skip during ordinary listing (lets older valid rows
    win); for the manifest reader these stay skippable (manifest is optional
    metadata; a corrupt manifest must not hide the session).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Cline tests | module found via `ls tests/unit tests/adapters \| grep -i cline`; run with `PYTHONPATH=src python3 -m unittest <module> -v` | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | 0 |

## Scope

**In scope**: `src/portable_resume/adapters/cline.py`; cline test module(s);
new synthetic fixtures under `tests/fixtures/cline/` as needed;
`plans/README.md` row.

**Out of scope**:
- `hermes.py` (reference only), all other adapters.
- `_load_messages_payload` / `stable_read_bytes` internals.
- The soft bounded check path (`_list_messages_soft_ok`) — unchanged.

## Git workflow

- Branch: `plan/035-cline-diagnostic-propagation`
- Commit style: `fix(cline): propagate unsafe/busy/budget diagnostics instead of silent skip`

## Steps

### Step 1: Fix `_session_has_extractable`

Rewrite the handler to:

```python
    except DiagnosticError as error:
        if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY", "E_LIMIT_EXCEEDED"}:
            raise
        if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
            if raise_on_bad:
                raise
            return False
        raise
```

(The trailing `raise` for unknown codes replaces the old blanket
`return False` — an unrecognized diagnostic must not be interpreted as "no
extractable turn". This is stricter than hermes and correct here; if an
existing test fails on it, see STOP conditions.)

Also fix the earlier size-cap branch in the same function if it exists:
`if size > source_cap: if raise_on_bad: raise DiagnosticError.limit_exceeded(); return False`
— during ordinary listing an oversized file is a legitimate skip (keep), on
selection it already raises (keep). No change needed there; just confirm.

**Verify**: cline test module passes; full suite result noted (see STOP).

### Step 2: Fix the manifest handler

Split the except:

```python
            except DiagnosticError as error:
                if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY", "E_LIMIT_EXCEEDED"}:
                    raise
                # corrupt/unsupported manifest: optional metadata, keep the session
            except (json.JSONDecodeError, _DuplicateKey, UnicodeDecodeError):
                pass
```

**Verify**: full suite OK.

### Step 3: Update the docstring

Make `_session_has_extractable`'s docstring state the now-true contract:
unsafe/busy/budget always propagate; corrupt/unsupported skip during listing
and raise on selection.

### Step 4: Tests

Add to the cline test module (fixtures synthetic, per CONTRIBUTING rules):

1. **Symlinked messages file, explicit show**: fixture whose
   `<id>.messages.json` is a symlink → `show <id>` raises/exits
   `E_UNSAFE_PATH` (was: `E_NO_MATCH`).
2. **Symlinked messages file, listing**: `list` raises `E_UNSAFE_PATH`
   (fail-closed listing) — assert the code, not just non-zero.
3. **Budget exhaustion mid-listing**: lowered `ReadBudget` that exhausts on
   the manifest reads → `E_LIMIT_EXCEEDED` propagates (was: silent partial
   metadata).
4. **Corrupt manifest still skips**: fixture with malformed `<id>.json`
   manifest → session still listed (metadata-less), exit 0 — pins the
   preserved behavior.

Model the symlink fixtures on existing unsafe-path tests (find via
`grep -rln "E_UNSAFE_PATH" tests/ | head`).

**Verify**: 4 new tests pass; full suite OK.

### Step 5: Full gates

**Verify**: `self_verify.py` 0; `check_secrets.py` 0; smoke matrix 0.

## Test plan

As Step 4 (≥ 4 new cases). Existing cline fixtures must keep passing
unchanged — any existing-test failure means current behavior was pinned; see
STOP.

## Done criteria

- [ ] Handler excerpts above replaced; no blanket `return False` on unknown diagnostics in `_session_has_extractable`
- [ ] The 4 new tests pass; full suite + gates green
- [ ] Docstring matches behavior
- [ ] `plans/README.md` updated

## STOP conditions

- An existing test pins the silent-skip behavior for `E_UNSAFE_PATH` /
  `E_SOURCE_BUSY` / `E_LIMIT_EXCEEDED` (i.e. it asserts `E_NO_MATCH` or a
  partial listing for such fixtures) — report the test name and its assertion;
  the maintainer must decide which contract wins before you proceed.
- The `raise`-on-unknown-codes change in Step 1 breaks a test for a code not
  listed in this plan — report the code; do not silently re-add the blanket
  `return False`.

## Maintenance notes

- Reviewer: scrutinize that ordinary listing still skips corrupt candidates
  (the "older valid rows can win" property) — tests 3 and 4 together pin the
  boundary.
- TEST-03 (bounds-coverage backfill for crush/hermes/openhands) remains
  unplanned this round; when it lands, fold these cases into the shared
  conformance suite.
