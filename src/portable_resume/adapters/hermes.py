"""Read Hermes Agent ``state.db`` SQLite as inert context.

Pinned format: ``hermes-state-sqlite-v1`` (``schema_version`` = 23).
Default store: ``$HERMES_HOME/state.db`` or ``~/.hermes/state.db``.

Authority: SQLite sessions + messages. FTS virtual tables are never queried.
Never invokes Hermes CLI/gateway, Skill hub, taps, messaging platforms, or
migrations. Does not import ``hermes_state`` / SessionDB.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import private_sqlite_connection, query_only_live_sqlite
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "hermes-state-sqlite-v1"
SCHEMA_VERSION = 23
DB_NAME = "state.db"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_REQUIRED_TABLES = frozenset({"schema_version", "sessions", "messages"})
_SESSION_COLUMNS = frozenset(
    {
        "id",
        "source",
        "parent_session_id",
        "started_at",
        "ended_at",
        "title",
        "cwd",
        "archived",
        "system_prompt",
    }
)
_MESSAGE_COLUMNS = frozenset(
    {
        "id",
        "session_id",
        "role",
        "content",
        "tool_call_id",
        "tool_calls",
        "tool_name",
        "timestamp",
        "reasoning",
        "active",
    }
)
# Messaging/platform labels allowed as high-level source tags (never IDs).
_SAFE_SOURCES = frozenset(
    {
        "cli",
        "telegram",
        "discord",
        "slack",
        "whatsapp",
        "signal",
        "web",
        "api",
        "gateway",
        "unknown",
    }
)
_PUBLIC_ROLES = frozenset({"user", "assistant", "tool", "tool_result", "function"})


def _root_candidate(query: Query) -> str:
    if query.source_root:
        return query.source_root
    home = os.environ.get("HERMES_HOME")
    if home and home.strip():
        path = home.strip()
        if not os.path.isabs(path):
            raise DiagnosticError("E_UNSAFE_PATH", source="hermes", provider=FORMAT_ID)
        return path
    return os.path.expanduser("~/.hermes")


def _existing_root(query: Query) -> str | None:
    candidate = _root_candidate(query)
    try:
        # Exact state.db path
        if os.path.isfile(candidate) and os.path.basename(candidate) == DB_NAME:
            parent = os.path.dirname(os.path.abspath(candidate))
            return canonical_root(parent)
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


def _database_path(query: Query, root: str) -> str | None:
    if query.source_root:
        candidate = os.path.abspath(query.source_root)
        if os.path.isfile(candidate) and os.path.basename(candidate) == DB_NAME:
            return candidate if _regular_file(candidate, root) else None
    path = os.path.join(root, DB_NAME)
    return path if _regular_file(path, root) else None


def _stamp_sql(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        # Hermes uses Unix epoch floats; ms would be > 1e12.
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


def _cwd_from(value: object) -> str | None:
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
    return private_sqlite_connection(
        database, root=root, bounds=limits, provider=FORMAT_ID
    )


def _require_schema(connection: sqlite3.Connection) -> None:
    try:
        integrity = connection.execute("PRAGMA integrity_check(1)").fetchone()
        if integrity != ("ok",):
            raise DiagnosticError("E_CORRUPT_RECORD", source="hermes", provider=FORMAT_ID)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('schema_version','sessions','messages')"
            )
        }
        if not _REQUIRED_TABLES.issubset(tables):
            raise DiagnosticError(
                "E_UNSUPPORTED_FORMAT", source="hermes", provider=FORMAT_ID
            )
        session_cols = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(sessions)")
        }
        message_cols = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(messages)")
        }
        if not _SESSION_COLUMNS.issubset(session_cols) or not _MESSAGE_COLUMNS.issubset(
            message_cols
        ):
            raise DiagnosticError(
                "E_UNSUPPORTED_FORMAT", source="hermes", provider=FORMAT_ID
            )
        version_row = connection.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        if (
            version_row is None
            or version_row[0] is None
            or int(version_row[0]) != SCHEMA_VERSION
        ):
            raise DiagnosticError(
                "E_UNSUPPORTED_FORMAT", source="hermes", provider=FORMAT_ID
            )
    except sqlite3.DatabaseError as error:
        raise DiagnosticError(
            "E_UNSUPPORTED_FORMAT", source="hermes", provider=FORMAT_ID
        ) from error
    except (TypeError, ValueError) as error:
        raise DiagnosticError(
            "E_UNSUPPORTED_FORMAT", source="hermes", provider=FORMAT_ID
        ) from error


def _exact_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    # Optional profile:session composite — native id is the suffix.
    if ":" in text:
        _profile, session = text.split(":", 1)
        session = session.strip()
        if session and _SESSION_ID_RE.fullmatch(session):
            return session
        return None
    if _SESSION_ID_RE.fullmatch(text):
        return text
    return None


def _safe_title(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[: DEFAULT_BOUNDS.title_chars]
    return None


def _row_summary(
    *,
    database: str,
    session_id: str,
    title: object,
    cwd_value: object,
    started_at: object,
    ended_at: object,
    query: Query,
    require_age: bool,
) -> SessionSummary | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    cwd = _cwd_from(cwd_value)
    if query.cwd is not None:
        if cwd is None or not same_cwd(cwd, query.cwd):
            return None
    stamp = _stamp_sql(ended_at) or _stamp_sql(started_at)
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    return SessionSummary(
        source="hermes",
        session_id=session_id,
        source_path=database,
        title=_safe_title(title),
        cwd=cwd,
        branch=None,
        created_at=_stamp_sql(started_at),
        updated_at=stamp,
        provider=FORMAT_ID,
        warnings=(),
    )


def _content_text(content: object) -> str | None:
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


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
        SELECT role, content
        FROM messages
        WHERE session_id = ?
          AND COALESCE(active, 1) = 1
          AND role IN ('user', 'assistant', 'tool', 'tool_result', 'function')
        ORDER BY id ASC
        LIMIT ?
        """,
        (session_id, row_limit),
    )
    for role, content in rows:
        if not isinstance(role, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="hermes", provider=FORMAT_ID)
        if content is not None and not isinstance(content, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="hermes", provider=FORMAT_ID)
        if isinstance(content, str):
            encoded = content.encode("utf-8")
            if len(encoded) > budget.limits.record_bytes:
                raise DiagnosticError.limit_exceeded()
            budget.consume_bytes(len(encoded))
        budget.consume_records()
        text = _content_text(content)
        if text is not None:
            return True
    return False


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

    if exact_id is not None:
        rows = connection.execute(
            """
            SELECT id, title, cwd, started_at, ended_at, parent_session_id, archived
            FROM sessions
            WHERE id = ? OR lower(id) = lower(?)
            LIMIT 2
            """,
            (exact_id, exact_id),
        ).fetchall()
        require_age = False
        if not rows:
            return []
    else:
        if scan_limit <= 0:
            return []
        # Root sessions only: hide child/subagent and archived from default list.
        rows = connection.execute(
            """
            SELECT id, title, cwd, started_at, ended_at, parent_session_id, archived
            FROM sessions
            WHERE (parent_session_id IS NULL OR parent_session_id = '')
              AND COALESCE(archived, 0) = 0
            ORDER BY COALESCE(ended_at, started_at) DESC, started_at DESC, id ASC
            LIMIT ?
            """,
            (scan_limit,),
        ).fetchall()
        require_age = True

    values: list[SessionSummary] = []
    for row in rows:
        session_id, title, cwd_value, started_at, ended_at, parent, archived = row
        if exact_id is None:
            if isinstance(parent, str) and parent.strip():
                continue
            if archived in (1, True):
                continue
            try:
                if not _session_has_extractable_turn(
                    connection, str(session_id), budget
                ):
                    continue
            except DiagnosticError as error:
                if error.code in {
                    "E_LIMIT_EXCEEDED",
                    "E_SOURCE_BUSY",
                    "E_UNSAFE_PATH",
                    "E_CORRUPT_RECORD",
                }:
                    raise
                continue
        item = _row_summary(
            database=database,
            session_id=str(session_id),
            title=title,
            cwd_value=cwd_value,
            started_at=started_at,
            ended_at=ended_at,
            query=query,
            require_age=require_age,
        )
        if item is not None:
            values.append(item)
            budget.consume_records()
            if exact_id is None and len(values) >= list_limit:
                break
    return values


