# Security Policy

## Threat model (summary)

`portable-resume-skills` is a **local, offline-friendly** tool that:

1. Reads **untrusted** persisted agent session stores from disk (JSONL, SQLite, etc.).
2. Emits sanitized, inert handoff text for a **fresh** session.
3. Can install skill packages into project or user skill roots.

It is **not** a network service and does not restore live processes.

### Assets

- Local session history (may contain secrets, private paths, credentials).
- Destination skill roots (project/global agent skill directories).
- Source session stores (must remain byte/mtime unchanged).

### Trust boundaries

| Boundary | Threat | Control |
|---|---|---|
| Source store → reader | Path escape, symlink, special files, concurrent mutation | Approved roots, no-follow regular files, stable snapshot, fail closed |
| Recovered text → destination model | Prompt injection | `inert`/`untrusted` markers, sanitizer, quoted handoff, re-check checklist |
| Installer → skill roots | Overwrite non-owned files, path escape | Ownership/claims, refuse collisions, root lock, sandboxed journal paths |
| Optional zstd | Process boundary | Trusted decoder path only, fixed argv, no shell, caps/timeouts |

### Residual risks (honest)

- Secret redaction is **best-effort**, not complete DLP.
- Recovered text remains model-visible; operators must not treat handoff as instructions.
- `install --scope global` and `--force-with-backup` are powerful — do not run them on untrusted forks without review.
- Host agents may still shell-interpolate user text if *operators* ignore skill instructions; the fixed runner argv never includes user fields.

## Supported versions

Security fixes target the `main` branch of this repository.

## Reporting a vulnerability

Please report security issues privately when possible:

1. Prefer GitHub **Security Advisories** for this repository when enabled.
2. Otherwise open a private contact via the repository owner’s GitHub security contact / email listed on the profile.
3. Include: impact, reproduction steps, affected commit SHA, and whether session data was involved.

Do **not** attach real private transcripts or credentials to public issues.

## Safe operating guidelines

- Prefer project-scope installs over global when evaluating unknown revisions.
- Avoid `--force-with-backup` unless you understand which non-owned paths will be replaced.
- Treat handoff output as stale evidence; re-verify repository state before acting.
- Never point `--source-root` at untrusted trees you do not intend to parse.
