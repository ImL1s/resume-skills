# Plan 049: Stop promoting `pi` extension banners into "Latest explicit user request"

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b4611c..HEAD -- src/portable_resume/adapters/pi.py tests/`
> Written against `main` at `2b4611c`. On excerpt mismatch, STOP.

## Status

- **Implementation status**: **DONE**
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (scoped to one adapter)
- **Depends on**: none
- **Category**: bug (handoff content fidelity)
- **Planned at**: commit `2b4611c`, 2026-08-01
- **Issue**: https://github.com/ImL1s/resume-skills/issues/166

## Why this matters

The `pi` adapter maps any displayable `custom_message` — an
extension-injected banner — to `{"role": "user"}`. The session's
`last_user_request` is then derived as the last turn with `role == "user"`,
and the handoff labels it **"Latest explicit user request"**. Because injected
banners are typically the *newest* records, they reliably win that scan.

Reproduced against the committed fixture
`tests/fixtures/pi/s-pi-03-tool-and-custom`:

```
### Latest explicit user request
> synthetic custom extension context
```

The actual user request in that fixture is `synthetic request needing tools`
(turn `[0 user]`); the quoted text is a `custom_message` with
`customType: "synthetic-extension"`.

The field a resuming agent trusts most for "what was I asked to do" can
therefore be machine-injected text, under a heading that explicitly asserts
it is an *explicit user request* — a semantic the pipeline does not enforce.

## Current state

- **The promotion** — `src/portable_resume/adapters/pi.py` around lines
  610–617:

```python
        if kind == "custom_message":
            if entry.get("display") is not True:
                return [], found
            content = entry.get("content")
            if not isinstance(content, str) or not content.strip():
                found.append("W_MISSING_BLOB")
                return [], found
            return self._append_turn({"role": "user", "content": content, "timestamp": timestamp}, ordinal, query, budget, found), found
```

- **The scan that picks it up** — same file, around line 160:

```python
        last_user_request=next((turn.content for turn in reversed(values) if turn.role == "user"), None),
        last_assistant_action=next((turn.content for turn in reversed(values) if turn.role == "assistant"), None),
```

- **The heading** — `src/portable_resume/handoff.py` `_assemble` renders
  `### Latest explicit user request` from `session.last_user_request`.
- **The fixture** — `tests/fixtures/pi/s-pi-03-tool-and-custom` (render it
  with `--cwd /tmp/project --within-min 0`).
- **Roles available**: `user`, `assistant`, `tool` — check
  `src/portable_resume/model.py` and the envelope schema
  (`src/portable_resume/resources/portable-resume-v1.schema.json`) for the
  permitted role set **before** introducing any new role value.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Reproduce | `PYTHONPATH=src python3 scripts/portable-resume pi show latest --cwd /tmp/project --within-min 0 --source-root tests/fixtures/pi/s-pi-03-tool-and-custom/agent --format handoff` | before: banner under "Latest explicit user request"; after: the real request |
| Pi tests | `PYTHONPATH=src python3 -m unittest tests.unit.test_pi_adapter -v` | pass |
| Full suite | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK |
| Gates | `python3 scripts/self_verify.py && python3 scripts/check_secrets.py` | exit 0 |

## Scope

**In scope**: `src/portable_resume/adapters/pi.py`; `tests/unit/test_pi_adapter.py`
(and any other pi test module); `plans/README.md` row.

**Out of scope**:
- Introducing a new role value in the public envelope — see STOP conditions.
- Dropping `custom_message` turns from the transcript entirely: they are
  legitimate recovered context and must still appear in the bounded evidence,
  just not as *the user's request*.
- Other adapters — audit and report only (Step 4).
- The `### Latest explicit user request` heading text — plan 047 territory.

## Git workflow

- Branch: `plan/049-pi-custom-message-role`
- Commit style: `fix(pi): custom_message must not become the latest user request`

## Steps

### Step 1: Choose the mechanism (record the choice)

Two options — pick ONE and state it in your report:

**A. Exclude non-authored turns from the scan** (preferred; no schema
surface): keep `role: "user"` so the banner still renders in the transcript,
but mark the turn as non-authored (e.g. a local flag on the dict the adapter
builds, or track the ordinal) and skip such turns when computing
`last_user_request`.

**B. Give `custom_message` a different role**: cleaner semantically, but only
viable if the envelope schema already permits the role you pick. Verify
against the schema first — inventing a role value is a public contract change.

Prefer **A** unless the schema plainly allows B.

**Verify**: choice recorded before code changes.

### Step 2: Implement

Apply the chosen mechanism so that:
- `last_user_request` reflects the newest **authored** user turn;
- the `custom_message` content still appears in `### Bounded transcript
  evidence` (it is real recovered context);
- when a session contains *only* custom messages and no authored user turn,
  `last_user_request` is `None` and the handoff renders its existing
  `_(not persisted)_` form rather than falling back to a banner.

**Verify**: the reproduce command now shows `synthetic request needing tools`
under "Latest explicit user request", and the banner text is still present in
the transcript section.

### Step 3: Tests

In the pi test module:
1. The fixture above: `last_user_request` is the authored request, not the
   banner.
2. The banner still appears in the rendered handoff transcript.
3. Custom-message-only session → `last_user_request` is `None`, handoff
   renders the not-persisted form, exit 0.
4. `display: false` custom messages remain excluded entirely (existing
   behavior — pin it).

Assert at least (1) and (2) through **rendered handoff text**, not only the
adapter's Python objects.

**Verify**: new tests pass; full suite OK.

### Step 4: Audit other adapters for the same promotion (report only)

Search for synthesized/injected records mapped to `role: "user"`:

```bash
grep -rn '"role": "user"' src/portable_resume/adapters/
```

For each hit, note whether the source record is genuinely user-authored or
machine-generated (summaries, banners, system notices, tool wrappers).
**Do not fix others here** — list them in the completion report as the scope
of a follow-up.

**Verify**: report contains one line per hit.

### Step 5: Full gates

**Verify**: full suite OK; `self_verify.py` → 0; `check_secrets.py` → 0;
smoke matrix → 0.

## Test plan

Step 3 (4 cases). Structural pattern: existing `tests/unit/test_pi_adapter.py`
plus whichever module asserts on rendered handoff text.

## Done criteria

- [ ] The reproduce command shows the authored request, not the extension banner
- [ ] Banner content still visible in the bounded transcript
- [ ] Custom-only session yields `None` (no banner fallback)
- [ ] No new role value added to the public envelope (`git diff` on the schema is empty)
- [ ] Cross-adapter audit list in the completion report
- [ ] Full suite + gates green; `plans/README.md` updated

## STOP conditions

- Option B looks necessary but the envelope schema does not permit the role —
  STOP; do not edit the schema.
- Another adapter turns out to have the same defect with a *worse* impact
  (e.g. injecting synthesized summaries as user requests on a flagship
  source) — report it prominently; it may deserve to jump the queue.
- Excluding banners from the scan makes an existing pi test fail because it
  asserted the banner *is* the last user request — report; that assertion
  pinned the bug.

## Maintenance notes

- Reviewer: check the fix does not silently drop `custom_message` from the
  transcript — the goal is correct attribution, not deletion.
- If `pi` later gains more synthesized record kinds, they must follow the
  same non-authored treatment; consider a shared helper if a second kind
  appears.
