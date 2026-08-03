# Windows productization handoff (#125 / #209)

## If you cannot find the plan files

They live under **`docs/plans/`**, not only `plans/`:

| File | Path |
|------|------|
| **Index (start)** | [`docs/plans/windows-productization/INDEX.md`](docs/plans/windows-productization/INDEX.md) |
| **Phase 4 relative mutations (next)** | [`docs/plans/windows-productization/04-relative-mutations.md`](docs/plans/windows-productization/04-relative-mutations.md) |
| Phase 3 RootLock (already landed) | [`docs/plans/windows-productization/03-rootlock-wire.md`](docs/plans/windows-productization/03-rootlock-wire.md) — reference only |
| Pointer under plans/ | [`plans/windows-productization/README.md`](plans/windows-productization/README.md) |

### Stale clone fix (Windows)

```bat
git fetch origin main
git checkout main
git pull origin main
dir docs\plans\windows-productization
```

Must see `INDEX.md` and `04-relative-mutations.md`. Tip should include Phase 3 RootLock on main (`55c3279` or later) plus plan-pack merges (#220 / #221).

## Next work for low model on real `nt`

1. Read `docs/plans/windows-productization/INDEX.md`  
2. Implement **only** `docs/plans/windows-productization/04-relative-mutations.md`  
3. Keep Policy B fail-closed (`require_mutating_install_platform` on product install/uninstall/recover)  
4. PR body: `Relates to #125` — never `Closes #125` until Phase 7  

**Do not re-implement Phase 3** — `RootLock` already uses Win32 exclusive lock on real Windows.
