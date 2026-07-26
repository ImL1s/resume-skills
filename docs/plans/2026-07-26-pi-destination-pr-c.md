# Pi Destination (PR C) Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Pi as a ninth destination host (`.pi/skills` / `~/.pi/agent/skills`) so the registry-derived matrix becomes **9 sources × 9 destinations = 81**, without claiming native Pi UI activation.

**Architecture:** Reuse the existing host-neutral Skill payload and installer. Register `DestinationProfile(key="pi")` + matching `HostProfile` in `catalog.py`. Keep alternates (`.agents/skills`) documented only — do not multi-install. Update honesty docs/tests from `9×8=72` to `9×9=81`. Published `0.3.3` remains 64-cell.

**Tech Stack:** Python 3.11+ stdlib only, unittest, existing `portable_resume.install` + registries.

**Baseline on main:** Phase 0 (#49), Pi PR A/B (#50/#51), Codex follow-up (#54), OpenClaw/goose fixtures (#53/#55). Installer P0s #20/#31 partial-on-main already gate destination work.

**Process rules (non-negotiable):**
- Branch off latest `main`; one PR for this plan.
- Canonical verify before claiming done.
- **PR merge gate:** CI green **and** Codex/`@codex review` returned on **current HEAD**. Fix P1s; disposition P2s. Never merge while Codex is still pending/errored.
- Do not claim host UI / marketplace / dual-OS from installed-runner smoke alone.
- No real home paths in tracked files; stdlib-only; inert handoff only.

**Canonical verify:**

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
python3 scripts/check_docs.py
```

Expected after implementation: smoke **81/81**.

---

### Task 1: Failing tests for Pi destination registry + roots

**Files:**
- Modify: `tests/unit/test_registry.py`
- Modify: `tests/unit/test_hosts_catalog.py`
- Modify: `tests/unit/test_status_honesty.py` (prepare assertions that will fail until docs land in Task 4 — only change matrix/destination expectations that must fail with code, keep docs updates for Task 4)

**Step 1: Write the failing tests**

In `tests/unit/test_registry.py`, change `test_current_nine_sources_and_eight_destinations` to expect nine destinations including `pi`, and `cells == 81`. Rename for clarity if needed.

```python
def test_current_nine_sources_and_nine_destinations(self) -> None:
    self.assertEqual(
        enabled_source_keys(),
        frozenset(
            {
                "antigravity",
                "claude",
                "codex",
                "cursor",
                "grok",
                "kimi",
                "opencode",
                "pi",
                "qwen",
            }
        ),
    )
    self.assertEqual(
        enabled_destination_keys(),
        frozenset(
            {
                "antigravity",
                "claude",
                "codex",
                "cursor",
                "grok",
                "kimi",
                "opencode",
                "pi",
                "qwen",
            }
        ),
    )
    dims = matrix_dimensions()
    self.assertEqual(dims["sources"], 9)
    self.assertEqual(dims["destinations"], 9)
    self.assertEqual(dims["cells"], 81)
```

Also update `test_matrix_cells_match_dimensions` expected length from 72 → 81.

In `tests/unit/test_hosts_catalog.py` `test_default_roots_match_public_table`, add:

```python
"pi": (".pi/skills", ".pi/agent/skills"),
```

Add a focused install-root test:

```python
def test_pi_resolve_skill_roots(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        project = Path(tmp) / "proj"
        home.mkdir()
        project.mkdir()
        project_root = resolve_skill_root(
            host="pi", scope="project", project_dir=str(project), home_dir=str(home)
        )
        global_root = resolve_skill_root(
            host="pi", scope="global", project_dir=str(project), home_dir=str(home)
        )
        self.assertTrue(project_root.endswith(os.path.join("proj", ".pi", "skills")))
        self.assertTrue(
            global_root.endswith(os.path.join("home", ".pi", "agent", "skills"))
        )
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.unit.test_registry.RegistryInvariantTests.test_current_nine_sources_and_nine_destinations \
  tests.unit.test_hosts_catalog.HostsCatalogTests.test_default_roots_match_public_table \
  tests.unit.test_hosts_catalog.HostsCatalogTests.test_pi_resolve_skill_roots -v
```

Expected: FAIL — `pi` missing from destinations / HOST_PROFILES / KeyError.

**Step 3: Commit failing tests only**

```bash
git add tests/unit/test_registry.py tests/unit/test_hosts_catalog.py
git commit -m "$(cat <<'EOF'
test: expect Pi destination in 9×9 registry matrix

Lock PR C acceptance before wiring HostProfile roots (#38).
EOF
)"
```

---

### Task 2: Register Pi destination + HostProfile

**Files:**
- Modify: `src/portable_resume/registry.py`
- Modify: `src/portable_resume/install/catalog.py`

**Step 1: Minimal implementation**

In `registry.py`:

1. Add to `_DESTINATION_PAYLOAD_PROFILES`: `"pi": "pi-v1"`.
2. Add to `_DESTINATION_ROOTS`: `"pi": (".pi/skills", ".pi/agent/skills")`.
3. Either extend the comprehension source beyond `_EIGHT_KEYS` for destinations, or after the eight-key loop:

```python
DESTINATION_PROFILES["pi"] = DestinationProfile(
    key="pi",
    payload_profile="pi-v1",
    status="supported",
    direct_skill=True,
    project_rel=".pi/skills",
    global_rel=".pi/agent/skills",
)
```

Prefer keeping `_EIGHT_KEYS` for the original eight and explicitly appending `pi` (mirrors source registration style).

In `catalog.py` `HOST_PROFILES`, add a full `HostProfile` for `pi`:

```python
"pi": HostProfile(
    key="pi",
    profile_id="pi-v1",
    project_rel=".pi/skills",
    global_rel=".pi/agent/skills",
    display_name="Pi agent",
    official_docs=(
        "https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md",
    ),
    project_layout="<project>/.pi/skills/<name>/SKILL.md",
    global_layout="~/.pi/agent/skills/<name>/SKILL.md",
    alternate_project_roots=(".agents/skills",),
    alternate_global_roots=("~/.agents/skills",),
    install_methods=(
        "This installer: install-resume-skills install --host pi --scope project|global",
        "Manual: copy each resume-*/ folder into .pi/skills/ or ~/.pi/agent/skills/",
    ),
    activation_help=(
        "Invoke `/skill:resume-<source>` (Pi progressive disclosure). "
        "Any invocation tail is substituted into the skill prompt only; it is never process argv."
    ),
    activation_examples=(
        "/skill:resume-codex",
        "/skill:resume-pi",
    ),
    arguments_note=(
        "If this host expands invocation tail into the skill prompt, use that text as the "
        "session <ref> (or omit for latest). It is never process argv by itself. "
        "Optional advanced path: write portable-resume/request-v1 then "
        "`run_reader.py --request-file <path>`."
    ),
    caveats=(
        "Pi has no built-in permission system; recovered text is inert/untrusted and must not be executed.",
        "Alternate .agents/skills roots are compatibility-only; this installer defaults to .pi paths.",
        "Visual picker / native CLI activation evidence is a separate not-run claim until PR D.",
    ),
    evidence_notes=(
        "Pi Agent Skills docs: project .pi/skills and global ~/.pi/agent/skills "
        "(checked 2026-07-26). Installed-runner smoke is filesystem packaging only."
    ),
    evidence_level="verified-filesystem",
),
```

Do **not** add native package surfaces / marketplace builders for Pi in this PR.

**Step 2: Run Task-1 tests — expect PASS**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_registry tests.unit.test_hosts_catalog -q
```

**Step 3: Commit**

```bash
git add src/portable_resume/registry.py src/portable_resume/install/catalog.py
git commit -m "$(cat <<'EOF'
feat: add Pi destination Skill roots to registries

Enable .pi/skills and ~/.pi/agent/skills direct installs (#38 PR C).
EOF
)"
```

---

### Task 3: Installer + installed-runner matrix green at 81

**Files:**
- Modify only if needed: `tests/integration/test_matrix_and_installer.py` (should already use `matrix_dimensions()`)
- Possibly touch `scripts/smoke_installed_matrix.py` only if fixture map hard-codes destinations (prefer dynamic)

**Step 1: Add/adjust a focused install lifecycle test for host=`pi`**

```python
def test_pi_install_verify_uninstall(self) -> None:
    root = self.makeTemp()  # use existing temp helper pattern in file
    plan = plan_install(host="pi", scope="project", root=root)
    execute_install(plan)
    verify = verify_install(host="pi", scope="project", root=root)
    self.assertTrue(verify["ok"])
    skill = Path(root) / ".pi" / "skills" / "resume-claude" / "SKILL.md"
    self.assertTrue(skill.is_file())
    uninstall = uninstall_install(host="pi", scope="project", root=root)
    self.assertTrue(uninstall["ok"])
```

Mirror the exact helper names already used in `test_install_verify_reinstall_uninstall` — do not invent new APIs.

**Step 2: Run**

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_matrix_and_installer -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Expected: PASS; smoke prints `cells=81/81`.

**Step 3: Commit**

```bash
git add tests/integration/test_matrix_and_installer.py
git commit -m "$(cat <<'EOF'
test: cover Pi destination install lifecycle and 81-cell smoke

Prove packaging matrix expands with destination pi (#38).
EOF
)"
```

If smoke already passes with zero test-file changes, commit only if a new focused test was added; otherwise skip empty commit.

---

### Task 4: Honesty docs + honesty-test updates

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/host-support.md`
- Modify: `docs/install-hosts.md`
- Modify: `docs/source-formats.md` (Pi destination row)
- Modify: `README.md` / `AGENTS.md` (9×9=81 language; keep published 0.3.3 = 64)
- Modify: `tests/unit/test_status_honesty.py`
- Optionally update status banner in `docs/plans/2026-07-26-next-wave-support.md` (Task 13 done)

**Step 1: Update honesty tests first (TDD for docs)**

```python
# test_status_does_not_claim_next_wave_supported:
# REMOVE forbidden "pi destination: supported" check OR replace with allowing
# "Pi destination" + "supported" only when STATUS clearly means filesystem install,
# while still forbidding native UI claims.
self.assertNotIn("OpenClaw: supported", text)
self.assertNotIn("goose source: supported", text.lower())
# Allow Pi destination filesystem support; forbid premature UI claim:
self.assertNotRegex(text, r"(?i)pi[^.\n]{0,40}(picker|native activation).{0,20}pass")

# matrix language:
self.assertRegex(text, r"9\s*[×x]\s*9\s*=\s*81|9×9=81|currently 9×9")

# test_status_reflects_pi_merge_honesty:
# Require destination supported for install/smoke, and UI still not-run:
self.assertRegex(text, r"(?i)pi.*destination.*(supported|pass)")
self.assertRegex(text, r"(?i)(native|picker|host.?ui).*(not-run|not claimed)")
```

Also update `test_agents_md_uses_registry_derived_matrix_language` to accept `9×9`.

**Step 2: Run honesty tests — expect FAIL**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_status_honesty -v
```

**Step 3: Edit docs to match**

Minimum STATUS changes:
- Destination profiles: **9** including Pi
- Packaging / installed-runner: **81/81** on `main` (`9×9=81`); published `0.3.3` still 64-cell
- Open work: Pi PR C filesystem destination **done**; PR D activation **not-run**
- Do **not** write the exact banned phrase `pi destination: supported` if honesty test still forbids it — prefer `Pi destination install: supported (filesystem)` / table cells

`docs/host-support.md`: add `pi-v1` row; note activation picker `not-run`.

`docs/install-hosts.md`: replace stale “eight destinations” with registry-derived nine; add Pi row.

**Step 4: Run full verify**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
python3 scripts/check_docs.py
```

**Step 5: Commit**

```bash
git add docs/ STATUS.md README.md AGENTS.md tests/unit/test_status_honesty.py docs/plans/2026-07-26-next-wave-support.md
git commit -m "$(cat <<'EOF'
docs: claim Pi destination filesystem support at 9×9=81

Keep published 0.3.3 at 64 cells; native Pi UI activation stays not-run.
EOF
)"
```

---

### Task 5: Open PR and enforce AI-review merge gate

**Files:** none (git/gh only)

**Step 1: Push branch and open PR**

Branch name: `feat/pi-destination-pr-c-2026-07-26`

PR title: `feat: add Pi destination Skill profile (9×9=81)`

PR body must include:
- Summary: Pi destination roots + 81-cell matrix
- Honesty: no native UI claim; 0.3.3 stays 64
- Test plan checklist (canonical four + check_docs)
- Explicit note: **Do not merge until CI green and Codex review returns on HEAD**

**Step 2: Comment `@codex review`**

**Step 3: Wait**

- Poll CI until all checks SUCCESS on HEAD
- Poll Codex until review comment names **this** HEAD SHA
- If P1 → fix, push, re-request `@codex review` on new HEAD
- If P2 → fix or document disposition in PR comment
- If Codex `Unknown error` → re-request; do not merge on empty/error

**Step 4: Squash-merge only when gate satisfied; delete branch**

```bash
gh pr merge <N> --squash --delete-branch
```

---

## Out of scope

- Pi native CLI activation evidence (PR D / `docs/host-ui-smoke.md`)
- OpenClaw/goose adapters (still fixtures-only)
- PackageSurface / marketplace archives for Pi
- Closing #38 entirely (leave open until PR D if activation is part of acceptance; or close with note that UI remains not-run — prefer leave open or partial comment)
- Raising published release to claim 81 cells

---

## Done when

- [ ] `enabled_destination_keys()` includes `pi`
- [ ] `matrix_dimensions()["cells"] == 81`
- [ ] smoke `81/81`
- [ ] Docs/honesty tests green
- [ ] PR merged only after CI + Codex on final HEAD
