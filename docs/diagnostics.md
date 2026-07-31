# Diagnostics reference

Portable Resume exposes stable process exit codes and machine-readable diagnostics for automation. Each machine diagnostic is one compact JSON line on stderr. The reader writes no other error prose; installer argument parsing may write argparse usage text before its JSON diagnostic. Successful result envelopes and ambiguous-selection candidate envelopes are written to stdout, so callers can parse stdout without mixing it with error metadata.

## Diagnostic JSON shape

For example, an invalid source or action emits:

```json
{"attempts":null,"code":"E_INVALID_INPUT","exit_code":2,"family":[],"message":"The request is invalid.","provider":null,"schema_version":"portable-resume/diagnostic-v1","source":null}
```

| Field | Meaning |
|---|---|
| `schema_version` | Always `portable-resume/diagnostic-v1`. |
| `code` | Stable `E_*` diagnostic identifier. |
| `message` | Fixed English prose selected by `code`. |
| `exit_code` | Numeric process exit status associated with `code`. |
| `source` | Enabled source key when it is safe and relevant; otherwise `null`. |
| `provider` | Bounded provider or format identifier; otherwise `null`. |
| `attempts` | Non-negative stable-read attempt count when relevant; otherwise `null`. |
| `family` | Bounded basename-like family member identifiers; otherwise an empty array. |

Messages are fixed English prose selected by code. Recovered text, filesystem paths, and user data never appear in diagnostic messages. Optional identifiers are bounded and sanitized before serialization.

## Exit codes

This table is generated from `ExitCode` in `src/portable_resume/diagnostics.py`.

<!-- generated:exit-codes-table:begin (run scripts/render_docs.py --write) -->
| Number | Name | Meaning | Caller action |
|---:|---|---|---|
| 0 | `OK` | The command completed successfully. | Parse the stdout result. |
| 2 | `INVALID_INPUT` | Arguments or request data are invalid. | Correct the invocation; do not retry unchanged input. |
| 3 | `NO_MATCH` | No eligible persisted session matched. | Treat this as an empty result or broaden the query. |
| 4 | `AMBIGUOUS` | More than one eligible session matched. | Parse the stdout candidates envelope and choose an exact reference. |
| 5 | `UNSUPPORTED` | The store format or requested capability is unavailable. | Select a supported source/capability or install the optional capability. |
| 6 | `UNSAFE_OR_BUSY` | A path, live store, install root, or recovery state is unsafe or busy. | Retry later or inspect the reported store/install safety state. |
| 7 | `CORRUPT_OR_LIMIT` | Persisted data is corrupt, a bound was exceeded, or verification failed. | Inspect the result, reduce scope if applicable, and repair or recreate invalid state. |
| 8 | `INVARIANT` | An internal contract invariant failed. | Preserve the diagnostic and file a bug. |
<!-- generated:exit-codes-table:end (run scripts/render_docs.py --write) -->

## Error codes

The table is generated from `ERROR_EXIT_CODES` and the fixed `DiagnosticError` messages in `src/portable_resume/diagnostics.py`.

<!-- generated:error-codes-table:begin (run scripts/render_docs.py --write) -->
| Code | Exit | Fixed message | Emitted by |
|---|---:|---|---|
| `E_INVALID_INPUT` | 2 | The request is invalid. | Reader and installer |
| `E_NO_MATCH` | 3 | No eligible session matched the request. | Reader |
| `E_AMBIGUOUS` | 4 | More than one eligible session matched the request. | Reader |
| `E_UNSUPPORTED_FORMAT` | 5 | No supported persisted-session format was detected. | Reader |
| `E_CAPABILITY_UNAVAILABLE` | 5 | The requested source capability is unavailable. | Reader |
| `E_UNSAFE_PATH` | 6 | The requested path is outside an approved safe root or is not a regular file. | Reader |
| `E_SOURCE_BUSY` | 6 | The source changed during bounded stable-read attempts. | Reader |
| `E_SQLITE_HOT_JOURNAL` | 6 | The SQLite family contains an unproven rollback journal. | Reader |
| `E_LIMIT_EXCEEDED` | 7 | A configured resource bound was exceeded. | Reader |
| `E_CORRUPT_RECORD` | 7 | A persisted record is corrupt or invalid. | Reader |
| `E_INVARIANT` | 8 | An internal contract invariant failed. | Reader and installer |
| `E_INSTALL_BUSY` | 6 | Another install operation holds the destination root lock. | Installer |
| `E_INSTALL_CONFLICT` | 6 | A destination path conflicts with a non-owned or incompatible file. | Installer |
| `E_INSTALL_SHADOW` | 6 | A higher-precedence discovery root already holds a divergent Portable Resume Skill. | Installer |
| `E_INSTALL_UNSUPPORTED_PLATFORM` | 5 | Mutating installer operations are not supported on this platform. | Installer |
| `E_RECOVERY_REQUIRED` | 6 | A durable install journal requires recovery before mutation. | Installer |
| `E_VERIFY_MISMATCH` | 7 | Installed files do not match the owned manifest. | Installer |
<!-- generated:error-codes-table:end (run scripts/render_docs.py --write) -->

## Reader self-check result warnings

<!-- generated:self-check-result-contract:begin (run scripts/render_docs.py --write) -->
The reader's `self-check` command has a separate JSON result contract on stdout. These result warnings are not `diagnostic-v1` stderr diagnostics:

| Result warning | Meaning |
|---|---|
| `W_REGISTRY_INVALID:<ExceptionType>` | Registry validation raised the named exception type. |
| `W_SCHEMA_MISSING` | The bundled request schema file is absent. |

Either warning makes the self-check result's `ok` field false. The command still writes the result envelope to stdout and returns exit 7 (`CORRUPT_OR_LIMIT`), rather than emitting an error diagnostic.
<!-- generated:self-check-result-contract:end (run scripts/render_docs.py --write) -->

## Envelope warning codes

The ordinary list/show warnings below are not stderr diagnostics. They ride inside the stdout envelope's `warnings` array and do not independently change the process exit status. The list is generated from `WARNING_CODES`.

<!-- generated:warning-codes-list:begin (run scripts/render_docs.py --write) -->
- `W_BINARY_OMITTED`
- `W_BROKEN_CHAIN`
- `W_CONTROLS_REMOVED`
- `W_HOST_DISCOVERY_UNPROVEN`
- `W_LIVE_SMOKE_NOT_RUN`
- `W_METADATA_REDACTED`
- `W_MISSING_BLOB`
- `W_OPTIONAL_ZSTD_UNAVAILABLE`
- `W_PARTIAL_TAIL`
- `W_SKILL_DUPLICATE`
- `W_SKILL_SHADOW`
- `W_STALE_INDEX`
- `W_TRUNCATED`
- `W_UNKNOWN_RECORD_SKIPPED`
<!-- generated:warning-codes-list:end (run scripts/render_docs.py --write) -->

## Installer result exits

Installer commands return versioned result documents on stdout. In addition to JSON diagnostics, `matrix` returns exit 7 when its result is not OK, while `audit-host` returns exit 6 for a blocking aggregate result. `verify` can emit `E_VERIFY_MISMATCH` with exit 7 when installed files do not match the owned manifest. Callers should therefore inspect both the process status and the command's stdout result document.
