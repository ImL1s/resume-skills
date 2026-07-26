"""Rebuild synthetic goose sessions.db fixtures (stdlib sqlite3 only)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKING_DIR = "/tmp/project"
NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
NOW_TS = NOW.strftime("%Y-%m-%d %H:%M:%S")
NOW_MS = int(NOW.timestamp() * 1000)

SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    user_set_name BOOLEAN DEFAULT FALSE,
    session_type TEXT NOT NULL DEFAULT 'user',
    working_dir TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    extension_data TEXT DEFAULT '{}',
    total_tokens INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    accumulated_total_tokens INTEGER,
    accumulated_input_tokens INTEGER,
    accumulated_output_tokens INTEGER,
    accumulated_cache_read_tokens INTEGER,
    accumulated_cache_write_tokens INTEGER,
    accumulated_cost REAL,
    schedule_id TEXT,
    recipe_json TEXT,
    user_recipe_values_json TEXT,
    provider_name TEXT,
    model_config_json TEXT,
    goose_mode TEXT NOT NULL DEFAULT 'auto',
    archived_at TIMESTAMP,
    project_id TEXT,
    parent_session_id TEXT
)
"""

MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_timestamp INTEGER NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tokens INTEGER,
    metadata_json TEXT
)
"""

USAGE_LEDGER_TABLE = """
CREATE TABLE IF NOT EXISTS usage_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    created_timestamp INTEGER NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    cost REAL,
    cost_source TEXT,
    is_compaction INTEGER DEFAULT 0
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id)",
    "CREATE INDEX IF NOT EXISTS idx_usage_ledger_session ON usage_ledger(session_id)",
)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_core_schema(conn: sqlite3.Connection, *, include_usage_ledger: bool = True) -> None:
    conn.execute(SCHEMA_VERSION_TABLE)
    conn.execute(SESSIONS_TABLE)
    conn.execute(MESSAGES_TABLE)
    if include_usage_ledger:
        conn.execute(USAGE_LEDGER_TABLE)
    for statement in INDEXES:
        if not include_usage_ledger and "usage_ledger" in statement:
            continue
        conn.execute(statement)


def _insert_schema_versions(conn: sqlite3.Connection, versions: range) -> None:
    for version in versions:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, NOW_TS),
        )


def _insert_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    name: str,
    session_type: str,
    parent_session_id: str | None = None,
    archived_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sessions (
            id, name, description, user_set_name, session_type, working_dir,
            created_at, updated_at, extension_data, total_tokens, input_tokens,
            output_tokens, accumulated_total_tokens, accumulated_input_tokens,
            accumulated_output_tokens, goose_mode, archived_at, parent_session_id
        ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, '{}', 120, 40, 80, 120, 40, 80, 'auto', ?, ?)
        """,
        (
            session_id,
            name,
            name,
            session_type,
            WORKING_DIR,
            NOW_TS,
            NOW_TS,
            archived_at,
            parent_session_id,
        ),
    )


def _insert_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    message_id: str,
    role: str,
    text: str,
) -> None:
    content = json.dumps([{"type": "text", "text": text}], separators=(",", ":"))
    conn.execute(
        """
        INSERT INTO messages (
            message_id, session_id, role, content_json, created_timestamp, timestamp, tokens
        ) VALUES (?, ?, ?, ?, ?, ?, 40)
        """,
        (message_id, session_id, role, content, NOW_MS, NOW_TS),
    )


def _insert_usage_ledger_row(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    model: str = "synthetic-model",
    cost: float = 0.01,
    is_compaction: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO usage_ledger (
            session_id, created_timestamp, model, input_tokens, output_tokens,
            total_tokens, cache_read_tokens, cache_write_tokens, cost, cost_source,
            is_compaction
        ) VALUES (?, ?, ?, 40, 80, 120, 0, 0, ?, 'reported', ?)
        """,
        (session_id, NOW_MS, model, cost, is_compaction),
    )


