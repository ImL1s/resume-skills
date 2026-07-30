"""Read Crush project SQLite (crush.db) as inert context.

Pinned format: ``crush-sqlite-v1`` (goose_db_version max = 7, migrations through
20260127000000_add_read_files_table).

Default data directory is per-project ``.crush/`` containing ``crush.db``.
``--source-root`` may be a data directory, a project root with ``.crush/``, or
an exact approved ``crush.db`` path. Without ``source_root``, when ``cwd`` is
set the adapter tries ``<cwd>/.crush`` only (no recursive home scan).

Never invokes Crush CLI/TUI, ``crush serve``, migrations, MCP, or providers.
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

FORMAT_ID = "crush-sqlite-v1"
# Migrations: initial + summary_message_id + created_at_indexes + provider +
# is_summary_message + todos + read_files (pressly/goose version_id sequence).
SCHEMA_VERSION = 7
DB_BASENAME = "crush.db"
DATA_DIR_NAME = ".crush"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_REQUIRED_TABLES = frozenset({"goose_db_version", "sessions", "messages"})
_SESSION_COLUMNS = frozenset(
    {
        "id",
        "parent_session_id",
        "title",
        "message_count",
        "updated_at",
        "created_at",
    }
)
_MESSAGE_COLUMNS = frozenset(
    {"id", "session_id", "role", "parts", "created_at", "updated_at"}
)
_PUBLIC_ROLES = frozenset({"user", "assistant", "tool"})


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = item
    return value


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


def _regular_dir(path: str) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    return not stat.S_ISLNK(mode) and stat.S_ISDIR(mode)


def _resolve_database(query: Query) -> tuple[str, str] | None:
    """Return (database_path, containment_root) or None when unavailable."""

    if query.source_root:
        candidate = query.source_root
        try:
            if os.path.isfile(candidate) and os.path.basename(candidate) == DB_BASENAME:
                parent = os.path.dirname(os.path.abspath(candidate))
                root = canonical_root(parent)
                path = os.path.abspath(candidate)
                if _regular_file(path, root):
                    return path, root
                return None
            if not os.path.isdir(candidate):
                return None
            root = canonical_root(candidate)
        except DiagnosticError:
            if query.source_root:
                raise
            return None
        # Data directory form: <root>/crush.db
        direct = os.path.join(root, DB_BASENAME)
        if _regular_file(direct, root):
            return direct, root
        # Project form: <project>/.crush/crush.db
        nested_dir = os.path.join(root, DATA_DIR_NAME)
        nested = os.path.join(nested_dir, DB_BASENAME)
        if _regular_dir(nested_dir) and _regular_file(nested, root):
            return nested, root
        return None

    # No source_root: only try <cwd>/.crush (closed policy — no home scan).
    if query.cwd:
        try:
            cwd = canonicalize_cwd(query.cwd)
        except DiagnosticError:
            return None
        data_dir = os.path.join(cwd, DATA_DIR_NAME)
        database = os.path.join(data_dir, DB_BASENAME)
        if not _regular_dir(data_dir):
            return None
        try:
            root = canonical_root(data_dir)
        except DiagnosticError:
            return None
        if _regular_file(database, root):
            return database, root
    return None


def _open_connection(database: str, root: str, budget: ReadBudget | None = None):
    limits = budget.limits if budget is not None else DEFAULT_BOUNDS
    try:
        size = os.path.getsize(database)
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    if size > limits.sqlite_snapshot_bytes:
        return query_only_live_sqlite(database, root=root, provider=FORMAT_ID)
    return private_sqlite_connection(
        database, root=root, bounds=limits, provider=FORMAT_ID
    )


def _require_schema(connection: sqlite3.Connection) -> None:
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('goose_db_version','sessions','messages','files','read_files')"
            )
        }
        if not _REQUIRED_TABLES.issubset(tables):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="crush", provider=FORMAT_ID)
        session_cols = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(sessions)")
        }
        message_cols = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(messages)")
        }
        if not _SESSION_COLUMNS.issubset(session_cols) or not _MESSAGE_COLUMNS.issubset(
            message_cols
        ):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="crush", provider=FORMAT_ID)
        version_row = connection.execute(
            "SELECT MAX(version_id) FROM goose_db_version"
        ).fetchone()
        if version_row is None or version_row[0] is None or int(version_row[0]) != SCHEMA_VERSION:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="crush", provider=FORMAT_ID)
    except sqlite3.DatabaseError as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="crush", provider=FORMAT_ID) from error
    except (TypeError, ValueError) as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="crush", provider=FORMAT_ID) from error


def _exact_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    if _SESSION_ID_RE.fullmatch(text):
        return text
    return None


def _stamp_ms(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        # Crush stores milliseconds; also accept seconds.
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
    return None


def _parts_text(parts_json: str) -> str | None:
    try:
        payload = json.loads(parts_json, object_pairs_hook=_object)
    except (json.JSONDecodeError, _DuplicateKey, RecursionError, UnicodeDecodeError) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="crush", provider=FORMAT_ID) from error
    if not isinstance(payload, list):
        raise DiagnosticError("E_CORRUPT_RECORD", source="crush", provider=FORMAT_ID)
    chunks: list[str] = []
    for part in payload:
        if not isinstance(part, Mapping):
            continue
        kind = part.get("type")
        data = part.get("data")
        if not isinstance(data, Mapping):
            continue
        if kind == "text":
            text = data.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
        elif kind == "tool_result":
            text = data.get("content")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
        elif kind == "tool_call":
            name = data.get("name")
            input_text = data.get("input")
            if isinstance(name, str) and name.strip():
                if isinstance(input_text, str) and input_text.strip():
                    chunks.append(f"{name}: {input_text}")
                else:
                    chunks.append(name)
        elif kind == "shell_command":
            command = data.get("command")
            output = data.get("output")
            if isinstance(command, str) and command.strip():
                if isinstance(output, str) and output.strip():
                    chunks.append(f"$ {command}\n{output}")
                else:
                    chunks.append(f"$ {command}")
        # Skip reasoning, binary, image_url, finish.
    if not chunks:
        return None
    return "\n".join(chunks)


def _session_has_extractable_turn(
    connection: sqlite3.Connection,
    session_id: str,
    budget: ReadBudget,
) -> bool:
    row_limit = min(budget.limits.transcript_records, DEFAULT_BOUNDS.transcript_records)
    if row_limit <= 0:
        return False
    rows = connection.execute(
        """
        SELECT role, parts
        FROM messages
        WHERE session_id = ?
          AND role IN ('user', 'assistant', 'tool')
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (session_id, row_limit),
    )
    for role, parts in rows:
        if not isinstance(role, str) or not isinstance(parts, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="crush", provider=FORMAT_ID)
        encoded = parts.encode("utf-8")
        if len(encoded) > budget.limits.record_bytes:
            raise DiagnosticError.limit_exceeded()
        budget.consume_bytes(len(encoded))
        budget.consume_records()
        text = _parts_text(parts)
        if text is not None and text.strip():
            return True
    return False


