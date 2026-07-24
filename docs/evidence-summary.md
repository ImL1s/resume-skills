# Evidence summary

## Current 0.3.0 local release candidate

The current tree defines eight source adapters × eight destination hosts.
Fresh local verification on 2026-07-24 used:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

| Claim | Current evidence |
|---|---|
| 64 Skill packages render/install | **pass**, self-check and matrix |
| 64 installed readers list/show fixtures | **pass**, exact synthetic identity/content checks |
| Python test suite | **264 tests pass** |
| Wheel and sdist import outside checkout | **pass**, both artifacts; 64 cells and verified Qwen quick-install |
| Local candidate wheel SHA-256 | `748c74ba1726c3b6bdcadc7667f6d424709b8b536440c5cb1c8c67ad6f8381ae` |
| Local candidate sdist SHA-256 | `7f7017e11889bff80bb6c583af60adfb8384cca10df1c6b120455d18d2d1071d` |
| 8 direct + 7 plugin/marketplace archives | **pass**, deterministic build and structure tests |
| Native local plugin/extension installation | **6/7 pass**: Claude, Codex, Qwen, Grok, Antigravity, Kimi |
| Cursor native plugin load | **not-run**; archive structure only |
| Host UI NL/picker activation | **not-run** |
| Public marketplace installation | **not-run** |
| `v0.3.0` dual-OS/tag release | **not-run** |
| Cursor full bubble graph | **not claimed** |

Native install versions, routes, and plugin digests are recorded in
[`host-ui-smoke.md`](host-ui-smoke.md). These local checks do not prove a
published marketplace listing or Skill activation through a host picker.

The release workflow will write `release-evidence.json` containing the resolved tag commit, Actions run URL, verified OS/Python bounds, matrix counts, artifact sizes/digests, and explicit `not-run` UI fields. `SHA256SUMS` and GitHub artifact attestations cover the release candidate.

## Historical archive: v0.2.3

| Field | Value |
|---|---|
| Date | 2026-07-22 |
| Tag / SHA | `v0.2.3` / `5ff9eba503e28971e5044015cd0666c2807a3d89` |
| Workflow | `ci` |
| Run | https://github.com/ImL1s/resume-skills/actions/runs/29890453185 |
| Jobs | Ubuntu/macOS × Python 3.11/3.12 succeeded |
| Scope | historical six-by-six release only |

Do not reuse that run as proof for 0.3.0.

## Remote sign-off template

After the new tag succeeds, append rather than pre-claim:

```text
Tag: vX.Y.Z
Commit: <40-hex SHA>
Actions: <immutable run URL>
GitHub Release: <release URL>
PyPI: <project/version URL or explicitly skipped>
Maintainer/date: <name>, <ISO date>
```
