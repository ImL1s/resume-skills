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

Update `docs/STATUS.md` and `docs/evidence-summary.md` dual-OS rows to **claimed** with links.

### Current claim (v0.2.3)

| Field | Value |
|---|---|
| Tag / SHA | `v0.2.3` / `5ff9eba503e28971e5044015cd0666c2807a3d89` |
| Run | https://github.com/ImL1s/resume-skills/actions/runs/29890453185 |
| Jobs | ubuntu/macOS × py3.11/3.12 all success |

Re-claim when cutting a new version tag if the tip SHA differs.

Do **not** claim host UI NL live in the same edit unless `docs/host-ui-smoke.md` NL table has evidence.
