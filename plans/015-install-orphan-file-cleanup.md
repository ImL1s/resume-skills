# Plan 015: Delete owned orphan files on install upgrade

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/install/transaction.py src/portable_resume/install/manifest.py tests/integration/`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 001 (path containment) **required**
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

When a new bundle materializes fewer/renamed relative paths, `build_manifest` drops unreferenced keys from the manifest but `execute_install` only `os.replace`s new files. Stale owned skill files remain on disk; hosts may load orphan skills; verify ignores extras.

## Current state

- `manifest.py` removes unreferenced paths from manifest structure (~134-135 area)
- `execute_install` commits only `plan.files` keys
- `uninstall_claim` deletes when last claim releases a file and hash matches

## Scope

**In scope**: install upgrade path under lock; tests  
**Out of scope**: Deleting foreign/non-owned files; force wipe of drifted content (keep uninstall drift retention semantics)

## Steps

### Step 1: Compute orphans under lock

After rebuilding manifest / during execute:

```python
orphans = set(existing.files) - set(plan.files)
```

For each orphan:

1. Validate path with `_dest_under_root` (plan 001).
2. If on-disk file hash matches **old** manifest entry sha256 **and** after claim rebuild no other claim references it, `os.remove`.
3. If hash mismatch (user edited), retain (same as uninstall drift) and leave out of new manifest or keep a retained_drift note in result JSON if already patterned.

### Step 2: Journal safety

Record orphan deletions in journal before remove so recover can reason (best-effort; if journal schema is rigid, delete only in complete state with same care as commit).

### Step 3: Tests

- Install generation N with files A,B; materialize plan with only A; execute → B removed if hash matches
- B modified on disk → retained

**Verify**: integration tests + full suite.

## Done criteria

- [ ] Upgrades remove owned matching orphans
- [ ] Drifted files retained
- [ ] Plan 001 containment still holds
- [ ] README DONE

## STOP conditions

- Shared multi-claim paths would delete still-referenced files — must re-check claims after rebuild exactly like uninstall

## Maintenance notes

Reviewer: multi-host shared root claims are the riskiest case; add test with two claims if fixtures allow.
