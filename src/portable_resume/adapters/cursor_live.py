"""Live Cursor CLI store.db + Desktop composer providers (extracted)."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import private_sqlite_connection, query_only_live_sqlite, stable_read_bytes

# Reuse shared helpers from the fixture/adapter module without circular import of ADAPTER.
from . import cursor as _cursor

LIVE_CLI_FORMAT = _cursor.LIVE_CLI_FORMAT
LIVE_DESKTOP_FORMAT = _cursor.LIVE_DESKTOP_FORMAT
_regular_directory = _cursor._regular_directory
_cwd_hash = _cursor._cwd_hash
_within = _cursor._within
_object = _cursor._object
_DuplicateKey = _cursor._DuplicateKey

def _ms_to_rfc3339(value: object) -> str | None:
    if type(value) is not int:
        return None
    seconds = value / 1000 if value >= 1_577_836_800_000 else value
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _desktop_app_storage_dirs() -> list[str]:
    home = os.path.expanduser("~")
    return [
        os.path.join(home, "Library", "Application Support", "Cursor", "User", "globalStorage"),
        os.path.join(home, ".config", "Cursor", "User", "globalStorage"),
    ]


def _content_to_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "\n".join(chunks) if chunks else None
    return None


def _list_live_cli_stores(root: str, query: Query) -> list[SessionSummary]:
    chats = os.path.join(root, "chats")
    if not _regular_directory(chats, root):
        return []
    prefer = _cwd_hash(query.cwd) if query.cwd else None
    try:
        hash_names = sorted(os.listdir(chats))
    except OSError as error:
        raise DiagnosticError.source_busy(provider=LIVE_CLI_FORMAT) from error
    values: list[SessionSummary] = []
    for name in hash_names:
        if prefer is not None and name != prefer:
            continue
        bucket = os.path.join(chats, name)
        if not _regular_directory(bucket, root):
            continue
        try:
            session_names = sorted(os.listdir(bucket))
        except OSError:
            continue
        for session_name in session_names:
            if len(values) >= DEFAULT_BOUNDS.scanned_records:
                break
            try:
                session_id = str(uuid.UUID(session_name))
            except ValueError:
                continue
            session_dir = os.path.join(bucket, session_name)
            store = os.path.join(session_dir, "store.db")
            if not os.path.isfile(store) or os.path.islink(store):
                continue
            if not is_within(store, root):
                continue
            meta_path = os.path.join(session_dir, "meta.json")
            cwd: str | None = None
            title: str | None = None
            created_at: str | None = None
            updated_at: str | None = None
            if os.path.lexists(meta_path):
                try:
                    read = stable_read_bytes(
                        meta_path,
                        root=root,
                        max_bytes=min(DEFAULT_BOUNDS.record_bytes, 256 * 1024),
                        budget=None,
                    )
                    meta = json.loads(read.data.decode("utf-8"))
                    if isinstance(meta, dict):
                        if isinstance(meta.get("cwd"), str):
                            cwd = canonicalize_cwd(meta["cwd"])
                        title = meta.get("title") if isinstance(meta.get("title"), str) else None
                        created_at = _ms_to_rfc3339(meta.get("createdAtMs"))
                        updated_at = _ms_to_rfc3339(meta.get("updatedAtMs"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, DiagnosticError):
                    pass
            if query.cwd is not None:
                if cwd is not None and not same_cwd(cwd, query.cwd):
                    continue
                if cwd is None and prefer is None:
                    continue
                if cwd is None:
                    cwd = canonicalize_cwd(query.cwd)
            if updated_at is None:
                try:
                    updated_at = datetime.fromtimestamp(
                        os.lstat(store).st_mtime, timezone.utc
                    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
                except OSError:
                    continue
            if not _within(updated_at, query, session_id):
                continue
            values.append(
                SessionSummary(
                    source="cursor",
                    session_id=session_id,
                    source_path=store,
                    title=title,
                    cwd=cwd,
                    created_at=created_at,
                    updated_at=updated_at,
                    provider=LIVE_CLI_FORMAT,
                )
            )
        if len(values) >= DEFAULT_BOUNDS.scanned_records:
            break
    # Rank newest first so latest is not UUID/name-order capped.
    values.sort(
        key=lambda item: (
            item.updated_at is None,
            item.updated_at or "",
            item.session_id,
        ),
        reverse=True,
    )
    return values


def _show_live_cli_store(
    path: str, root: str, session_id: str, budget: ReadBudget, *, max_tool_chars: int
) -> Session:
    if not is_within(path, root) or not path.endswith("store.db"):
        raise DiagnosticError.unsafe_path()
    try:
        size = os.path.getsize(path)
    except OSError as error:
        raise DiagnosticError("E_SOURCE_BUSY", source="cursor", provider=LIVE_CLI_FORMAT) from error
    ctx = (
        query_only_live_sqlite(path, root=root, provider=LIVE_CLI_FORMAT)
        if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes
        else private_sqlite_connection(path, root=root, provider=LIVE_CLI_FORMAT)
    )
    warnings: list[str] = []
    turns: list[Turn] = []
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=max_tool_chars)
    cwd: str | None = None
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    meta_path = os.path.join(os.path.dirname(path), "meta.json")
    if os.path.lexists(meta_path):
        try:
            read = stable_read_bytes(
                meta_path,
                root=root,
                max_bytes=min(DEFAULT_BOUNDS.record_bytes, 256 * 1024),
                budget=budget,
            )
            meta = json.loads(read.data.decode("utf-8"))
            if isinstance(meta, dict):
                if isinstance(meta.get("cwd"), str):
                    cwd = canonicalize_cwd(meta["cwd"])
                title = meta.get("title") if isinstance(meta.get("title"), str) else None
                created_at = _ms_to_rfc3339(meta.get("createdAtMs"))
                updated_at = _ms_to_rfc3339(meta.get("updatedAtMs"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, DiagnosticError):
            warnings.append("W_STALE_INDEX")
    with ctx as connection:
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "blobs" not in tables:
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="cursor", provider=LIVE_CLI_FORMAT)
            # Deterministic order: rowid insertion order (stable), then id.
            rows = connection.execute(
                "SELECT id, data FROM blobs ORDER BY rowid ASC, id ASC LIMIT ?",
                (DEFAULT_BOUNDS.scanned_records,),
            ).fetchall()
        except sqlite3.Error as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=LIVE_CLI_FORMAT) from error
    for row in rows:
        budget.consume_records()
        if len(row) != 2 or not isinstance(row[0], str) or not isinstance(row[1], (bytes, memoryview)):
            continue
        data = bytes(row[1])
        if len(data) > DEFAULT_BOUNDS.record_bytes:
            warnings.append("W_TRUNCATED")
            continue
        try:
            payload = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError):
            warnings.append("W_BINARY_OMITTED")
            continue
        if not isinstance(payload, dict):
            continue
        role = payload.get("role")
        if role not in {"user", "assistant", "tool"}:
            if role == "system":
                continue
            continue
        text = _content_to_text(payload.get("content"))
        if text is None:
            continue
        turn, turn_warnings = sanitize_turn_record(
            {
                "role": role,
                "content": text,
                "tool_name": payload.get("name") if isinstance(payload.get("name"), str) else None,
            },
            ordinal=len(turns),
            bounds=turn_bounds,
        )
        warnings.extend(turn_warnings)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)
    if updated_at is None:
        try:
            updated_at = datetime.fromtimestamp(os.lstat(path).st_mtime, timezone.utc).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
        except OSError:
            updated_at = None
    return Session(
        source="cursor",
        session_id=session_id,
        source_path=path,
        title=title,
        cwd=cwd,
        created_at=created_at,
        updated_at=updated_at,
        last_user_request=next((turn.content for turn in reversed(turns) if turn.role == "user"), None),
        last_assistant_action=next((turn.content for turn in reversed(turns) if turn.role == "assistant"), None),
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _list_live_desktop(query: Query) -> list[SessionSummary]:
    values: list[SessionSummary] = []
    for storage in _desktop_app_storage_dirs():
        database = os.path.join(storage, "state.vscdb")
        if not os.path.isfile(database) or os.path.islink(database):
            continue
        try:
            root = canonical_root(storage)
        except DiagnosticError:
            continue
        if not is_within(database, root):
            continue
        try:
            size = os.path.getsize(database)
        except OSError:
            continue
        try:
            ctx = (
                query_only_live_sqlite(database, root=root, provider=LIVE_DESKTOP_FORMAT)
                if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes
                else private_sqlite_connection(database, root=root, provider=LIVE_DESKTOP_FORMAT)
            )
            with ctx as connection:
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "composerHeaders" not in tables:
                    continue
                rows = connection.execute(
                    "SELECT composerId, workspaceId, createdAt, lastUpdatedAt, isArchived, isSubagent, value "
                    "FROM composerHeaders WHERE IFNULL(isSubagent,0)=0 AND IFNULL(isArchived,0)=0 "
                    "ORDER BY lastUpdatedAt DESC LIMIT ?",
                    (DEFAULT_BOUNDS.listed_sessions * 4,),
                ).fetchall()
        except DiagnosticError:
            continue
        except sqlite3.Error:
            continue
        for row in rows:
            if len(values) >= DEFAULT_BOUNDS.listed_sessions:
                break
            if len(row) != 7 or not isinstance(row[0], str):
                continue
            composer_id = row[0]
            try:
                uuid.UUID(composer_id)
            except ValueError:
                if composer_id in {"empty-state-draft"}:
                    continue
            value_raw = row[6]
            cwd: str | None = None
            title: str | None = None
            if isinstance(value_raw, str):
                try:
                    payload = json.loads(value_raw)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    title = payload.get("name") if isinstance(payload.get("name"), str) else None
                    if title is None and isinstance(payload.get("subtitle"), str):
                        title = payload["subtitle"]
                    wi = payload.get("workspaceIdentifier")
                    if isinstance(wi, dict):
                        uri = wi.get("uri")
                        if isinstance(uri, dict) and isinstance(uri.get("fsPath"), str):
                            try:
                                cwd = canonicalize_cwd(uri["fsPath"])
                            except DiagnosticError:
                                cwd = None
                        elif isinstance(uri, dict) and isinstance(uri.get("path"), str):
                            try:
                                cwd = canonicalize_cwd(uri["path"])
                            except DiagnosticError:
                                cwd = None
            if query.cwd is not None:
                if cwd is None or not same_cwd(cwd, query.cwd):
                    continue
            updated_at = _ms_to_rfc3339(row[3])
            if updated_at is None or not _within(updated_at, query, composer_id):
                continue
            values.append(
                SessionSummary(
                    source="cursor",
                    session_id=composer_id,
                    source_path=database,
                    title=title,
                    cwd=cwd,
                    created_at=_ms_to_rfc3339(row[2]),
                    updated_at=updated_at,
                    provider=LIVE_DESKTOP_FORMAT,
                )
            )
    return values


def _show_live_desktop(
    path: str, session_id: str, budget: ReadBudget, *, max_tool_chars: int
) -> Session:
    """List-level metadata + optional composerData text; bubble graph not fully restored."""
    storage = os.path.dirname(path)
    root = canonical_root(storage)
    if not is_within(path, root):
        raise DiagnosticError.unsafe_path()
    try:
        size = os.path.getsize(path)
    except OSError as error:
        raise DiagnosticError("E_SOURCE_BUSY", source="cursor", provider=LIVE_DESKTOP_FORMAT) from error
    ctx = (
        query_only_live_sqlite(path, root=root, provider=LIVE_DESKTOP_FORMAT)
        if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes
        else private_sqlite_connection(path, root=root, provider=LIVE_DESKTOP_FORMAT)
    )
    warnings: list[str] = ["W_MISSING_BLOB"]  # full bubble chain not claimed
    with ctx as connection:
        try:
            row = connection.execute(
                "SELECT composerId, createdAt, lastUpdatedAt, value FROM composerHeaders WHERE composerId=?",
                (session_id,),
            ).fetchone()
            text_blob = None
            if "cursorDiskKV" in {
                r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }:
                text_blob = connection.execute(
                    "SELECT value FROM cursorDiskKV WHERE key=?",
                    (f"composerData:{session_id}",),
                ).fetchone()
        except sqlite3.Error as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=LIVE_DESKTOP_FORMAT) from error
    if row is None:
        raise DiagnosticError("E_NO_MATCH", source="cursor", provider=LIVE_DESKTOP_FORMAT)
    cwd = None
    title = None
    if isinstance(row[3], str):
        try:
            payload = json.loads(row[3])
            if isinstance(payload, dict):
                title = payload.get("name") if isinstance(payload.get("name"), str) else None
                wi = payload.get("workspaceIdentifier")
                if isinstance(wi, dict) and isinstance(wi.get("uri"), dict):
                    fs = wi["uri"].get("fsPath") or wi["uri"].get("path")
                    if isinstance(fs, str):
                        cwd = canonicalize_cwd(fs)
        except (json.JSONDecodeError, DiagnosticError):
            pass
    turns: list[Turn] = []
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=max_tool_chars)
    if text_blob and isinstance(text_blob[0], (str, bytes)):
        raw = text_blob[0].decode("utf-8") if isinstance(text_blob[0], bytes) else text_blob[0]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("text"), str) and data["text"].strip():
            turn, tw = sanitize_turn_record(
                {"role": "user", "content": data["text"]},
                ordinal=0,
                bounds=turn_bounds,
            )
            warnings.extend(tw)
            if turn is not None:
                budget.consume_turns()
                turns.append(turn)
    return Session(
        source="cursor",
        session_id=session_id,
        source_path=path,
        title=title,
        cwd=cwd,
        created_at=_ms_to_rfc3339(row[1]),
        updated_at=_ms_to_rfc3339(row[2]),
        last_user_request=next((turn.content for turn in reversed(turns) if turn.role == "user"), None),
        last_assistant_action=None,
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(warnings)),
    )


