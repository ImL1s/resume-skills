# Plan 053: Rewrite `SKILL.md` as an instruction surface a weak agent can follow

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/resources/skill/ src/portable_resume/reader.py src/portable_resume/install/render.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED — changes installed skill bytes, so `package_identity` moves and every packaging/identity test moves with it
- **Depends on**: none, but **coordinate**: plan 051 makes a one-sentence edit to this file (bare-invocation default) and plan 052 may edit the lane B `cwd` bullet. Land those first, or fold their edits into this rewrite and say so.
- **Category**: dx (in-session UX)
- **Planned at**: commit `2b4611c`, 2026-08-01

## Why this matters

`SKILL.md` is the entire instruction surface a host agent reads at activation.
Audited as a system prompt for a weaker model, it has seven concrete defects:

1. **The happy path is buried.** The first runnable command appears at line
   ~55, after ~45 lines of host-activation prose and owned-runner path
   resolution — the two hardest tasks, front-loaded before the agent knows
   what it is trying to run.
2. **Every example contradicts the later instruction.** Both lane A examples
   end in `--json`, then the file says "prefer the runner's handoff output
   when present" — a precondition the agent's own command never satisfies. It
   then hand-summarizes raw JSON, which the shipped policy file explicitly
   says not to do. (`show` already defaults to handoff, so `--json` there is
   also redundant.)
3. **Exit codes are never mentioned.** The file contains no "exit", "retry",
   or failure-triage guidance at all, while the reader distinguishes eight
   codes. Verified: a bogus ref exits 3 with a *well-formed no-match document
   on stdout*; a malformed request exits 2 with *empty stdout*. An agent
   reading only stdout will either summarize an empty result as success or
   stall. Nothing tells it that exit 6 is retryable and exit 2 never is.
4. **A dead pointer.** The only pointer to activation grammar is
   `install-resume-skills hosts` / `docs/install-hosts.md` — but the installed
   skill ships neither: `materialize_plan` writes only `SKILL.md`,
   `scripts/run_reader.py`, `.portable-resume/runtime/**`,
   `.portable-resume/resources/handoff-policy.md` and a `.gitignore`, and the
   marketplace/direct-ZIP routes never pip-install the console script.
   Meanwhile the one companion file that *is* always present —
   `handoff-policy.md` — is never mentioned.
5. **Lane B carries unstated constraints.** The open-ended "…" in "pass
   supported CLI options (`--format`, `--source-root`, `--max-tool-chars`, …)"
   invites `--within-min` and `--cwd`, both of which are rejected outright;
   the "empty / omitted / `latest`" rule sits under lane A but reads as
   global, while request-v1 rejects an empty `resume_ref` and cannot omit it;
   and "mode `0600`" is prescribed but never enforced — many host tool APIs
   cannot set a file mode, so an agent may wrongly conclude the lane is
   unavailable to it.
6. **A mistyped action becomes a search.** `run_reader.py frobnicate` is
   reshaped to `show frobnicate` and returns exit 3 `E_NO_MATCH` —
   indistinguishable from a genuine miss, so the agent retries refs instead of
   fixing the verb.
