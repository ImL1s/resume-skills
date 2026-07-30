"""Read goose sessions.db SQLite as inert context.

Pinned format: ``goose-sessions-sqlite-v15`` (``schema_version`` max = 15).
Default store: ``<root>/sessions/sessions.db`` under the goose data directory
(``$XDG_DATA_HOME/goose`` or ``~/.local/share/goose``).

Never invokes goose CLI/Desktop, Chat Recall, MCP, ACP, or migrations.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import private_sqlite_connection, query_only_live_sqlite
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "goose-sessions-sqlite-v15"
SCHEMA_VERSION = 15
DB_REL = os.path.join("sessions", "sessions.db")
_DEFAULT_EXCLUDE_TYPES = frozenset(
    {"scheduled", "sub_agent", "hidden", "gateway", "acp", "terminal"}
)
_REQUIRED_TABLES = frozenset({"schema_version", "sessions", "messages", "usage_ledger"})
_SESSION_COLUMNS = frozenset(
    {
        "id",
        "name",
        "session_type",
        "working_dir",
        "created_at",
        "updated_at",
        "archived_at",
        "parent_session_id",
    }
)
_MESSAGE_COLUMNS = frozenset(
    {"id", "message_id", "session_id", "role", "content_json", "created_timestamp"}
)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = item
    return value


def _root_candidate(query: Query) -> str:
    if query.source_root:
        return query.source_root
    # Windows Goose Desktop/CLI uses %APPDATA%/Block/goose/data (upstream Paths).
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "Block", "goose", "data")
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return os.path.join(data_home, "goose")
    return os.path.expanduser("~/.local/share/goose")


def _existing_root(query: Query) -> str | None:
    candidate = _root_candidate(query)
    try:
        if not os.path.isdir(candidate):
            return None
        return canonical_root(candidate)
    except DiagnosticError:
        if query.source_root:
            raise
        return None


def _regular_file(path: str, root: str) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        return False
    try:
        return is_within(path, root)
    except DiagnosticError:
        return False


def _database_path(root: str) -> str | None:
    path = os.path.join(root, DB_REL)
    return path if _regular_file(path, root) else None


def _stamp_sql(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return (
                datetime.fromtimestamp(number, timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        text = value.strip().replace(" ", "T", 1)
        if not text.endswith("Z") and "+" not in text[10:]:
            text = text + "Z" if "T" in text else text.replace(" ", "T") + "Z"
        try:
            return (
                datetime.fromisoformat(text.replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
        except ValueError:
            return None
    return None


def _cwd_from_working_dir(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return canonicalize_cwd(value)
    except DiagnosticError:
        return None


def _open_connection(database: str, root: str, budget: ReadBudget | None = None):
    limits = budget.limits if budget is not None else DEFAULT_BOUNDS
    try:
        size = os.path.getsize(database)
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    if size > limits.sqlite_snapshot_bytes:
        return query_only_live_sqlite(database, root=root, provider=FORMAT_ID)
    return private_sqlite_connection(database, root=root, provider=FORMAT_ID)


def _require_schema(connection: sqlite3.Connection) -> None:
    try:
        integrity = connection.execute("PRAGMA integrity_check(1)").fetchone()
        if integrity != ("ok",):
            raise DiagnosticError("E_CORRUPT_RECORD", source="goose", provider=FORMAT_ID)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('schema_version','sessions','messages','usage_ledger')"
            )
        }
        if tables != _REQUIRED_TABLES:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="goose", provider=FORMAT_ID)
        session_cols = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(sessions)")
        }
        message_cols = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(messages)")
        }
        if not _SESSION_COLUMNS.issubset(session_cols) or not _MESSAGE_COLUMNS.issubset(message_cols):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="goose", provider=FORMAT_ID)
        version_row = connection.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        if version_row is None or version_row[0] is None or int(version_row[0]) != SCHEMA_VERSION:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="goose", provider=FORMAT_ID)
    except sqlite3.DatabaseError as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="goose", provider=FORMAT_ID) from error
    except (TypeError, ValueError) as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="goose", provider=FORMAT_ID) from error


def _exact_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    if _SESSION_ID_RE.fullmatch(text):
        return text
    return None


def _row_summary(
    *,
    database: str,
    session_id: str,
    name: object,
    working_dir: object,
    created_at: object,
    updated_at: object,
    query: Query,
    require_age: bool,
) -> SessionSummary | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    cwd = _cwd_from_working_dir(working_dir)
    if query.cwd is not None:
        if cwd is None or not same_cwd(cwd, query.cwd):
            return None
    stamp = _stamp_sql(updated_at) or _stamp_sql(created_at)
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    title = name if isinstance(name, str) and name.strip() else None
    return SessionSummary(
        source="goose",
        session_id=session_id,
        source_path=database,
        title=title,
        cwd=cwd,
        branch=None,
        created_at=_stamp_sql(created_at),
        updated_at=stamp,
        provider=FORMAT_ID,
        warnings=(),
    )


def _list_sessions(
    connection: sqlite3.Connection,
    *,
    database: str,
    query: Query,
    exact_id: str | None,
) -> list[SessionSummary]:
    def _fetch_exact(session_key: str) -> list[tuple]:
        return connection.execute(
            """
            SELECT id, name, session_type, working_dir, created_at, updated_at, archived_at
            FROM sessions
            WHERE id = ? OR lower(id) = lower(?)
            LIMIT 2
            """,
            (session_key, session_key),
        ).fetchall()

    def _fetch_normal() -> list[tuple]:
        limit = DEFAULT_BOUNDS.scanned_records + 1
        rows = connection.execute(
            """
            SELECT id, name, session_type, working_dir, created_at, updated_at, archived_at
            FROM sessions
            WHERE session_type = 'user'
              AND archived_at IS NULL
              AND EXISTS (
                SELECT 1 FROM messages m
                WHERE m.session_id = sessions.id
                  AND m.role IN ('user', 'assistant', 'tool')
                  AND (
                    m.content_json LIKE '%"text"%'
                    OR m.content_json LIKE '%"content"%'
                  )
              )
            ORDER BY updated_at DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if len(rows) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        return rows

    if exact_id is not None:
        rows = _fetch_exact(exact_id)
        require_age = False
        # Exact miss falls back so free-text / title selection still works (Codex P2).
        if not rows:
            rows = _fetch_normal()
            require_age = True
            exact_id = None
    else:
        rows = _fetch_normal()
        require_age = True

    values: list[SessionSummary] = []
    for row in rows:
        session_id, name, session_type, working_dir, created_at, updated_at, archived_at = row
        if exact_id is None:
            if archived_at is not None:
                continue
            if isinstance(session_type, str) and session_type in _DEFAULT_EXCLUDE_TYPES:
                continue
        item = _row_summary(
            database=database,
            session_id=session_id,
            name=name,
            working_dir=working_dir,
            created_at=created_at,
            updated_at=updated_at,
            query=query,
            require_age=require_age,
        )
        if item is not None:
            values.append(item)
            if exact_id is None and len(values) >= DEFAULT_BOUNDS.listed_sessions:
                break
    return values


