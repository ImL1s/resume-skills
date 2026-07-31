"""Read Cline local hub/session stores as inert context.

Pinned format: ``cline-session-json-v1`` (messages file version = 1) with optional
SQLite index ``sessions.db`` under the Cline data tree.

Default layout (upstream sdk/packages/shared storage paths, 2026-07):

    ~/.cline/data/db/sessions.db                 # index (never a transcript)
    ~/.cline/data/sessions/<id>/<id>.json        # manifest
    ~/.cline/data/sessions/<id>/<id>.messages.json  # authoritative turns

Authority: messages JSON is the transcript source of truth; SQLite is list/index
only. Never invokes Cline CLI/hub/SDK, connectors, or migrations.
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
from ..snapshot import (
    private_sqlite_connection,
    query_only_live_sqlite,
    stable_read_bytes,
    stable_read_windows,
)
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "cline-session-json-v1"
INDEX_PROVIDER = "cline-session-index-sqlite-v1"
MESSAGES_VERSION = 1
# List eligibility must not full-decode multi-MB transcripts (Codex P1).
_LIST_ELIGIBILITY_BYTES = 256 * 1024
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_REQUIRED_SESSION_COLUMNS = frozenset(
    {
        "session_id",
        "source",
        "started_at",
        "status",
        "cwd",
        "workspace_root",
        "parent_session_id",
        "is_subagent",
        "prompt",
        "messages_path",
        "updated_at",
    }
)
_PUBLIC_ROLES = frozenset({"user", "assistant", "tool"})
_SYNTHETIC_USER_KINDS = frozenset(
    {
        "auto_compaction",
        "compaction_budget_emergency",
        "completion_reminder",
        "loop_detection_notice",
        "manual_compaction",
        "mistake_stop_notice",
        "recovery_notice",
    }
)


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


def _default_cline_dir() -> str:
    env = os.environ.get("CLINE_DIR")
    if env and env.strip():
        return env.strip()
    return os.path.expanduser("~/.cline")


def _layout_from_root(candidate: str) -> tuple[str | None, str | None, str] | None:
    """Return (sessions_db|None, sessions_dir|None, containment_root)."""

    try:
        if os.path.isfile(candidate):
            base = os.path.basename(candidate)
            parent = os.path.dirname(os.path.abspath(candidate))
            if base == "sessions.db":
                # When DB is under .../data/db/sessions.db, containment must be
                # the data dir so sibling .../data/sessions/<id>/*.json is allowed.
                if os.path.basename(parent) == "db":
                    data_dir = os.path.dirname(parent)
                    root = canonical_root(data_dir)
                    sessions_dir = None
                    sibling = os.path.join(data_dir, "sessions")
                    if _regular_dir(sibling):
                        sessions_dir = sibling
                else:
                    root = canonical_root(parent)
                    sessions_dir = None
                if not _regular_file(os.path.abspath(candidate), root):
                    return None
                return os.path.abspath(candidate), sessions_dir, root
            if base.endswith(".json") and not base.endswith(".messages.json"):
                # Exact manifest path: .../<id>/<id>.json
                session_dir = parent
                root = canonical_root(os.path.dirname(session_dir) if os.path.basename(os.path.dirname(session_dir)) else session_dir)
                path = os.path.abspath(candidate)
                if not _regular_file(path, root):
                    return None
                # sessions_dir is parent of session_dir
                sessions_dir = os.path.dirname(session_dir)
                db_guess = os.path.join(os.path.dirname(sessions_dir), "db", "sessions.db")
                db = db_guess if _regular_file(db_guess, root) else None
                return db, sessions_dir, root
            return None
        if not os.path.isdir(candidate):
            return None
        root = canonical_root(candidate)
    except DiagnosticError:
        return None

    # ~/.cline
    db = os.path.join(root, "data", "db", "sessions.db")
    sessions = os.path.join(root, "data", "sessions")
    if _regular_file(db, root) or _regular_dir(sessions):
        return (
            db if _regular_file(db, root) else None,
            sessions if _regular_dir(sessions) else None,
            root,
        )

    # ~/.cline/data
    db = os.path.join(root, "db", "sessions.db")
    sessions = os.path.join(root, "sessions")
    if _regular_file(db, root) or _regular_dir(sessions):
        return (
            db if _regular_file(db, root) else None,
            sessions if _regular_dir(sessions) else None,
            root,
        )

    # ~/.cline/data/db — contain under parent data dir so sibling sessions/ is allowed.
    if os.path.basename(root.rstrip(os.sep)) == "db":
        try:
            data_root = canonical_root(os.path.dirname(root))
        except DiagnosticError:
            return None
        db_path = os.path.join(data_root, "db", "sessions.db")
        sessions = os.path.join(data_root, "sessions")
        if _regular_file(db_path, data_root) or _regular_dir(sessions):
            return (
                db_path if _regular_file(db_path, data_root) else None,
                sessions if _regular_dir(sessions) else None,
                data_root,
            )

    # ~/.cline/data/sessions
    if any(
        name.endswith(".json") or _regular_dir(os.path.join(root, name))
        for name in _safe_listdir(root)
    ):
        db = os.path.join(os.path.dirname(root), "db", "sessions.db")
        return (
            db if _regular_file(db, root) else None,
            root,
            root,
        )
    return None


def _safe_listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


def _resolve_layout(query: Query) -> tuple[str | None, str | None, str] | None:
    if query.source_root:
        return _layout_from_root(query.source_root)
    return _layout_from_root(_default_cline_dir())


def _open_connection(database: str, root: str, budget: ReadBudget | None = None):
    limits = budget.limits if budget is not None else DEFAULT_BOUNDS
    try:
        size = os.path.getsize(database)
    except OSError as error:
        raise DiagnosticError.source_busy(provider=INDEX_PROVIDER) from error
    if size > limits.sqlite_snapshot_bytes:
        return query_only_live_sqlite(database, root=root, provider=INDEX_PROVIDER)
    return private_sqlite_connection(
        database, root=root, bounds=limits, provider=INDEX_PROVIDER
    )


def _require_index_schema(connection: sqlite3.Connection) -> None:
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
            )
        }
        if "sessions" not in tables:
            raise DiagnosticError(
                "E_UNSUPPORTED_FORMAT", source="cline", provider=INDEX_PROVIDER
            )
        cols = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(sessions)")
        }
        if not _REQUIRED_SESSION_COLUMNS.issubset(cols):
            raise DiagnosticError(
                "E_UNSUPPORTED_FORMAT", source="cline", provider=INDEX_PROVIDER
            )
    except sqlite3.DatabaseError as error:
        raise DiagnosticError(
            "E_UNSUPPORTED_FORMAT", source="cline", provider=INDEX_PROVIDER
        ) from error


def _exact_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    if _SESSION_ID_RE.fullmatch(text):
        return text
    return None


def _stamp_iso(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return (
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    except ValueError:
        return None


def _messages_path_for(
    *,
    session_id: str,
    messages_path: object,
    sessions_dir: str | None,
    root: str,
) -> str | None:
    # Prefer the closed layout path; only accept explicit paths that stay under root
    # and whose basename matches the selected session (prevents cross-session swaps).
    if sessions_dir is not None:
        candidate = os.path.join(sessions_dir, session_id, f"{session_id}.messages.json")
        if _regular_file(candidate, root):
            return candidate
    if isinstance(messages_path, str) and messages_path.strip():
        path = messages_path.strip()
        if not os.path.isabs(path) and sessions_dir is not None:
            path = os.path.join(sessions_dir, session_id, path)
        if (
            _regular_file(path, root)
            and os.path.basename(path) == f"{session_id}.messages.json"
        ):
            return path
    return None


def _content_chunks(content: object) -> list[str]:
    if isinstance(content, str) and content.strip():
        return [content]
    if not isinstance(content, list):
        return []
    chunks: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
        elif kind in {"tool_result", "tool-result"}:
            text = item.get("content")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
            elif isinstance(text, list):
                chunks.extend(_content_chunks(text))
        elif kind in {"tool_use", "tool-use", "tool_call"}:
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                chunks.append(name)
    return chunks


def _turn_from_message(message: Mapping[str, Any]) -> tuple[str, str] | None:
    role = message.get("role")
    if not isinstance(role, str) or role not in _PUBLIC_ROLES:
        return None
    meta = message.get("metadata")
    if isinstance(meta, Mapping):
        kind = meta.get("kind")
        if isinstance(kind, str) and kind in _SYNTHETIC_USER_KINDS:
            return None
        display = meta.get("displayRole")
        if isinstance(display, str) and display.strip().lower() in {
            "system",
            "status",
            "error",
        }:
            return None
    chunks = _content_chunks(message.get("content"))
    if not chunks:
        return None
    text = "\n".join(chunks).strip()
    if not text:
        return None
    return role, text


def _load_messages_payload(
    path: str,
    root: str,
    budget: ReadBudget,
    *,
    expected_session_id: str | None = None,
    max_bytes: int | None = None,
) -> list[Mapping[str, Any]]:
    ceiling = min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes)
    limit = ceiling if max_bytes is None else min(max_bytes, ceiling)
    # stable_read_bytes rejects max_bytes above sqlite_snapshot_bytes.
    limit = min(limit, DEFAULT_BOUNDS.sqlite_snapshot_bytes)
    try:
        # Fail closed on oversize before allocating a full buffer when possible.
        size = os.lstat(path).st_size
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    if size > limit:
        raise DiagnosticError.limit_exceeded()
    try:
        read = stable_read_bytes(
            path,
            root=root,
            max_bytes=limit,
            budget=budget,
        )
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    raw = read.data
    if len(raw) > budget.limits.source_read_bytes:
        raise DiagnosticError.limit_exceeded()
    try:
        # json.loads accepts bytes — avoid an extra full-string decode copy.
        payload = json.loads(raw, object_pairs_hook=_object)
    except (
        json.JSONDecodeError,
        _DuplicateKey,
        RecursionError,
        UnicodeDecodeError,
    ) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="cline", provider=FORMAT_ID) from error
    if not isinstance(payload, Mapping):
        raise DiagnosticError("E_CORRUPT_RECORD", source="cline", provider=FORMAT_ID)
    version = payload.get("version")
    if version != MESSAGES_VERSION:
        raise DiagnosticError(
            "E_UNSUPPORTED_FORMAT", source="cline", provider=FORMAT_ID
        )
    if expected_session_id is not None:
        payload_id = payload.get("sessionId")
        if not isinstance(payload_id, str) or payload_id != expected_session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cline", provider=FORMAT_ID)
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise DiagnosticError("E_CORRUPT_RECORD", source="cline", provider=FORMAT_ID)
    return [m for m in messages if isinstance(m, Mapping)]


def _window_text(data: bytes) -> str:
    """Decode a byte window; incomplete boundary code points become U+FFFD."""

    if not data:
        return ""
    return data.decode("utf-8", errors="replace")


def _list_messages_soft_ok(
    path: str,
    root: str,
    budget: ReadBudget,
    *,
    expected_session_id: str,
) -> bool:
    """Bounded list eligibility for oversized messages (no full decode).

    Path already binds ``session_id`` via ``{id}/{id}.messages.json``. Windows only
    reject clear envelope mismatches (wrong version / wrong sessionId). Public
    roles may live in the unsampled middle — show validates turns fully.
    """

    head_limit = min(_LIST_ELIGIBILITY_BYTES, 4 * 1024 * 1024)
    tail_limit = min(64 * 1024, head_limit)
    try:
        windows = stable_read_windows(
            path,
            root=root,
            head_bytes=head_limit,
            tail_bytes=tail_limit,
            max_bytes=min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
            budget=budget,
            require_size_within_max=False,
        )
    except DiagnosticError:
        # Path + size already accepted; IO glitch during soft check → skip.
        return False
    text = _window_text(windows.head)
    if windows.tail and windows.tail != windows.head:
        text = text + "\n" + _window_text(windows.tail)
    if not text.strip():
        return False
    # Reject only unambiguous envelope mismatches visible in the windows.
    if re.search(r'"version"\s*:\s*(\d+)', text):
        if not re.search(r'"version"\s*:\s*1\b', text):
            return False
    if re.search(r'"sessionId"\s*:\s*"', text):
        if not re.search(
            rf'"sessionId"\s*:\s*"{re.escape(expected_session_id)}"',
            text,
        ):
            return False
    budget.consume_records()
    return True


def _session_has_extractable(
    *,
    session_id: str,
    messages_path: str | None,
    root: str,
    budget: ReadBudget,
    raise_on_bad: bool = False,
) -> bool:
    """Require a safe authoritative messages payload (prompt alone is insufficient).

    During ordinary listing (``raise_on_bad=False``):
    - corrupt / unsupported candidates are skipped so older valid rows can win
    - multi-MB files use a soft bounded check (no full JSON decode, no role-in-window)
    Explicit selection / show still full-loads and raises.
    """

    if messages_path is None:
        return False
    try:
        size = os.lstat(messages_path).st_size
    except OSError:
        return False
    if size <= 0:
        return False
    source_cap = min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes)
    if size > source_cap:
        if raise_on_bad:
            raise DiagnosticError.limit_exceeded()
        return False
    list_cap = min(
        budget.limits.record_bytes,
        DEFAULT_BOUNDS.record_bytes,
        _LIST_ELIGIBILITY_BYTES,
    )
    if not raise_on_bad and size > list_cap:
        return _list_messages_soft_ok(
            messages_path,
            root,
            budget,
            expected_session_id=session_id,
        )
    try:
        messages = _load_messages_payload(
            messages_path,
            root,
            budget,
            expected_session_id=session_id,
            max_bytes=list_cap if not raise_on_bad else None,
        )
    except DiagnosticError as error:
        if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
            if raise_on_bad:
                raise
            return False
        if error.code == "E_LIMIT_EXCEEDED" and not raise_on_bad:
            return False
        return False
    for message in messages[: min(64, budget.limits.transcript_records or 64)]:
        budget.consume_records()
        if _turn_from_message(message) is not None:
            return True
    return False


def _row_summary(
    *,
    session_id: str,
    source_path: str,
    prompt: object,
    cwd_value: object,
    workspace_root: object,
    started_at: object,
    updated_at: object,
    query: Query,
    require_age: bool,
) -> SessionSummary | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    cwd: str | None = None
    for candidate in (cwd_value, workspace_root):
        if isinstance(candidate, str) and candidate.strip():
            try:
                cwd = canonicalize_cwd(candidate)
                break
            except DiagnosticError:
                continue
    if query.cwd is not None:
        if cwd is None or not same_cwd(cwd, query.cwd):
            return None
    stamp = _stamp_iso(updated_at) or _stamp_iso(started_at)
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    title = None
    if isinstance(prompt, str) and prompt.strip():
        title = prompt.strip().splitlines()[0][: DEFAULT_BOUNDS.title_chars]
    return SessionSummary(
        source="cline",
        session_id=session_id,
        source_path=source_path,
        title=title,
        cwd=cwd,
        branch=None,
        created_at=_stamp_iso(started_at),
        updated_at=stamp,
        provider=FORMAT_ID,
        warnings=(),
    )


def _list_from_sessions_dir(
    *,
    sessions_dir: str,
    root: str,
    query: Query,
    exact_id: str | None,
    budget: ReadBudget,
) -> list[SessionSummary]:
    """Bounded JSON discovery when the SQLite index is absent (Codex P1)."""

    scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
    list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
    if exact_id is None and list_limit <= 0:
        return []
    require_age = exact_id is None
    candidates: list[str]
    if exact_id is not None:
        candidates = [exact_id]
    else:
        names = sorted(_safe_listdir(sessions_dir))
        if len(names) > scan_limit:
            raise DiagnosticError.limit_exceeded()
        candidates = [name for name in names if _SESSION_ID_RE.fullmatch(name)]
    values: list[SessionSummary] = []
    for session_id in candidates:
        msg_path = _messages_path_for(
            session_id=session_id,
            messages_path=None,
            sessions_dir=sessions_dir,
            root=root,
        )
        if msg_path is None:
            continue
        if not _session_has_extractable(
            session_id=session_id,
            messages_path=msg_path,
            root=root,
            budget=budget,
            raise_on_bad=exact_id is not None,
        ):
            continue
        # Optional manifest for metadata only (identity must match directory id).
        prompt = None
        cwd_value = None
        workspace_root = None
        started_at = None
        updated_at = None
        manifest_path = os.path.join(sessions_dir, session_id, f"{session_id}.json")
        if _regular_file(manifest_path, root):
            try:
                read = stable_read_bytes(
                    manifest_path,
                    root=root,
                    max_bytes=min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes),
                    budget=budget,
                )
                manifest = json.loads(read.data.decode("utf-8"), object_pairs_hook=_object)
                if isinstance(manifest, Mapping):
                    mid = manifest.get("session_id")
                    if isinstance(mid, str) and mid and mid != session_id:
                        # Stale/copied manifest: ignore metadata, keep messages authority.
                        pass
                    else:
                        prompt = manifest.get("prompt")
                        cwd_value = manifest.get("cwd")
                        workspace_root = manifest.get("workspace_root")
                        started_at = manifest.get("started_at")
                        updated_at = manifest.get("updated_at") or manifest.get("started_at")
                        parent = manifest.get("parent_session_id")
                        is_sub = manifest.get("is_subagent")
                        if exact_id is None and (
                            (isinstance(parent, str) and parent.strip())
                            or is_sub in (1, True)
                        ):
                            continue
            except (DiagnosticError, json.JSONDecodeError, _DuplicateKey, UnicodeDecodeError):
                pass
        item = _row_summary(
            session_id=session_id,
            source_path=msg_path,
            prompt=prompt,
            cwd_value=cwd_value,
            workspace_root=workspace_root,
            started_at=started_at,
            updated_at=updated_at,
            query=query,
            require_age=require_age,
        )
        if item is not None:
            # Do not truncate here: candidates are ID-sorted, not recency-sorted.
            # Outer list() sorts by updated_at then applies listed_sessions (Codex P1).
            values.append(item)
            budget.consume_records()
            if exact_id is None and len(values) >= scan_limit:
                break
    return values


def _list_from_index(
    connection: sqlite3.Connection,
    *,
    database: str,
    sessions_dir: str | None,
    root: str,
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
            SELECT session_id, parent_session_id, is_subagent, prompt, cwd, workspace_root,
                   messages_path, started_at, updated_at
            FROM sessions
            WHERE session_id = ? OR lower(session_id) = lower(?)
            LIMIT 2
            """,
            (exact_id, exact_id),
        ).fetchall()
        require_age = False
        if not rows:
            # Stale/lagging index: recover authoritative messages JSON by exact id
            # before abandoning exact mode (Codex P1).
            if sessions_dir is not None:
                return _list_from_sessions_dir(
                    sessions_dir=sessions_dir,
                    root=root,
                    query=query,
                    exact_id=exact_id,
                    budget=budget,
                )
            return []
    else:
        if scan_limit <= 0:
            return []
        rows = connection.execute(
            """
            SELECT session_id, parent_session_id, is_subagent, prompt, cwd, workspace_root,
                   messages_path, started_at, updated_at
            FROM sessions
            WHERE (parent_session_id IS NULL OR parent_session_id = '')
              AND COALESCE(is_subagent, 0) = 0
            ORDER BY updated_at DESC, started_at DESC, session_id ASC
            LIMIT ?
            """,
            (scan_limit,),
        ).fetchall()
        require_age = True

    values: list[SessionSummary] = []
    for row in rows:
        (
            session_id,
            parent_session_id,
            is_subagent,
            prompt,
            cwd_value,
            workspace_root,
            messages_path,
            started_at,
            updated_at,
        ) = row
        msg_path = _messages_path_for(
            session_id=str(session_id),
            messages_path=messages_path,
            sessions_dir=sessions_dir,
            root=root,
        )
        if exact_id is None:
            if isinstance(parent_session_id, str) and parent_session_id.strip():
                continue
            if is_subagent in (1, True):
                continue
            if not _session_has_extractable(
                session_id=str(session_id),
                messages_path=msg_path,
                root=root,
                budget=budget,
                raise_on_bad=False,
            ):
                continue
        # Prefer authoritative messages path so exact-path selection works (Codex P2).
        summary_path = msg_path if msg_path is not None else database
        item = _row_summary(
            session_id=str(session_id),
            source_path=summary_path,
            prompt=prompt,
            cwd_value=cwd_value,
            workspace_root=workspace_root,
            started_at=started_at,
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


def _show_from_messages(
    *,
    session_id: str,
    source_path: str,
    messages_path: str,
    root: str,
    query: Query,
    budget: ReadBudget,
    title: str | None,
    cwd: str | None,
    created_at: str | None,
    updated_at: str | None,
) -> Session:
    if query.cwd is not None and (cwd is None or not same_cwd(cwd, query.cwd)):
        raise DiagnosticError("E_NO_MATCH", source="cline", provider=FORMAT_ID)
    messages = _load_messages_payload(
        messages_path, root, budget, expected_session_id=session_id
    )
    turns: list[Turn] = []
    warnings: list[str] = []
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
    limit = budget.limits.transcript_records
    count = 0
    for message in messages:
        count += 1
        if count > limit:
            raise DiagnosticError.limit_exceeded()
        budget.consume_transcript_records()
        parsed = _turn_from_message(message)
        if parsed is None:
            continue
        role, text = parsed
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
    last_assistant = next(
        (t.content for t in reversed(turns) if t.role == "assistant"), None
    )
    return Session(
        source="cline",
        session_id=session_id,
        source_path=source_path,
        title=title,
        cwd=cwd,
        branch=None,
        created_at=created_at,
        updated_at=updated_at or created_at,
        last_user_request=last_user,
        last_assistant_action=last_assistant,
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(warnings)),
    )


