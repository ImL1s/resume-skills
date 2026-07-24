# Evidence summary

## Published archive: v0.3.0

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

## Fresh verification

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
