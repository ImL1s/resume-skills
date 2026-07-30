# Crush fixtures

Synthetic `crush.db` stores for `crush-sqlite-v1` (goose_db_version max 7).

Rebuild: `python3 tests/fixtures/crush/build_fixtures.py`

Cases:
- `s-cr-01-user-basic` — root user/assistant turns
- `s-cr-02-parent-child` — child session hidden from default list
- `s-cr-03-unsupported-schema` — wrong goose_db_version max
