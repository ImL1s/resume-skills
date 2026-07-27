# Release CI/CD and claim checklist

`.github/workflows/release.yml` is the release authority. A configured workflow
alone is not evidence that a release ran; each published version needs its own
archived run and immutable commit.

## One-time repository setup

1. Protect `main`; require the `ci` workflow before merge.
2. Create a GitHub environment named **`pypi`** and add appropriate reviewer/protection rules.
3. In PyPI, create a Trusted Publisher for this repository, workflow file `release.yml`, environment `pypi`, and project `portable-resume`.
4. Keep Actions permissions restricted; the workflow grants write/OIDC permissions only to the jobs that need them.
5. Maintain the independent
   [`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace).
   Its CI validates every change; scheduled, manual, and repository-dispatch
   workflows synchronize stable source releases.

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
4. Build wheel, sdist, one direct host archive per enabled destination (currently nine, including Pi), and seven plugin/marketplace archives once.
5. Smoke-install the exact wheel and sdist outside the checkout on both OSes.
6. Generate artifact digests, `release-evidence.json`, and a `SHA256SUMS` that
   uses the flat basenames delivered by GitHub Releases.
7. Recreate that flat download layout and verify every checksum on Ubuntu and
   macOS.
8. Create GitHub artifact attestations and a **draft** Release containing those exact bytes.
9. Publish the same Python artifacts through PyPI Trusted Publishing.
10. Publish the staged GitHub Release only after PyPI succeeds. A manual dispatch may deliberately skip PyPI.
11. Synchronize the public marketplace and verify its release:

    ```bash
    gh workflow run sync.yml \
      --repo ImL1s/portable-resume-marketplace \
      -f tag=vX.Y.Z
    ```

    The marketplace also polls daily and accepts the
    `portable-resume-release` repository-dispatch event.

## Manual recovery / dry release

`workflow_dispatch` accepts an existing annotated tag and `publish_pypi=false`. This validates and publishes the GitHub Release without PyPI. Re-running the same tag refreshes draft assets with `--clobber`; published version bytes must never be replaced on PyPI.

## Claim requirements

Archive all of the following in [`evidence-summary.md`](evidence-summary.md): exact tag and 40-character SHA, immutable Actions run URL, GitHub Release URL, PyPI version URL or explicit skip, successful OS jobs, and maintainer/date sign-off.

Host UI/picker, public marketplace, and vendor-curated directory claims remain
separate and require their own rows in
[`host-ui-smoke.md`](host-ui-smoke.md).

### Current state

- `v0.3.4`: **published** from annotated tag object
  `f952856476dbf7742d16c0f42638497c0a930b28` at commit
  `fa1344bf62eb26332baea7b7ef4540a1a37acba8`.
  [Release run 30269713516, attempt 1](https://github.com/ImL1s/resume-skills/actions/runs/30269713516)
  passed dual-OS gates, exact-byte smoke, flat-download checksum verification,
  attestation, PyPI Trusted Publishing, and GitHub Release publication
  (`packaging_cells=81`, `installed_runner_cells=81`).
- Kimi PR #58 received a current-head Codex callback with no major issues for
  `4ecf2b5aa5` before merge
  ([review evidence](https://github.com/ImL1s/resume-skills/pull/58#issuecomment-5091411213)).
  The earlier PR #49 final-review bot exception remains documented in
  [`STATUS.md`](STATUS.md) and is not retroactively claimed as a successful
  callback.
- Published outputs:
  [GitHub Release](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4)
  and [PyPI](https://pypi.org/project/portable-resume/0.3.4/).
- Public marketplace:
  [`ImL1s/portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
  at commit `7833e4a3628213f78eb8458f30e9873d43a95fa6`.
  [Marketplace CI 30270409963](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30270409963)
  and [marketplace release 30270407710](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30270407710)
  passed after the nine-skill catalog test fix; its
  [`v0.3.4` release](https://github.com/ImL1s/portable-resume-marketplace/releases/tag/v0.3.4)
  is public. Fresh 0.3.4 host reinstall UI evidence remains **not-run**.
- `v0.3.2`: **published** from annotated tag object
  `a1a17fc21a7ea65bd2717b2ce3faa89fe21d0b5a` at commit
  `284865a4dc8c1c3dca16ee40f5204053cabb3a92`.
  [Release run 30093776529, attempt 1](https://github.com/ImL1s/resume-skills/actions/runs/30093776529)
  passed 14 jobs: dual-OS gates, exact-byte smoke, flat-download checksum
  verification, attestation, PyPI Trusted Publishing, and GitHub Release
  publication.
- Published outputs (historical):
  [GitHub Release](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2)
  and [PyPI](https://pypi.org/project/portable-resume/0.3.2/).
- Public marketplace (historical v0.3.2 trees superseded on main):
  earlier publication commit `0806e186674d22925f23aaa57d83a403ebfb8515` and
  [`v0.3.2` release](https://github.com/ImL1s/portable-resume-marketplace/releases/tag/v0.3.2).
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

Separate v0.3.2-era local evidence verifies headless Skill invocation on eight
host CLI surfaces and exact local installation of all seven supported native
package formats, including Cursor. Pi native activation remains **not-run**.
This release workflow does not reproduce those credentialed host checks.
Separate v0.3.2 post-release evidence verifies public marketplace installation
on all six compatible hosts and Cursor/Kimi marketplace picker flows; fresh
v0.3.4 host-by-host reinstall remains **not-run**. Sanitized readbacks are
retained in
[`evidence/public-marketplace-v0.3.2.json`](evidence/public-marketplace-v0.3.2.json).
Other visual Skill pickers, vendor-curated
Claude/Cursor directory listings, and Cursor full bubble-graph completeness
remain excluded.
