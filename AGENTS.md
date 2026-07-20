# Agent notes — portable-resume-skills

## Product

Offline, local-only **context migration** across six coding-agent sources × six destination hosts.

- Emit **inert, untrusted handoff** for a **fresh** session.
- **Not** live process / session restore.
- **stdlib-only** runtime (no third-party packages on the product path).
- Source stores must remain immutable; never invoke the source agent CLI from readers.

## Verify before claiming done

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

Scripts under `scripts/` inject `src` onto `sys.path`. Unittest still needs `PYTHONPATH=src` (or `pip install -e .`).

## Honesty gates

- **Host UI live activation** (36 cells): stay `not-run` until per-host evidence exists (`docs/STATUS.md`, `docs/host-ui-smoke.md`).
- **Dual-OS release claim**: CI dual-OS green ≠ claimed; see `docs/release-claim.md`.
- **Cursor full bubble graph**: not claimed until fixtures + restore prove it.
- Do not copy `~/.grok/bundled/skills/**` into this tree (clean-room).

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
