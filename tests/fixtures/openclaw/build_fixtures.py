#!/usr/bin/env python3
"""Regenerate checked-in OpenClaw per-agent SQLite synthetic fixtures (stdlib only)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = 11
APP_VERSION = "0.0.0-synthetic"
TS = 1_700_000_000_000

_MINIMAL_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
  meta_key TEXT NOT NULL PRIMARY KEY,
  role TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  agent_id TEXT,
  app_version TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT NOT NULL PRIMARY KEY,
  channel TEXT NOT NULL,
  account_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('direct', 'group', 'channel')),
  peer_id TEXT NOT NULL,
  delivery_target TEXT NOT NULL,
  parent_conversation_id TEXT,
  thread_id TEXT,
  native_channel_id TEXT,
  native_direct_user_id TEXT,
  label TEXT,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS session_nodes (
  session_key TEXT NOT NULL PRIMARY KEY,
  current_session_id TEXT NOT NULL,
  entry_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  status TEXT CHECK (status IS NULL OR status IN ('running', 'done', 'failed', 'killed', 'timeout')),
  created_at INTEGER,
  created_via TEXT CHECK (created_via IS NULL OR created_via IN ('operator', 'spawn', 'channel', 'cron', 'talk', 'run', 'plugin', 'internal')),
  created_actor_type TEXT CHECK (created_actor_type IS NULL OR created_actor_type IN ('human', 'agent', 'system')),
  created_actor_id TEXT,
  parent_session_key TEXT,
  spawned_by TEXT,
  fork_source_session_key TEXT,
  fork_source_session_id TEXT,
  fork_source_entry_id TEXT,
  label TEXT,
  display_name TEXT,
  category TEXT,
  icon TEXT,
  pinned_at INTEGER,
  archived_at INTEGER,
  last_read_at INTEGER,
  last_interaction_at INTEGER,
  last_activity_at INTEGER
) STRICT;

CREATE TABLE IF NOT EXISTS session_windows (
  session_id TEXT NOT NULL PRIMARY KEY,
  session_key TEXT NOT NULL,
  previous_session_id TEXT,
  reason TEXT CHECK (reason IS NULL OR reason IN ('initial', 'reset', 'rollover', 'fork', 'rewind', 'switch', 'recovery', 'compaction')),
  session_scope TEXT NOT NULL DEFAULT 'conversation' CHECK (session_scope IN ('conversation', 'shared-main', 'group', 'channel')),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  transcript_updated_at INTEGER DEFAULT NULL,
  transcript_observed_at INTEGER DEFAULT NULL,
  session_entry_provenance INTEGER NOT NULL DEFAULT 0 CHECK (session_entry_provenance IN (0, 1)),
  acp_owned INTEGER NOT NULL DEFAULT 0 CHECK (acp_owned IN (0, 1)),
  plugin_owner_id TEXT,
  hook_external_content_source TEXT CHECK (hook_external_content_source IS NULL OR hook_external_content_source IN ('gmail', 'webhook')),
  started_at INTEGER,
  ended_at INTEGER,
  status TEXT CHECK (status IS NULL OR status IN ('running', 'done', 'failed', 'killed', 'timeout')),
  chat_type TEXT CHECK (chat_type IS NULL OR chat_type IN ('direct', 'group', 'channel')),
  channel TEXT,
  account_id TEXT,
  primary_conversation_id TEXT,
  model_provider TEXT,
  model TEXT,
  agent_harness_id TEXT,
  parent_session_key TEXT,
  spawned_by TEXT,
  display_name TEXT,
  FOREIGN KEY (session_key) REFERENCES session_nodes(session_key) ON DELETE CASCADE,
  FOREIGN KEY (primary_conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL
) STRICT;

CREATE TABLE IF NOT EXISTS session_conversations (
  session_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'participant', 'related')),
  first_seen_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  PRIMARY KEY (session_id, conversation_id, role),
  FOREIGN KEY (session_id) REFERENCES session_windows(session_id) ON DELETE CASCADE,
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE IF NOT EXISTS transcript_events (
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (session_id, seq),
  FOREIGN KEY (session_id) REFERENCES session_windows(session_id) ON DELETE CASCADE
) STRICT;
"""


def _entry_json(*, session_key: str, cwd: str = "/tmp/project") -> str:
    return json.dumps(
        {
            "sessionKey": session_key,
            "cwd": cwd,
            "model": "synthetic-model",
            "redacted": True,
        },
        separators=(",", ":"),
    )


