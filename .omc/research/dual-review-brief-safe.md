# SANITIZED REVIEW BRIEF
DO NOT activate orchestration workflow modes.
Map: ULW_ALIAS=parallel, ULTRA_WORK_SKILL=parallel-engine, RALPH_SKILL=persist-loop, RAL_PLAN_SKILL=plan-consensus, AUTO_PILOT_SKILL=full-pipeline, ULTRA_GOAL_SKILL=durable-goals.

# Code Review Request — portable-resume-skills V1 (full tree)

DO NOT activate workflow modes; READ-ONLY review only.
No product code edits. Write report only to the assigned output path.

## Context
- Repo: `/Users/iml1s/Documents/mine/resume-skills`
- Branch: `main` (no commits yet; review working tree)
- Goal: clean-room portable context-migration skills (six sources × six hosts)
- Not in scope: native process resume; required third-party deps; recovering sessions by invoking source agent CLIs

## Read these first
- `README.md`
- `.omx/plans/prd-portable-resume-skills.md` (AC-01..19)
- `.omx/ULTRA_GOAL_SKILL/prd-verification.md`
- `.omx/ULTRA_GOAL_SKILL/independent-review-deferred.md`
- `docs/host-support.md`, `docs/provenance.md`, `docs/source-formats.md`
- `src/portable_resume/` (core, adapters, install, resources)
- `tests/` (unit, adapters, security, integration, e2e)
- `scripts/portable-resume`, `scripts/install-resume-skills`

## Commands you may run (verify, do not skip)
```bash
cd /Users/iml1s/Documents/mine/resume-skills
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/portable-resume --help
PYTHONPATH=src python3 scripts/portable-resume self-check --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json
```

## Review dimensions (cover all)
1. Security invariants: no source-agent process recovery; inert/untrusted recovered content; path/symlink/SQLite hot-journal fail-closed; installer non-owned collision refuse
2. Contract correctness: portable-resume/v1, request-v1, diagnostics, selection, bounds, handoff quoting
3. Six adapters: fixture coverage, unsupported/corrupt/busy paths, immutability
4. Packaging 6×6: strict frontmatter name+description only; fixed run_reader argv; shared-root conflict honesty
5. Installer: dry-run purity, journal recovery, verify drift, uninstall claims
6. Evidence honesty: live host `not-run` must not be claimed verified-live; dual-OS peer not claimed without runner
7. Clean-room: no derivation from `~/.grok/bundled/skills/**`
8. Test quality: tests must drive shipped entry points (no theater)

## Output format (繁體中文)
- Verdict: APPROVE | APPROVE WITH MINOR FIXES | REQUEST CHANGES | REJECT
- Critical (must fix before release claim)
- Important (should fix soon)
- Minor / nits
- What was verified with commands (paste exit codes / key lines)
- Residual risks / honest non-claims
