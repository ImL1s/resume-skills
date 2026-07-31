# Cline fixtures

Synthetic `~/.cline/data` layout for `cline-session-json-v1`:

- `data/db/sessions.db` — SQLite index
- `data/sessions/<id>/<id>.messages.json` — authoritative turns (version 1)

Rebuild: `python3 tests/fixtures/cline/build_fixtures.py`

Cases:

- `s-cl-01-user-basic` — root user/assistant turns
- `s-cl-02-parent-subagent` — subagent hidden from default list
- `s-cl-03-unsupported-messages` — messages version != 1
