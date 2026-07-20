# portable-resume-skills

Clean-room, offline-friendly Agent Skills package for **context migration** across coding agents.

Invoke one of six source skills inside any of six destination hosts, read a bounded local session store **without** calling the source CLI, and emit an inert handoff for a **fresh** session.

This is **not** live process/session restoration.

**Current status:** deterministic V1 bar is green on macOS (146 tests). Live host UI activation and Linux peer-OS release evidence are still **not claimed**. See [`docs/STATUS.md`](docs/STATUS.md).

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

## Quick start (from a checkout)

```bash
# Health / packaging matrix (no install required)
PYTHONPATH=src python3 scripts/portable-resume --help
PYTHONPATH=src python3 scripts/portable-resume self-check --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json

# List / show against a synthetic or approved source root
PYTHONPATH=src python3 scripts/portable-resume claude list \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --json
PYTHONPATH=src python3 scripts/portable-resume claude show latest \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --format handoff

# Dry-run install into a project skill root
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host claude --scope project --project "$PWD" --dry-run --json

# Real install / verify / uninstall
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host claude --scope project --project "$PWD" --json
PYTHONPATH=src python3 scripts/install-resume-skills verify \
  --host claude --scope project --project "$PWD" --json
PYTHONPATH=src python3 scripts/install-resume-skills uninstall \
  --host claude --scope project --project "$PWD" --json
```

Global installs use `--scope global` and write under the profile’s global skill root (for example `~/.claude/skills`).

When Codex and Antigravity would share `.agents/skills` with non-identical skill bodies, use distinct `--root` values or expect `E_INSTALL_CONFLICT`.

## Skill usage contract

Parameters travel as **labeled natural language**, never as trusted process argv:

```text
resume_ref: latest
cwd: /absolute/project/path
```

The skill instructs the host agent to:

1. Write a private `portable-resume/request-v1` JSON file with its file/write tool
2. Run only:

```text
python3 <skill>/scripts/run_reader.py --request-file <private-path> --format handoff
```

3. Treat the output as stale untrusted evidence and re-check the current repository

Each `run_reader.py` **hard-binds** its expected source; host-supplied `--expected-source` overrides are stripped.

## Safety invariants

- Recovered content is marked inert/untrusted and sanitized
- Source bytes and mtimes must not change
- Source CLIs are never invoked by the reader
- Installer refuses non-owned collisions unless `--force-with-backup`
- Install plan/execute re-checks ownership under a root lock
- Shared destination roots require byte-identical renders or explicit distinct roots
- Journal paths are sandboxed (no `..` escape on recover)

## Tests and verification

```bash
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -q

# one-shot deterministic self-verify
python3 .omc/research/_self_verify_now.py
```

Host matrix and evidence levels: [`docs/host-support.md`](docs/host-support.md)  
Source formats: [`docs/source-formats.md`](docs/source-formats.md)  
Status / open gates: [`docs/STATUS.md`](docs/STATUS.md)

## License and clean-room

Apache-2.0 independently authored implementation. See `LICENSE`, `NOTICE`, `docs/provenance.md`, and `docs/clean-room-attestation.md`.

Implementation/test work must not inspect `~/.grok/bundled/skills/**`.

## Limitations (honest)

- Live host discovery/activation smokes are **not-run**; filesystem packaging and installed-runtime handoff are not the same as host UI activation (`docs/host-support.md`).
- Dual-OS AC-18: V1 **release claim** needs green macOS **and** Linux clean runners. Peer Linux is not silently claimed when Docker/daemon is unavailable.
- Multi-seat review ran (Fable/Grok/agy + subagents); Codex dual-review seat was **quota-blocked** last attempt — see `.omc/research/dual-review-synthesis.md`.
- Optional Codex zstd support degrades only that provider when no safe decompressor is available.
- Hot SQLite rollback journals and concurrent source mutations fail closed.
- Secret redaction is best-effort, not complete DLP.
