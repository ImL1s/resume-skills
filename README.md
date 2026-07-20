# portable-resume-skills

Clean-room, offline-friendly Agent Skills package for **context migration** across coding agents.

Invoke one of six source skills inside any of six destination hosts, read a bounded local session store **without** calling the source CLI, and emit an inert handoff for a **fresh** session.

This is **not** live process/session restoration.

## Sources and destinations

| Resume skill | Source store family |
|---|---|
| `resume-claude` | Claude Code projects JSONL |
| `resume-codex` | Codex SQLite / rollout JSONL |
| `resume-cursor` | Cursor CLI chats / Desktop vscdb |
| `resume-opencode` | OpenCode SQLite / file store |
| `resume-antigravity` | Antigravity transcript JSONL |
| `resume-grok` | Grok Build session updates JSONL |

Destination profiles: Claude Code, Codex CLI, Cursor, OpenCode, Antigravity CLI, Grok Build (36 package cells).

## Quick start (from a checkout)

```bash
# Reader help (no install required)
PYTHONPATH=src python3 scripts/portable-resume --help

# List / show a source against a synthetic root or real approved root
PYTHONPATH=src python3 scripts/portable-resume claude list --cwd "$PWD" --source-root /path/to/source-root
PYTHONPATH=src python3 scripts/portable-resume codex show latest --cwd "$PWD" --format handoff

# 36-cell matrix report
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json

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

Global installs use `--scope global` and write under the profile's global skill root (for example `~/.claude/skills`).

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

## Safety invariants

- Recovered content is marked inert/untrusted and sanitized
- Source bytes and mtimes must not change
- Source CLIs are never invoked by the reader
- Installer refuses non-owned collisions unless `--force-with-backup`
- Shared destination roots require byte-identical renders or explicit distinct roots

## Tests

```bash
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## License and clean-room

Apache-2.0 independently authored implementation. See `LICENSE`, `NOTICE`, `docs/provenance.md`, and `docs/clean-room-attestation.md`.

Implementation/test work must not inspect `~/.grok/bundled/skills/**`.

## Limitations (honest)

- Live host discovery/activation smokes are evidence-gated; filesystem packaging proof is not a substitute for installed-version smoke on every host (`docs/host-support.md` live column is `not-run` until proven).
- Dual-OS AC-18: a V1 **release claim** requires green clean runners on both macOS and Linux. This checkout’s automated gate proves the OS it runs on; the peer OS is not silently claimed.
- Optional Codex zstd support degrades only that provider when no safe decompressor is available.
- Hot SQLite rollback journals and concurrent source mutations fail closed.
- Secret redaction is best-effort, not complete DLP.
- Shared natural skill roots with host-specific bodies (for example Codex vs Antigravity on `.agents/skills`) require distinct explicit roots or byte-identical renders.
