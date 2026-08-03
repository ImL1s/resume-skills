# Windows productization handoff (#125 / #209)

## Status (current main)

| Item | State |
|------|--------|
| **#125** Windows mutating install (Phases 1–7) | **CLOSED** — PR #228 → `949180a` |
| **#209** V1 desktop dual-OS (Windows native + macOS) | **CLOSED** under reduced scope |
| WSL2 / musl / FreeBSD–BSD | **not-run** (out of V1; no fake green) |
| Windows CI hard gate | `scripts/smoke_windows_product_install.py` (claude/cursor/codex) — **not** 306/306 |
| Full installed-runner 306/306 | **Ubuntu-only** hard gate |

## Canonical docs

| File | Path |
|------|------|
| **Index** | [`docs/plans/windows-productization/INDEX.md`](docs/plans/windows-productization/INDEX.md) |
| **#209 honesty** | [`docs/plans/windows-productization/209-platform-honesty.md`](docs/plans/windows-productization/209-platform-honesty.md) |
| Historical phases 3–7 | under `docs/plans/windows-productization/` (reference only) |
| Pointer under plans/ | [`plans/windows-productization/README.md`](plans/windows-productization/README.md) |

### Stale clone fix (Windows)

```bat
git fetch origin main
git checkout main
git pull origin main
dir docs\plans\windows-productization
```

Must see `INDEX.md`. Tip should include Phase 7 (#228) or later.

## Do not re-open

1. Do not re-implement Phases 1–7 primitives.  
2. Do not re-fail-close product install on real Windows without a security regression.  
3. Do not claim Windows installed-runner **306/306** unless a real green run measures every cell.  
4. Do not mark WSL2 / musl / BSD verified without real host evidence.
