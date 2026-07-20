# Dual-OS release claim checklist

CI already runs on Ubuntu and macOS. A **dual-OS release claim** is stronger:
archived proof for a specific tag/SHA.

## Criteria (all required)

1. Git tag `vX.Y.Z` points at the claimed SHA.
2. GitHub Actions CI is **green** for that SHA on:
   - `ubuntu-latest`
   - `macos-latest`
3. Artifacts or log links for:
   - `python3 scripts/self_verify.py`
   - `python3 scripts/check_secrets.py`
4. Human sign-off line in `docs/evidence-summary.md` with date + URLs.

## Commands

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
git tag -a vX.Y.Z -m "release vX.Y.Z"
# push tag only after local gates pass; archive CI run URLs
```

## After claim

Update `docs/STATUS.md` dual-OS row to **claimed** with links.
Do **not** claim host UI live in the same edit unless host-ui evidence exists.
