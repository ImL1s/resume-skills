# Plan 030: Report user mistakes as `E_INVALID_INPUT`, constrain `--host`, and dedupe the shadow `family`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat a4dc4d6..HEAD -- src/portable_resume/install/cli.py src/portable_resume/install/discovery.py tests/`
> This plan was written against the working tree of branch
> `fix/issue-118-embedded-identity` (base commit `a4dc4d6`, with uncommitted
> changes present in `install/cli.py`). Compare the "Current state" excerpts
> against the live code before proceeding; on a mismatch, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (CLI UX / error contract)
- **Planned at**: commit `a4dc4d6`, 2026-07-31

## Why this matters

Three related defects make the installer's most common user mistakes report as
tool failures:

1. Running `install`/`verify`/`uninstall` with `--scope project` but no
   `--project` crashes inside root resolution and is swallowed by the blanket
   `except Exception`, emitting `E_INVARIANT` (exit 8, "An internal contract
   invariant failed") instead of `E_INVALID_INPUT` (exit 2). The correct guard
   exists for `install` but sits *after* the code that throws, so it is
   unreachable; `verify`/`uninstall` have no guard at all. `audit-host` gets it
   right, proving the intended contract.
2. `install`/`verify`/`uninstall`/`audit-host` accept `--host` as a free-form
   string, so a typo yields the content-free "The request is invalid." with no
   list of valid keys — while `quick-install` uses argparse `choices` and
   prints all valid keys.
3. `E_INSTALL_SHADOW`'s `family` array is built without dedup, so one blocking
   root holding 8 skills fills the entire `[:8]` cap with 8 identical tokens
   and truncates any second, genuinely different blocking root.

## Current state

- `src/portable_resume/install/cli.py` — the installer CLI.

  Targets are resolved before any project-scope validation (lines ~333–337):

```python
        hosts = _hosts(ns.host)
        targets = [
            (host, _root_for(host, ns.scope, ns.project, ns.home, ns.root))
            for host in hosts
        ]
```

  `_root_for` calls `resolve_skill_root(...)` which throws when
  `scope="project"` and `project_dir` is `None`. The blanket handler at the end
  of `run()` converts that into `E_INVARIANT`:

```python
    except Exception:
        return emit_diagnostic(DiagnosticError("E_INVARIANT"), stream=sys.stderr)
```

  The intended (currently unreachable for this failure) guard inside the
  install branch (lines ~346–347):

```python
            if ns.scope == "project" and not project_for_scan and not ns.root:
                raise DiagnosticError.invalid()
```

  The correct pattern already exists for `audit-host` (lines ~311–315):

```python
        if ns.command == "audit-host":
            if ns.host == "all" or ns.host not in HOST_KEYS:
                raise DiagnosticError.invalid()
            if ns.scope == "project" and not ns.project and not ns.root:
                raise DiagnosticError.invalid()
```

  `--host` argument definitions without `choices` (install at ~line 53; verify
  ~70; uninstall ~81; audit-host ~146):

```python
    inst.add_argument("--host", required=True, help="host key or 'all'")
```

  versus `quick-install` (lines ~97–103), the exemplar:

```python
    quick.add_argument(
        "host",
        nargs="?",
        default="all",
        choices=(*sorted(HOST_KEYS), "all"),
        help="host key; defaults to all",
    )
```

- `src/portable_resume/install/discovery.py` — `require_no_blocking_shadow`
  (lines ~1233–1239):

```python
    if report["aggregate_policy"] == POLICY_BLOCK:
        blockers = [
            f["root_id"]
            for f in report["findings"]
            if f.get("policy") == POLICY_BLOCK and not f.get("is_selected")
        ]
        raise DiagnosticError("E_INSTALL_SHADOW", family=tuple(blockers[:8]))
```

  In-repo dedupe precedent: `tuple(dict.fromkeys(...))` is used in
  `src/portable_resume/reader.py` for envelope warnings.

- Reproductions (verified during audit):
  - `install-resume-skills install --host claude --scope project` →
    `{"code":"E_INVARIANT","exit_code":8,...}` — should be exit 2.
  - `install-resume-skills install --host clade --scope global` →
    `E_INVALID_INPUT` with no key list — with `choices` argparse lists all keys.
  - Observed `family` on a real conflict: `["grok.project.primary" × 8]`.

- Conventions: content-free diagnostics (no dynamic content in messages);
  argparse `SystemExit` is already converted to the structured diagnostic at
  `cli.py` lines ~266–272 with exit 2 preserved — `choices` failures ride that
  path.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Repro (before fix) | `PYTHONPATH=src python3 scripts/install-resume-skills install --host claude --scope project; echo $?` | exits 8 before, 2 after |
| Unit tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Installer smoke | `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py` | exit 0 |
| Full local gate | `python3 scripts/self_verify.py` | exit 0 |

## Scope

**In scope**:
- `src/portable_resume/install/cli.py`
- `src/portable_resume/install/discovery.py` (the `blockers` dedupe only)
- `tests/unit/test_install_cli_validation.py` (create; or extend the existing
  installer CLI test module if one covers `run()` argument handling — check
  `grep -rln "install.cli" tests/unit/` first and follow its structure)
- `plans/README.md` — status row

**Out of scope**:
- The `E_INSTALL_SHADOW` message text or a remediation hint — that is plan 031.
- `require_no_blocking_shadow`'s policy logic (what blocks vs warns) — plan 031
  / CORRECTNESS-03 territory.
- `quick-install` behavior (already correct).
- The blanket `except Exception → E_INVARIANT` handler itself — it is the
  last-resort safety net; we fix the inputs that wrongly reach it.

## Git workflow

- Branch: `plan/030-installer-arg-validation`
- Commit style: `fix(install): validate scope/project before root resolution; constrain --host; dedupe shadow family`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Hoist project-scope validation before target resolution

In `run()` in `cli.py`, immediately after the `quick-install` alias block and
before ANY use of `ns.project`/`ns.root` for root resolution, add a shared
guard for the commands that take `--scope`:

```python
        if getattr(ns, "scope", None) == "project" and not getattr(ns, "project", None) and not getattr(ns, "root", None):
            raise DiagnosticError.invalid()
```

Place it so `install`, `verify`, and `uninstall` all hit it before the
`targets = [...]` comprehension. Keep the existing `audit-host` inline check
(harmless duplication) and keep the now-redundant install-branch check or
remove it — if removed, confirm the shadow-scan block still receives a
non-None `project_for_scan` in global scope (that fallback to `os.getcwd()`
stays untouched).

**Verify**: `PYTHONPATH=src python3 scripts/install-resume-skills install --host claude --scope project; echo $?` → stderr JSON has `"code":"E_INVALID_INPUT"`, exit `2`. Repeat for `verify` and `uninstall` → exit `2`.

### Step 2: Constrain `--host` with argparse choices

For `install`, `verify`, `uninstall`: `choices=(*sorted(HOST_KEYS), "all")`.
For `audit-host`: `choices=tuple(sorted(HOST_KEYS))` (it rejects `all`).
Keep `_hosts()` and the `audit-host` runtime check unchanged as defense in
depth. Keep each option's `help=` text.

**Verify**:
- `PYTHONPATH=src python3 scripts/install-resume-skills install --host clade --scope global; echo $?` → argparse usage lists valid keys on stderr, followed by the JSON diagnostic; exit `2`.
- `PYTHONPATH=src python3 scripts/install-resume-skills audit-host --host all --scope global; echo $?` → exit `2`.

### Step 3: Dedupe the shadow family

In `discovery.py`, change the raise to:

```python
        raise DiagnosticError("E_INSTALL_SHADOW", family=tuple(dict.fromkeys(blockers))[:8])
```

(Preserve first-seen order; cap after dedupe.)

**Verify**: `PYTHONPATH=src python3 -m unittest discover -s tests -q` → OK (no existing test asserts duplicated family entries; if one does, STOP).

### Step 4: Tests

In the new/extended test module (unittest):

1. For each of `install`, `verify`, `uninstall`: invoke
   `portable_resume.install.cli.run([...])` with `--scope project` and no
   `--project`, capture stderr, assert exit code 2 and `"code":"E_INVALID_INPUT"`.
2. `--host` typo on `install` exits 2 (SystemExit path preserved).
3. Family dedupe: `unittest.mock.patch` `scan_skill_duplicates` in
   `discovery` to return a report with `aggregate_policy = POLICY_BLOCK` and
   findings containing duplicated `root_id`s plus one distinct second root;
   call `require_no_blocking_shadow(...)`; assert the raised error's `family`
   contains each root exactly once and includes the second root.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.unit.test_install_cli_validation -v` → all pass.

### Step 5: Full gates

**Verify**: full unittest suite OK; `smoke_installed_matrix.py` exit 0;
`self_verify.py` exit 0; `check_secrets.py` exit 0.

## Test plan

- New tests as in Step 4 (≥ 5 cases: 3 commands × missing-project, host typo,
  family dedupe).
- Existing installer tests must stay green — especially
  `tests/integration/test_matrix_and_installer.py` (exercises multi-root
  installs and compensation).
- Verification: `PYTHONPATH=src python3 -m unittest discover -s tests -q` → all pass.

## Done criteria

- [ ] The three repro commands exit 2 with `E_INVALID_INPUT` (was 8 / `E_INVARIANT`)
- [ ] `--host` typos on install/verify/uninstall/audit-host list valid keys via argparse and exit 2
- [ ] `family` in `E_INSTALL_SHADOW` is deduplicated (test proves a second root survives the cap)
- [ ] Full suite + smoke matrix + self_verify + check_secrets all pass
- [ ] No files outside the in-scope list modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The `cli.py` control flow around lines 333–360 no longer matches the excerpt
  (e.g. #32/#118 follow-up landed) — re-map before editing; report if the guard
  placement is no longer obvious.
- Any existing test asserts exit 8 / `E_INVARIANT` for these inputs (would
  mean the current behavior was intentionally pinned — report, don't overwrite).
- Adding `choices` changes the exit code for host typos to anything other
  than 2.

## Maintenance notes

- Future subcommands that take `--scope` must go through the same hoisted
  guard; a reviewer should reject a new subcommand that resolves roots before
  validation.
- The `[:8]` family cap is now post-dedupe; if the diagnostic schema ever
  grows a root-count field, revisit.
- Deferred: static remediation hint for `E_INSTALL_SHADOW` (plan 031);
  argparse-prose-vs-JSON stream separation (UX-08, unplanned this round).
