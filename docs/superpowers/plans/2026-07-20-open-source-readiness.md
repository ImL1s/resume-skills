# Open-Source Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `resume-skills` safe to flip public on GitHub without leaking local paths/PII, without overclaiming clean-room provenance, and with minimal public-facing security/contributor docs.

**Architecture:** Hygiene first (git ignore + untrack research artifacts + path-scan gate), then honest legal/docs rewrite, then public-facing SECURITY/CONTRIBUTING + self-verify script relocation, then optional installer path hardening, finally verification and push (visibility public only after green gates).

**Tech Stack:** Python 3 stdlib project, git/gh CLI, unittest, Apache-2.0.

**Spec sources:** `.omc/research/opensource-security.md`, `opensource-legal.md`, `opensource-docs.md` multi-agent audits (2026-07-20).

---

## File map

| Path | Responsibility |
|---|---|
| `.gitignore` | Stop tracking local research/session state |
| `scripts/self_verify.py` | Public deterministic self-check (no absolute home paths) |
| `tests/security/test_public_tree_hygiene.py` | Fail if tracked files contain `/Users/`, private emails, PEM, etc. |
| `docs/provenance.md`, `NOTICE`, `docs/clean-room-attestation.md` | Honest reimplementation narrative |
| `docs/evidence-summary.md` | Public, path-free evidence summary (replaces research links) |
| `SECURITY.md`, `CONTRIBUTING.md` | Public security + contributor gates |
| `README.md`, `docs/STATUS.md`, `docs/host-support.md` | Point only at public paths |
| `src/portable_resume/install/transaction.py` | Use `commonpath` for dest-under-root check |
| `docs/superpowers/plans/2026-07-20-open-source-readiness.md` | This plan |

**Explicitly not in public tree after hygiene:** raw dual-review logs under `.omc/research/` (ignored; may remain local only).

---

### Task 1: Git hygiene + public-tree path scan test

**Files:**
- Modify: `.gitignore`
- Create: `tests/security/test_public_tree_hygiene.py`
- Modify: git index (untrack `.omc/research/*` except nothing — all research ignored)

- [x] **Step 1: Write the failing hygiene test**

Create `tests/security/test_public_tree_hygiene.py`:

```python
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


FORBIDDEN = [
    re.compile(r"/" + "Users" + r"/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"REDACTED_PRIVATE_EMAIL"),
    re.compile(r"-----BEGIN (RSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
]


class PublicTreeHygieneTests(unittest.TestCase):
    def test_tracked_files_have_no_local_pii_or_secrets(self) -> None:
        listed = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
        self.assertGreater(len(listed), 50)
        hits: list[str] = []
        for rel in listed:
            path = Path(rel)
            if not path.is_file():
                continue
            # allow binary fixtures without text scan
            if path.suffix in {".sqlite", ".vscdb", ".zst"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in FORBIDDEN:
                if pat.search(text):
                    hits.append(f"{rel}: {pat.pattern}")
        self.assertEqual(hits, [], msg="public tree leaks local paths/secrets:\n" + "\n".join(hits[:50]))

    def test_research_logs_are_not_tracked(self) -> None:
        listed = set(subprocess.check_output(["git", "ls-files"], text=True).splitlines())
        offenders = [p for p in listed if p.startswith(".omc/research/") and p.endswith((".log", ".md"))]
        # dual-review raw logs and opensource audit dumps must not ship
        bad = [p for p in offenders if "dual-review" in p or "opensource-" in p or "live-smoke" in p or "linux-gate" in p]
        self.assertEqual(bad, [])
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.security.test_public_tree_hygiene -v`  
Expected: FAIL with hits under `.omc/research/` absolute paths.

- [x] **Step 3: Update `.gitignore` and untrack research**

Append to `.gitignore` (keep existing entries):

```gitignore
# Local agent research / dual-review artifacts — do not publish
.omc/research/
```

Then:

```bash
git rm -r --cached .omc/research 2>/dev/null || true
```

Move only the self-verify helper later in Task 3; do not re-add research logs.

- [x] **Step 4: Re-run hygiene test**

Run: `PYTHONPATH=src python3 -m unittest tests.security.test_public_tree_hygiene -v`  
Expected: PASS (no tracked research logs; product tree has no home absolute paths).

- [x] **Step 5: Commit**

```bash
git add .gitignore tests/security/test_public_tree_hygiene.py
git commit -m "chore: ignore local research artifacts and gate public-tree hygiene"
```

---

### Task 2: Honest provenance / NOTICE / attestation

**Files:**
- Modify: `NOTICE`
- Modify: `docs/provenance.md`
- Modify: `docs/clean-room-attestation.md`
- Create: `tests/unit/test_provenance_honesty.py` (lightweight string checks)

