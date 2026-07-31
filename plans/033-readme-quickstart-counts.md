# Plan 033: Fix the broken README onboarding path and the stale counts (thirteen/nine/alt-text/CHANGELOG)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On any
> STOP condition, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- README.md docs/install-hosts.md CHANGELOG.md`
> Written against the working tree of branch `fix/issue-118-embedded-identity`
> (base `a4dc4d6`). On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (docs only)
- **Depends on**: none. **Coordinate with plan 042** (registry-generated docs):
  042 is the root-cause fix for count drift; this plan is the immediate
  correction. If 042 has already landed, re-check whether these spots are now
  generated regions and skip any that are.
- **Category**: docs
- **Planned at**: commit `a4dc4d6`, 2026-07-31

## Why this matters

The README quick start breaks at its second step for the exact audience it
targets: a `pipx` user has no `src/` or `scripts/`, yet every advanced command
in the README uses the `PYTHONPATH=src python3 scripts/...` checkout form.
Separately, three stale numbers contradict the project's headline "17 sources ×
18 hosts": `docs/install-hosts.md` says "thirteen profiles", the README hero
image alt text says "Nine sources … nine sessions", and `CHANGELOG.md` has a
structural defect (an `## Unreleased` section *above* the `# Changelog` H1,
plus a second `## Unreleased` below it). For a project whose brand is evidence
discipline, self-contradiction in the first ten lines is a real cost.

## Current state

- `README.md:4` — hero alt text:

```
  <img src="docs/assets/portable-resume-skills-hero-v2.jpg" alt="Nine local coding-agent sources flow into a sealed context archive, then into nine fresh destination sessions" width="920" />
```

  while `README.md:8` says "17 sources × 18 hosts (derived from registries)".

- `README.md:99-121` — under "The lower-level transactional command remains
  available…", all commands are checkout-form, e.g.:

```
PYTHONPATH=src python3 scripts/portable-resume --version
PYTHONPATH=src python3 scripts/install-resume-skills --version
python3 scripts/check_version_state.py --require-git --json
PYTHONPATH=src python3 scripts/portable-resume claude show latest \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --format handoff
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --dry-run
```

  The installed-form equivalents (`portable-resume …`,
  `install-resume-skills …`) are never shown for these commands. The installer
  itself models the split correctly: `install-resume-skills hosts` prints both
  `cmd:` (installed) and `source_checkout:` variants per host (see
  `src/portable_resume/install/catalog.py`, `_installer_command_pair`).

- `docs/install-hosts.md:48`:

```
install-resume-skills quick-install all         # all thirteen user-global profiles
```

  Actual host count is 18 (registry-derived; `install-resume-skills hosts`
  prints "Destination hosts: 18").

- `CHANGELOG.md` structure (verified):
  line 1 `## Unreleased` … line 48 `# Changelog` … line 50 `## Unreleased`.
  The two Unreleased sections' contents must be merged under the H1.

- Docs gate: `python3 scripts/check_docs.py` enforces required commands/links
  and locale files; `scripts/check_docs.py` REQUIRED_COMMANDS includes
  `pipx install portable-resume` and `install-resume-skills quick-install all`
  — keep those strings intact in README.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Docs gate | `python3 scripts/check_docs.py` | exit 0 |
| Full gate | `python3 scripts/self_verify.py` | exit 0 |
| Count truth | `PYTHONPATH=src python3 -c "from portable_resume.install.catalog import HOST_KEYS; print(len(HOST_KEYS))"` | `18` |

## Scope

**In scope**: `README.md`, `docs/install-hosts.md` (line 48 comment only),
`CHANGELOG.md` (structure merge only), `plans/README.md` status row.

**Out of scope**:
- `docs/i18n/**` — the 12-locale "nine destinations" drift is plan 042's
  one-time reconciliation (root-cause fix); don't hand-edit locales here.
- `docs/host-support.md` "9×9=81" line — also plan 042 (generated region).
- `scripts/check_docs.py` — plan 042 rewires its host list.
- CHANGELOG *content* (entries themselves) — merge structure only, do not
  rewrite or drop any entry text.

