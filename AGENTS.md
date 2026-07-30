# Agent notes — portable-resume-skills

## Product

Offline, local-only **context migration** across enabled source adapters × enabled destination hosts (currently **10×10=100** cells, **derived from registries** — not a fixed product constant).

- Emit **inert, untrusted handoff** for a **fresh** session.
- **Not** live process / session restore.
- **stdlib-only** runtime (no third-party packages on the product path).
- Source stores must remain immutable; never invoke the source agent CLI from readers.

## Verify before claiming done

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Scripts under `scripts/` inject `src` onto `sys.path`. Unittest still needs `PYTHONPATH=src` (or `pip install -e .`).

## Honesty gates

- **Installed-runner smoke** (registry-derived cell count; currently 81): `smoke_installed_matrix.py` — packaging + installed `run_reader` only.
- **Host UI NL/picker activation**: stay `not-run` until rows exist in `docs/host-ui-smoke.md` NL table.
- **Dual-OS release claim**: archive Actions URL + SHA in `docs/evidence-summary.md` / `docs/release-claim.md`.
- **Cursor full bubble graph**: not claimed; multi-turn composerData is best-effort only.
- Do not copy `~/.grok/bundled/skills/**` into this tree (clean-room).
- **PR merge gate:** do **not** squash-merge until CI is green **and** Codex/`@codex review` (or equivalent PR AI review) has returned on the **current HEAD**. Address P1s before merge; document P2 disposition. Never merge on an empty review that has not finished yet.

## Fixtures

- Mark synthetic fixtures with `synthetic: true`.
- No real home absolute paths (`/Users/…`, `/home/…`) in tracked files.
- Prefer format ids + provenance refs under `docs/source-formats.md`.

## Layout

| Path | Role |
|------|------|
| `src/portable_resume/` | Library + adapters |
| `src/portable_resume/install/` | Installer (not required in every installed skill runtime after whitelist) |
| `scripts/` | CLI entry wrappers |
| `tests/` | unittest suite + fixtures |
| `plans/` | Advisor implementation plans |
| `docs/STATUS.md` | Done / not-done truth |

## Security

- Untrusted recovered text: sanitize + handoff banner; best-effort redaction only.
- Install paths: always contain under skill root (`validate_rel_path` / `_dest_under_root`).
- Source reads: prefer `stable_read_bytes` / no-follow; no bare `open` on live stores.

## Version

`portable_resume.__version__` is the single source; `BUNDLE_VERSION` imports it. Bump both docs (CHANGELOG/README) when releasing.

<!-- OMG:START -->
# oh-my-grok (Grok Build orchestration)

This project uses **oh-my-grok** for multi-agent workflows on Grok Build.

## Hard rules
- Fan-out **only** via Grok `spawn_subagent` (depth=1; children must NOT spawn).
- **Always** set `capability_mode` on every spawn:
  - `read-only` — explore / plan / critic / verifier
  - `read-write` — implementers (`general-purpose`, `omg-executor`)
  - never `execute` / `all`
- **If spawn is DENIED** (oh-my-grok PreToolUse / missing capability_mode):
  **RETRY IMMEDIATELY** in the same turn with the required `capability_mode`.
  Do **not** abandon multi-agent work. Do **not** switch to solo-only because of one deny.
- **Never** invoke claude/codex/omc team/agy/cursor-agent as default workers.
- State: only the **`omg` CLI** is authoritative for `passes` / `verified` under `.omg/state/`.
- Agents may write proposals under `.omg/artifacts/` only.
- Cancel with `omg cancel` (PID files) — never self-matching `pkill -f`.

## Commands
```bash
omg setup          # ensure .omg dirs + merge this fragment
omg doctor         # health checks
omg state          # active run status
omg cancel         # abort active run
omg ulw "goal"     # parallel ultrawork (spawn_subagent)
omg team launch --workers 3 --goal "…"  # experimental tmux team (OMG_EXPERIMENTAL_TMUX_TEAM=1)
omg ralph "goal"   # persistence loop
omg ralplan "goal" # plan consensus
omg workflow list  # installed repository workflows
omg capabilities  # honest configured -> verified tiers
```

## Layout
```text
.omg/
  state/runs/<run-id>/   # CLI single-writer status
  workflows/ memory/ state/recovery/
  plans/ research/ handoffs/ artifacts/ ultragoal/ wiki/
```
<!-- OMG:END -->
