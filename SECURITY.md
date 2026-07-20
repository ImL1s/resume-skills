# Security Policy

## Threat model (summary)

`portable-resume-skills` is a **local, offline-friendly** tool that:

1. Reads **untrusted** persisted agent session stores from disk (JSONL, SQLite, etc.).
2. Emits **partially** sanitized, inert-marked handoff text for a **fresh** session.
3. Can install skill packages into project or user skill roots (those skills are then loadable by host agents).

It is **not** a network service and does not restore live processes.

### Assets

- Local session history (may contain secrets, private paths, credentials).
- Destination skill roots (project/global agent skill directories).
- Source session stores (must remain byte/mtime unchanged).
- Temporary private SQLite/file copies created during stable reads.

### Trust boundaries

| Boundary | Threat | Control |
|---|---|---|
| Source store → reader | Path escape, symlink, special files, concurrent mutation | Approved roots, no-follow regular files, stable snapshot, fail closed |
| Recovered text → destination model | Prompt injection | `inert`/`untrusted` markers, sanitizer, quoted handoff, re-check checklist |
| Installer → skill roots | Overwrite non-owned files, path escape, malicious skill supply chain | Ownership/claims, refuse collisions, root lock, sandboxed journal paths, dry-run |
| Optional zstd | Process boundary | Trusted absolute decoder paths only, fixed argv, `shell=False`, empty PATH, caps/timeouts |

### Supply chain (important)

Installing skills means writing instruction files that a host agent may later execute with the user’s privileges.

- Treat any third-party revision as untrusted until reviewed.
- Prefer `--scope project` and `--dry-run` first.
- `--scope global` writes under the host’s user skill roots (see `docs/host-support.md`).
- `--force-with-backup` may replace non-owned conflicting files after copying them under `.portable-resume/backups/`.
- If a host ignores skill instructions and shells user text, that is **out of scope** for the fixed runner argv (which never includes user fields).

### Secret redaction (honest coverage)

Redaction is **best-effort**, not complete DLP. Patterns include common shapes such as:

- AWS-like `AKIA…`
- Common `sk-…` / Bearer-like tokens
- Simple `label=value` secret-looking pairs
- Some metadata field names (`system_prompt`, signatures, etc.)

**Not guaranteed:** arbitrary JWTs, PEM blocks, uncommon cloud tokens, free-form passwords, secrets split across turns. Assume residual secrets may remain in handoff text and host logs.

### Residual risks

- Recovered text remains model-visible; operators must not treat handoff as instructions.
- Temp snapshot directories may briefly hold session-derived bytes; failures should clean up, but crash windows exist.
- Handoff on stdout may be captured by host logging.
- Windows file locking is weaker than POSIX flock in V1.
- The only intentional child process is the optional trusted zstd decoder for compressed Codex rollouts.

## Supported versions

Security fixes target the `main` branch of this repository.

## Reporting a vulnerability

1. Prefer GitHub **Security Advisories** when enabled for this repository.
2. Otherwise contact the repository owner via their GitHub security contact.
3. Include: impact, reproduction steps, affected commit SHA, and whether session data was involved.

Do **not** attach real private transcripts or credentials to public issues.

## Safe operating guidelines

- Prefer project-scope installs when evaluating unknown revisions.
- Avoid `--force-with-backup` unless you understand which non-owned paths will be replaced.
- Treat handoff output as stale evidence; re-verify repository state before acting.
- Never point `--source-root` at trees you do not intend to parse.
- Do not paste handoff blobs into public tickets without redaction review.
