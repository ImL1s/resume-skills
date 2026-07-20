# Contributing

Thanks for helping improve portable-resume-skills.

## Environment

- Python 3.11+ recommended (stdlib only; no third-party runtime deps).
- macOS and Linux are the primary development targets.

## Before you open a PR

```bash
python3 scripts/self_verify.py
```

Or:

```bash
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

## Fixture rules

- Every adapter fixture directory needs a `fixture.json` with `"synthetic": true`.
- Use `tests/helpers/fixture_manifest.py` validation patterns.
- **Forbidden in fixtures and product code:**
  - Real user transcripts
  - Credentials / API keys
  - Absolute developer home paths (`/Users/...`, `/home/...`)
  - Any content copied from `~/.grok/bundled/skills/**`

## Documentation honesty

- Do not mark host rows as live-verified without real activation smoke evidence (`docs/host-support.md`).
- Do not claim dual-OS release completeness without archived Linux + macOS green runs.
- Prefer `docs/evidence-summary.md` for public evidence; do not commit local research logs under `.omc/research/`.

## Code style

- Keep the reader process free of source-agent CLI invocation.
- Prefer fail-closed diagnostics with stable error codes.
- Keep diffs small and reviewable.

## License

By contributing, you agree your contributions are licensed under Apache-2.0 (see `LICENSE`).
