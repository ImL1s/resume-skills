# Contributing

## Environment and layout

Use Python 3.11+; the product runtime is stdlib-only. Core code is under `src/portable_resume/`, adapters under `src/portable_resume/adapters/`, installer code under `src/portable_resume/install/`, wrappers under `scripts/`, and tests/fixtures under `tests/`.

## Required checks

Run all four before opening a pull request:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

### Fast iteration during development

The full gate above takes several minutes. While iterating, run only what your
change touches; the full gate remains mandatory before opening the pull request.

```bash
# Stage-scoped verification (same stages CI uses; see --help for the list)
python3 scripts/self_verify.py --only unit          # just the unittest stage
python3 scripts/self_verify.py --only docs          # localized quick-start docs gate
python3 scripts/self_verify.py --profile ci-compat  # what one CI matrix cell runs

# One test module / one test
PYTHONPATH=src python3 -m unittest tests.unit.test_self_verify_profiles -v
PYTHONPATH=src python3 -m unittest tests.unit.test_self_verify_profiles.SelfVerifyProfileTests.test_resolve_only_preserves_canonical_order
```

The `docs` stage checks the localized quick-start documentation. For other
documentation, run the focused unittest that covers the changed policy or
behavior; the full gate remains mandatory before the pull request.

### Editable install (drops the `PYTHONPATH` prefix)

```bash
pip install -e .
portable-resume self-check
install-resume-skills hosts
```

### pytest (optional local convenience)

The authoritative runner is unittest (what CI runs). If you have pytest
installed, the suite collects cleanly and gives you `-k` filtering and `-x`:

```bash
PYTHONPATH=src python3 -m pytest tests -q -k cline -x
```

Do not add pytest-only constructs (fixtures, markers) to the tests.

For packaging/release changes, also build wheel/sdist, run `scripts/smoke_distribution.py`, and build host archives with `scripts/build_host_packages.py` in a temporary output directory.

Run `python3 scripts/check_docs.py` after changing installation, version, host,
or release guidance. It enforces all 12 localized quick-start files, canonical
commands, host coverage, reference links, and version markers.

## Code and fixture rules

- Use four-space Python indentation, type hints, `snake_case` functions/modules, and `PascalCase` classes.
- Prefer existing bounds, stable-read, diagnostics, and transaction helpers; add no runtime dependency without explicit project approval.
- Never invoke a source-agent CLI or mutate a source store.
- Every fixture manifest must have `"synthetic": true`, a registered `format_id`, and a `docs/source-formats.md` provenance anchor.
- Never commit real transcripts, credentials, absolute developer home paths, or content from `~/.grok/bundled/skills/**`.

## Tests and documentation

Name unittest files `test_*.py` and methods `test_*`. Add focused parser/security tests before widening an adapter. Keep filesystem, installed-runner, host UI, marketplace, and remote-release claims separate; update `docs/STATUS.md` only with fresh evidence.

## Commits and pull requests

Follow the existing imperative, scoped history style (for example, `fix: contain plugin install paths` or `docs: record release evidence`). Keep commits reviewable. Pull requests should explain behavior and security impact, list exact checks, link issues when applicable, and include UI screenshots only for real host-UI changes.
