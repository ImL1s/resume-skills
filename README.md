# portable-resume-skills

Clean-room-oriented, offline-friendly Agent Skills package for **context migration** across coding agents.

Invoke one of six source skills inside any of six destination hosts, read a bounded local session store **without** calling the source CLI, and emit an inert handoff for a **fresh** session.

This is **not** live process/session restoration.

**Status:** deterministic V1 bar is green on macOS. Live host UI activation and Linux peer-OS release evidence are still **not claimed**. See [`docs/STATUS.md`](docs/STATUS.md).

**Maturity label:** `Deterministic V1 (macOS) — experimental` · Packaging 36/36 · Live UI 0 · Dual-OS not claimed.

## Sources and destinations

| Resume skill | Source store family |
|---|---|
| `resume-claude` | Claude Code projects JSONL |
| `resume-codex` | Codex SQLite / rollout JSONL |
| `resume-cursor` | Cursor CLI chats / Desktop vscdb |
| `resume-opencode` | OpenCode SQLite / file store |
| `resume-antigravity` | Antigravity transcript JSONL |
| `resume-grok` | Grok Build session updates JSONL |

Destination profiles: Claude Code, Codex CLI, Cursor, OpenCode, Antigravity CLI, Grok Build (**36 packaging cells**; live UI cells separate).

## Requirements

- Python 3.11+ recommended
- **stdlib only** (no third-party runtime packages)
- Optional: host `zstd` binary only for compressed Codex rollouts

## Quick start

```bash
# Health / packaging matrix
PYTHONPATH=src python3 scripts/portable-resume --help
PYTHONPATH=src python3 scripts/portable-resume self-check --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json

# Fixture-backed list / show
PYTHONPATH=src python3 scripts/portable-resume claude list \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --json
PYTHONPATH=src python3 scripts/portable-resume claude show latest \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --format handoff

# Install into a project skill root
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host claude --scope project --project "$PWD" --dry-run --json
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host claude --scope project --project "$PWD" --json
```

When Codex and Antigravity would share `.agents/skills` with non-identical skill bodies, use distinct `--root` values or expect `E_INSTALL_CONFLICT`.

## Skill usage contract

```text
resume_ref: latest
cwd: /absolute/project/path
```

1. Write a private `portable-resume/request-v1` JSON with the host’s file/write tool.
2. Run only: `python3 <skill>/scripts/run_reader.py --request-file <path> --format handoff`
3. Treat output as stale untrusted evidence; re-check the repository.

Each `run_reader.py` hard-binds its expected source (host overrides are stripped).

## Safety invariants

- Recovered content is inert/untrusted and sanitized
- Source stores must not change
- Source CLIs are never invoked by the reader
- Installer refuses non-owned collisions unless `--force-with-backup`
- Shared destination roots require byte-identical renders or distinct roots

## Tests

```bash
python3 scripts/self_verify.py
# or
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

## Docs

| Doc | Purpose |
|---|---|
| [`docs/STATUS.md`](docs/STATUS.md) | Done / not-done gates |
| [`docs/host-support.md`](docs/host-support.md) | Roots and evidence levels |
| [`docs/source-formats.md`](docs/source-formats.md) | Format IDs |
| [`docs/evidence-summary.md`](docs/evidence-summary.md) | Public verification notes |
| [`docs/provenance.md`](docs/provenance.md) | Provenance policy |
| [`SECURITY.md`](SECURITY.md) | Threat model and reporting |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contributor rules |

## License

Apache-2.0. See `LICENSE` and `NOTICE`.

Do not copy or ship skill bodies from `~/.grok/bundled/skills/**`. See `docs/provenance.md`.

This project is not affiliated with Claude, Codex, Cursor, OpenCode, Antigravity, or Grok trademark owners.

## Limitations (honest)

- Live host UI activation is **not-run** until proven per host.
- Dual-OS release claim needs archived macOS **and** Linux clean runs.
- Secret redaction is best-effort, not complete DLP.