- [x] **Step 1: Write failing honesty tests**

Create `tests/unit/test_provenance_honesty.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path


class ProvenanceHonestyTests(unittest.TestCase):
    def test_notice_does_not_claim_zero_inspection_of_installed_bundle(self) -> None:
        text = Path("NOTICE").read_text(encoding="utf-8")
        # Must not use absolute "never inspected" language that contradicts planning evidence.
        lowered = text.lower()
        self.assertNotIn("never inspected", lowered)
        self.assertNotIn("was not inspected", lowered)
        self.assertIn("independently authored", lowered)
        self.assertIn("apache", lowered)

    def test_provenance_uses_compatibility_reimplementation_language(self) -> None:
        text = Path("docs/provenance.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)reimplement|compatibility|behavioral")
        # Still forbid shipping bundled bodies
        self.assertIn("~/.grok/bundled/skills", text)

    def test_attestation_is_scoped_not_universal(self) -> None:
        text = Path("docs/clean-room-attestation.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)(foundation|G001|scope|limited)")
```

- [x] **Step 2: Run tests — expect FAIL** on current absolute language if present.

Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_provenance_honesty -v`

- [x] **Step 3: Rewrite docs honestly**

**`NOTICE`** full content:

```text
Portable Resume Skills
Copyright 2026 Portable Resume Skills contributors

Licensed under the Apache License, Version 2.0.

This project is an independently authored, stdlib-only reimplementation of
cross-agent context-migration *behavior* inspired by publicly documented
Agent Skills patterns and public product documentation.