def _content_text(content_json: str) -> str | None:
    try:
        payload = json.loads(content_json, object_pairs_hook=_object)
    except (json.JSONDecodeError, _DuplicateKey, RecursionError, UnicodeDecodeError) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="goose", provider=FORMAT_ID) from error
    if isinstance(payload, str) and payload.strip():
        return payload
    if not isinstance(payload, list):
        raise DiagnosticError("E_CORRUPT_RECORD", source="goose", provider=FORMAT_ID)
    chunks: list[str] = []
    for part in payload:
        if isinstance(part, str) and part.strip():
            chunks.append(part)
            continue
        if not isinstance(part, Mapping):
            continue
        kind = part.get("type")
        if kind in {None, "text"}:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
        elif kind in {"toolRequest", "toolResponse", "tool_use", "tool_result"}:
            # Keep only short text fields if present; skip raw binary/tool blobs.
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    if not chunks:
        return None
    return "\n".join(chunks)


def _show_session(
    connection: sqlite3.Connection,
    *,
    database: str,
    session_id: str,
    query: Query,
    budget: ReadBudget,
) -> Session:
    rows = connection.execute(
        """
        SELECT id, name, working_dir, created_at, updated_at
        FROM sessions
        WHERE id = ?
        LIMIT 2
        """,
        (session_id,),
    ).fetchall()
    if len(rows) != 1:
        raise DiagnosticError("E_NO_MATCH", source="goose", provider=FORMAT_ID)
    _id, name, working_dir, created_at, updated_at = rows[0]
    cwd = _cwd_from_working_dir(working_dir)
    if query.cwd is not None and (cwd is None or not same_cwd(cwd, query.cwd)):
        raise DiagnosticError("E_NO_MATCH", source="goose", provider=FORMAT_ID)

    limit = budget.limits.transcript_records + 1
    cursor = connection.execute(
        """
        SELECT message_id, role, content_json, created_timestamp
        FROM messages
        WHERE session_id = ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (session_id, limit),
    )
    turns: list[Turn] = []
    warnings: list[str] = []
    total_bytes = 0
    seen_message_ids: set[str] = set()
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
    count = 0
    for message_id, role, content_json, _created in cursor:
        count += 1
        if count > budget.limits.transcript_records:
            raise DiagnosticError.limit_exceeded()
        if not isinstance(role, str) or not isinstance(content_json, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="goose", provider=FORMAT_ID)
        if isinstance(message_id, str) and message_id:
            if message_id in seen_message_ids:
                raise DiagnosticError("E_CORRUPT_RECORD", source="goose", provider=FORMAT_ID)
            seen_message_ids.add(message_id)
        encoded = content_json.encode("utf-8")
        if len(encoded) > budget.limits.record_bytes:
            raise DiagnosticError.limit_exceeded()
        total_bytes += len(encoded)
        if total_bytes > budget.limits.source_read_bytes:
            raise DiagnosticError.limit_exceeded()
        mapped_role = role
        if role in {"toolResult", "tool_result", "function"}:
            mapped_role = "tool"
        if mapped_role not in {"user", "assistant", "tool"}:
            continue
        text = _content_text(content_json)
        if text is None:
            continue
        turn, turn_warnings = sanitize_turn_record(
            {"role": mapped_role, "content": text},
            ordinal=len(turns),
            bounds=turn_bounds,
        )
        warnings.extend(turn_warnings)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)

    last_user = next((t.content for t in reversed(turns) if t.role == "user"), None)
    last_assistant = next((t.content for t in reversed(turns) if t.role == "assistant"), None)
    title = name if isinstance(name, str) and name.strip() else None
    return Session(
        source="goose",
        session_id=session_id,
        source_path=database,
        title=title,
        cwd=cwd,
        branch=None,
        created_at=_stamp_sql(created_at),
        updated_at=_stamp_sql(updated_at) or _stamp_sql(created_at),
        last_user_request=last_user,
        last_assistant_action=last_assistant,
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(warnings)),
    )


class GooseAdapter:
    key = "goose"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = _existing_root(query)
        return (root,) if root else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            root = _existing_root(query)
            if root is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            database = _database_path(root)
            if database is None:
                sessions = os.path.join(root, "sessions")
                if os.path.isdir(sessions) and not os.path.islink(sessions):
                    return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
                return CapabilityReport(self.key, FORMAT_ID, "unavailable", root=root)
            try:
                with _open_connection(database, root) as connection:
                    _require_schema(connection)
            except DiagnosticError as error:
                if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                    return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                if error.code in {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD"}:
                    return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
                raise
            return CapabilityReport(
                self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,)
            )
        except DiagnosticError as error:
            state = "unsafe" if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"} else "unsupported"
            return CapabilityReport(self.key, FORMAT_ID, state)

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        database = _database_path(root)
        if database is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        exact = _exact_ref(query.ref)
        list_query = query
        if exact is not None and query.within_min is None:
            list_query = Query(
                source=query.source,
                ref=query.ref,
                cwd=query.cwd,
                within_min=0,
                source_root=query.source_root,
                max_tool_chars=query.max_tool_chars,
            )
        with _open_connection(database, root, budget) as connection:
            _require_schema(connection)
            values = _list_sessions(
                connection,
                database=database,
                query=list_query,
                exact_id=exact,
            )
        values.sort(key=lambda item: item.session_id)
        values.sort(key=lambda item: item.updated_at or "", reverse=True)
        values.sort(key=lambda item: item.updated_at is None)
        if exact is not None:
            return values
        return values[: DEFAULT_BOUNDS.listed_sessions]

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        database = ref.source_path or _database_path(root)
        if database is None or not _regular_file(database, root):
            raise DiagnosticError.unsafe_path()
        session_id = ref.session_id
        with _open_connection(database, root, budget) as connection:
            _require_schema(connection)
            return _show_session(
                connection,
                database=database,
                session_id=session_id,
                query=query,
                budget=budget,
            )


ADAPTER = GooseAdapter()
