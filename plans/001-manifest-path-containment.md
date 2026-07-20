# Plan 001: Contain every install-manifest path under skill root

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat bc7baf0..HEAD -- src/portable_resume/install/transaction.py src/portable_resume/install/manifest.py tests/integration/test_installer_transaction.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

`plan_install` / `execute_install` already reject `..` and absolute paths via `_safe_rel_path` / `_dest_under_root`. `verify_root` and `uninstall_claim` do **not**: they `os.path.join(root, rel)` using keys from a loaded `manifest.json`. A local attacker who can write the skill root’s `.portable-resume/manifest.json` can plant a `../../…` file entry; when the user later uninstalls (and on-disk hash still matches), `os.remove` can delete a file **outside** the skill root. This is the highest-confidence security fix in the v0.2.0 audit.

## Current state

- `src/portable_resume/install/transaction.py` — install transaction, lock, verify, uninstall
- `src/portable_resume/install/manifest.py` — `Manifest.loads` / dumps

Install containment (good pattern to reuse):

```python
# transaction.py ~225-245
def _safe_rel_path(rel: str) -> str:
    if not rel or rel.startswith("/") or rel.startswith("\\") or "\x00" in rel:
        raise DiagnosticError("E_INSTALL_CONFLICT")
    parts = Path(rel).parts
    if any(part in {"..", ""} for part in parts):
        raise DiagnosticError("E_INSTALL_CONFLICT")
    return Path(*parts).as_posix()

def _dest_under_root(root: str, rel: str) -> str:
    safe = _safe_rel_path(rel)
    dest = os.path.realpath(os.path.join(root, safe))
    root_real = os.path.realpath(root)
    ...
```

Uninstall / verify (vulnerable):

```python
# transaction.py ~477-486 (verify)
path = os.path.join(root, rel)
...
# transaction.py ~534-542 (uninstall)
abs_path = os.path.join(root, path)
if os.path.isfile(abs_path):
    if sha256_file(abs_path) == entry.sha256:
        os.remove(abs_path)
```

```python
# manifest.py ~56-66
files = {
    path: FileEntry(path=path, sha256=entry["sha256"], ...)
    for path, entry in data.get("files", {}).items()
}
```

Conventions: raise `DiagnosticError("E_INSTALL_CONFLICT")` or `E_VERIFY_MISMATCH` fail-closed; never print path contents that might be secrets. Tests live under `tests/integration/test_installer_transaction.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit/integration | `PYTHONPATH=src python3 -m unittest discover -s tests -q` | OK, exit 0 |
| Self verify | `python3 scripts/self_verify.py` | exit 0 |
| Secrets gate | `python3 scripts/check_secrets.py` | `SECRET/PATH GATE CLEAN` |

## Scope

**In scope**:
- `src/portable_resume/install/manifest.py`
- `src/portable_resume/install/transaction.py`
- `tests/integration/test_installer_transaction.py` (or new focused security test under `tests/security/`)

**Out of scope**:
- Installer CLI UX / new flags
- Windows locking (separate plan)
- Changing backup layout or package identity algorithm

## Git workflow

- Branch: `advisor/001-manifest-path-containment`
- Commits: conventional, e.g. `fix: contain uninstall/verify paths under skill root`
- Do NOT push unless the operator asks

## Steps

### Step 1: Validate paths on `Manifest.loads`

In `manifest.py` `loads`, for every `files` key call the same rules as `_safe_rel_path` (import from transaction **or** move `_safe_rel_path` to a tiny shared helper in `manifest.py` / `install/paths.py` to avoid circular imports). Reject absolute, NUL, empty, `..` segments. On bad path: raise `ValueError` that callers map to `DiagnosticError("E_INSTALL_CONFLICT")` or `E_VERIFY_MISMATCH`.

**Verify**: `python3 -c "from portable_resume.install.manifest import Manifest; ..."` with a malicious path raises (use a tiny unit test in step 3).

### Step 2: Route verify and uninstall through `_dest_under_root`

Replace every `os.path.join(root, rel)` used for read/delete of claim files with `_dest_under_root(root, rel)`. If validation fails, treat as verify mismatch / install conflict (fail closed), **do not** delete.

Also apply to any other read of SKILL.md content in `verify_root` that currently joins raw rel.

**Verify**: `rg -n 'os\.path\.join\(root, (rel|path)\)' src/portable_resume/install/transaction.py` — remaining joins only for support paths (`SUPPORT_DIR`, journal) that are fixed names, not manifest keys.

### Step 3: Regression tests

Add tests:

1. Write a skill root with a normal install, then hand-edit `manifest.json` to add a file key `../../tmp/portable-resume-escape-target` (create a temp file outside root with matching sha if needed for the delete path). Call `uninstall_claim` — assert outside file still exists; assert error or skip-remove without escape.
2. `verify_root` with the same malicious entry fails closed without reading outside content into errors.
3. Happy-path install/verify/uninstall still passes.

Model after existing transaction tests in `tests/integration/test_installer_transaction.py`.

**Verify**: `PYTHONPATH=src python3 -m unittest tests.integration.test_installer_transaction -q` (and any new module) → pass.

### Step 4: Full gates

**Verify**:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
```

All exit 0.

## Test plan

- Malicious `../` and absolute path keys in loaded manifest
- Uninstall does not delete outside root
- Verify fails closed
- Normal install → verify → uninstall still green

## Done criteria

- [ ] `Manifest.loads` rejects unsafe paths
- [ ] uninstall/verify only touch paths under `os.path.realpath(root)`
- [ ] New regression tests pass
- [ ] Full unittest + self_verify + check_secrets exit 0
- [ ] No files outside scope modified
- [ ] `plans/README.md` row → DONE

## STOP conditions

- Manifest schema change required beyond path validation (e.g. multi-root claims redesign)
- Tests require writing real user home paths (use tempdirs only)
- Circular import cannot be resolved without large refactor — then extract `_safe_rel_path` to `install/pathutil.py` only; do not invent new packages under `src/`

## Maintenance notes

- Any future code that iterates `manifest.files` keys **must** use `_dest_under_root`.
- Reviewer: confirm no `os.remove` on unvalidated joins remains in install package.
- Deferred: history/gitleaks scan of published tags (plan 008).