Planning-time observation of installed tooling may have informed *requirements*,
but this repository does not redistribute, copy, or ship skill bodies from
any untracked installed bundle (including ~/.grok/bundled/skills/**).

Fixtures under tests/fixtures are synthetic. Trademarks of Claude, Codex,
Cursor, OpenCode, Antigravity, and Grok remain with their owners; this project
is not affiliated with or endorsed by those vendors.

Optional decompression, when used, relies on a host-provided zstd binary and
is not a required runtime dependency of this package.
```

**`docs/provenance.md`** — replace author attestation section with:

```markdown
## Author attestation (deterministic V1)

Implementation is an independently written **compatibility reimplementation**.

Allowed inputs for implementation/test work:

1. Repository plans/specs under project docs and (when present) local planning notes.
2. Public official documentation for host skill roots and Agent Skills metadata.
3. Publicly licensed upstream trees (for example Apache-2.0 xAI Grok Build) used only as *behavioral* reference.
4. Independently authored synthetic fixtures.

**Hard prohibition for product code and fixtures:** do not copy, paste, translate, or ship bodies from `~/.grok/bundled/skills/**` or private user transcripts.

**Honesty note:** planning-time inspection of installed tools may have informed requirements. That is not a license to redistribute those files. Public clones must not require private bundles.

This attestation covers deterministic packaging and reader behavior. It does **not** claim live host UI activation completeness or dual-OS release completeness (see `docs/STATUS.md`).
```

**`docs/clean-room-attestation.md`** — ensure scope is explicit (foundation + adapters + installer as independently authored; planning observation ≠ code derivation). Keep "No excluded source was opened" only if still true for *implementation* lane; otherwise rephrase to "Product sources and fixtures do not contain copied installed-bundle bodies."

- [x] **Step 4: Run honesty tests — PASS**

- [x] **Step 5: Commit**

```bash
git add NOTICE docs/provenance.md docs/clean-room-attestation.md tests/unit/test_provenance_honesty.py
git commit -m "docs: honest compatibility reimplementation provenance"
```

---

### Task 3: Public self-verify script + docs path cleanup

**Files:**
- Create: `scripts/self_verify.py` (portable; no home absolute hardcoding)
- Modify: `README.md`, `docs/STATUS.md`, `docs/host-support.md`
- Create: `docs/evidence-summary.md`

- [x] **Step 1: Write failing test that public docs do not link raw research logs**

Add to `tests/unit/test_provenance_honesty.py` (or new `tests/unit/test_public_docs_links.py`):

```python
class PublicDocsLinkTests(unittest.TestCase):
    def test_readme_and_status_do_not_require_omc_research(self) -> None:
        for path in (Path("README.md"), Path("docs/STATUS.md"), Path("docs/host-support.md")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(".omc/research/", text, msg=str(path))
            self.assertNotRegex(text, r"/" + "Users" + r"/[A-Za-z]", text, msg=str(path))
```

Run and expect FAIL while README still points at `.omc/research/`.

- [x] **Step 2: Implement `scripts/self_verify.py`**

Portable version of self-verify:

```python
#!/usr/bin/env python3
"""Deterministic self-verify for a checkout (no absolute home paths)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(argv: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(REPO),
        env=env or {**os.environ, "PYTHONPATH": str(REPO / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    print("repo", REPO)
    c = run([sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"])
    print("compileall", c.returncode)
    t = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"])
    print((t.stderr or t.stdout)[-300:])
    print("unittest", t.returncode)
    s = run([sys.executable, str(REPO / "scripts" / "portable-resume"), "self-check", "--json"])
    print(s.stdout.strip())
    print("self-check", s.returncode)
    m = run([sys.executable, str(REPO / "scripts" / "install-resume-skills"), "matrix", "--json"])
    matrix = json.loads(m.stdout) if m.returncode == 0 else {}
    print("matrix", m.returncode, {
        "ok": matrix.get("ok"),
        "cell_count": matrix.get("cell_count"),
        "live_cells_supported": matrix.get("live_cells_supported"),
    })
    # fixture list/show
    fx = REPO / "tests/fixtures/claude/s-cla-01-ordered-parent-chain/root"
    lst = run([
        sys.executable, str(REPO / "scripts" / "portable-resume"),
        "claude", "list", "--cwd", "/workspace/project",
        "--source-root", str(fx), "--json",
    ])
    print("list", lst.returncode)
    sh = run([
        sys.executable, str(REPO / "scripts" / "portable-resume"),
        "claude", "show", "latest", "--cwd", "/workspace/project",
        "--source-root", str(fx), "--format", "handoff",
    ])
    print("show", sh.returncode, "untrusted", "untrusted" in (sh.stdout or "").lower())
    ok = all(x == 0 for x in (c.returncode, t.returncode, s.returncode, m.returncode, lst.returncode, sh.returncode))
    print("OVERALL_SELF_VERIFY", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Make executable: `chmod +x scripts/self_verify.py`

- [x] **Step 3: Write `docs/evidence-summary.md`** (no absolute paths)

```markdown
# Evidence summary (public)

## Deterministic bar (macOS last verified)

- `python3 -m unittest discover -s tests -q` → green (146+ tests when full suite present)
- `scripts/portable-resume self-check --json` → `ok: true`, six adapters
- `scripts/install-resume-skills matrix --json` → packaging cells 36; live cells 0
- Install lifecycle: dry-run pure; verify drift fails closed; uninstall removes claim

## Multi-seat review (summary only)

- Fable / Grok / agy: APPROVE WITH MINOR FIXES (session notes, not reproduced here)
- Codex seat: may be quota-blocked; do not invent APPROVE
- Architect critic: requested honest live/Linux non-claims (retained in STATUS)

## Not claimed

- Live host UI activation for 36 cells
- Linux peer clean-runner AC-18 dual-OS release
```

- [x] **Step 4: Update README/STATUS/host-support** to use `scripts/self_verify.py` and `docs/evidence-summary.md` only (no `.omc/research/`, no `.omx/` required links for public readers). For provenance references to planning, say "local planning notes (not shipped)" instead of `.omx/...` paths.

- [x] **Step 5: Run tests**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_provenance_honesty tests.security.test_public_tree_hygiene -v
python3 scripts/self_verify.py
```

Expected: all PASS / OVERALL_SELF_VERIFY PASS

- [x] **Step 6: Commit**

```bash
git add scripts/self_verify.py README.md docs/STATUS.md docs/host-support.md docs/evidence-summary.md tests/unit/test_provenance_honesty.py tests/unit/test_public_docs_links.py 2>/dev/null || true
git commit -m "docs: public self-verify path and path-free evidence summary"
```

---

### Task 4: SECURITY.md + CONTRIBUTING.md

**Files:**
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Modify: `README.md` (link both)

- [x] **Step 1: Write tests that required public policy files exist**

```python
# tests/unit/test_public_policy_files.py
from pathlib import Path
import unittest

class PublicPolicyFilesTests(unittest.TestCase):
    def test_security_and_contributing_exist(self) -> None:
        for name in ("SECURITY.md", "CONTRIBUTING.md"):
            text = Path(name).read_text(encoding="utf-8")
            self.assertGreater(len(text), 400)
        sec = Path("SECURITY.md").read_text(encoding="utf-8")
        self.assertRegex(sec, r"(?i)threat|session|report|vulnerab")
        con = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("synthetic", con)
        self.assertIn("~/.grok/bundled/skills", con)
```

Run → FAIL until files exist.

- [x] **Step 2: Create `SECURITY.md`**

Must include:
- Threat model: local untrusted session stores; prompt injection in recovered text; installer can write skill roots
- Do not run `install --scope global --force-with-backup` on untrusted forks without review
- Reader never invokes source CLIs
- Report vulnerabilities via GitHub private security advisories / issues labeled security
- Secret redaction is best-effort

- [x] **Step 3: Create `CONTRIBUTING.md`**

Must include:
- Python 3.11+ recommended; stdlib only
- `python3 scripts/self_verify.py` before PR
- Fixtures must set `"synthetic": true` and use `tests/helpers/fixture_manifest.py`
- Forbidden: real transcripts, credentials, absolute home paths, copying `~/.grok/bundled/skills/**`
- Honest docs: do not mark live host rows verified without smoke evidence

- [x] **Step 4: Link from README** under License section

- [x] **Step 5: Run policy tests + full unittest subset**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_public_policy_files tests.security.test_public_tree_hygiene -v
```

- [x] **Step 6: Commit**

```bash
git add SECURITY.md CONTRIBUTING.md README.md tests/unit/test_public_policy_files.py
git commit -m "docs: add SECURITY and CONTRIBUTING for public project"
```

---

### Task 5: Installer dest containment uses commonpath

**Files:**
- Modify: `src/portable_resume/install/transaction.py` (`_dest_under_root`)
- Modify: `tests/integration/test_installer_transaction.py` (already has path escape test; ensure still passes)

- [x] **Step 1: Confirm existing escape test still present**

`tests/integration/test_installer_transaction.py::test_journal_path_escape_is_ignored_on_recover` must remain.

- [x] **Step 2: Change `_dest_under_root` to commonpath**

Replace prefix `startswith` check with:

```python
def _dest_under_root(root: str, rel: str) -> str:
    safe = _safe_rel_path(rel)
    dest = os.path.realpath(os.path.join(root, safe))
    root_real = os.path.realpath(root)
    try:
        if os.path.commonpath((dest, root_real)) != root_real:
            raise DiagnosticError("E_INSTALL_CONFLICT")
    except ValueError as error:
        # different drives on Windows, etc.
        raise DiagnosticError("E_INSTALL_CONFLICT") from error
    return dest
```

- [x] **Step 3: Run**

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_installer_transaction tests.integration.test_matrix_and_installer -v
```

Expected: PASS

- [x] **Step 4: Commit**

```bash
git add src/portable_resume/install/transaction.py
git commit -m "fix: contain install destinations with commonpath"
```

---

### Task 6: Full verification + push (keep private OR document public flip)

**Files:** none required beyond verification output

- [x] **Step 1: Full suite**

```bash
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
```

Expected: OK / PASS

- [x] **Step 2: Tracked-tree hard gate**

```bash
git ls-files | python3 -c "import sys; print(sum(1 for _ in sys.stdin))"
git ls-files | rg -n '/Users/[A-Za-z]|@hotmail\\.com|BEGIN PRIVATE|sk-[A-Za-z0-9]{20}' && exit 1 || echo CLEAN
```

Expected: `CLEAN`

- [x] **Step 3: Push commits to origin**

```bash
git push origin HEAD
```

- [x] **Step 4: Public visibility (only if Step 2 CLEAN and user wanted open source)**

```bash
gh repo edit ImL1s/resume-skills --visibility public --accept-visibility-change-consequences
gh repo view ImL1s/resume-skills --json visibility -q .visibility
```

Expected: `PUBLIC`  
If author email rewrite is required and history still contains hotmail, **do not** flip public until rewrite completes; instead stop and report BLOCKED with rewrite commands.

**Author rewrite (only if needed before public):**

```bash
git filter-branch -f --env-filter '
export GIT_AUTHOR_EMAIL="41898282+ImL1s@users.noreply.github.com"
export GIT_COMMITTER_EMAIL="41898282+ImL1s@users.noreply.github.com"
export GIT_AUTHOR_NAME="ImL1s"
export GIT_COMMITTER_NAME="ImL1s"
' -- --all
# or git filter-repo equivalent; then force-push with user consent
```

For this plan prefer: **if only two commits exist and remote is private**, rewrite then force-push is acceptable for open-source prep when user already requested public.

- [x] **Step 5: Final commit only if docs needed for STATUS after public**

Update `docs/STATUS.md` open-source line to note public readiness date if flipped.

---

## Self-review (plan author)

1. **Spec coverage:** Multi-agent P0s covered — research hygiene, provenance honesty, public self-verify, SECURITY/CONTRIBUTING, dead links, installer commonpath, verify+push.  
2. **Placeholders:** None intentional; full file contents provided for critical docs/scripts.  
3. **Type consistency:** N/A beyond existing `DiagnosticError` / installer APIs.  
4. **Out of scope:** Live UI smokes, Linux Docker green, Codex quota unblocking (documented not claimed).

---

## Execution note

User invoked **subagent-driven-development** together with this plan. After save, controller should execute tasks on a branch `opensource-prep` (or main with explicit consent — remote already on main for this private repo; prefer branch then merge if history rewrite not needed).