def _message_event(*, role: str, text: str) -> str:
    return json.dumps(
        {"type": "message", "role": role, "text": text, "redacted": True},
        separators=(",", ":"),
    )


def _compaction_event(*, summary: str) -> str:
    return json.dumps(
        {"type": "compaction", "summary": summary, "firstKeptSeq": 1},
        separators=(",", ":"),
    )


def _branch_summary_event(*, branch: str) -> str:
    return json.dumps(
        {"type": "branch_summary", "branch": branch, "note": "synthetic"},
        separators=(",", ":"),
    )


def _open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    connection.executescript(_MINIMAL_DDL)
    return connection


def _write_schema_meta(
    connection: sqlite3.Connection,
    *,
    agent_id: str,
    schema_version: int = SCHEMA_VERSION,
) -> None:
    connection.execute(f"PRAGMA user_version = {int(schema_version)}")
    connection.execute(
        """
        INSERT INTO schema_meta (
          meta_key, role, schema_version, agent_id, app_version, created_at, updated_at
        ) VALUES (?, 'agent', ?, ?, ?, ?, ?)
        """,
        ("primary", schema_version, agent_id, APP_VERSION, TS, TS),
    )


def _seed_basic(
    connection: sqlite3.Connection,
    *,
    agent_id: str,
    session_key: str = "agent:main:direct:fixture-peer",
    session_id: str = "sess-basic-0001",
    conversation_id: str = "conv-basic-0001",
) -> None:
    _write_schema_meta(connection, agent_id=agent_id)
    connection.execute(
        """
        INSERT INTO conversations (
          conversation_id, channel, account_id, kind, peer_id, delivery_target,
          created_at, updated_at
        ) VALUES (?, 'fixture', 'default', 'direct', 'fixture-peer', 'fixture-peer', ?, ?)
        """,
        (conversation_id, TS, TS),
    )
    connection.execute(
        """
        INSERT INTO session_nodes (
          session_key, current_session_id, entry_json, updated_at, created_at,
          created_via, display_name, last_interaction_at
        ) VALUES (?, ?, ?, ?, ?, 'operator', 'Synthetic basic', ?)
        """,
        (session_key, session_id, _entry_json(session_key=session_key), TS, TS, TS),
    )
    connection.execute(
        """
        INSERT INTO session_windows (
          session_id, session_key, reason, session_scope, created_at, updated_at,
          started_at, chat_type, channel, account_id, primary_conversation_id, display_name
        ) VALUES (?, ?, 'initial', 'conversation', ?, ?, ?, 'direct', 'fixture', 'default', ?, 'Synthetic basic')
        """,
        (session_id, session_key, TS, TS, TS, conversation_id),
    )
    connection.execute(
        """
        INSERT INTO session_conversations (
          session_id, conversation_id, role, first_seen_at, last_seen_at
        ) VALUES (?, ?, 'primary', ?, ?)
        """,
        (session_id, conversation_id, TS, TS),
    )
    events = [
        _message_event(role="user", text="Resume context from /tmp/project"),
        _message_event(role="assistant", text="Synthetic assistant reply"),
    ]
    for index, event_json in enumerate(events, start=1):
        connection.execute(
            """
            INSERT INTO transcript_events (session_id, seq, event_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, index, event_json, TS + index),
        )


def _seed_compaction_reset(connection: sqlite3.Connection, *, agent_id: str) -> None:
    session_key = "agent:main:direct:compaction-peer"
    initial_id = "sess-compact-initial"
    reset_id = "sess-compact-reset"
    conversation_id = "conv-compact-0001"
    _write_schema_meta(connection, agent_id=agent_id)
    connection.execute(
        """
        INSERT INTO conversations (
          conversation_id, channel, account_id, kind, peer_id, delivery_target,
          created_at, updated_at
        ) VALUES (?, 'fixture', 'default', 'direct', 'compaction-peer', 'compaction-peer', ?, ?)
        """,
        (conversation_id, TS, TS),
    )
    connection.execute(
        """
        INSERT INTO session_nodes (
          session_key, current_session_id, entry_json, updated_at, created_at,
          created_via, display_name, last_interaction_at
        ) VALUES (?, ?, ?, ?, ?, 'operator', 'Compaction reset', ?)
        """,
        (session_key, reset_id, _entry_json(session_key=session_key), TS + 2, TS, TS + 2),
    )
    for session_id, reason, previous in (
        (initial_id, "initial", None),
        (reset_id, "reset", initial_id),
    ):
        connection.execute(
            """
            INSERT INTO session_windows (
              session_id, session_key, previous_session_id, reason, session_scope,
              created_at, updated_at, started_at, chat_type, channel, account_id,
              primary_conversation_id, display_name
            ) VALUES (?, ?, ?, ?, 'conversation', ?, ?, ?, 'direct', 'fixture', 'default', ?, ?)
            """,
            (
                session_id,
                session_key,
                previous,
                reason,
                TS,
                TS + 1,
                TS,
                conversation_id,
                f"Window {reason}",
            ),
        )
        connection.execute(
            """
            INSERT INTO session_conversations (
              session_id, conversation_id, role, first_seen_at, last_seen_at
            ) VALUES (?, ?, 'primary', ?, ?)
            """,
            (session_id, conversation_id, TS, TS),
        )
    events = [
        _message_event(role="user", text="Long thread before compaction"),
        _compaction_event(summary="Synthetic compaction kept first message"),
        _branch_summary_event(branch="side-task"),
        _message_event(role="assistant", text="Post-reset assistant line"),
    ]
    for index, event_json in enumerate(events, start=1):
        connection.execute(
            """
            INSERT INTO transcript_events (session_id, seq, event_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (reset_id, index, event_json, TS + index),
        )


def _seed_internal_filter(connection: sqlite3.Connection, *, agent_id: str) -> None:
    _write_schema_meta(connection, agent_id=agent_id)
    rows = (
        (
            "agent:main:direct:operator-peer",
            "sess-operator-01",
            "conv-operator-01",
            "operator",
            "Operator session",
            [_message_event(role="user", text="Visible operator session")],
        ),
        (
            "agent:main:internal:cron-tick",
            "sess-internal-01",
            "conv-internal-01",
            "internal",
            "Internal cron",
            [_message_event(role="system", text="Internal heartbeat row")],
        ),
        (
            "agent:main:cron:scheduled",
            "sess-cron-01",
            "conv-cron-01",
            "cron",
            "Cron session",
            [_message_event(role="system", text="Scheduled cron row")],
        ),
    )
    for session_key, session_id, conversation_id, created_via, display_name, events in rows:
        connection.execute(
            """
            INSERT INTO conversations (
              conversation_id, channel, account_id, kind, peer_id, delivery_target,
              created_at, updated_at
            ) VALUES (?, 'fixture', 'default', 'direct', ?, ?, ?, ?)
            """,
            (conversation_id, session_key.rsplit(":", 1)[-1], session_key.rsplit(":", 1)[-1], TS, TS),
        )
        connection.execute(
            """
            INSERT INTO session_nodes (
              session_key, current_session_id, entry_json, updated_at, created_at,
              created_via, display_name, last_interaction_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_key,
                session_id,
                _entry_json(session_key=session_key),
                TS,
                TS,
                created_via,
                display_name,
                TS,
            ),
        )
        connection.execute(
            """
            INSERT INTO session_windows (
              session_id, session_key, reason, session_scope, created_at, updated_at,
              started_at, chat_type, channel, account_id, primary_conversation_id, display_name
            ) VALUES (?, ?, 'initial', 'conversation', ?, ?, ?, 'direct', 'fixture', 'default', ?, ?)
            """,
            (session_id, session_key, TS, TS, TS, conversation_id, display_name),
        )
        connection.execute(
            """
            INSERT INTO session_conversations (
              session_id, conversation_id, role, first_seen_at, last_seen_at
            ) VALUES (?, ?, 'primary', ?, ?)
            """,
            (session_id, conversation_id, TS, TS),
        )
        for index, event_json in enumerate(events, start=1):
            connection.execute(
                """
                INSERT INTO transcript_events (session_id, seq, event_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, index, event_json, TS + index),
            )


def _seed_corrupt_meta(connection: sqlite3.Connection, *, agent_id: str) -> None:
    absurd_version = 99_999
    _write_schema_meta(connection, agent_id=agent_id, schema_version=absurd_version)
    connection.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
    session_key = "agent:main:direct:corrupt-peer"
    session_id = "sess-corrupt-01"
    conversation_id = "conv-corrupt-01"
    connection.execute(
        """
        INSERT INTO conversations (
          conversation_id, channel, account_id, kind, peer_id, delivery_target,
          created_at, updated_at
        ) VALUES (?, 'fixture', 'default', 'direct', 'corrupt-peer', 'corrupt-peer', ?, ?)
        """,
        (conversation_id, TS, TS),
    )
    connection.execute(
        """
        INSERT INTO session_nodes (
          session_key, current_session_id, entry_json, updated_at, created_at,
          created_via, display_name, last_interaction_at
        ) VALUES (?, ?, ?, ?, ?, 'operator', 'Corrupt meta', ?)
        """,
        (session_key, session_id, _entry_json(session_key=session_key), TS, TS, TS),
    )
    connection.execute(
        """
        INSERT INTO session_windows (
          session_id, session_key, reason, session_scope, created_at, updated_at,
          started_at, chat_type, channel, account_id, primary_conversation_id, display_name
        ) VALUES (?, ?, 'initial', 'conversation', ?, ?, ?, 'direct', 'fixture', 'default', ?, 'Corrupt meta')
        """,
        (session_id, session_key, TS, TS, TS, conversation_id),
    )
    connection.execute(
        """
        INSERT INTO session_conversations (
          session_id, conversation_id, role, first_seen_at, last_seen_at
        ) VALUES (?, ?, 'primary', ?, ?)
        """,
        (session_id, conversation_id, TS, TS),
    )
    connection.execute(
        """
        INSERT INTO transcript_events (session_id, seq, event_json, created_at)
        VALUES (?, 1, ?, ?)
        """,
        (session_id, _message_event(role="user", text="Should fail closed on meta mismatch"), TS + 1),
    )


def _write_fixture_json(case_dir: Path, *, case: str, expected_operation: str, expected_code: int) -> None:
    payload = {
        "case": case,
        "expected_code": expected_code,
        "expected_operation": expected_operation,
        "expected_warnings": [],
        "format_id": "openclaw-agent-sqlite-v1",
        "provenance_ref": "docs/source-formats.md#openclaw-openclaw-agent-sqlite-v1",
        "source": "openclaw",
        "synthetic": True,
    }
    (case_dir / "fixture.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def build_all(root: Path | None = None) -> None:
    fixture_root = Path(root) if root is not None else FIXTURE_ROOT
    case_specs: list[tuple[str, str, str, int]] = [
        ("s-oc-01-basic", "show", 0),
        ("s-oc-02-multi-agent", "list", 0),
        ("s-oc-03-compaction-reset", "show", 0),
        ("s-oc-04-internal-filter", "list", 0),
        ("s-oc-05-corrupt-meta", "error", 5),
    ]
    for case, operation, code in case_specs:
        case_dir = fixture_root / case
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_fixture_json(case_dir, case=case, expected_operation=operation, expected_code=code)

    basic_db = fixture_root / "s-oc-01-basic" / "agents/main/agent/openclaw-agent.sqlite"
    with _open_db(basic_db) as connection:
        _seed_basic(connection, agent_id="main")
        connection.commit()

    multi_main = fixture_root / "s-oc-02-multi-agent" / "agents/main/agent/openclaw-agent.sqlite"
    with _open_db(multi_main) as connection:
        _seed_basic(connection, agent_id="main", session_key="agent:main:direct:main-peer", session_id="sess-main-0001")
        connection.commit()
    multi_worker = fixture_root / "s-oc-02-multi-agent" / "agents/worker/agent/openclaw-agent.sqlite"
    with _open_db(multi_worker) as connection:
        _seed_basic(
            connection,
            agent_id="worker",
            session_key="agent:worker:direct:worker-peer",
            session_id="sess-worker-0001",
            conversation_id="conv-worker-0001",
        )
        connection.commit()

    compact_db = fixture_root / "s-oc-03-compaction-reset" / "agents/main/agent/openclaw-agent.sqlite"
    with _open_db(compact_db) as connection:
        _seed_compaction_reset(connection, agent_id="main")
        connection.commit()

    internal_db = fixture_root / "s-oc-04-internal-filter" / "agents/main/agent/openclaw-agent.sqlite"
    with _open_db(internal_db) as connection:
        _seed_internal_filter(connection, agent_id="main")
        connection.commit()

    corrupt_db = fixture_root / "s-oc-05-corrupt-meta" / "agents/main/agent/openclaw-agent.sqlite"
    with _open_db(corrupt_db) as connection:
        _seed_corrupt_meta(connection, agent_id="main")
        connection.commit()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="optional output root (default: this fixtures dir)")
    args = parser.parse_args()
    build_all(root=args.root)
