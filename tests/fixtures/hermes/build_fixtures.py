"""Rebuild synthetic Hermes state.db fixtures (stdlib sqlite3 only)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent
CWD = "/tmp/project"
# Unix epoch floats (Hermes timestamps)
T0 = 1704110400.0  # 2024-01-01 12:00:00 UTC
BASIC_ID = "hm000101-0101-4101-8101-010101010101"
CHILD_ID = "hm000102-0202-4202-8202-020202020202"
SCHEMA_VERSION = 23

SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    session_key TEXT,
    chat_id TEXT,
    chat_type TEXT,
    thread_id TEXT,
    display_name TEXT,
    origin_json TEXT,
    expiry_finalized INTEGER DEFAULT 0,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    cwd TEXT,
    git_branch TEXT,
    git_repo_root TEXT,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    api_call_count INTEGER DEFAULT 0,
    handoff_state TEXT,
    handoff_platform TEXT,
    handoff_error TEXT,
    compression_failure_cooldown_until REAL,
    compression_failure_error TEXT,
    compression_fallback_streak INTEGER NOT NULL DEFAULT 0,
    compression_ineffective_count INTEGER NOT NULL DEFAULT 0,
    profile_name TEXT,
    rewind_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    effect_disposition TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_content TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT,
    codex_message_items TEXT,
    platform_message_id TEXT,
    observed INTEGER DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    compacted INTEGER NOT NULL DEFAULT 0,
    api_content TEXT,
    display_kind TEXT,
    display_metadata TEXT
);
CREATE TABLE state_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    return conn


def _insert_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    source: str = "cli",
    title: str | None = None,
    parent_session_id: str | None = None,
    archived: int = 0,
    started_at: float = T0,
    ended_at: float | None = None,
    cwd: str = CWD,
    user_id: str | None = None,
    chat_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sessions (
            id, source, user_id, chat_id, title, parent_session_id,
            started_at, ended_at, cwd, archived, system_prompt, model
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            source,
            user_id,
            chat_id,
            title,
            parent_session_id,
            started_at,
            ended_at,
            cwd,
            archived,
            "synthetic system prompt must never appear",
            "synthetic-model",
        ),
    )


def _insert_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    timestamp: float,
    tool_name: str | None = None,
    tool_calls: str | None = None,
    reasoning: str | None = None,
    active: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO messages (
            session_id, role, content, tool_name, tool_calls, timestamp,
            reasoning, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, role, content, tool_name, tool_calls, timestamp, reasoning, active),
    )


def _manifest(case_dir: Path, *, case: str, expected_code: int = 0, op: str = "show") -> None:
    payload = {
        "case": case,
        "expected_code": expected_code,
        "expected_operation": op if expected_code == 0 else "error",
        "expected_warnings": [],
        "format_id": "hermes-state-sqlite-v1",
        "provenance_ref": "docs/source-formats.md#hermes-state-sqlite-v1",
        "source": "hermes",
        "synthetic": True,
    }
    (case_dir / "fixture.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build() -> None:
    # basic root CLI session
    case = FIXTURE_ROOT / "s-hm-01-user-basic"
    case.mkdir(parents=True, exist_ok=True)
    conn = _connect(case / "state.db")
    _insert_session(conn, session_id=BASIC_ID, title="synthetic hermes title")
    _insert_message(
        conn,
        session_id=BASIC_ID,
        role="user",
        content="synthetic hermes user prompt",
        timestamp=T0,
    )
    _insert_message(
        conn,
        session_id=BASIC_ID,
        role="assistant",
        content="synthetic hermes assistant reply",
        timestamp=T0 + 1,
        reasoning="secret reasoning must not appear",
    )
    conn.commit()
    conn.close()
    _manifest(case, case="s-hm-01-user-basic")

    # parent + child subagent (child hidden from default list)
    case = FIXTURE_ROOT / "s-hm-02-parent-child"
    case.mkdir(parents=True, exist_ok=True)
    conn = _connect(case / "state.db")
    _insert_session(conn, session_id=BASIC_ID, title="parent root")
    _insert_message(
        conn, session_id=BASIC_ID, role="user", content="parent user", timestamp=T0
    )
    _insert_message(
        conn,
        session_id=BASIC_ID,
        role="assistant",
        content="parent assistant",
        timestamp=T0 + 1,
    )
    _insert_session(
        conn,
        session_id=CHILD_ID,
        title="child subagent",
        parent_session_id=BASIC_ID,
        started_at=T0 + 10,
    )
    _insert_message(
        conn,
        session_id=CHILD_ID,
        role="user",
        content="child should hide from list",
        timestamp=T0 + 10,
    )
    _insert_message(
        conn,
        session_id=CHILD_ID,
        role="assistant",
        content="child reply",
        timestamp=T0 + 11,
    )
    conn.commit()
    conn.close()
    _manifest(case, case="s-hm-02-parent-child")

    # unsupported schema version
    case = FIXTURE_ROOT / "s-hm-03-unsupported-schema"
    case.mkdir(parents=True, exist_ok=True)
    conn = _connect(case / "state.db")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    _insert_session(conn, session_id=BASIC_ID, title="stale schema")
    _insert_message(
        conn, session_id=BASIC_ID, role="user", content="x", timestamp=T0
    )
    conn.commit()
    conn.close()
    _manifest(case, case="s-hm-03-unsupported-schema", expected_code=5, op="error")

    (FIXTURE_ROOT / "MANIFEST.md").write_text(
        "# Hermes fixtures\n\nSynthetic `hermes-state-sqlite-v1` (schema 23).\n"
        "Mark `synthetic: true`. No real home paths.\n",
        encoding="utf-8",
    )
    (FIXTURE_ROOT / "__init__.py").write_text("", encoding="utf-8")
    print("built hermes fixtures")


if __name__ == "__main__":
    build()
