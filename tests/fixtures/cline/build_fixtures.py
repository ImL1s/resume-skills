"""Rebuild synthetic Cline sessions.db + messages fixtures (stdlib only)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent
CWD = "/tmp/project"
NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat().replace("+00:00", "Z")
BASIC_ID = "cl000101-0101-4101-8101-010101010101"
CHILD_ID = "cl000102-0202-4202-8202-020202020202"

SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    pid INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    exit_code INTEGER,
    status TEXT NOT NULL,
    status_lock INTEGER NOT NULL DEFAULT 0,
    interactive INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    cwd TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    team_name TEXT,
    enable_tools INTEGER NOT NULL,
    enable_spawn INTEGER NOT NULL,
    enable_teams INTEGER NOT NULL,
    parent_session_id TEXT,
    parent_agent_id TEXT,
    agent_id TEXT,
    conversation_id TEXT,
    is_subagent INTEGER NOT NULL DEFAULT 0,
    prompt TEXT,
    metadata_json TEXT,
    transcript_path TEXT NOT NULL DEFAULT '',
    hook_path TEXT NOT NULL DEFAULT '',
    messages_path TEXT,
    updated_at TEXT NOT NULL
)
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute(SESSIONS_TABLE)
    return conn


def _messages_payload(session_id: str, messages: list[dict]) -> str:
    return json.dumps(
        {
            "version": 1,
            "updated_at": NOW_ISO,
            "agent": "lead",
            "sessionId": session_id,
            "messages": messages,
        },
        indent=2,
        sort_keys=True,
    )


def _write_session_files(
    sessions_dir: Path,
    *,
    session_id: str,
    messages: list[dict],
) -> Path:
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    messages_path = session_dir / f"{session_id}.messages.json"
    messages_path.write_text(
        _messages_payload(session_id, messages) + "\n", encoding="utf-8"
    )
    manifest = {
        "version": 1,
        "session_id": session_id,
        "source": "cli",
        "pid": 1,
        "started_at": NOW_ISO,
        "status": "completed",
        "interactive": True,
        "provider": "synthetic",
        "model": "synthetic-model",
        "cwd": CWD,
        "workspace_root": CWD,
        "enable_tools": True,
        "enable_spawn": False,
        "enable_teams": False,
        # Relative artifact name only — no absolute host paths in fixtures.
        "messages_path": f"{session_id}.messages.json",
    }
    (session_dir / f"{session_id}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return messages_path


def _insert_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    prompt: str,
    messages_path: str,
    parent_session_id: str | None = None,
    is_subagent: int = 0,
    updated_at: str = NOW_ISO,
) -> None:
    conn.execute(
        """
        INSERT INTO sessions (
            session_id, source, pid, started_at, ended_at, exit_code, status,
            interactive, provider, model, cwd, workspace_root,
            enable_tools, enable_spawn, enable_teams,
            parent_session_id, is_subagent, prompt, messages_path, updated_at
        ) VALUES (?, 'cli', 1, ?, ?, 0, 'completed', 1, 'synthetic', 'synthetic-model',
                  ?, ?, 1, 0, 0, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            NOW_ISO,
            NOW_ISO,
            CWD,
            CWD,
            parent_session_id,
            is_subagent,
            prompt,
            messages_path,
            updated_at,
        ),
    )


def _manifest(case_dir: Path, *, case: str, expected_operation: str = "show", expected_code: int = 0) -> None:
    payload = {
        "case": case,
        "expected_code": expected_code,
        "expected_operation": expected_operation,
        "expected_warnings": [],
        "format_id": "cline-session-json-v1",
        "provenance_ref": "docs/source-formats.md#cline-session-json-v1",
        "source": "cline",
        "synthetic": True,
    }
    (case_dir / "fixture.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_s_cl_01() -> None:
    case = "s-cl-01-user-basic"
    case_dir = FIXTURE_ROOT / case
    data = case_dir / "data"
    db_path = data / "db" / "sessions.db"
    sessions_dir = data / "sessions"
    conn = _connect(db_path)
    messages = [
        {
            "id": "m1",
            "role": "user",
            "content": [{"type": "text", "text": "synthetic cline user prompt"}],
        },
        {
            "id": "m2",
            "role": "assistant",
            "content": [{"type": "text", "text": "synthetic cline assistant reply"}],
        },
    ]
    _write_session_files(sessions_dir, session_id=BASIC_ID, messages=messages)
    # Leave messages_path empty so the reader resolves the closed layout path
    # under data/sessions/<id>/<id>.messages.json (no absolute host paths).
    _insert_session(
        conn,
        session_id=BASIC_ID,
        prompt="synthetic cline user prompt",
        messages_path="",
    )
    conn.commit()
    conn.close()
    _manifest(case_dir, case=case)


def build_s_cl_02_subagent() -> None:
    case = "s-cl-02-parent-subagent"
    case_dir = FIXTURE_ROOT / case
    data = case_dir / "data"
    db_path = data / "db" / "sessions.db"
    sessions_dir = data / "sessions"
    conn = _connect(db_path)
    parent_msgs = [
        {"id": "p1", "role": "user", "content": "parent user text"},
        {"id": "p2", "role": "assistant", "content": "parent assistant text"},
    ]
    child_msgs = [
        {"id": "c1", "role": "user", "content": "child should hide from default list"},
    ]
    _write_session_files(sessions_dir, session_id=BASIC_ID, messages=parent_msgs)
    _write_session_files(sessions_dir, session_id=CHILD_ID, messages=child_msgs)
    _insert_session(
        conn,
        session_id=BASIC_ID,
        prompt="parent user text",
        messages_path="",
    )
    _insert_session(
        conn,
        session_id=CHILD_ID,
        prompt="child should hide from default list",
        messages_path="",
        parent_session_id=BASIC_ID,
        is_subagent=1,
        updated_at="2024-01-02T12:00:00.000000Z",
    )
    conn.commit()
    conn.close()
    _manifest(case_dir, case=case)


def build_s_cl_03_unsupported() -> None:
    case = "s-cl-03-unsupported-messages"
    case_dir = FIXTURE_ROOT / case
    data = case_dir / "data"
    db_path = data / "db" / "sessions.db"
    sessions_dir = data / "sessions"
    conn = _connect(db_path)
    session_dir = sessions_dir / BASIC_ID
    session_dir.mkdir(parents=True, exist_ok=True)
    messages_path = session_dir / f"{BASIC_ID}.messages.json"
    messages_path.write_text(
        json.dumps({"version": 99, "messages": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    _insert_session(
        conn,
        session_id=BASIC_ID,
        prompt="",
        messages_path="",
    )
    conn.commit()
    conn.close()
    _manifest(case_dir, case=case, expected_operation="error", expected_code=5)


def main() -> None:
    build_s_cl_01()
    build_s_cl_02_subagent()
    build_s_cl_03_unsupported()
    print("cline fixtures rebuilt")


if __name__ == "__main__":
    main()
