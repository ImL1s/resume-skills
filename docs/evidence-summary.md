# Evidence summary


## v0.4.1 (2026-08-03)

- Tag: `v0.4.1` → commit `a2ae025dcdf6a3944eb6752caadd67a53c28f46e`
- Release workflow: [Actions run 30837046570](https://github.com/ImL1s/resume-skills/actions/runs/30837046570) (success)
- GitHub Release: https://github.com/ImL1s/resume-skills/releases/tag/v0.4.1
- PyPI: https://pypi.org/project/portable-resume/0.4.1/
- Highlights: Windows mutating install (#125), win+mac V1 honesty (#209 reduced), list JSON flake fix, smoke cwd normalize
- Windows installed-runner: focused product-install smoke only (not full 306/306 on Windows)
- Host UI / marketplace reinstall on this tip: **not-run**

## Unreleased main: release identity and tag-policy evidence

| Field | Evidence |
|---|---|
| Date / maintainer | 2026-08-01 / `ImL1s` |
| Artifact identity merge | [PR #150](https://github.com/ImL1s/resume-skills/pull/150) → `ff119f16f2af76468e848a828bde51433d968754` |
| PR current-head CI | [run 30660388798](https://github.com/ImL1s/resume-skills/actions/runs/30660388798), 10/10 jobs associated with head `9beccaf21c0ef2acc24492924e67de05b5d09f82` |
| PR current-head AI review | [Codex no-major callback](https://github.com/ImL1s/resume-skills/pull/150#issuecomment-5146921285), reviewed `9beccaf21c` |
| Main CI | [run 30661760699](https://github.com/ImL1s/resume-skills/actions/runs/30661760699), 10/10 PASS for `ff119f16f2af76468e848a828bde51433d968754` |
| Repository ruleset | [Immutable semantic release tags, ID `20148806`](https://github.com/ImL1s/resume-skills/rules/20148806) |
| Ruleset readback | `target=tag`; `enforcement=active`; include `refs/tags/v*`; rules `update` + `deletion`; `bypass_actors=[]` |
| PR package evidence | synthetic merge-result identity SHA-256 `c4aac7a08c97116233214d9ce1d0a9752240540bfe9be0ccf9a01ef00f905fbc`; 27/27 artifacts matched; wheel `8daa309f22eb62dbaeaab4d988ab0e3b3d717b53e97e180b6f0923617089c46a`; sdist `ebdddbe5c0ac91075481e76b9240f87c27a5920cf4e24ee64195c3e50c82e359` |

The API readback was captured immediately after creation and proves the active
repository policy has no bypass actors. The PR workflow's artifact identity is
bound to GitHub's synthetic `pull_request` merge checkout
`737e87126ef4b0553458f7400f41e3c37d5463f3`, not mislabeled as the PR head or
the eventual squash commit. This evidence completes the pre-release integrity
work tracked in #118; it does **not** publish `0.4.0`, rerun host UI/pickers, or
upgrade any separate `not-run` claim.

## Published archive: v0.3.4

| Field | Evidence |
|---|---|
| Date / maintainer | 2026-07-27 / `ImL1s` |
| Annotated tag | `v0.3.4`; tag object `f952856476dbf7742d16c0f42638497c0a930b28` |
| Release commit | `fa1344bf62eb26332baea7b7ef4540a1a37acba8` |
| Main CI | [run 30269684151](https://github.com/ImL1s/resume-skills/actions/runs/30269684151) |
| Release CI/CD | [run 30269713516, attempt 1](https://github.com/ImL1s/resume-skills/actions/runs/30269713516) |
| GitHub Release | [Portable Resume v0.3.4](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4) |
| PyPI | [portable-resume 0.3.4](https://pypi.org/project/portable-resume/0.3.4/) |

The release run passed annotated-tag validation; dual-OS release gates on Python
3.11 and 3.14; one-time artifact build; exact wheel/sdist smoke on all four
release cells; flat-download checksum verification; artifact attestation; PyPI
Trusted Publishing; and staged GitHub Release publication.
`release-evidence.json` records `packaging_cells=81`,
`installed_runner_cells=81`, `source_count=9`, `destination_count=9`, and keeps
`host_ui_nl` / `marketplace_ui_install` as **not-run** for this tag (prior host
UI rows remain under older archive sections).

Primary product changes in this release: Kimi large-session streaming under
`source_read_bytes` (Issue #14 / PR #58), Pi destination Skill profile expanding
the matrix to 9×9=81, and registry-derived release evidence cell counts.
PR #58 received a current-head Codex callback with no major issues for
`4ecf2b5aa5` before merge
([evidence](https://github.com/ImL1s/resume-skills/pull/58#issuecomment-5091411213)).
The earlier PR #49 final-review bot exception remains explicitly recorded in
[`STATUS.md`](STATUS.md); this archive does not rewrite that historical process
exception as a successful callback.

### Published Python artifacts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `portable_resume-0.3.4-py3-none-any.whl` | 157541 | `60a73e376e1be436353b00a8984eccd5156130684c2895c643e9e95a4689959f` |
| `portable_resume-0.3.4.tar.gz` | 135285 | `0eefc5bb0ec1541f39ccc2256e747b1130e99f1a95a77d016534246e46cafb33` |

A fresh public download retrieved all 22 GitHub Release assets and verified all
21 `SHA256SUMS` entries. `gh attestation verify` passed for the 21 intended
attested assets against `.github/workflows/release.yml` and source commit
`fa1344bf62eb26332baea7b7ef4540a1a37acba8`; the extra
`host-packages-build.json` asset is checksum-covered and byte-identical to the
attested `host-packages.json`.

PyPI and GitHub Release report matching SHA-256 digests for both Python
artifacts. A fresh isolated public PyPI install reported version `0.3.4`, no
runtime dependencies, and passed both `self-check` and installer matrix
readback at **81/81** cells.

### Public marketplace synchronization: v0.3.4

| Field | Evidence |
|---|---|
| Public repository | [`ImL1s/portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace) |
| Sync commit | `7833e4a3628213f78eb8458f30e9873d43a95fa6` |
| Annotated tag | `v0.3.4`; tag object `a3b8a2a5f14a8dbef4d901ff8ee87a5f9ad76a8c` |
| Marketplace release | [`v0.3.4`](https://github.com/ImL1s/portable-resume-marketplace/releases/tag/v0.3.4) |
| Marketplace CI | [run 30270409963](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30270409963) |
| Marketplace release workflow | [run 30270407710](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30270407710) |

The first automated `Sync upstream release` dispatch for `v0.3.4`
([run 30270168250](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30270168250))
failed because the marketplace unit test still expected eight Skills after the
Pi destination skill landed. The catalog test was updated to nine Skills
(including `resume-pi`), `scripts/sync_release.py --tag v0.3.4` was re-run, and
the synchronized trees were committed and tagged. Fresh host-by-host marketplace
reinstall for **0.3.4** remains **not-run** (see `release-evidence.json`); the
6/6 host install claim below stays bound to the earlier v0.3.2 evidence section.

## Published archive: v0.3.2

| Field | Evidence |
|---|---|
| Date / maintainer | 2026-07-24 / `ImL1s` |
| Annotated tag | `v0.3.2`; tag object `a1a17fc21a7ea65bd2717b2ce3faa89fe21d0b5a` |
| Release commit | `284865a4dc8c1c3dca16ee40f5204053cabb3a92` |
| Main CI | [run 30093652499](https://github.com/ImL1s/resume-skills/actions/runs/30093652499) |
| Release CI/CD | [run 30093776529, attempt 1](https://github.com/ImL1s/resume-skills/actions/runs/30093776529) |
| GitHub Release | [Portable Resume v0.3.2](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2) |
| PyPI | [portable-resume 0.3.2](https://pypi.org/project/portable-resume/0.3.2/) |

The nine-job main CI run passed Ubuntu and macOS on Python 3.11, 3.12, 3.13,
and 3.14 plus exact distribution smoke. The 14-job release run passed
annotated-tag validation; dual-OS release gates on Python 3.11 and 3.14;
one-time artifact build; exact wheel/sdist smoke on all four release cells;
artifact attestation; PyPI Trusted Publishing; and staged GitHub Release
publication.

The release corrects `SHA256SUMS` to use flat GitHub Release asset basenames,
rejects duplicate basenames, and verifies a simulated flat download on Ubuntu
and macOS before publication. A fresh public download verified all 20 manifest
entries with `shasum -a 256 --check`. GitHub attestation verification passed
for the 20 intended attested assets; the 21st asset,
`host-packages-build.json`, is checksum-covered and byte-identical to the
attested `host-packages.json`.

### Published Python artifacts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `portable_resume-0.3.2-py3-none-any.whl` | 139222 | `299f57415955d705e7124c735417f3a2e4525c30d35b4df6b4e499575851c510` |
| `portable_resume-0.3.2.tar.gz` | 118968 | `ec7ed14bd4ca59bc1e2c4dc7d9ab0c98f46ecaf106104c1fd2b4d00c0ba9f256` |

PyPI and GitHub Release bytes match for both Python artifacts. An isolated
public PyPI install reported version `0.3.2`, no runtime dependencies, and
passed `self-check` for all eight adapters and 64 cells. Separate temporary
roots quick-installed and verified all eight destination profiles with 43
owned files each.

Fresh post-release checks installed all seven exact `0.3.2` native
plugin/extension archives on their current host surfaces. Cursor loaded the
plugin and executed its bundled reader; Kimi's TUI listed Portable Resume
`0.3.2` with eight Skills. Host-native headless Skill invocation remains **8/8
pass** from the recorded CLI rows. Exact commands, hashes, and proof boundaries
are in [`host-ui-smoke.md`](host-ui-smoke.md).

## Public marketplace publication: v0.3.2

| Field | Evidence |
|---|---|
| Public repository | [`ImL1s/portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace) |
| Publication commit | `4997715cd8f2680ab9e196ba43ec4af323a56bd1` |
| Current marketplace commit | `0806e186674d22925f23aaa57d83a403ebfb8515` |
| Annotated tag | `v0.3.2`; tag object `29a583bbe6017ec3934d8504b1a5e5ae636329dc` |
| Marketplace release | [`v0.3.2`](https://github.com/ImL1s/portable-resume-marketplace/releases/tag/v0.3.2) |
| Initial publication CI | [marketplace run 30097511787](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30097511787); [release run 30097512849](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30097512849) |
| Current CI / sync | [marketplace run 30103298262](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30103298262); [manual network sync 30103342413](https://github.com/ImL1s/portable-resume-marketplace/actions/runs/30103342413) |
| Sanitized host evidence | [`public-marketplace-v0.3.2.json`](evidence/public-marketplace-v0.3.2.json) |

Fresh isolated installs from the public catalogs passed on all six compatible
hosts: Claude 2.1.218, Codex 0.145.0, Cursor Agent
2026.07.23-e383d2b, Qwen 0.20.1, Grok 0.2.111, and Kimi 0.29.1. Cursor and Kimi
were installed through their visual marketplace pickers; all six readbacks
confirmed the installed plugin. Version-reporting surfaces showed `0.3.2`, and
the applicable hosts reported eight Skills. Antigravity and OpenCode have no
compatible public catalog for this package shape and retain their
release/direct installation paths.

Qwen and Grok consume the marketplace's Claude-compatible subtree rather than
the standalone Qwen/Grok release archives. The evidence record therefore binds
those installs to publication commit `4997715…`, path
`plugins/claude/portable-resume`, and Git tree
`fd069e937013dca2ba6d45aa5ee2665f2a869da0`. The marketplace sync now rejects
unsafe or colliding ZIP paths, malformed catalogs, checksum mismatch,
downgrades, same-version content divergence, and oversized compressed
downloads; its CI also compares an existing tag's release index before
committing.

The immutable marketplace `v0.3.2` tag retains its historical README. The
GitHub Release body now explicitly supersedes the obsolete Cursor/Qwen commands
with the verified `/plugin` and `--scope user` routes; the generated README for
the next release already contains those corrected commands.

This proves an independently maintained public marketplace and real host
installation. It does not prove inclusion in the vendors' curated Claude or
Cursor directories; those authenticated submission/readback gates remain
separate.

## Published archive: v0.3.1

| Field | Evidence |
|---|---|
| Date / maintainer | 2026-07-24 / `ImL1s` |
| Annotated tag | `v0.3.1`; tag object `bf483ebd503143faa1ce73bc5aa95fac95bc0648` |
| Release commit | `d50a1e33db2824830dabc469b7d566031aa45697` |
| Main CI | [run 30089095568](https://github.com/ImL1s/resume-skills/actions/runs/30089095568) |
| Release CI/CD | [run 30089194956, attempt 1](https://github.com/ImL1s/resume-skills/actions/runs/30089194956) |
| GitHub Release | [Portable Resume v0.3.1](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.1) |
| PyPI | [portable-resume 0.3.1](https://pypi.org/project/portable-resume/0.3.1/) |

The main CI run passed Ubuntu and macOS on Python 3.11, 3.12, 3.13, and
3.14, plus exact distribution smoke. The release run passed annotated-tag
validation; dual-OS release gates on Python 3.11 and 3.14; one-time artifact
build; exact wheel/sdist smoke on all four release cells; GitHub artifact
attestation; PyPI Trusted Publishing; and staged GitHub Release publication.

The release removes mistakenly scoped destination-host
network/documentation-tool guidance from generated Skills and product
documentation. Qwen/Kimi support remains offline context migration and
destination installation only.

### Published Python artifacts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `portable_resume-0.3.1-py3-none-any.whl` | 139183 | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` |
| `portable_resume-0.3.1.tar.gz` | 118912 | `34bda0453b40739b7af5e182418856e547016d1831d58d50e93290fe17986ff1` |

PyPI and GitHub Release report matching digests. `SHA256SUMS`,
`release-evidence.json`, eight direct Skill archives, and seven
plugin/marketplace archives are attached to the release.

### v0.3.1 checksum-manifest limitation

The artifact bytes and recorded SHA-256 values are correct, but the published
`SHA256SUMS` entries retain build-tree prefixes such as `dist/` and
`release-assets/hosts/`. GitHub downloads release assets into one flat
directory, so a direct `shasum -a 256 --check SHA256SUMS` cannot locate those
prefixed paths. A basename-aware local check verified all 20 referenced
artifacts. `v0.3.2` supersedes this manifest layout and adds dual-OS regression
coverage; the immutable `v0.3.1` assets are not replaced.

## Historical local verification: v0.3.2-era

Local verification on 2026-07-24 used:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Results: **267** Python tests, **64/64** package cells, and **64/64**
installed-reader cells passed. Fresh wheel and sdist builds also passed
isolated 64-cell smoke.

Public marketplace installation passed **6/6** compatible hosts, and the Cursor
and Kimi marketplace pickers passed. Other visual Skill pickers and
vendor-curated directory listings remain unclaimed. Cursor's full bubble graph
remains **not claimed**. PyPI publication and local native-package acceptance
remain separate evidence gates.

## Historical archive: v0.3.0

| Field | Evidence |
|---|---|
| Date / maintainer | 2026-07-24 / `ImL1s` |
| Annotated tag | `v0.3.0`; tag object `6afb60448e20f4b2d9ba38485a6bdbdbfa6a7e87` |
| Release commit | `78c2acd0f9841d90d87f85eff151b842a80dc011` |
| Main CI | [run 30084529804](https://github.com/ImL1s/resume-skills/actions/runs/30084529804) |
| Release CI/CD | [run 30084711240, attempt 2](https://github.com/ImL1s/resume-skills/actions/runs/30084711240) |
| GitHub Release | [Portable Resume v0.3.0](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.0) |
| PyPI | [portable-resume 0.3.0](https://pypi.org/project/portable-resume/0.3.0/) |

The main CI run passed Ubuntu and macOS on Python 3.11, 3.12, 3.13, and
3.14, plus the distribution build/smoke job. The release run passed annotated
tag validation; release gates on both OSes with Python 3.11 and 3.14; one-time
artifact build; exact wheel/sdist smoke on all four release cells; artifact
attestation; PyPI Trusted Publishing; and staged GitHub Release publication.

### Published Python artifacts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `portable_resume-0.3.0-py3-none-any.whl` | 139434 | `63aa2e34a188dcfed5d4833224bf5682a59ef711e90715e651b1c1a446586bbc` |
| `portable_resume-0.3.0.tar.gz` | 119262 | `a4b26ae2cb4e4db177cf3f9639fb6eeb758c0f31b0ea8c914d0d6a7c101a0055` |

The PyPI digests match the corresponding GitHub Release assets.
`SHA256SUMS`, `release-evidence.json`, eight direct Skill archives, and seven
plugin/marketplace archives are attached to the same release.

### v0.3.0 fresh verification

Local verification on 2026-07-24 used:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Results: **64/64** package cells, **64/64** installed-reader cells, and
**264** Python tests passed. A separate empty virtual environment installed
`portable-resume==0.3.0` from public PyPI, ran `self-check`, produced the
64-cell matrix, installed all eight Skills into a temporary Qwen user root, and
verified that installation successfully.

Native local plugin/extension installation passed for Claude, Codex, Qwen,
Grok, Antigravity, and Kimi. Cursor native plugin loading, host UI
natural-language/picker activation, and public host marketplace installation
remain **not-run**. Cursor's full bubble graph remains **not claimed**. PyPI
publication does not satisfy those separate host evidence gates.

## Historical archive: v0.2.3

`v0.2.3` remains historical only: commit
`5ff9eba503e28971e5044015cd0666c2807a3d89`, [Actions run
29890453185](https://github.com/ImL1s/resume-skills/actions/runs/29890453185),
Ubuntu/macOS × Python 3.11/3.12. It does not prove the 0.3.0 changes.
