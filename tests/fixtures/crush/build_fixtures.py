"""Rebuild synthetic Crush crush.db fixtures (stdlib sqlite3 only)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent
WORKING_DIR = "/tmp/project"
NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
BASIC_ID = "cr000101-0101-4101-8101-010101010101"
CHILD_ID = "cr000102-0202-4202-8202-020202020202"
SCHEMA_VERSION = 7

SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    parent_session_id TEXT,
    title TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0.0,
    updated_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    summary_message_id TEXT,
    todos TEXT
)
"""

MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    parts TEXT NOT NULL DEFAULT '[]',
    model TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    finished_at INTEGER,
    provider TEXT,
    is_summary_message INTEGER DEFAULT 0 NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
)
"""

GOOSE_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS goose_db_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL,
    is_applied INTEGER NOT NULL,
    tstamp TIMESTAMP DEFAULT (datetime('now'))
)
"""

FILES_TABLE = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    path TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
)
"""

READ_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS read_files (
    session_id TEXT NOT NULL,
    path TEXT NOT NULL,
    read_at INTEGER NOT NULL,
    PRIMARY KEY (path, session_id)
)
"""


def _parts_text(text: str) -> str:
    return json.dumps(
        [{"type": "text", "data": {"text": text}}],
        separators=(",", ":"),
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_schema(conn: sqlite3.Connection, *, version: int = SCHEMA_VERSION) -> None:
    conn.execute(GOOSE_VERSION_TABLE)
    conn.execute(SESSIONS_TABLE)
    conn.execute(MESSAGES_TABLE)
    conn.execute(FILES_TABLE)
    conn.execute(READ_FILES_TABLE)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id)")
    for version_id in range(1, version + 1):
        conn.execute(
            "INSERT INTO goose_db_version (version_id, is_applied) VALUES (?, 1)",
            (version_id,),
        )


def _insert_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    title: str,
    parent_session_id: str | None = None,
    message_count: int = 0,
    created_at: int = NOW_MS,
    updated_at: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sessions (
            id, parent_session_id, title, message_count,
            prompt_tokens, completion_tokens, cost, updated_at, created_at
        ) VALUES (?, ?, ?, ?, 10, 20, 0.01, ?, ?)
        """,
        (
            session_id,
            parent_session_id,
            title,
            message_count,
            updated_at if updated_at is not None else created_at,
            created_at,
        ),
    )


def _insert_message(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    session_id: str,
    role: str,
    text: str,
    created_at: int = NOW_MS,
) -> None:
    conn.execute(
        """
        INSERT INTO messages (
            id, session_id, role, parts, model, created_at, updated_at, finished_at, provider
        ) VALUES (?, ?, ?, ?, 'synthetic', ?, ?, ?, 'synthetic')
        """,
        (
            message_id,
            session_id,
            role,
            _parts_text(text),
            created_at,
            created_at,
            created_at,
        ),
    )


def _write_manifest(
    case_dir: Path,
    *,
    case: str,
    expected_operation: str = "show",
    expected_code: int = 0,
) -> None:
    payload = {
        "case": case,
        "expected_code": expected_code,
        "expected_operation": expected_operation,
        "expected_warnings": [],
        "format_id": "crush-sqlite-v1",
        "provenance_ref": "docs/source-formats.md#crush-sqlite-v1",
        "source": "crush",
        "synthetic": True,
    }
    (case_dir / "fixture.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_s_cr_01() -> None:
    case = "s-cr-01-user-basic"
    case_dir = FIXTURE_ROOT / case
    db_path = case_dir / "crush.db"
    conn = _connect(db_path)
    _create_schema(conn)
    _insert_session(conn, session_id=BASIC_ID, title="basic crush session", message_count=2)
    _insert_message(
        conn,
        message_id="msg-user-1",
        session_id=BASIC_ID,
        role="user",
        text="synthetic crush user prompt",
    )
    _insert_message(
        conn,
        message_id="msg-asst-1",
        session_id=BASIC_ID,
        role="assistant",
        text="synthetic crush assistant reply",
        created_at=NOW_MS + 1,
    )
    conn.commit()
    conn.close()
    _write_manifest(case_dir, case=case)


def build_s_cr_02_parent_child() -> None:
    case = "s-cr-02-parent-child"
    case_dir = FIXTURE_ROOT / case
    db_path = case_dir / "crush.db"
    conn = _connect(db_path)
    _create_schema(conn)
    _insert_session(conn, session_id=BASIC_ID, title="parent session", message_count=2)
    _insert_message(
        conn,
        message_id="p-user",
        session_id=BASIC_ID,
        role="user",
        text="parent user text",
    )
    _insert_message(
        conn,
        message_id="p-asst",
        session_id=BASIC_ID,
        role="assistant",
        text="parent assistant text",
        created_at=NOW_MS + 1,
    )
    _insert_session(
        conn,
        session_id=CHILD_ID,
        title="child session",
        parent_session_id=BASIC_ID,
        message_count=1,
        created_at=NOW_MS + 1000,
        updated_at=NOW_MS + 2000,
    )
    _insert_message(
        conn,
        message_id="c-user",
        session_id=CHILD_ID,
        role="user",
        text="child should be hidden from default list",
        created_at=NOW_MS + 2000,
    )
    conn.commit()
    conn.close()
    _write_manifest(case_dir, case=case)


def build_s_cr_03_unsupported() -> None:
    case = "s-cr-03-unsupported-schema"
    case_dir = FIXTURE_ROOT / case
    db_path = case_dir / "crush.db"
    conn = _connect(db_path)
    _create_schema(conn, version=3)  # wrong max version
    _insert_session(conn, session_id=BASIC_ID, title="old schema", message_count=1)
    _insert_message(
        conn,
        message_id="u-1",
        session_id=BASIC_ID,
        role="user",
        text="should probe unsupported",
    )
    conn.commit()
    conn.close()
    _write_manifest(case_dir, case=case, expected_operation="error", expected_code=5)


def main() -> None:
    build_s_cr_01()
    build_s_cr_02_parent_child()
    build_s_cr_03_unsupported()
    print("crush fixtures rebuilt")


if __name__ == "__main__":
    main()
