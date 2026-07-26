# Goose sessions.db synthetic fixtures (schema v15)

All cases are independently authored (`synthetic: true`). No adapter or registry support is claimed.
Legacy JSONL session stores are **out of scope** for this PR.

Upstream authority: `aaif-goose/goose` `CURRENT_SCHEMA_VERSION = 15` (`session_manager.rs`).
`session_type` strings use upstream `SessionType` snake_case (`sub_agent`, not `sub-agent`).

| Case | Format ID | Notes |
|---|---|---|
| `s-go-01-user-basic` | `goose-sessions-sqlite-v15` | Schema v15 + one `user` session with user/assistant messages |
| `s-go-02-session-types` | `goose-sessions-sqlite-v15` | Rows for `user`, `scheduled`, `sub_agent`, `hidden`, `gateway`, `acp` |
| `s-go-03-parent-subagent` | `goose-sessions-sqlite-v15` | `parent_session_id` linkage + `usage_ledger` rows |
| `s-go-04-archived` | `goose-sessions-sqlite-v15` | `archived_at` set on a `user` session |
| `s-go-05-unsupported-schema` | `goose-sessions-sqlite-v15` | `schema_version` row **99**; missing `usage_ledger` table |

## Future adapter filter expectations

Normal `list` should prefer `session_type = user` sessions. By default exclude
`scheduled`, `sub_agent`, `hidden`, `gateway`, and `acp` unless explicitly requested.
Archived sessions (`archived_at` not null) are excluded from default list unless an
archive-aware query is added later.

Provenance: `docs/source-formats.md#goose-goose-sessions-sqlite-v15`.