def _row_summary(
    *,
    database: str,
    session_id: str,
    title: object,
    created_at: object,
    updated_at: object,
    query: Query,
    require_age: bool,
) -> SessionSummary | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    # Crush sessions do not store cwd; bind to query.cwd when provided for handoff metadata.
    cwd: str | None = None
    if query.cwd is not None:
        try:
            cwd = canonicalize_cwd(query.cwd)
        except DiagnosticError:
            return None
    stamp = _stamp_ms(updated_at) or _stamp_ms(created_at)
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    name = title if isinstance(title, str) and title.strip() else None
    return SessionSummary(
        source="crush",
        session_id=session_id,
        source_path=database,
        title=name,
        cwd=cwd,
        branch=None,
        created_at=_stamp_ms(created_at),
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
    budget: ReadBudget,
) -> list[SessionSummary]:
    scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
    list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
    if exact_id is None and list_limit <= 0:
        return []

    def _fetch_exact(session_key: str) -> list[tuple]:
        return connection.execute(
            """
            SELECT id, parent_session_id, title, message_count, created_at, updated_at
            FROM sessions
            WHERE id = ? OR lower(id) = lower(?)
            LIMIT 2
            """,
            (session_key, session_key),
        ).fetchall()

    def _fetch_normal() -> list[tuple]:
        if scan_limit <= 0:
            return []
        return connection.execute(
            """
            SELECT id, parent_session_id, title, message_count, created_at, updated_at
            FROM sessions
            WHERE (parent_session_id IS NULL OR parent_session_id = '')
              AND message_count > 0
              AND EXISTS (
                SELECT 1 FROM messages m
                WHERE m.session_id = sessions.id
                  AND m.role IN ('user', 'assistant', 'tool')
              )
            ORDER BY updated_at DESC, id ASC
            LIMIT ?
            """,
            (scan_limit,),
        ).fetchall()

    if exact_id is not None:
        rows = _fetch_exact(exact_id)
        require_age = False
        if not rows:
            rows = _fetch_normal()
            require_age = True
            exact_id = None
            if list_limit <= 0:
                return []
    else:
        rows = _fetch_normal()
        require_age = True

    values: list[SessionSummary] = []
    for row in rows:
        session_id, parent_session_id, title, _message_count, created_at, updated_at = row
        if exact_id is None:
            if isinstance(parent_session_id, str) and parent_session_id.strip():
                continue
            if not _session_has_extractable_turn(connection, session_id, budget):
                continue
        item = _row_summary(
            database=database,
            session_id=session_id,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            query=query,
            require_age=require_age,
        )
        if item is not None:
            if exact_id is None and len(values) >= list_limit:
                break
            values.append(item)
            budget.consume_records()
            if exact_id is None and len(values) >= list_limit:
                break
    return values


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
        SELECT id, parent_session_id, title, created_at, updated_at
        FROM sessions
        WHERE id = ?
        LIMIT 2
        """,
        (session_id,),
    ).fetchall()
    if len(rows) != 1:
        raise DiagnosticError("E_NO_MATCH", source="crush", provider=FORMAT_ID)
    _id, _parent, title, created_at, updated_at = rows[0]
    cwd: str | None = None
    if query.cwd is not None:
        try:
            cwd = canonicalize_cwd(query.cwd)
        except DiagnosticError as error:
            raise DiagnosticError("E_NO_MATCH", source="crush", provider=FORMAT_ID) from error

    limit = budget.limits.transcript_records + 1
    cursor = connection.execute(
        """
        SELECT id, role, parts, created_at
        FROM messages
        WHERE session_id = ?
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (session_id, limit),
    )
    turns: list[Turn] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
    count = 0
    for message_id, role, parts, _created in cursor:
        count += 1
        if count > budget.limits.transcript_records:
            raise DiagnosticError.limit_exceeded()
        if not isinstance(role, str) or not isinstance(parts, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="crush", provider=FORMAT_ID)
        if isinstance(message_id, str) and message_id:
            if message_id in seen_ids:
                raise DiagnosticError("E_CORRUPT_RECORD", source="crush", provider=FORMAT_ID)
            seen_ids.add(message_id)
        encoded = parts.encode("utf-8")
        if len(encoded) > budget.limits.record_bytes:
            raise DiagnosticError.limit_exceeded()
        budget.consume_transcript_records()
        budget.consume_bytes(len(encoded))
        if role not in _PUBLIC_ROLES:
            continue
        text = _parts_text(parts)
        if text is None:
            continue
        turn, turn_warnings = sanitize_turn_record(
            {"role": role, "content": text},
            ordinal=len(turns),
            bounds=turn_bounds,
        )
        warnings.extend(turn_warnings)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)

    last_user = next((t.content for t in reversed(turns) if t.role == "user"), None)
    last_assistant = next((t.content for t in reversed(turns) if t.role == "assistant"), None)
    name = title if isinstance(title, str) and title.strip() else None
    return Session(
        source="crush",
        session_id=session_id,
        source_path=database,
        title=name,
        cwd=cwd,
        branch=None,
        created_at=_stamp_ms(created_at),
        updated_at=_stamp_ms(updated_at) or _stamp_ms(created_at),
        last_user_request=last_user,
        last_assistant_action=last_assistant,
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(warnings)),
    )


class CrushAdapter:
    key = "crush"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        resolved = _resolve_database(query)
        return (resolved[1],) if resolved else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            resolved = _resolve_database(query)
            if resolved is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            database, root = resolved
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
        resolved = _resolve_database(query)
        if resolved is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        database, root = resolved
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
                budget=budget,
            )
        values.sort(key=lambda item: item.session_id)
        values.sort(key=lambda item: item.updated_at or "", reverse=True)
        values.sort(key=lambda item: item.updated_at is None)
        if exact is not None:
            return values
        list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
        return values[:list_limit]

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        resolved = _resolve_database(query)
        if resolved is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        database, root = resolved
        session_id = ref.session_id
        if not session_id:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
        with _open_connection(database, root, budget) as connection:
            _require_schema(connection)
            return _show_session(
                connection,
                database=database,
                session_id=session_id,
                query=query,
                budget=budget,
            )


ADAPTER = CrushAdapter()