class ClineAdapter:
    key = "cline"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        layout = _resolve_layout(query)
        return (layout[2],) if layout else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            layout = _resolve_layout(query)
            if layout is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            database, sessions_dir, root = layout
            json_ok = bool(sessions_dir and _regular_dir(sessions_dir))
            index_ok = False
            if database is not None:
                try:
                    with _open_connection(database, root) as connection:
                        _require_index_schema(connection)
                    index_ok = True
                except DiagnosticError as error:
                    if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                        return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                    if error.code not in {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD"}:
                        raise
            if index_ok and json_ok:
                return CapabilityReport(
                    self.key,
                    FORMAT_ID,
                    "supported",
                    root=root,
                    evidence=(FORMAT_ID, INDEX_PROVIDER),
                )
            if json_ok or index_ok:
                return CapabilityReport(
                    self.key,
                    FORMAT_ID,
                    "partial",
                    root=root,
                    evidence=(FORMAT_ID if json_ok else INDEX_PROVIDER,),
                )
            return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
        except DiagnosticError as error:
            state = (
                "unsafe"
                if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}
                else "unsupported"
            )
            return CapabilityReport(self.key, FORMAT_ID, state)

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        layout = _resolve_layout(query)
        if layout is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        database, sessions_dir, root = layout
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
        values: list[SessionSummary] = []
        if database is not None:
            try:
                with _open_connection(database, root, budget) as connection:
                    _require_index_schema(connection)
                    values = _list_from_index(
                        connection,
                        database=database,
                        sessions_dir=sessions_dir,
                        root=root,
                        query=list_query,
                        exact_id=exact,
                        budget=budget,
                    )
            except DiagnosticError as error:
                # Optional index: corrupt/unsupported schema must not block
                # authoritative JSON recovery when sessions_dir is present.
                if (
                    error.code in {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD"}
                    and sessions_dir is not None
                ):
                    values = _list_from_sessions_dir(
                        sessions_dir=sessions_dir,
                        root=root,
                        query=list_query,
                        exact_id=exact,
                        budget=budget,
                    )
                else:
                    raise
        elif sessions_dir is not None:
            values = _list_from_sessions_dir(
                sessions_dir=sessions_dir,
                root=root,
                query=list_query,
                exact_id=exact,
                budget=budget,
            )
        else:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        values.sort(key=lambda item: item.session_id)
        values.sort(key=lambda item: item.updated_at or "", reverse=True)
        values.sort(key=lambda item: item.updated_at is None)
        if exact is not None:
            return values
        list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
        return values[:list_limit]

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        layout = _resolve_layout(query)
        if layout is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        database, sessions_dir, root = layout
        session_id = ref.session_id
        if not session_id:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        prompt = None
        cwd_value = None
        workspace_root = None
        started_at = None
        updated_at = None
        messages_path_col = None
        source_path = database or ""

        if database is not None:
            try:
                with _open_connection(database, root, budget) as connection:
                    _require_index_schema(connection)
                    rows = connection.execute(
                        """
                        SELECT prompt, cwd, workspace_root, messages_path, started_at, updated_at
                        FROM sessions WHERE session_id = ?
                        LIMIT 2
                        """,
                        (session_id,),
                    ).fetchall()
                    if len(rows) == 1:
                        (
                            prompt,
                            cwd_value,
                            workspace_root,
                            messages_path_col,
                            started_at,
                            updated_at,
                        ) = rows[0]
                        source_path = database
            except DiagnosticError as error:
                if error.code not in {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD"}:
                    raise
                # Fall through to sessions_dir / messages JSON authority.

        # Index-absent path: recover metadata from the session manifest when present.
        if (
            sessions_dir is not None
            and cwd_value is None
            and workspace_root is None
        ):
            manifest_path = os.path.join(sessions_dir, session_id, f"{session_id}.json")
            if _regular_file(manifest_path, root):
                try:
                    read = stable_read_bytes(
                        manifest_path,
                        root=root,
                        max_bytes=min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes),
                        budget=budget,
                    )
                    manifest = json.loads(
                        read.data.decode("utf-8"), object_pairs_hook=_object
                    )
                    if isinstance(manifest, Mapping):
                        prompt = prompt or manifest.get("prompt")
                        cwd_value = manifest.get("cwd")
                        workspace_root = manifest.get("workspace_root")
                        started_at = started_at or manifest.get("started_at")
                        updated_at = updated_at or manifest.get("updated_at") or manifest.get(
                            "started_at"
                        )
                except (
                    DiagnosticError,
                    json.JSONDecodeError,
                    _DuplicateKey,
                    UnicodeDecodeError,
                ):
                    pass

        msg_path = _messages_path_for(
            session_id=session_id,
            messages_path=messages_path_col,
            sessions_dir=sessions_dir,
            root=root,
        )
        if msg_path is None:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        cwd: str | None = None
        for candidate in (cwd_value, workspace_root):
            if isinstance(candidate, str) and candidate.strip():
                try:
                    cwd = canonicalize_cwd(candidate)
                    break
                except DiagnosticError:
                    continue
        title = None
        if isinstance(prompt, str) and prompt.strip():
            title = prompt.strip().splitlines()[0][: DEFAULT_BOUNDS.title_chars]
        # Keep source_path aligned with list() (messages path preferred) so the
        # reader invariant list.source_path == show.source_path holds.
        return _show_from_messages(
            session_id=session_id,
            source_path=msg_path or source_path,
            messages_path=msg_path,
            root=root,
            query=query,
            budget=budget,
            title=title,
            cwd=cwd,
            created_at=_stamp_iso(started_at),
            updated_at=_stamp_iso(updated_at),
        )


ADAPTER = ClineAdapter()
