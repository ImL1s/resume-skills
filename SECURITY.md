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
| request-v1 file → reader | Pathname swap / symlink race on `--request-file` | Pre-open `lstat` identity bound to opened fd; final-component `dir_fd` + `O_NOFOLLOW`; double-read content verify; fail closed without symlink-safe open primitives |
| Recovered text → destination model | Prompt injection | `inert`/`untrusted` markers, sanitizer, quoted handoff, re-check checklist |
| Installer → skill roots | Overwrite non-owned files, path escape, parent/control symlink races, malicious skill supply chain | Ownership/claims, refuse collisions, pinned root lock, no-follow control store (`.portable-resume` lock/journal/manifest atomic replace), descriptor-relative payload commit/rollback/uninstall/verify, sandboxed journal stage/backup cleanup, dry-run |
| Optional zstd | Process boundary | Trusted absolute decoder paths only, fixed argv, `shell=False`, empty PATH, caps/timeouts |

### request-v1 file boundary

Optional `portable-resume/request-v1` documents are read only as regular, non-symlink files bounded by `DEFAULT_BOUNDS.request_bytes`. On POSIX platforms with `O_NOFOLLOW` / `O_DIRECTORY` / `dir_fd`:

1. Pre-open `lstat` requires a small regular file and records `(st_dev, st_ino, mode, size, mtime_ns)`.
2. The basename is opened descriptor-relative under the parent with `O_NOFOLLOW` (intermediate parent-path aliases such as macOS `/var` may still resolve).
3. The first `fstat` must match the pre-open fingerprint so a concurrent regular→regular pathname replacement cannot be accepted as the originally validated inode.
4. Bytes are read twice from the same descriptor; metadata must remain stable through a final pathname `lstat`.

Platforms that cannot guarantee symlink-safe final-component open (including Windows without these primitives) fail closed for request-file mode rather than claiming no-follow protection from a raceable pathname check alone. Mutation or replacement fails deterministically with content-free `E_INVALID_INPUT` diagnostics — request bytes from a failed attempt never reach JSON parsing.

### Supply chain (important)

Installing skills means writing instruction files that a host agent may later execute with the user’s privileges.

- Treat any third-party revision as untrusted until reviewed.
- Prefer `--scope project` and `--dry-run` first.
- `--scope global` writes under the host’s user skill roots (see `docs/host-support.md`).
- `--force-with-backup` may replace non-owned conflicting files after copying them under `.portable-resume/backups/`.
- If a host ignores skill instructions and shells user text, that is **out of scope** for the fixed runner argv (which never includes user fields).

### Secret redaction (honest coverage)

Redaction is **best-effort**, not complete DLP. The tracked-tree secret gate (`scripts/check_secrets.py`) scans `git ls-files` only (not git history). Runtime patterns include common shapes such as PEM private-key blocks, Slack `xox*`, Google-like `AIza…`, and:

- AWS-like `AKIA…`
- Common `sk-…` / Bearer-like tokens
- Simple `label=value` secret-looking pairs
- Some metadata field names (`system_prompt`, signatures, etc.)

**Not guaranteed:** arbitrary JWTs, uncommon cloud tokens, free-form passwords, secrets split across turns or obfuscated. PEM / Slack / AIza shapes are best-effort covered above but residual secrets may still remain in handoff text and host logs.

### Installer control plane and payload path races

On POSIX (Linux/macOS) the installer:

- Pins the skill root and rejects a symlinked or non-directory `.portable-resume` support dir.
- Opens `install.lock`, `journal.json`, and `manifest.json` with no-follow regular-file checks; lock metadata is truncated before rewrite.
- Writes journal and manifest via unique temporary names under the support dir, then atomic replace (not a predictable `*.tmp` pathname open).
- Commits, rolls back, uninstalls, and verifies payload files through directory file descriptors (`O_NOFOLLOW`) so a parent directory swapped for a symlink after planning cannot redirect writes/deletes outside the skill root.

Windows remains weaker: exclusive locking and full dirfd semantics are residual under issue #29; mutating install/uninstall fails closed where descriptor-relative primitives are unavailable rather than falling back to unsafe ambient pathname replace.

### Residual risks

- Recovered text remains model-visible; operators must not treat handoff as instructions.
- Temp snapshot directories may briefly hold session-derived bytes; failures should clean up, but crash windows exist.
- Handoff on stdout may be captured by host logging.
- Windows file locking is weaker than POSIX flock in V1; installer path races on Windows are gated fail-closed (#29) rather than claimed parity.
- The only intentional child process is the optional trusted zstd decoder for compressed Codex rollouts.
- Previous-manifest byte snapshots inside the journal for crash forensics remain best-effort via per-path rollback files; a richer previous-manifest generation record may still land under follow-up installer work.

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
