"""Read OpenClaw per-agent SQLite sessions as inert context.

Pinned format: ``openclaw-agent-sqlite-v1`` (``PRAGMA user_version = 11`` plus
matching ``schema_meta``). Discovery walks only

    <root>/agents/<agentId>/agent/openclaw-agent.sqlite

and never invokes the OpenClaw Gateway, CLI, doctor, or migration tools.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import private_sqlite_connection, query_only_live_sqlite
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "openclaw-agent-sqlite-v1"
SCHEMA_VERSION = 11
DB_BASENAME = "openclaw-agent.sqlite"
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFAULT_EXCLUDE_VIA = frozenset({"internal", "cron", "spawn", "run", "plugin"})
_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "schema_meta": frozenset(
        {"meta_key", "role", "schema_version", "agent_id", "app_version", "created_at", "updated_at"}
    ),
    "session_nodes": frozenset(
        {
            "session_key",
            "current_session_id",
            "entry_json",
            "updated_at",
            "created_via",
            "display_name",
            "archived_at",
            "last_interaction_at",
            "created_at",
        }
    ),
    "session_windows": frozenset({"session_id", "session_key", "reason", "created_at", "updated_at"}),
    "transcript_events": frozenset({"session_id", "seq", "event_json", "created_at"}),
}


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
    return os.path.expanduser("~/.openclaw")


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


def _regular_dir(path: str, root: str) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        return False
    try:
        return is_within(path, root)
    except DiagnosticError:
        return False


def _regular_db_file(path: str, root: str) -> bool:
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


def _composite_id(agent_id: str, session_id: str) -> str:
    return f"{agent_id}:{session_id}"


def _parse_ref(value: str | None) -> tuple[str | None, str | None]:
    """Return (agent_id_or_None, session_id_or_None) from a ref string.

    Free-text titles (spaces / non-id tokens) return ``(None, None)`` so the
    generic selector can match them after a normal bounded list.
    """

    if not value:
        return None, None
    text = value.strip()
    if not text or text == "latest":
        return None, None
    if ":" in text:
        agent, session = text.split(":", 1)
        agent = agent.strip()
        session = session.strip()
        if (
            agent
            and session
            and _AGENT_ID_RE.fullmatch(agent)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}", session)
        ):
            return agent, session
        return None, None
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}", text):
        return None, text
    return None, None


def _ms_stamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if number > 10_000_000_000:  # epoch milliseconds
        number /= 1000.0
    try:
        return (
            datetime.fromtimestamp(number, timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return None


def _cwd_from_entry(entry_json: str | None) -> str | None:
    if not entry_json:
        return None
    try:
        payload = json.loads(entry_json, object_pairs_hook=_object)
    except (json.JSONDecodeError, _DuplicateKey, RecursionError, UnicodeDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("cwd")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return canonicalize_cwd(raw)
    except DiagnosticError:
        return None


def _agent_db_paths(root: str) -> list[tuple[str, str]]:
    """Return ``(agent_id, db_path)`` under ``agents/*/agent/openclaw-agent.sqlite``."""

    agents = os.path.join(root, "agents")
    if not _regular_dir(agents, root):
        return []
    values: list[tuple[str, str]] = []
    try:
        with os.scandir(agents) as entries:
            names = []
            for entry in entries:
                if len(names) >= DEFAULT_BOUNDS.scanned_records:
                    raise DiagnosticError.limit_exceeded()
                names.append(entry.name)
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    names.sort()
    for name in names:
        if not _AGENT_ID_RE.fullmatch(name):
            continue
        agent_dir = os.path.join(agents, name)
        if not _regular_dir(agent_dir, root):
            continue
        agent_sub = os.path.join(agent_dir, "agent")
        if not _regular_dir(agent_sub, root):
            continue
        database = os.path.join(agent_sub, DB_BASENAME)
        if _regular_db_file(database, root):
            values.append((name, database))
            if len(values) > DEFAULT_BOUNDS.scanned_records:
                raise DiagnosticError.limit_exceeded()
    return values


def _open_connection(database: str, root: str, budget: ReadBudget | None = None):
    limits = budget.limits if budget is not None else DEFAULT_BOUNDS
    try:
        size = os.path.getsize(database)
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    if size > limits.sqlite_snapshot_bytes:
        return query_only_live_sqlite(database, root=root, provider=FORMAT_ID)
    return private_sqlite_connection(database, root=root, provider=FORMAT_ID)


def _require_schema(connection: sqlite3.Connection, *, expected_agent: str | None = None) -> str:
    """Validate closed schema and return the agent_id from schema_meta."""

    try:
        integrity = connection.execute("PRAGMA integrity_check(1)").fetchone()
        if integrity != ("ok",):
            raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
        user_version = connection.execute("PRAGMA user_version").fetchone()
        if user_version is None or int(user_version[0]) != SCHEMA_VERSION:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="openclaw", provider=FORMAT_ID)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('schema_meta','session_nodes','session_windows','transcript_events')"
            )
        }
        if tables != set(_REQUIRED_COLUMNS):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="openclaw", provider=FORMAT_ID)
        for table, required in _REQUIRED_COLUMNS.items():
            columns = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            if not required.issubset(columns):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="openclaw", provider=FORMAT_ID)
        meta = connection.execute(
            """
            SELECT role, schema_version, agent_id
            FROM schema_meta
            WHERE meta_key = 'primary'
            LIMIT 2
            """
        ).fetchall()
        if len(meta) != 1:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="openclaw", provider=FORMAT_ID)
        role, schema_version, agent_id = meta[0]
        if role != "agent" or int(schema_version) != SCHEMA_VERSION:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="openclaw", provider=FORMAT_ID)
        if not isinstance(agent_id, str) or not _AGENT_ID_RE.fullmatch(agent_id):
            raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
        if expected_agent is not None and agent_id != expected_agent:
            raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
        return agent_id
    except sqlite3.DatabaseError as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="openclaw", provider=FORMAT_ID) from error
    except (TypeError, ValueError) as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="openclaw", provider=FORMAT_ID) from error


def _row_to_summary(
    *,
    agent_id: str,
    database: str,
    session_id: str,
    entry_json: object,
    updated_at: object,
    created_at: object,
    display_name: object,
    last_interaction_at: object,
    query: Query,
    require_age: bool,
) -> SessionSummary | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    cwd = _cwd_from_entry(entry_json if isinstance(entry_json, str) else None)
    if query.cwd is not None:
        if cwd is None or not same_cwd(cwd, query.cwd):
            return None
    stamp = _ms_stamp(last_interaction_at if last_interaction_at is not None else updated_at)
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    title = display_name if isinstance(display_name, str) and display_name.strip() else None
    return SessionSummary(
        source="openclaw",
        session_id=_composite_id(agent_id, session_id),
        source_path=database,
        title=title,
        cwd=cwd,
        branch=None,
        created_at=_ms_stamp(created_at),
        updated_at=stamp,
        provider=FORMAT_ID,
        warnings=(),
    )


def _exact_session_summaries(
    connection: sqlite3.Connection,
    *,
    agent_id: str,
    database: str,
    session_filter: str,
    query: Query,
) -> list[SessionSummary]:
    """Resolve exact composite/native ids before the normal listing cap."""

    values: list[SessionSummary] = []
    nodes = connection.execute(
        """
        SELECT
          current_session_id, entry_json, updated_at, created_at, display_name,
          last_interaction_at, archived_at, created_via
        FROM session_nodes
        WHERE current_session_id = ?
        LIMIT 4
        """,
        (session_filter,),
    ).fetchall()
    for row in nodes:
        item = _row_to_summary(
            agent_id=agent_id,
            database=database,
            session_id=row[0],
            entry_json=row[1],
            updated_at=row[2],
            created_at=row[3],
            display_name=row[4],
            last_interaction_at=row[5],
            query=query,
            require_age=False,
        )
        if item is not None:
            values.append(item)
    if values:
        return values
    # Historical/reset window not pointed by current_session_id.
    windows = connection.execute(
        """
        SELECT
          w.session_id,
          n.entry_json,
          w.updated_at,
          w.created_at,
          COALESCE(w.display_name, n.display_name),
          n.last_interaction_at
        FROM session_windows w
        LEFT JOIN session_nodes n ON n.session_key = w.session_key
        WHERE w.session_id = ?
        LIMIT 4
        """,
        (session_filter,),
    ).fetchall()
    for row in windows:
        item = _row_to_summary(
            agent_id=agent_id,
            database=database,
            session_id=row[0],
            entry_json=row[1],
            updated_at=row[2],
            created_at=row[3],
            display_name=row[4],
            last_interaction_at=row[5],
            query=query,
            require_age=False,
        )
        if item is not None:
            values.append(item)
    return values


def _list_nodes(
    connection: sqlite3.Connection,
    *,
    agent_id: str,
    database: str,
    query: Query,
    include_internal: bool,
) -> list[SessionSummary]:
    rows = connection.execute(
        """
        SELECT
          session_key,
          current_session_id,
          entry_json,
          updated_at,
          created_at,
          created_via,
          display_name,
          archived_at,
          last_interaction_at
        FROM session_nodes
        ORDER BY COALESCE(last_interaction_at, updated_at, created_at) DESC, current_session_id ASC
        """
    ).fetchall()
    if len(rows) > DEFAULT_BOUNDS.scanned_records:
        raise DiagnosticError.limit_exceeded()
    values: list[SessionSummary] = []
    for row in rows:
        (
            _session_key,
            session_id,
            entry_json,
            updated_at,
            created_at,
            created_via,
            display_name,
            archived_at,
            last_interaction_at,
        ) = row
        if archived_at is not None and not include_internal:
            continue
        if (
            not include_internal
            and isinstance(created_via, str)
            and created_via in _DEFAULT_EXCLUDE_VIA
        ):
            continue
        item = _row_to_summary(
            agent_id=agent_id,
            database=database,
            session_id=session_id,
            entry_json=entry_json,
            updated_at=updated_at,
            created_at=created_at,
            display_name=display_name,
            last_interaction_at=last_interaction_at,
            query=query,
            require_age=not include_internal,
        )
        if item is None:
            continue
        values.append(item)
        if len(values) >= DEFAULT_BOUNDS.listed_sessions:
            break
    return values


def _decode_event(raw: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_object)
    except (json.JSONDecodeError, _DuplicateKey, RecursionError, UnicodeDecodeError) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID) from error
    if not isinstance(value, Mapping) or not isinstance(value.get("type"), str):
        raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
    return value


def _nested_message(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    raw = event.get("message")
    return raw if isinstance(raw, Mapping) else None


def _event_role(event: Mapping[str, Any]) -> str | None:
    role = event.get("role")
    if isinstance(role, str):
        return role
    nested = _nested_message(event)
    if nested is not None:
        nested_role = nested.get("role")
        if isinstance(nested_role, str):
            return nested_role
    return None


def _message_text(event: Mapping[str, Any]) -> str | None:
    for key in ("text", "content", "summary"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    nested = _nested_message(event)
    if nested is not None:
        for key in ("text", "content"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value
        # Nested content may be a list of parts with textual chunks.
        parts = nested.get("content")
        if isinstance(parts, list):
            chunks: list[str] = []
            for part in parts:
                if isinstance(part, str) and part.strip():
                    chunks.append(part)
                elif isinstance(part, Mapping):
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text)
            if chunks:
                return "\n".join(chunks)
    # Flat fixtures may store the message body under the bare "message" string key.
    bare = event.get("message")
    if isinstance(bare, str) and bare.strip():
        return bare
    return None


def _active_branch_events(decoded: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return active-branch conversation events (message/compaction).

    When events carry ``id``/``parentId``, walk from the latest leaf. Linear
    fixtures without ids keep sequence order. ``branch_summary`` stays in the
    ancestry index so children do not lose their parent pointer, but is not
    emitted as a turn. Compaction nodes may retarget ancestry via
    ``firstKeptEntryId`` / ``firstKeptSeq``.
    """

    graph_types = frozenset({"message", "custom_message", "compaction", "branch_summary"})
    emit_types = frozenset({"message", "custom_message", "compaction"})
    candidates = [event for event in decoded if event.get("type") in graph_types]
    if not candidates:
        return []
    if not any(isinstance(event.get("id"), str) and event.get("id") for event in candidates):
        return [event for event in candidates if event.get("type") in emit_types]

    by_id: dict[str, Mapping[str, Any]] = {}
    by_seq: dict[int, Mapping[str, Any]] = {}
    for index, event in enumerate(candidates):
        identifier = event.get("id")
        if isinstance(identifier, str) and identifier:
            if identifier in by_id:
                raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
            by_id[identifier] = event
        # Sequence position for firstKeptSeq is the event's own seq if present.
        seq = event.get("seq")
        if isinstance(seq, int):
            by_seq[seq] = event
        else:
            by_seq[index + 1] = event

    # Leaf is the latest graph node (including branch_summary). Emitting types are
    # preferred only when no later graph node exists; a trailing branch_summary
    # must win so we do not select an abandoned sibling (Codex P1).
    leaf: Mapping[str, Any] | None = None
    for event in reversed(candidates):
        identifier = event.get("id")
        if isinstance(identifier, str) and identifier in by_id:
            leaf = event
            break
    if leaf is None:
        return [event for event in candidates if event.get("type") in emit_types]

    path: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    current: Mapping[str, Any] | None = leaf
    while current is not None:
        identifier = current.get("id")
        if not isinstance(identifier, str) or not identifier:
            break
        if identifier in seen:
            raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
        seen.add(identifier)
        path.append(current)
        if current.get("type") == "compaction":
            kept_id = current.get("firstKeptEntryId")
            kept_seq = current.get("firstKeptSeq")
            if isinstance(kept_id, str) and kept_id in by_id:
                current = by_id[kept_id]
                continue
            if isinstance(kept_seq, int) and kept_seq in by_seq:
                current = by_seq[kept_seq]
                continue
        parent = current.get("parentId")
        if parent is None or parent == "":
            break
        if not isinstance(parent, str) or parent not in by_id:
            break
        current = by_id[parent]
    path.reverse()
    return [event for event in path if event.get("type") in emit_types]


def _show_session(
    connection: sqlite3.Connection,
    *,
    agent_id: str,
    session_id: str,
    database: str,
    query: Query,
    budget: ReadBudget,
) -> Session:
    node = connection.execute(
        """
        SELECT session_key, current_session_id, entry_json, updated_at, created_at,
               display_name, last_interaction_at
        FROM session_nodes
        WHERE current_session_id = ?
        LIMIT 2
        """,
        (session_id,),
    ).fetchall()
    if len(node) != 1:
        # Historical window reached by exact id (not current): allow window-only show.
        window = connection.execute(
            """
            SELECT session_id, session_key, display_name, created_at, updated_at
            FROM session_windows
            WHERE session_id = ?
            LIMIT 2
            """,
            (session_id,),
        ).fetchall()
        if len(window) != 1:
            raise DiagnosticError("E_NO_MATCH", source="openclaw", provider=FORMAT_ID)
        session_id_w, session_key, display_name, created_at, updated_at = window[0]
        entry_json = None
        parent = connection.execute(
            "SELECT entry_json, last_interaction_at FROM session_nodes WHERE session_key = ? LIMIT 1",
            (session_key,),
        ).fetchone()
        last_interaction_at = parent[1] if parent else None
        entry_json = parent[0] if parent else None
        title = display_name if isinstance(display_name, str) else None
        stamp = _ms_stamp(last_interaction_at if last_interaction_at is not None else updated_at)
        created = _ms_stamp(created_at)
    else:
        (
            _session_key,
            session_id_w,
            entry_json,
            updated_at,
            created_at,
            display_name,
            last_interaction_at,
        ) = node[0]
        title = display_name if isinstance(display_name, str) else None
        stamp = _ms_stamp(last_interaction_at if last_interaction_at is not None else updated_at)
        created = _ms_stamp(created_at)

    cwd = _cwd_from_entry(entry_json if isinstance(entry_json, str) else None)
    if query.cwd is not None and (cwd is None or not same_cwd(cwd, query.cwd)):
        raise DiagnosticError("E_NO_MATCH", source="openclaw", provider=FORMAT_ID)

    limit = budget.limits.transcript_records + 1
    cursor = connection.execute(
        """
        SELECT seq, event_json, created_at
        FROM transcript_events
        WHERE session_id = ?
        ORDER BY seq ASC
        LIMIT ?
        """,
        (session_id, limit),
    )
    turns: list[Turn] = []
    warnings: list[str] = []
    seen_seq: set[int] = set()
    total_bytes = 0
    decoded: list[Mapping[str, Any]] = []
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
    row_count = 0
    for seq, event_json, _created in cursor:
        row_count += 1
        if row_count > budget.limits.transcript_records:
            raise DiagnosticError.limit_exceeded()
        if not isinstance(seq, int):
            raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
        if seq in seen_seq:
            raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
        seen_seq.add(seq)
        if not isinstance(event_json, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="openclaw", provider=FORMAT_ID)
        encoded = event_json.encode("utf-8")
        if len(encoded) > budget.limits.record_bytes:
            raise DiagnosticError.limit_exceeded()
        total_bytes += len(encoded)
        if total_bytes > budget.limits.source_read_bytes:
            raise DiagnosticError.limit_exceeded()
        event = _decode_event(event_json)
        if event["type"] in {"custom", "session"}:
            continue
        # Attach SQL sequence for firstKeptSeq retention (Codex P1).
        annotated = dict(event)
        annotated["seq"] = seq
        # Keep branch_summary for ancestry only; turn emission filters it out.
        decoded.append(annotated)

    for event in _active_branch_events(decoded):
        kind = event["type"]
        if kind == "compaction":
            text = _message_text(event)
            if text is None:
                continue
            raw = {"role": "assistant", "content": text}
        elif kind in {"message", "custom_message"}:
            role = _event_role(event)
            if role in {"toolResult", "bashExecution", "tool_result", "function"}:
                role = "tool"
            if role not in {"user", "assistant", "tool"}:
                continue
            text = _message_text(event)
            if text is None and role == "tool":
                nested = _nested_message(event)
                source = nested if nested is not None else event
                command = source.get("command")
                output = source.get("output")
                chunks = []
                if isinstance(command, str) and command.strip():
                    chunks.append(command)
                if isinstance(output, str) and output.strip():
                    chunks.append(output)
                text = "\n".join(chunks) if chunks else None
            if text is None and kind == "custom_message":
                # Visible custom_message may omit role; treat as inert assistant context.
                if event.get("display") is False:
                    continue
                text = _message_text(event)
                if text is None:
                    continue
                role = "assistant"
            if text is None:
                continue
            raw = {"role": role, "content": text}
        else:
            continue
        turn, turn_warnings = sanitize_turn_record(
            raw,
            ordinal=len(turns),
            bounds=turn_bounds,
        )
        warnings.extend(turn_warnings)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)

    last_user = next((turn.content for turn in reversed(turns) if turn.role == "user"), None)
    last_assistant = next(
        (turn.content for turn in reversed(turns) if turn.role == "assistant"),
        None,
    )
    return Session(
        source="openclaw",
        session_id=_composite_id(agent_id, session_id),
        source_path=database,
        title=title,
        cwd=cwd,
        branch=None,
        created_at=created,
        updated_at=stamp,
        last_user_request=last_user,
        last_assistant_action=last_assistant,
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(warnings)),
    )


class OpenClawAdapter:
    key = "openclaw"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = _existing_root(query)
        return (root,) if root else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            root = _existing_root(query)
            if root is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            paths = _agent_db_paths(root)
            if not paths:
                agents = os.path.join(root, "agents")
                if _regular_dir(agents, root):
                    return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
                return CapabilityReport(self.key, FORMAT_ID, "unavailable", root=root)
            supported = False
            unsupported = False
            for agent_id, database in paths:
                try:
                    with _open_connection(database, root) as connection:
                        _require_schema(connection, expected_agent=agent_id)
                    supported = True
                except DiagnosticError as error:
                    if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                        return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                    if error.code == "E_UNSUPPORTED_FORMAT":
                        unsupported = True
                        continue
                    if error.code == "E_CORRUPT_RECORD":
                        unsupported = True
                        continue
                    raise
            if supported:
                state = "partial" if unsupported else "supported"
                return CapabilityReport(
                    self.key, FORMAT_ID, state, root=root, evidence=(FORMAT_ID,)
                )
            return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
        except DiagnosticError as error:
            state = "unsafe" if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"} else "unsupported"
            return CapabilityReport(self.key, FORMAT_ID, state)

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        agent_filter, session_filter = _parse_ref(query.ref)
        exact = bool(session_filter)
        include_internal = exact
        # Exact refs stay selectable outside default age window.
        list_query = query
        if exact and query.within_min is None:
            list_query = Query(
                source=query.source,
                ref=query.ref,
                cwd=query.cwd,
                within_min=0,
                source_root=query.source_root,
                max_tool_chars=query.max_tool_chars,
            )
        values: list[SessionSummary] = []
        any_supported = False
        for agent_id, database in _agent_db_paths(root):
            if agent_filter is not None and agent_id != agent_filter:
                continue
            try:
                with _open_connection(database, root, budget) as connection:
                    _require_schema(connection, expected_agent=agent_id)
                    if session_filter is not None:
                        # Exact refs bypass listed_sessions prefix (Codex P1).
                        items = _exact_session_summaries(
                            connection,
                            agent_id=agent_id,
                            database=database,
                            session_filter=session_filter,
                            query=list_query,
                        )
                    else:
                        items = _list_nodes(
                            connection,
                            agent_id=agent_id,
                            database=database,
                            query=list_query,
                            include_internal=include_internal,
                        )
                any_supported = True
            except DiagnosticError as error:
                if error.code == "E_UNSUPPORTED_FORMAT":
                    continue
                raise
            # Bound per agent, but never stop scanning other agents before the
            # global timestamp sort (Codex P1 multi-agent latest).
            values.extend(items[: DEFAULT_BOUNDS.listed_sessions])
        if not values and not any_supported and _agent_db_paths(root):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        # Newest first; ascending session_id tie-break (stable sort).
        values.sort(key=lambda item: item.session_id)
        values.sort(
            key=lambda item: item.updated_at or "",
            reverse=True,
        )
        # Missing timestamps last.
        values.sort(key=lambda item: item.updated_at is None)
        if session_filter is not None:
            return values
        return values[: DEFAULT_BOUNDS.listed_sessions]

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        agent_id, session_id = _parse_ref(ref.session_id)
        if agent_id is None or session_id is None:
            # Composite missing — try treating whole id as native session id.
            agent_id, session_id = None, ref.session_id
        database = ref.source_path
        if database is None:
            matches = self.list(
                Query(
                    source=query.source,
                    ref=ref.session_id,
                    cwd=query.cwd,
                    within_min=0,
                    source_root=query.source_root,
                    max_tool_chars=query.max_tool_chars,
                ),
                budget,
            )
            if len(matches) != 1:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
            database = matches[0].source_path
            agent_id, session_id = _parse_ref(matches[0].session_id)
        if database is None or not _regular_db_file(database, root):
            raise DiagnosticError.unsafe_path()
        # Resolve agent from path when composite was incomplete.
        path_agent = None
        parts = os.path.normpath(database).split(os.sep)
        if len(parts) >= 4 and parts[-1] == DB_BASENAME and parts[-2] == "agent":
            path_agent = parts[-3]
        if agent_id is None:
            agent_id = path_agent
        if agent_id is None or session_id is None:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
        with _open_connection(database, root, budget) as connection:
            meta_agent = _require_schema(connection, expected_agent=path_agent or agent_id)
            if meta_agent != agent_id and path_agent is not None:
                agent_id = meta_agent
            return _show_session(
                connection,
                agent_id=agent_id,
                session_id=session_id,
                database=database,
                query=query,
                budget=budget,
            )


ADAPTER = OpenClawAdapter()
