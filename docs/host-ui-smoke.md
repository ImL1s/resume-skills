# Host UI live activation smoke protocol

Packaging 36/36 proves filesystem install + `run_reader` against fixtures.
**Host UI live** means a human (or host-native automation) invoked the skill
*inside* the destination host and obtained an inert handoff.

Status remains **not-run** until rows are filled with evidence.

## Evidence schema

| Field | Description |
|-------|-------------|
| host | One of: claude, codex, cursor, opencode, antigravity, grok |
| source | resume skill source key |
| host_version | Host app/CLI version string |
| activation | Exact command / slash path used |
| result | pass / fail / blocked |
| notes | Short, no secrets |
| date | ISO date |

## Minimal procedure (per host)

1. From a project tree:

   ```bash
   PYTHONPATH=src python3 scripts/install-resume-skills install \
     --host <host> --scope project --project "$PWD" --json
   ```

2. Open the host; invoke `/resume-claude` (or host-equivalent from `docs/install-hosts.md`).
3. Confirm the host runs the installed `run_reader.py` (not the source agent CLI).
4. Confirm handoff includes the untrusted security banner; treat content as stale.
5. Record a row in the evidence table below (or in `docs/evidence-summary.md`).

## Evidence table (template)

| host | source | host_version | activation | result | notes | date |
|------|--------|--------------|------------|--------|-------|------|
| | | | | | | |

## Policy

- Do not set matrix `live_cells_supported` above 0 without filled rows.
- Failures are useful evidence; mark `fail`/`blocked` rather than inventing pass.
