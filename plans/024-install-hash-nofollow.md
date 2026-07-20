# Plan 024: Hash and backup install destinations without following symlinks

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/install/manifest.py src/portable_resume/install/transaction.py tests/integration/`

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 001 preferred
- **Category**: security
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Install path classification does `islink` then `sha256_file` via following `open`. Backup uses `shutil.copy2` which can follow symlinks. TOCTOU can copy/hash content from outside the skill root into `.portable-resume/backups/`. Snapshot layer already standardizes no-follow reads; install should match.

## Current state

```python
# manifest.py:81-88
def sha256_file(path: str) -> str:
    with open(path, "rb") as handle:
        ...
```

`transaction.py` checks `os.path.islink(dest)` before hash, but race remains.

## Scope

**In scope**: install-local hash/copy helpers; tests  
**Out of scope**: snapshot.py rewrite; Windows lock (optional note only)

## Steps

### Step 1: No-follow hash

Open with `os.open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)` where available; fstat must be regular file; hash from fd. On platforms without O_NOFOLLOW, document residual and keep islink+open as best effort.

### Step 2: Backup copy

Refuse if lexists and islink; copy via fd or `shutil.copyfile` after O_NOFOLLOW open to owned temp under backup root.

### Step 3: Test

Race-hard to test; at minimum: if dest is symlink at classify time → `E_INSTALL_CONFLICT` (already); add test that sha256 helper rejects symlink path.

**Verify**: integration + full suite.

## Done criteria

- [ ] Install hash helper does not follow symlinks when O_NOFOLLOW exists
- [ ] Backup refuses symlinks
- [ ] Suite green; README DONE

## STOP conditions

- Unifying with `snapshot.stable_read_bytes` causes install to require approved roots incorrectly — keep install-local helper

## Maintenance notes

Reviewer: ensure uninstall still uses same safe hash as plan 001 paths.
