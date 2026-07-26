# OpenClaw per-agent SQLite synthetic fixtures

All cases are independently authored (`synthetic: true`). No adapter or registry support is claimed.

Pinned format: `openclaw-agent-sqlite-v1` with `PRAGMA user_version = 11` and matching `schema_meta.schema_version`.

Privacy: fixture `entry_json` and `event_json` payloads are synthetic. No real phone numbers, emails, API keys, or home paths. Cwd-like fields use `/tmp/project` only.

| Case | Format ID | Notes |
|---|---|---|
| `s-oc-01-basic` | `openclaw-agent-sqlite-v1` | Single agent DB with message transcript events |
| `s-oc-02-multi-agent` | `openclaw-agent-sqlite-v1` | `main` + `worker` agent databases under one fixture root |
| `s-oc-03-compaction-reset` | `openclaw-agent-sqlite-v1` | Reset window chain with compaction + branch_summary events |
| `s-oc-04-internal-filter` | `openclaw-agent-sqlite-v1` | `created_via=internal` and `cron` session rows for future filter tests |
| `s-oc-05-corrupt-meta` | `openclaw-agent-sqlite-v1` | `schema_meta.schema_version` absurd vs `user_version` for fail-closed |

Regenerate checked-in DBs:

```bash
python3 tests/fixtures/openclaw/build_fixtures.py
```

Provenance: `docs/source-formats.md#openclaw-openclaw-agent-sqlite-v1`.
