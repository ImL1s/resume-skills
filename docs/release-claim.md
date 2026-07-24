# Release CI/CD and claim checklist

`.github/workflows/release.yml` is the release authority. A configured workflow
alone is not evidence that a release ran; each published version needs its own
archived run and immutable commit.

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
6. Generate artifact digests, `release-evidence.json`, and a `SHA256SUMS` that
   uses the flat basenames delivered by GitHub Releases.
7. Recreate that flat download layout and verify every checksum on Ubuntu and
   macOS.
8. Create GitHub artifact attestations and a **draft** Release containing those exact bytes.
9. Publish the same Python artifacts through PyPI Trusted Publishing.
10. Publish the staged GitHub Release only after PyPI succeeds. A manual dispatch may deliberately skip PyPI.

## Manual recovery / dry release

`workflow_dispatch` accepts an existing annotated tag and `publish_pypi=false`. This validates and publishes the GitHub Release without PyPI. Re-running the same tag refreshes draft assets with `--clobber`; published version bytes must never be replaced on PyPI.

## Claim requirements

Archive all of the following in [`evidence-summary.md`](evidence-summary.md): exact tag and 40-character SHA, immutable Actions run URL, GitHub Release URL, PyPI version URL or explicit skip, successful OS jobs, and maintainer/date sign-off.

Host UI/picker and marketplace UI claims remain separate and require rows in [`host-ui-smoke.md`](host-ui-smoke.md).

### Current state

- `v0.3.2`: **published** from annotated tag object
  `a1a17fc21a7ea65bd2717b2ce3faa89fe21d0b5a` at commit
  `284865a4dc8c1c3dca16ee40f5204053cabb3a92`.
  [Release run 30093776529, attempt 1](https://github.com/ImL1s/resume-skills/actions/runs/30093776529)
  passed 14 jobs: dual-OS gates, exact-byte smoke, flat-download checksum
  verification, attestation, PyPI Trusted Publishing, and GitHub Release
  publication.
- Published outputs:
  [GitHub Release](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2)
  and [PyPI](https://pypi.org/project/portable-resume/0.3.2/).
- `v0.3.1`: archived published release from annotated tag object
  `bf483ebd503143faa1ce73bc5aa95fac95bc0648` at commit
  `d50a1e33db2824830dabc469b7d566031aa45697`.
  [Release run 30089194956](https://github.com/ImL1s/resume-skills/actions/runs/30089194956)
  passed all dual-OS gates, exact-byte smoke, attestation, PyPI Trusted
  Publishing, and GitHub Release publication.
- `v0.3.0`: archived published release from annotated tag object
  `6afb60448e20f4b2d9ba38485a6bdbdbfa6a7e87` at commit
  `78c2acd0f9841d90d87f85eff151b842a80dc011`.
  [Release run 30084711240](https://github.com/ImL1s/resume-skills/actions/runs/30084711240)
  passed all dual-OS gates, exact-byte smoke, attestation, PyPI Trusted
  Publishing, and GitHub Release publication.
- `v0.2.3`: historical archived CI claim only; see evidence summary.

Separate local evidence verifies headless Skill invocation on all eight current
host CLIs and exact local installation of all seven supported native package
formats, including Cursor. This release workflow does not reproduce those
credentialed host checks. Visual picker interaction, public host marketplace
listings, and Cursor full bubble-graph completeness remain excluded.
