# Plan 041: Document the fast contributor loop (`--profile`/`--only`, editable install, pytest)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- CONTRIBUTING.md scripts/self_verify.py`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (docs only)
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `a4dc4d6`, 2026-07-31
- **Issue**: https://github.com/ImL1s/resume-skills/issues/141

## Why this matters

The documented pre-PR gate costs ~6 minutes measured (self_verify ~199 s +
smoke matrix ~73 s + unittest ~78 s + secrets ~1 s), and contributors pay all
of it for every iteration on a one-line change because `CONTRIBUTING.md`
documents only the unqualified commands. The staged solution already exists —
`scripts/self_verify.py --profile {ci-compat,ci-quality,local}` and
`--only STAGE` were built for issue #67 and CI uses them — but no
contributor-facing doc mentions them. Likewise `pip install -e .` yields
working console scripts (declared in `pyproject.toml [project.scripts]`) and
pytest collects the suite cleanly, yet every documented command uses
`PYTHONPATH=src python3 scripts/...` and unittest only. Three paragraphs fix a
6-minute loop.

## Current state

- `CONTRIBUTING.md` "Required checks" (verbatim today):

```markdown
Run all four before opening a pull request:

​```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
​```
```

- `scripts/self_verify.py` — stages and profiles (lines ~30–47): profiles
  `local` (all stages), `ci-compat` (`compile`, `unit`, `reader_self_check`,
  `installer_matrix`, `fixture_list_show`), `ci-quality` (`version_state`,
  `docs`, `secrets`); `--only STAGE` runs a single stage. The module docstring
  (line ~4) says stages are selectable "so local and CI can share one source
  of truth without re-running the same expensive work twice".
- `pyproject.toml`:

```toml
[project.scripts]
portable-resume = "portable_resume.reader:main"
install-resume-skills = "portable_resume.install.cli:main"
```

- pytest status: `PYTHONPATH=src python3 -m pytest tests -q --collect-only`
  collects the full suite (verified: 757 tests, matching unittest). pytest is
  NOT a project dependency and CI does not use it — the doc must present it as
  an optional local convenience, never a gate.
- `AGENTS.md` "Verify before claiming done" repeats the four commands and
  notes `Scripts under scripts/ inject src onto sys.path. Unittest still needs
  PYTHONPATH=src (or pip install -e .).` — the editable-install hint exists
  there but not in CONTRIBUTING.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Stage list | `python3 scripts/self_verify.py --help` | shows `--profile`, `--only`, stage names |
| Spot-check | `python3 scripts/self_verify.py --only docs` | runs the docs stage only, exit 0 |
| Docs gate | `python3 scripts/check_docs.py` | exit 0 |

## Scope

**In scope**: `CONTRIBUTING.md`, `plans/README.md` row. Optionally
`AGENTS.md` (one cross-reference line).

**Out of scope**:
- `scripts/self_verify.py` (no code changes — document what exists).
- `pyproject.toml` (do NOT add pytest to dev extras without maintainer
  approval — the empty `dev = []` may be deliberate).
- README (user-facing; contributor loop belongs in CONTRIBUTING).

## Git workflow

- Branch: `plan/041-contributor-fast-loop-docs`
- Commit style: `docs(contributing): document staged verification, editable install, pytest convenience`

## Steps

### Step 1: Add "Fast iteration" to CONTRIBUTING.md

Insert after the "Required checks" block (keep that block verbatim — the full
gate remains the pre-PR truth):

```markdown
### Fast iteration during development

The full gate above takes several minutes. While iterating, run only what your
change touches; the full gate remains mandatory before opening the PR.

​```bash
# Stage-scoped verification (same stages CI uses; see --help for the list)
python3 scripts/self_verify.py --only unit          # just the unittest stage
python3 scripts/self_verify.py --only docs          # after doc edits
python3 scripts/self_verify.py --profile ci-compat  # what one CI matrix cell runs

# One test module / one test
PYTHONPATH=src python3 -m unittest tests.unit.test_reader_contract -v
PYTHONPATH=src python3 -m unittest tests.unit.test_reader_contract.ClassName.test_name
​```

### Editable install (drops the PYTHONPATH prefix)

​```bash
pip install -e .
portable-resume self-check
install-resume-skills hosts
​```

### pytest (optional local convenience)

The authoritative runner is unittest (what CI runs). If you have pytest
installed, the suite collects cleanly and gives you `-k` filtering and `-x`:

​```bash
PYTHONPATH=src python3 -m pytest tests -q -k cline -x
​```

Do not add pytest-only constructs (fixtures, markers) to the tests.
```

Adjust the example module names to real ones (`ls tests/unit | head`) before
committing.

**Verify**: `python3 scripts/check_docs.py` → exit 0 (CONTRIBUTING is not in
its enforced set today, but run it anyway); every command in the new section
executes successfully when copy-pasted (run each once).

### Step 2: Cross-reference from AGENTS.md (optional, one line)

After the verify block in `AGENTS.md`, add:
`Staged/faster local runs: see CONTRIBUTING.md "Fast iteration".`

**Verify**: `grep -n "Fast iteration" AGENTS.md CONTRIBUTING.md` → 2 hits.

### Step 3: Full gates

**Verify**: `python3 scripts/self_verify.py` → 0; `python3 scripts/check_secrets.py` → 0.

## Test plan

Docs-only. The verification is that every documented command was executed
once and exited 0 (list them with their observed exit codes in the completion
report).

## Done criteria

- [ ] CONTRIBUTING has the three subsections; all commands verified by running them
- [ ] Full-gate block unchanged and still labeled mandatory pre-PR
- [ ] pytest framed as optional; "no pytest-only constructs" sentence present
- [ ] Gates green; `plans/README.md` updated

## STOP conditions

- `self_verify.py --only unit` does not exist or stage names differ from the
  excerpt (in-flight #118 edits) — document the real names; if profiles were
  removed, STOP.
- `pip install -e .` fails on this tree (setup.py/#118 in-flight state) — omit
  the editable section, report why.
- pytest collection errors on the current tree — omit the pytest section,
  report the error.

## Maintenance notes

- If a new stage is added to `self_verify.py`, the CONTRIBUTING examples stay
  valid (they reference `--help` for the list) — reviewers should keep example
  stage names real.
- The "no pytest-only constructs" line is the guard that keeps unittest
  authoritative; reviewers should reject `@pytest.mark` imports in tests.
