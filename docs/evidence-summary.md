# Evidence summary (public)

## Deterministic bar (macOS last verified)

- `python3 -m unittest discover -s tests -q` → green
- `scripts/portable-resume self-check --json` → `ok: true`, six adapters
- `scripts/install-resume-skills matrix --json` → packaging cells 36; live cells 0
- Install lifecycle: dry-run pure; verify drift fails closed; uninstall removes claim
- One-shot: `python3 scripts/self_verify.py` → `OVERALL_SELF_VERIFY PASS`

## Multi-seat review (summary only)

Independent review seats were run during private development. High-level outcomes:

- Multiple external/CLI seats returned APPROVE WITH MINOR FIXES or requested claim honesty
- Codex seat may be quota-blocked in some environments; do not invent APPROVE
- Residual product risks are tracked in `docs/STATUS.md` (live UI / dual-OS)

Raw dual-review logs are **not** shipped in this repository (local research only).

## Not claimed

- Live host UI activation for 36 cells
- Linux peer clean-runner dual-OS release completeness