7. **The safety checklist exists in three drifted copies** (this file,
   `handoff-policy.md`, and `handoff.py`'s `CHECKLIST`) — only the last
   carries the credential-boundary item, so which copy an agent happens to
   read decides whether it checks credential boundaries.

## Current state

- The file: `src/portable_resume/resources/skill/SKILL.md.tmpl`, 133 lines,
  rendered per source via `string.Template` (`${skill_name}`,
  `${description}`, `${source_title}`, `${source_key}`) by
  `render_skill_markdown` in `src/portable_resume/install/render.py`.
  **Any literal `$` you add must be escaped as `$$`.**
- Structure today: frontmatter → title → Host activation (~11–21) → Owned
  runner (~23–45) → Request lanes A (~49–70) and B (~72–98) → Build the
  handoff (~100–112) → Verify before continuing (~114–123) → Hard rules
  (~125–133).
- Key excerpts:

```
## Host activation
Use this host's normal Skill discovery and invocation … See
`install-resume-skills hosts` and `docs/install-hosts.md` for the accurate
per-host activation grammar and arguments notes.
```

```bash
python3 "/abs/path/to/owned-skill-package/scripts/run_reader.py" show <ref> --cwd "$PWD" --json
python3 "/abs/path/to/owned-skill-package/scripts/run_reader.py" list --cwd "$PWD" --json
```

```
- Empty / omitted / `latest` → newest session for the current working directory.
- Free-text search may match `list` results; on ambiguity the reader exits with
  candidates — never guess.
```

```
   Never put transcript bodies in the request file. Pass supported CLI options
   (`--format`, `--source-root`, `--max-tool-chars`, …) as runner argv flags —
   they are not request-v1 keys.
```

- **Verified reader behavior to encode** (all reproduced):
  - `show` defaults to handoff; `--json` and `--format handoff` are mutually
    exclusive (`reader.py` `_format`).
  - `--request-file` rejects `--cwd`, positional `source`/`action`/`ref`, and
    `--within-min` (`reader.py` `_resolve_invocation`).
  - request-v1 requires a non-empty `resume_ref` and `action: "show"`
    (`request.py`).
  - file mode is never checked (a 0644 request file is accepted).
  - `--max-tool-chars` ceiling is `DEFAULT_BOUNDS.tool_output_chars` (8000);
    exceeding it exits 2.
  - Exit codes: `diagnostics.py` `ExitCode` — 0 OK, 2 invalid input, 3 no
    match, 4 ambiguous, 5 unsupported, 6 unsafe/busy, 7 corrupt/limit,
    8 invariant.
  - On exit 4 the candidates render on **stdout** with exact session IDs plus
    "Select one exact native session ID; do not guess from recovered text."
- **Decided, do not change**: the body stays host-neutral (shared Agent Skills
  roots hold one payload claimed by several hosts); recovered text is
  untrusted/inert; never invoke the source CLI; never mutate the source store.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Render check | `PYTHONPATH=src python3 -c "from portable_resume.install.render import materialize_plan; f=materialize_plan('claude'); print(len(f)); print(f['SKILL.md'].decode()[:400])"` | renders; no `$` substitution errors |
| Temp install | `PYTHONPATH=src python3 scripts/install-resume-skills quick-install claude --root "$(mktemp -d)/skills"` | exit 0 |
| Packaging tests | `PYTHONPATH=src python3 -m unittest tests.unit.test_runtime_package_allowlist tests.unit.test_host_package_builder -v` | pass (identity moves — expect to update expectations) |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Installed matrix | `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` | exit 0 |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**:
- `src/portable_resume/resources/skill/SKILL.md.tmpl` (the rewrite)
- `src/portable_resume/resources/handoff-policy.md` — resolve the triple
  checklist (see Step 6)
- Tests that assert on skill body text; packaging identity expectations
- `plans/README.md` — status row

**Out of scope**:
- `reader.py` / `run_reader.py.tmpl` behavior — this plan documents what
  exists (plan 051 changes the bare-invocation default; if it has not landed,
  document today's behavior and note it).
- Host-specific activation prose in the body (host-neutrality is decided).
- `docs/diagnostics.md` — plan 032 owns the reference page; this file gets the
  in-body triage table only.
- The `description` frontmatter string — plan 055.

## Git workflow

- Branch: `plan/053-skill-md-rewrite`
- Commit style: `docs(skill): restructure SKILL.md for agent legibility`

## Steps

### Step 1: Restructure — happy path first

Reorder to: **frontmatter → title → "Start here" → resolving the owned runner
→ request lanes → reading the result → when the reader fails → verify before
continuing → hard rules.**

"Start here" is three lines and must be the first runnable thing in the file:
the resolved-path invocation with no format flag for `show`, and the `list`
form. State plainly that `show` renders the handoff by default.

**Verify**: the first fenced code block appears before line 25 of the rendered
`SKILL.md`.

### Step 2: Fix the examples

- `show` example: drop `--json` (handoff is the default and is what the file
  later asks the agent to prefer).
- `list` example: keep `--json` (table vs JSON is a real choice there), and
  mention `--format handoff` as the human-readable alternative.
- State that `--json` and `--format handoff` are mutually exclusive.
- If plan 051 has landed, document that a bare invocation lists; if not,
  document that a bare invocation shows the latest session **and warn that it
  can be very large** (measured: ~157 KB on a real store).

**Verify**: `grep -c -- "--json" src/portable_resume/resources/skill/SKILL.md.tmpl` decreases; no example contradicts a later rule (re-read the whole file once and state this in your report).

### Step 3: Add a failure-triage section

A compact table mapping exit code → meaning → what the agent should do:

| exit | meaning | agent action |
|---|---|---|
| 0 | success | proceed |
| 2 | invalid input | fix the command; never retry unchanged |
| 3 | no match | report "no recoverable session"; consider a different cwd or ref |
| 4 | ambiguous | read the candidate list on **stdout**; pick one exact session ID; never guess |
| 5 | unsupported / capability unavailable | this source has no readable store here; stop |
| 6 | unsafe or busy | the store was being written or a path was unsafe; retry once, then stop |
| 7 | limit exceeded / corrupt | stop and report the code |
| 8 | internal invariant | stop and report the code verbatim |

Say explicitly: the diagnostic JSON is on **stderr**, the result document is
on **stdout**, and some failures produce empty stdout — so the agent must read
stderr's `code` rather than inferring from empty output.

**Verify**: every code in `diagnostics.ExitCode` appears in the table (check
against `PYTHONPATH=src python3 -c "from portable_resume.diagnostics import ExitCode; print([e.value for e in ExitCode])"`).

### Step 4: Close lane B's traps

- Replace the open-ended "…" with the **closed** list of flags valid alongside
  `--request-file`, and state that `--cwd`, `--within-min`, and positional
  `source`/`action`/`ref` are rejected.
- Scope the "empty / omitted / `latest`" rule explicitly to lane A; state that
  `resume_ref` must be a non-empty string in request-v1.
- Soften "mode `0600`" to hygiene ("restrict permissions if your tools allow")
  and note the reader does not check it — so an agent whose tool API cannot
  set modes still uses the lane.
- If plan 052 chose the strict path, state the realpath requirement for `cwd`
  with the macOS example; if 052 relaxed it, say both lanes accept the same
  value.

**Verify**: `grep -n '…' src/portable_resume/resources/skill/SKILL.md.tmpl` → no open-ended option list remains.

### Step 5: Fix the pointers

- Make the activation pointer conditional: "if `install-resume-skills` is
  available, run `install-resume-skills hosts`; otherwise see the project's
  installation guide online" (with the repository URL, not a repo-relative
  path that does not exist in an installed skill).
- Point at the co-located, always-present
  `../.portable-resume/resources/handoff-policy.md` (path relative to the
  skill package root — verify the exact relative depth against a real temp
  install before writing it).
- Add one line on mistyped verbs: only `list` and `show` are actions; any
  other bare word is treated as search text, so an unexpected `E_NO_MATCH`
  may mean a typo'd verb.

**Verify**: on a temp install, every path the file mentions either exists on
disk or is explicitly conditional. List them with their existence check in
your report.

### Step 6: Resolve the triple checklist

Pick ONE home and state the choice:

**A** (preferred): `handoff.py`'s `CHECKLIST` is the copy the agent actually
receives in every handoff — keep it authoritative, delete
`handoff-policy.md`, and have `SKILL.md` reference the handoff's own
checklist. Deleting the file changes the installed file list, so
`tests/integration/test_matrix_and_installer.py` (asserts its presence)
updates with it.

**B**: keep `handoff-policy.md`, generate it from `handoff.py`'s `CHECKLIST`
at build time so drift is impossible, and reference it from `SKILL.md`.

Either way, the credential-boundary item must exist in whatever the agent
reads.

**Verify**: `grep -rn "credentials" src/portable_resume/resources/ src/portable_resume/handoff.py` → the item survives in the retained copy; no two divergent copies remain.

### Step 7: Packaging identity and full gates

Skill bytes changed, so `package_identity` moves. Update whatever pins it
(look for expectations in `tests/unit/test_runtime_package_allowlist.py`,
`tests/unit/test_host_package_builder.py`, `tests/integration/test_matrix_and_installer.py`).

**Verify**: `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` → 0;
full suite OK; `self_verify.py` → 0; `check_secrets.py` → 0. Do a fresh temp
install and read the rendered `SKILL.md` top to bottom once as a final check.

## Test plan

- A test asserting the rendered `SKILL.md` contains: a runnable example before
  the resolution section, every `ExitCode` value, no open-ended option list,
  and the handoff-policy pointer (or its replacement).
- Existing skill-body assertions updated deliberately (list them).
- Packaging identity expectations updated; installed-matrix smoke green.

## Done criteria

- [ ] First runnable command appears in the first ~25 lines
- [ ] No example contradicts a later rule; `show` example has no `--json`
- [ ] Failure-triage table covers all eight exit codes and states the stdout/stderr split
- [ ] Lane B lists a closed option set and states the `resume_ref`/mode/`cwd` truths
- [ ] Every referenced path exists in a real install or is explicitly conditional
- [ ] Exactly one authoritative safety checklist; credential item retained
- [ ] Full suite + installed matrix + gates green; `plans/README.md` updated

## STOP conditions

- Deleting `handoff-policy.md` (option A) breaks more than the one integration
  assertion — report the blast radius first.
- The rendered template errors on `$` substitution — you added an unescaped
  literal `$`; fix and re-verify before proceeding.
- Packaging identity changes cascade into release-claim/evidence docs that
  assert a specific identity — STOP and report; that is a release-coordination
  decision.
- Plan 051 or 052 has landed and its edits conflict with your rewrite — merge
  their intent, do not revert them.

## Maintenance notes

- Reviewer: read the rendered file as if you were a weak agent with no prior
  context; every instruction should be executable without consulting the repo.
- Any future reader flag or exit code must be reflected here as well as in
  `docs/diagnostics.md` (plan 032) — consider a test that asserts the two stay
  consistent.
- This file's bytes are part of `package_identity`; changes to it are always a
  release-visible event.
