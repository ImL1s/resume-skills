# Windows productization plans (pointer)

**Canonical path (read these):**

```text
docs/plans/windows-productization/INDEX.md
docs/plans/windows-productization/04-relative-mutations.md
```

Full pack: `docs/plans/windows-productization/` (Phases 1–3 landed baseline; next incomplete = Phase 4–7 + #209).

If this directory is empty of phase files, run:

```text
git fetch origin main
git checkout main
git pull origin main
```

Then open `docs/plans/windows-productization/INDEX.md`.

**Start here (current main): Phase 4 only** — `docs/plans/windows-productization/04-relative-mutations.md`  

Phase 3 RootLock Win32 wire is **already on main** — do not re-do `03-rootlock-wire.md`.  

PR body: `Relates to #125` — never `Closes #125` until Phase 7.
