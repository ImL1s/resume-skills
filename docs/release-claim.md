# Release CI/CD and claim checklist

`.github/workflows/release.yml` is the release authority. A configured workflow is not evidence that a release ran.

## One-time repository setup

1. Protect `main`; require the `ci` workflow before merge.
2. Create a GitHub environment named **`pypi`** and add appropriate reviewer/protection rules.
3. In PyPI, create a Trusted Publisher for this repository, workflow file `release.yml`, environment `pypi`, and project `portable-resume`.
4. Keep Actions permissions restricted; the workflow grants write/OIDC permissions only to the jobs that need them.

No long-lived PyPI token is required or expected.

## Pre-release

```bash
python3 scripts/self_verify.py
python3 scripts/check_docs.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
python3 scripts/check_release.py --tag vX.Y.Z --json
```

Update `portable_resume.__version__`, `pyproject.toml`, README, and CHANGELOG together. Commit a clean tree, merge to `main`, then create an **annotated** tag:

```bash
git tag -a vX.Y.Z -m "release vX.Y.Z"
git push origin vX.Y.Z
```

## Automated release order

1. Check out the requested tag with full history.
2. Require strict `vMAJOR.MINOR.PATCH`, matching source/package versions, CHANGELOG entry, clean tree, annotated tag, and reachability from `origin/main`.
3. Run the four canonical gates plus multilingual-document consistency on Ubuntu/macOS × Python 3.11/3.14.
4. Build wheel, sdist, eight direct host archives, and seven plugin/marketplace archives once.
5. Smoke-install the exact wheel and sdist outside the checkout on both OSes.
6. Generate artifact digests, `release-evidence.json`, `SHA256SUMS`, and GitHub attestations.
7. Create a **draft** GitHub Release containing those exact bytes.
8. Publish the same Python artifacts through PyPI Trusted Publishing.
9. Publish the staged GitHub Release only after PyPI succeeds. A manual dispatch may deliberately skip PyPI.

## Manual recovery / dry release

`workflow_dispatch` accepts an existing annotated tag and `publish_pypi=false`. This validates and publishes the GitHub Release without PyPI. Re-running the same tag refreshes draft assets with `--clobber`; published version bytes must never be replaced on PyPI.

## Claim requirements

Archive all of the following in [`evidence-summary.md`](evidence-summary.md): exact tag and 40-character SHA, immutable Actions run URL, GitHub Release URL, PyPI version URL or explicit skip, successful OS jobs, and maintainer/date sign-off.

Host UI/picker and marketplace UI claims remain separate and require rows in [`host-ui-smoke.md`](host-ui-smoke.md).

### Current state

- `v0.3.0`: workflow implemented, **not-run remotely**, no release claim.
- `v0.2.3`: historical archived CI claim only; see evidence summary.