## Git workflow

- Branch: `plan/033-readme-quickstart-counts`
- Commit style: `docs: split installed vs checkout quick start; fix stale counts and CHANGELOG structure`

## Steps

### Step 1: Fix the alt text

Reword `README.md:4` alt to be count-free, e.g. "Local coding-agent session
stores flow into a sealed context archive, then into fresh destination
sessions". No number in the sentence.

**Verify**: `grep -n "Nine\|nine" README.md` → no hit on line 4 (other
legitimate uses may exist — check each remaining hit is not a source/host
count claim; the "nine direct-skill ZIPs" release note at ~line 129 describes
the historical v0.3.4 release and stays).

### Step 2: Split the lower-level section into installed vs checkout forms

Restructure `README.md:96-121` into two clearly labeled variants. Pattern:

```markdown
Installed (pipx/pip):

​```bash
portable-resume self-check
install-resume-skills matrix
install-resume-skills install --host qwen --scope project --project "$PWD" --dry-run
install-resume-skills verify  --host qwen --scope project --project "$PWD"
​```

From a source checkout (no install):

​```bash
PYTHONPATH=src python3 scripts/portable-resume self-check
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --dry-run
​```
```

Keep every currently shown command available in at least one form; keep the
fixture `show` example under the checkout block (it references
`tests/fixtures/...`, which only exists in a checkout — say so in one
sentence). `python3 scripts/check_version_state.py --require-git --json` is
checkout-only (script not shipped in the wheel) — keep it under checkout.

**Verify**: `python3 scripts/check_docs.py` → exit 0; every REQUIRED_COMMANDS
string still present: `grep -c "pipx install portable-resume" README.md` ≥ 1,
`grep -c "install-resume-skills quick-install all" README.md` ≥ 1.

### Step 3: Fix the thirteen

`docs/install-hosts.md:48`: change the comment to count-free:
`# all user-global profiles (count derives from the registry)`.

**Verify**: `grep -n "thirteen" docs/install-hosts.md` → no matches.

### Step 4: Merge the CHANGELOG structure

Move the content of the top `## Unreleased` block (lines 1–47) under the
`# Changelog` H1, merging with the existing `## Unreleased` there (concatenate
bullet lists, deduplicate identical bullets if any, preserve every unique
entry's text verbatim). Result: file starts with `# Changelog`, exactly one
`## Unreleased`.

**Verify**: `grep -n "^# Changelog\|^## Unreleased" CHANGELOG.md` → exactly
two lines: `1:# Changelog` (or preceded only by blank/intro) and one
`## Unreleased`.

### Step 5: Full gates

**Verify**: `python3 scripts/check_docs.py` → 0; `python3 scripts/self_verify.py` → 0;
`python3 scripts/check_secrets.py` → 0.

## Test plan

Docs-only: the gates above are the tests. Additionally eyeball-render the
README section once (any Markdown preview) to confirm the two variants read
clearly.

## Done criteria

- [ ] README has explicit installed vs checkout blocks; a pipx user can run every installed-form command verbatim
- [ ] No count-bearing "nine/thirteen" claims remain in README alt text or install-hosts.md:48
- [ ] CHANGELOG has one `# Changelog` H1 at top and exactly one `## Unreleased`, no entry text lost (verify with `git diff --stat CHANGELOG.md` and a read-through of the diff)
- [ ] `check_docs.py`, `self_verify.py`, `check_secrets.py` all exit 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- `check_docs.py` fails on a REQUIRED_COMMANDS/REQUIRED_LINKS string you did
  not touch — pre-existing drift; report instead of widening scope.
- The CHANGELOG top block contains entries that conflict with (different text
  for the same change as) the lower Unreleased block — merging becomes a
  content decision; report with the conflicting pairs listed.
- Plan 042 landed first and converted any target line into a generated region
  marker — skip that line and note it in your report.

## Maintenance notes

- Plan 042 makes counts registry-generated; once it lands, this README section
  should contain no literal counts at all.
- Reviewer: check the CHANGELOG diff is purely structural (git word-diff makes
  dropped entries obvious).
