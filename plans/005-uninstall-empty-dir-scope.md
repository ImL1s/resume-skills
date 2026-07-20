# Plan 005: Scope uninstall empty-directory cleanup to owned paths

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/install/transaction.py tests/integration/`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 001 preferred (same file; land after or carefully merge)
- **Category**: security
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

After the last claim is uninstalled, `_cleanup_empty_dirs(root)` walks the **entire** skill root and `os.rmdir`s every empty directory. Shared roots (`.claude/skills`, `.agents/skills`) may contain empty skeletons from other tools; portable-resume must not delete foreign package directories.

## Current state

```python
# transaction.py ~547-575
_cleanup_empty_dirs(root)
...
def _cleanup_empty_dirs(root: str) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        ...
        os.rmdir(dirpath)
```

## Scope

**In scope**: `transaction.py` cleanup; integration tests  
**Out of scope**: Uninstall of non-empty foreign skills; recursive force delete

## Steps

### Step 1: Restrict cleanup

Only rmdir ancestors of:

1. Paths just removed in this uninstall (`removed` list), and/or
2. Owned prefixes: `.portable-resume/**`, `resume-*/**` (package skill names)

Do **not** walk and rmdir arbitrary siblings like `some-other-skill/`.

Suggested approach: for each removed file path, walk parents upward until `root`, attempt `os.rmdir` if empty; then clean empty `.portable-resume` subdirs if unused.

### Step 2: Test

- Skill root with `other-skill/` empty dir + portable install; uninstall portable → `other-skill/` still exists
- Owned empty dirs under `resume-claude/` removed after uninstall

**Verify**: integration test + full suite.

## Done criteria

- [ ] Foreign empty dirs preserved
- [ ] Owned empties still cleaned
- [ ] Suite green; README DONE

## STOP conditions

- Host roots nest skills in non-`resume-*` names owned by this package — check `materialize_plan` / catalog for actual relative paths before hardcoding prefix list

## Maintenance notes

If package naming changes, update the allowlist and tests together.