def build_s_go_01() -> None:
    case = ROOT / "s-go-01-user-basic"
    db_path = case / "sessions" / "sessions.db"
    conn = _connect(db_path)
    _create_core_schema(conn)
    _insert_schema_versions(conn, range(1, 16))
    session_id = "go000101-0101-4101-8101-010101010101"
    _insert_session(conn, session_id=session_id, name="basic user session", session_type="user")
    _insert_message(
        conn,
        session_id=session_id,
        message_id="go000101-msg-0001",
        role="user",
        text="synthetic goose user prompt",
    )
    _insert_message(
        conn,
        session_id=session_id,
        message_id="go000101-msg-0002",
        role="assistant",
        text="synthetic goose assistant reply",
    )
    conn.commit()
    conn.close()


def build_s_go_02() -> None:
    case = ROOT / "s-go-02-session-types"
    db_path = case / "sessions" / "sessions.db"
    conn = _connect(db_path)
    _create_core_schema(conn)
    _insert_schema_versions(conn, range(1, 16))
    session_types = (
        ("go020201-0201-4201-8201-020202020201", "user session", "user"),
        ("go020202-0202-4202-8202-020202020202", "scheduled session", "scheduled"),
        ("go020203-0203-4203-8203-020202020203", "subagent session", "sub_agent"),
        ("go020204-0204-4204-8204-020202020204", "hidden session", "hidden"),
        ("go020205-0205-4205-8205-020202020205", "gateway session", "gateway"),
        ("go020206-0206-4206-8206-020202020206", "acp session", "acp"),
    )
    for session_id, name, session_type in session_types:
        _insert_session(conn, session_id=session_id, name=name, session_type=session_type)
        _insert_message(
            conn,
            session_id=session_id,
            message_id=f"{session_id}-msg",
            role="user",
            text=f"synthetic {session_type} marker",
        )
    conn.commit()
    conn.close()


def build_s_go_03() -> None:
    case = ROOT / "s-go-03-parent-subagent"
    db_path = case / "sessions" / "sessions.db"
    conn = _connect(db_path)
    _create_core_schema(conn)
    _insert_schema_versions(conn, range(1, 16))
    parent_id = "go030301-0301-4301-8301-030303030301"
    child_id = "go030302-0302-4302-8302-030303030302"
    _insert_session(conn, session_id=parent_id, name="parent user session", session_type="user")
    _insert_session(
        conn,
        session_id=child_id,
        name="linked subagent session",
        session_type="sub_agent",
        parent_session_id=parent_id,
    )
    _insert_message(
        conn,
        session_id=parent_id,
        message_id="go030301-msg-0001",
        role="user",
        text="synthetic parent prompt",
    )
    _insert_message(
        conn,
        session_id=child_id,
        message_id="go030302-msg-0001",
        role="assistant",
        text="synthetic subagent reply",
    )
    _insert_usage_ledger_row(conn, session_id=parent_id, cost=0.02)
    _insert_usage_ledger_row(conn, session_id=child_id, cost=0.03, is_compaction=1)
    conn.commit()
    conn.close()


def build_s_go_04() -> None:
    case = ROOT / "s-go-04-archived"
    db_path = case / "sessions" / "sessions.db"
    conn = _connect(db_path)
    _create_core_schema(conn)
    _insert_schema_versions(conn, range(1, 16))
    session_id = "go040401-0401-4401-8401-040404040401"
    _insert_session(
        conn,
        session_id=session_id,
        name="archived user session",
        session_type="user",
        archived_at=NOW_TS,
    )
    _insert_message(
        conn,
        session_id=session_id,
        message_id="go040401-msg-0001",
        role="user",
        text="synthetic archived session marker",
    )
    conn.commit()
    conn.close()


def build_s_go_05() -> None:
    case = ROOT / "s-go-05-unsupported-schema"
    db_path = case / "sessions" / "sessions.db"
    conn = _connect(db_path)
    _create_core_schema(conn, include_usage_ledger=False)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (99, NOW_TS),
    )
    session_id = "go050501-0501-4501-8501-050505050501"
    _insert_session(conn, session_id=session_id, name="unsupported schema marker", session_type="user")
    conn.commit()
    conn.close()


def main() -> None:
    build_s_go_01()
    build_s_go_02()
    build_s_go_03()
    build_s_go_04()
    build_s_go_05()


if __name__ == "__main__":
    main()
