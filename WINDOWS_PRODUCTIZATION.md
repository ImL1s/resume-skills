# Windows productization handoff (#125 / #209)

## If you cannot find the plan files

They live under **`docs/plans/`**, not only `plans/`:

| File | Path |
|------|------|
| **Index (start)** | [`docs/plans/windows-productization/INDEX.md`](docs/plans/windows-productization/INDEX.md) |
| **Phase 3 RootLock** | [`docs/plans/windows-productization/03-rootlock-wire.md`](docs/plans/windows-productization/03-rootlock-wire.md) |
| Pointer under plans/ | [`plans/windows-productization/README.md`](plans/windows-productization/README.md) |

### Stale clone fix (Windows)

```bat
git fetch origin main
git checkout main
git pull origin main
dir docs\plans\windows-productization
```

Must see `INDEX.md` and `03-rootlock-wire.md`. Tip should include merges for PR #220 / #221 (`7e85289` / `d806e47` or later).

## Next work for low model on real `nt`

1. Read INDEX.md  
2. Implement **only** `03-rootlock-wire.md`  
3. Keep Policy B fail-closed; PR: `Relates to #125`
