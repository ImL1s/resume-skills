# Plan 017: Single version source, pyproject metadata, CI Python 3.11

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/__init__.py src/portable_resume/install/catalog.py .github/workflows/ci.yml pyproject.toml README.md CONTRIBUTING.md`

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW–MED
- **Depends on**: none
- **Category**: migration
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

`__version__`, `BUNDLE_VERSION`, README, and CHANGELOG can drift across releases. There is no `pyproject.toml` (no pip install / requires-python). CI only runs 3.12 while docs claim 3.11+. This blocks trustworthy packaging and external consumers.

## Current state

- `src/portable_resume/__init__.py`: `__version__ = "0.2.0"`
- `src/portable_resume/install/catalog.py`: `BUNDLE_VERSION = "0.2.0"`
- `.github/workflows/ci.yml`: `python-version: ["3.12"]`
- No `pyproject.toml`

Runtime must remain **stdlib-only** (no third-party runtime deps).

## Scope

**In scope**:
- Single version wiring (`BUNDLE_VERSION = __version__` or import from one module)
- Minimal `pyproject.toml` (name, version, requires-python, package dir)
- CI matrix 3.11 + 3.12
- README/CONTRIBUTING one-line updates for install/test via editable optional

**Out of scope**: Auto PyPI CD (direction / STATUS policy until host UI); adding runtime dependencies

## Steps

### Step 1: Single version

```python
# catalog.py
from portable_resume import __version__ as BUNDLE_VERSION
# or keep BUNDLE_VERSION and set __version__ from it — pick one direction
```

Add unit test: `__version__ == BUNDLE_VERSION`.

### Step 2: pyproject.toml

Minimal setuptools/hatchling config pointing at `src/`:

- `name = "portable-resume-skills"` (or repo’s preferred PyPI name — check README; if unset use `portable-resume`)
- `requires-python = ">=3.11"`
- Optional scripts entry points for `portable-resume` / `install-resume-skills` **only if** they do not break installed-skill runtime copy model

Verify: `pip install -e .` then `python -c "import portable_resume; print(portable_resume.__version__)"` works in a venv.

### Step 3: CI

```yaml
python-version: ["3.11", "3.12"]
```

Keep dual OS jobs.

### Step 4: Docs

README: note `pip install -e .` alternative to `PYTHONPATH=src` for development; scripts already self-inject path.

**Verify**: CI-equivalent local:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

## Done criteria

- [ ] One source of version truth + test
- [ ] pyproject exists; package importable via editable install
- [ ] CI config includes 3.11
- [ ] No runtime third-party deps added
- [ ] README DONE

## STOP conditions

- Editable install breaks e2e relocated bundle tests — fix packaging includes, do not drop e2e
- Choosing a PyPI name that conflicts — use a clearly local name and do not publish

## Maintenance notes

Release process: bump one version field only. PyPI publish remains manual/future.
