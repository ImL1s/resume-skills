# Evidence summary

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

## Fresh local verification

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

Visual picker interaction and public host marketplace installation remain
**not-run**. Cursor's full bubble graph remains **not claimed**. PyPI
publication and local native-package acceptance do not satisfy those separate
host evidence gates.

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
