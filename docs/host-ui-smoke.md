# Host UI live activation smoke protocol

## Layers (do not conflate)

| Layer | What it proves | Status |
|---|---|---|
| Packaging matrix | 36 skill bodies render + install files | **done** |
| Installed runner smoke | Host skill root + `run_reader` list/show on fixtures | **done** — `scripts/smoke_installed_matrix.py` (36/36) |
| Host UI NL / picker | User invokes skill **inside** host UI and gets handoff | **not-run** |

Packaging + installed runner ≠ host NL activation.

## Installed runner smoke (automated)

```bash
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
# optional JSON:
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py --json
```

Uses distinct `--root skills-<host>` per host (avoids Codex/Antigravity shared-root conflict) and `--within-min 0` for synthetic fixture ages.

## Host UI NL activation (manual / host automation)

**Host UI live** means a human (or host-native automation) invoked the skill *inside* the destination host and obtained an inert handoff.

### Evidence schema

| Field | Description |
|-------|-------------|
| host | claude, codex, cursor, opencode, antigravity, grok |
| source | resume skill source key |
| host_version | Host app/CLI version string |
| activation | Exact slash command / picker path |
| result | pass / fail / blocked |
| notes | Short, no secrets |
| date | ISO date |

### Procedure

1. Install into the host’s real skill root (see `docs/install-hosts.md`):

   ```bash
   PYTHONPATH=src python3 scripts/install-resume-skills install \
     --host <host> --scope project --project "$PWD" --json
   ```

2. Open the host; invoke `/resume-claude` (or host-equivalent).
3. Confirm the host runs installed `run_reader.py` (not the source agent CLI).
4. Confirm handoff includes the untrusted security banner.
5. Record a row below.

### Evidence table (NL activation — empty until run)

| host | source | host_version | activation | result | notes | date |
|------|--------|--------------|------------|--------|-------|------|
| | | | | | | |

## Policy

- Do not set matrix `live_cells_supported` / host UI live above 0 without **NL activation** rows.
- Installed-runner smoke may be green while host UI remains not-run.
