# Windows productization plans (pointer)

**Canonical path (read these):**

```text
docs/plans/windows-productization/INDEX.md
docs/plans/windows-productization/209-platform-honesty.md
```

Full pack (historical phases): `docs/plans/windows-productization/`

**#125 Phases 1–7 are COMPLETE** on main (Policy B lifted on real Windows).  
**#209 V1 desktop dual-OS (win+mac) is CLOSED**; WSL2 / musl / BSD remain **not-run**.

If this directory is empty of pointers, run:

```text
git fetch origin main
git checkout main
git pull origin main
```

Then open `docs/plans/windows-productization/INDEX.md`.

Windows CI hard gate: `scripts/smoke_windows_product_install.py` (not full 306 matrix).