def _turn_from_message(
    role: object,
    content: object,
    tool_name: object,
) -> tuple[str, str] | None:
    if not isinstance(role, str) or role not in _PUBLIC_ROLES:
        return None
    text = _content_text(content)
    if text is None and role in {"tool", "tool_result", "function"}:
        if isinstance(tool_name, str) and tool_name.strip():
            text = tool_name.strip()
    if text is None:
        return None
    public_role = "tool" if role in {"tool", "tool_result", "function"} else role
    return public_role, text


class HermesAdapter:
    key = "hermes"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = _existing_root(query)
        return (root,) if root else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            root = _existing_root(query)
            if root is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            database = _database_path(query, root)
            if database is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable", root=root)
            with _open_connection(database, root) as connection:
                _require_schema(connection)
            return CapabilityReport(
                self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,)
            )
        except DiagnosticError as error:
            if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                return CapabilityReport(self.key, FORMAT_ID, "unsafe")
            if error.code == "E_UNSUPPORTED_FORMAT":
                return CapabilityReport(self.key, FORMAT_ID, "unsupported")
            if error.code == "E_CORRUPT_RECORD":
                return CapabilityReport(self.key, FORMAT_ID, "unsupported")
            return CapabilityReport(self.key, FORMAT_ID, "unsupported")

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        database = _database_path(query, root)
        if database is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
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
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        database = _database_path(query, root)
        if database is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        session_id = ref.session_id
        if not session_id or not _SESSION_ID_RE.fullmatch(session_id):
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        with _open_connection(database, root, budget) as connection:
            _require_schema(connection)
            rows = connection.execute(
                """
                SELECT id, title, cwd, started_at, ended_at
                FROM sessions WHERE id = ?
                LIMIT 2
                """,
                (session_id,),
            ).fetchall()
            if len(rows) != 1:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
            _sid, title, cwd_value, started_at, ended_at = rows[0]
            cwd = _cwd_from(cwd_value)
            if query.cwd is not None and (cwd is None or not same_cwd(cwd, query.cwd)):
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

            limit = min(budget.limits.transcript_records, DEFAULT_BOUNDS.transcript_records)
            messages = connection.execute(
                """
                SELECT role, content, tool_name, tool_calls, reasoning
                FROM messages
                WHERE session_id = ?
                  AND COALESCE(active, 1) = 1
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, limit + 1),
            ).fetchall()
            if len(messages) > limit:
                raise DiagnosticError.limit_exceeded()

            turns: list[Turn] = []
            warnings: list[str] = []
            turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
            for role, content, tool_name, tool_calls, reasoning in messages:
                budget.consume_transcript_records()
                # Never surface reasoning / system-adjacent fields.
                _ = reasoning
                _ = tool_calls
                if isinstance(content, str):
                    encoded = content.encode("utf-8")
                    if len(encoded) > budget.limits.record_bytes:
                        raise DiagnosticError.limit_exceeded()
                    budget.consume_bytes(len(encoded))
                parsed = _turn_from_message(role, content, tool_name)
                if parsed is None:
                    continue
                public_role, text = parsed
                turn, turn_warnings = sanitize_turn_record(
                    {"role": public_role, "content": text},
                    ordinal=len(turns),
                    bounds=turn_bounds,
                )
                warnings.extend(turn_warnings)
                if turn is not None:
                    budget.consume_turns()
                    turns.append(turn)

        if not turns:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        last_user = next((t.content for t in reversed(turns) if t.role == "user"), None)
        last_assistant = next(
            (t.content for t in reversed(turns) if t.role == "assistant"), None
        )
        return Session(
            source="hermes",
            session_id=session_id,
            source_path=database,
            title=_safe_title(title),
            cwd=cwd,
            branch=None,
            created_at=_stamp_sql(started_at),
            updated_at=_stamp_sql(ended_at) or _stamp_sql(started_at),
            last_user_request=last_user,
            last_assistant_action=last_assistant,
            turns=tuple(turns),
            warnings=tuple(dict.fromkeys(warnings)),
        )


ADAPTER = HermesAdapter()
