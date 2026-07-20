"""Read pinned Cursor CLI chat and Desktop snapshot formats."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import StableRead, private_sqlite_connection, query_only_live_sqlite, stable_read_bytes
from .base import CapabilityReport, ResolvedRef

CLI_FORMAT = "cursor-cli-chat-v1"
DESKTOP_FORMAT = "cursor-desktop-vscdb-v1"
LIVE_CLI_FORMAT = "cursor-cli-store-v1"
LIVE_DESKTOP_FORMAT = "cursor-desktop-composer-v1"
_METADATA_KEYS = frozenset(
    {
        "format",
        "id",
        "cwd",
        "cwd_hash",
        "title",
        "created_at",
        "updated_at",
        "archived",
        "composer_kind",
        "git_branch",
        "transcripts",
    }
)
_TRANSCRIPT_TYPES = frozenset({"message", "system", "control", "reasoning"})
_COMPOSER_COLUMNS = {
    "id": "TEXT",
    "cwd": "TEXT",
    "cwd_hash": "TEXT",
    "title": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
    "archived": "INTEGER",
    "composer_kind": "TEXT",
    "git_branch": "TEXT",
}
_LINK_COLUMNS = {"composer_id": "TEXT", "ordinal": "INTEGER", "blob_key": "TEXT"}
_BLOB_COLUMNS = {"blob_key": "TEXT", "payload_json": "TEXT"}


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise _DuplicateKey(key)
        output[key] = value
    return output


def _root_candidate(query: Query) -> str:
    return query.source_root or os.environ.get("CURSOR_HOME") or os.path.expanduser("~/.cursor")


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


def _regular_directory(path: str, root: str) -> bool:
    try:
        current = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(current.st_mode) and not stat.S_ISLNK(current.st_mode) and is_within(path, root)


def _cwd_hash(cwd: str) -> str:
    try:
        digest = hashlib.md5(cwd.encode("utf-8"), usedforsecurity=False)
    except TypeError:  # pragma: no cover - compatibility with older Python builds
        digest = hashlib.md5(cwd.encode("utf-8"))
    return digest.hexdigest()


def _rfc3339(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _mtime(read: StableRead) -> str:
    return datetime.fromtimestamp(read.fingerprint.mtime_ns / 1_000_000_000, timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _within(updated_at: str | None, query: Query, identifier: str) -> bool:
    from .common import within_query_age

    return within_query_age(
        updated_at,
        query_ref=query.ref,
        session_id=identifier,
        within_min=query.within_min,
        default_minutes=DEFAULT_BOUNDS.listing_age_minutes,
    )


def _json_bytes(data: bytes, provider: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=provider) from error
    if not isinstance(value, dict):
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="cursor", provider=provider)
    return value


def _chat_hash_dirs(root: str, query: Query) -> list[str]:
    chats = os.path.join(root, "chats")
    if not _regular_directory(chats, root):
        return []
    if query.cwd is not None:
        candidate = os.path.join(chats, _cwd_hash(canonicalize_cwd(query.cwd)))
        return [candidate] if _regular_directory(candidate, root) else []
    try:
        names = sorted(os.listdir(chats))
    except OSError as error:
        raise DiagnosticError.source_busy(provider=CLI_FORMAT) from error
    if len(names) > DEFAULT_BOUNDS.scanned_records:
        raise DiagnosticError.limit_exceeded()
    return [path for name in names if (path := os.path.join(chats, name)) and _regular_directory(path, root)]


def _metadata_paths(root: str, query: Query) -> list[str]:
    output: list[str] = []
    visited = 0
    exact = _exact_uuid_ref(query.ref)
    for hash_dir in _chat_hash_dirs(root, query):
        try:
            names = sorted(os.listdir(hash_dir))
        except OSError as error:
            raise DiagnosticError.source_busy(provider=CLI_FORMAT) from error
        visited += len(names)
        if visited > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        for name in names:
            try:
                uuid.UUID(name)
            except ValueError:
                continue
            if exact is not None and name != exact:
                continue
            session = os.path.join(hash_dir, name)
            if not _regular_directory(session, root):
                continue
            metadata = os.path.join(session, "metadata.json")
            try:
                current = os.lstat(metadata)
            except OSError:
                continue
            if stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode):
                output.append(metadata)
    return output


def _exact_uuid_ref(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _metadata(path: str, root: str, budget: ReadBudget) -> tuple[StableRead, dict[str, Any]]:
    observation = stable_read_bytes(path, root=root, max_bytes=DEFAULT_BOUNDS.request_bytes, budget=budget)
    value = _json_bytes(observation.data, CLI_FORMAT)
    if set(value) != _METADATA_KEYS or value.get("format") != CLI_FORMAT:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="cursor", provider=CLI_FORMAT)
    if not isinstance(value.get("id"), str) or not isinstance(value.get("cwd"), str) or not isinstance(value.get("cwd_hash"), str):
        raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=CLI_FORMAT)
    try:
        identifier = str(uuid.UUID(value["id"]))
        cwd = canonicalize_cwd(value["cwd"])
    except (ValueError, DiagnosticError) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=CLI_FORMAT) from error
    session_dir = os.path.dirname(path)
    actual_hash = os.path.basename(os.path.dirname(session_dir))
    if identifier != os.path.basename(session_dir) or value["cwd_hash"] != _cwd_hash(cwd) or actual_hash != value["cwd_hash"]:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="cursor", provider=CLI_FORMAT)
    if type(value.get("archived")) is not bool or value.get("composer_kind") not in {"project", "subagent"}:
        raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=CLI_FORMAT)
    transcripts = value.get("transcripts")
    if not isinstance(transcripts, list) or any(not isinstance(item, str) for item in transcripts):
        raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=CLI_FORMAT)
    value["id"] = identifier
    value["cwd"] = cwd
    return observation, value


def _safe_relative(session: str, value: str, root: str, *, required_prefix: str) -> str:
    if os.path.isabs(value) or "\x00" in value or any(part == ".." for part in Path(value).parts):
        raise DiagnosticError("E_UNSAFE_PATH", source="cursor", provider=CLI_FORMAT)
    candidate = canonicalize_cwd(os.path.join(session, value))
    expected = canonicalize_cwd(os.path.join(session, required_prefix))
    if not is_within(candidate, expected) or not is_within(candidate, root):
        raise DiagnosticError("E_UNSAFE_PATH", source="cursor", provider=CLI_FORMAT)
    return candidate


def _transcript_paths(metadata_path: str, metadata: Mapping[str, Any], root: str) -> tuple[list[str], tuple[str, ...]]:
    session = os.path.dirname(metadata_path)
    output: list[str] = []
    warnings: list[str] = []
    for link in metadata["transcripts"]:
        candidate = _safe_relative(session, link, root, required_prefix="transcripts")
        try:
            current = os.lstat(candidate)
        except OSError:
            warnings.append("W_STALE_INDEX")
            continue
        if stat.S_ISLNK(current.st_mode):
            raise DiagnosticError("E_UNSAFE_PATH", source="cursor", provider=CLI_FORMAT)
        if not stat.S_ISREG(current.st_mode):
            warnings.append("W_STALE_INDEX")
            continue
        output.append(candidate)
    transcript_dir = os.path.join(session, "transcripts")
    if _regular_directory(transcript_dir, root):
        try:
            names = sorted(os.listdir(transcript_dir))
        except OSError as error:
            raise DiagnosticError.source_busy(provider=CLI_FORMAT) from error
        if len(names) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        discovered: list[str] = []
        for name in names:
            candidate = os.path.join(transcript_dir, name)
            try:
                current = os.lstat(candidate)
            except OSError:
                continue
            if name.endswith(".jsonl") and stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode):
                discovered.append(candidate)
        extras = [path for path in discovered if path not in output]
        if extras:
            warnings.append("W_STALE_INDEX")
            output.extend(extras)
    return output, tuple(dict.fromkeys(warnings))


def _parse_transcript(
    path: str,
    session_dir: str,
    root: str,
    budget: ReadBudget,
) -> tuple[list[dict[str, Any]], tuple[str, ...], str]:
    observation = stable_read_bytes(path, root=root, max_bytes=DEFAULT_BOUNDS.record_bytes, budget=budget)
    warnings: list[str] = []
    output: list[dict[str, Any]] = []
    lines = observation.data.splitlines(keepends=True)
    for index, raw in enumerate(lines):
        budget.consume_records()
        partial = index == len(lines) - 1 and not raw.endswith((b"\n", b"\r"))
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped.decode("utf-8"), object_pairs_hook=_object)
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
            if partial:
                warnings.append("W_PARTIAL_TAIL")
                break
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=CLI_FORMAT) from error
        if not isinstance(value, dict) or value.get("type") not in _TRANSCRIPT_TYPES:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="cursor", provider=CLI_FORMAT)
        if value.get("type") != "message" or value.get("role") not in {"user", "assistant", "tool"}:
            continue
        content = value.get("content")
        if content is None and isinstance(value.get("content_blob"), str):
            blob = _safe_relative(session_dir, value["content_blob"], root, required_prefix="blobs")
            try:
                blob_read = stable_read_bytes(blob, root=root, max_bytes=DEFAULT_BOUNDS.record_bytes, budget=budget)
            except DiagnosticError as error:
                if error.code == "E_UNSAFE_PATH" and not os.path.lexists(blob):
                    warnings.append("W_MISSING_BLOB")
                    continue
                raise
            try:
                content = blob_read.data.decode("utf-8")
            except UnicodeDecodeError:
                warnings.append("W_BINARY_OMITTED")
                continue
        if not isinstance(content, str):
            warnings.append("W_MISSING_BLOB")
            continue
        output.append(
            {
                "role": value["role"],
                "content": content,
                "timestamp": _rfc3339(value.get("timestamp")),
                "tool_name": value.get("tool_name") if isinstance(value.get("tool_name"), str) else None,
            }
        )
    return output, tuple(dict.fromkeys(warnings)), _mtime(observation)


def _cli_summary(path: str, root: str, query: Query, budget: ReadBudget) -> SessionSummary | None:
    metadata_read, metadata = _metadata(path, root, budget)
    identifier = metadata["id"]
    ref_id = _exact_uuid_ref(query.ref)
    if (metadata["archived"] or metadata["composer_kind"] == "subagent") and ref_id != identifier and query.ref != identifier:
        return None
    if query.cwd is not None and not same_cwd(metadata["cwd"], query.cwd):
        return None
    transcript_paths, index_warnings = _transcript_paths(path, metadata, root)
    warnings = list(index_warnings)
    title = metadata["title"] if isinstance(metadata.get("title"), str) else None
    content_updated: str | None = None
    if title is None and transcript_paths:
        records, record_warnings, content_updated = _parse_transcript(
            transcript_paths[0], os.path.dirname(path), root, budget
        )
        warnings.extend(record_warnings)
        title = next((record["content"] for record in records if record["role"] == "user"), None)
    metadata_updated = _rfc3339(metadata.get("updated_at")) or _mtime(metadata_read)
    if content_updated and content_updated > metadata_updated:
        metadata_updated = content_updated
        warnings.append("W_STALE_INDEX")
    if not _within(metadata_updated, query, identifier):
        return None
    return SessionSummary(
        source="cursor",
        session_id=identifier,
        source_path=path,
        title=title,
        cwd=metadata["cwd"],
        branch=metadata["git_branch"] if isinstance(metadata.get("git_branch"), str) else None,
        created_at=_rfc3339(metadata.get("created_at")),
        updated_at=metadata_updated,
        provider=CLI_FORMAT,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _database_paths(root: str) -> list[str]:
    candidates = [os.path.join(root, "state.vscdb"), os.path.join(root, "User", "globalStorage", "state.vscdb")]
    workspaces = os.path.join(root, "User", "workspaceStorage")
    if _regular_directory(workspaces, root):
        try:
            names = sorted(os.listdir(workspaces))
        except OSError as error:
            raise DiagnosticError.source_busy(provider=DESKTOP_FORMAT) from error
        if len(names) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        candidates.extend(os.path.join(workspaces, name, "state.vscdb") for name in names)
    output: list[str] = []
    for candidate in candidates:
        try:
            current = os.lstat(candidate)
        except OSError:
            continue
        if stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode) and is_within(candidate, root):
            output.append(canonicalize_cwd(candidate))
    return output


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, str]:
    try:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return {}
    output: dict[str, str] = {}
    for row in rows:
        if len(row) < 3 or not isinstance(row[1], str) or not isinstance(row[2], str):
            return {}
        output[row[1]] = row[2].upper().split("(", 1)[0]
    return output


def _desktop_signature(connection: sqlite3.Connection) -> bool:
    return (
        _columns(connection, "cursor_composers") == _COMPOSER_COLUMNS
        and _columns(connection, "cursor_transcript_links") == _LINK_COLUMNS
        and _columns(connection, "cursor_blobs") == _BLOB_COLUMNS
    )


def _desktop_summaries(path: str, root: str, query: Query, budget: ReadBudget) -> tuple[bool, list[SessionSummary]]:
    with private_sqlite_connection(path, root=root, provider=DESKTOP_FORMAT) as connection:
        if not _desktop_signature(connection):
            return False, []
        try:
            rows = connection.execute(
                "SELECT id,cwd,cwd_hash,title,created_at,updated_at,archived,composer_kind,git_branch "
                "FROM cursor_composers ORDER BY updated_at DESC,id ASC LIMIT ?",
                (DEFAULT_BOUNDS.scanned_records + 1,),
            ).fetchall()
        except sqlite3.Error as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT) from error
    if len(rows) > DEFAULT_BOUNDS.scanned_records:
        raise DiagnosticError.limit_exceeded()
    values: list[SessionSummary] = []
    exact = _exact_uuid_ref(query.ref)
    for row in rows:
        budget.consume_records()
        if len(row) != 9:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        identifier, cwd_raw, cwd_hash, title, created, updated, archived, kind, branch = row
        if not all(isinstance(value, str) for value in (identifier, cwd_raw, cwd_hash, updated, kind)):
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        if any(value is not None and not isinstance(value, str) for value in (title, created, branch)):
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        text_values = [identifier, cwd_raw, cwd_hash, updated, kind]
        text_values.extend(value for value in (title, created, branch) if isinstance(value, str))
        sizes = [len(value.encode("utf-8")) for value in text_values]
        if (
            len(identifier) > DEFAULT_BOUNDS.ref_chars
            or len(cwd_raw.encode("utf-8")) > 4096
            or len(cwd_hash) != 32
            or (isinstance(title, str) and len(title.encode("utf-8")) > 64 * 1024)
            or (isinstance(branch, str) and len(branch.encode("utf-8")) > 4096)
        ):
            raise DiagnosticError.limit_exceeded()
        budget.consume_bytes(sum(sizes))
        try:
            identifier = str(uuid.UUID(identifier))
            cwd = canonicalize_cwd(cwd_raw)
        except (ValueError, DiagnosticError) as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT) from error
        if exact is not None and identifier != exact:
            continue
        if cwd_hash != _cwd_hash(cwd) or type(archived) is not int or archived not in {0, 1} or kind not in {"project", "subagent"}:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        ref_id = _exact_uuid_ref(query.ref)
        if (archived or kind == "subagent") and ref_id != identifier and query.ref != identifier:
            continue
        if query.cwd is not None and not same_cwd(cwd, query.cwd):
            continue
        updated_at = _rfc3339(updated)
        if updated_at is None:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        if not _within(updated_at, query, identifier):
            continue
        values.append(
            SessionSummary(
                source="cursor",
                session_id=identifier,
                source_path=path,
                title=title if isinstance(title, str) else None,
                cwd=cwd,
                branch=branch if isinstance(branch, str) else None,
                created_at=_rfc3339(created),
                updated_at=updated_at,
                provider=DESKTOP_FORMAT,
            )
        )
    return True, values


def _desktop_session(
    path: str, root: str, identifier: str, budget: ReadBudget, *, max_tool_chars: int
) -> Session:
    with private_sqlite_connection(path, root=root, provider=DESKTOP_FORMAT) as connection:
        if not _desktop_signature(connection):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="cursor", provider=DESKTOP_FORMAT)
        try:
            row = connection.execute(
                "SELECT id,cwd,cwd_hash,title,created_at,updated_at,archived,composer_kind,git_branch "
                "FROM cursor_composers WHERE id=?",
                (identifier,),
            ).fetchone()
            links = connection.execute(
                "SELECT ordinal,blob_key FROM cursor_transcript_links WHERE composer_id=? ORDER BY ordinal ASC,blob_key ASC LIMIT ?",
                (identifier, DEFAULT_BOUNDS.normalized_turns + 1),
            ).fetchall()
            blob_rows = connection.execute(
                "SELECT blob_key,payload_json,length(CAST(payload_json AS BLOB)) FROM cursor_blobs WHERE blob_key IN "
                "(SELECT blob_key FROM cursor_transcript_links WHERE composer_id=?)",
                (identifier,),
            ).fetchall()
        except sqlite3.Error as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT) from error
    if row is None or len(row) != 9:
        raise DiagnosticError("E_NO_MATCH", source="cursor", provider=DESKTOP_FORMAT)
    if len(links) > DEFAULT_BOUNDS.normalized_turns:
        raise DiagnosticError.limit_exceeded()
    blobs: dict[str, str] = {}
    for blob_row in blob_rows:
        if (
            len(blob_row) != 3
            or not isinstance(blob_row[0], str)
            or not isinstance(blob_row[1], str)
            or type(blob_row[2]) is not int
        ):
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        if blob_row[2] > DEFAULT_BOUNDS.record_bytes:
            raise DiagnosticError.limit_exceeded()
        if blob_row[0] in blobs:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        blobs[blob_row[0]] = blob_row[1]
    _, cwd_raw, cwd_hash, title, created, updated, _, _, branch = row
    if not isinstance(cwd_raw, str) or not isinstance(cwd_hash, str):
        raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
    cwd = canonicalize_cwd(cwd_raw)
    if cwd_hash != _cwd_hash(cwd):
        raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
    warnings: list[str] = []
    ordinals: list[int] = []
    turns: list[Turn] = []
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=max_tool_chars)
    for ordinal, blob_key in links:
        budget.consume_records()
        if type(ordinal) is not int or not isinstance(blob_key, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT)
        ordinals.append(ordinal)
        payload = blobs.get(blob_key)
        if payload is None:
            warnings.append("W_MISSING_BLOB")
            continue
        budget.consume_bytes(len(payload.encode("utf-8")))
        try:
            value = json.loads(payload, object_pairs_hook=_object)
        except (json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="cursor", provider=DESKTOP_FORMAT) from error
        if not isinstance(value, dict) or value.get("type") != "message" or value.get("role") not in {"user", "assistant", "tool"}:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="cursor", provider=DESKTOP_FORMAT)
        turn, turn_warnings = sanitize_turn_record(
            {
                "role": value["role"],
                "content": value.get("content"),
                "timestamp": _rfc3339(value.get("timestamp")),
                "tool_name": value.get("tool_name") if isinstance(value.get("tool_name"), str) else None,
            },
            ordinal=len(turns),
            bounds=turn_bounds,
        )
        warnings.extend(turn_warnings)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)
    if ordinals != list(range(len(ordinals))):
        warnings.append("W_STALE_INDEX")
    return Session(
        source="cursor",
        session_id=identifier,
        source_path=path,
        title=title if isinstance(title, str) else None,
        cwd=cwd,
        branch=branch if isinstance(branch, str) else None,
        created_at=_rfc3339(created),
        updated_at=_rfc3339(updated),
        last_user_request=next((turn.content for turn in reversed(turns) if turn.role == "user"), None),
        last_assistant_action=next((turn.content for turn in reversed(turns) if turn.role == "assistant"), None),
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(warnings)),
    )


from .cursor_live import (  # noqa: E402
    _content_to_text,
    _desktop_app_storage_dirs,
    _list_live_cli_stores,
    _list_live_desktop,
    _ms_to_rfc3339,
    _show_live_cli_store,
    _show_live_desktop,
)


class CursorAdapter:
    key = "cursor"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        roots: list[str] = []
        root = _existing_root(query)
        if root:
            roots.append(root)
        if query.source_root is None:
            for storage in _desktop_app_storage_dirs():
                if os.path.isdir(storage):
                    try:
                        roots.append(canonical_root(storage))
                    except DiagnosticError:
                        continue
        return tuple(dict.fromkeys(roots))

    def probe(self, query: Query) -> CapabilityReport:
        try:
            root = _existing_root(query)
            if root is None and not any(os.path.isdir(p) for p in _desktop_app_storage_dirs()):
                return CapabilityReport(self.key, None, "unavailable")
            if root is not None:
                for path in _metadata_paths(root, query):
                    try:
                        _metadata(path, root, ReadBudget())
                        return CapabilityReport(self.key, CLI_FORMAT, "supported", root=root, evidence=(CLI_FORMAT,))
                    except DiagnosticError as error:
                        if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                            return CapabilityReport(self.key, CLI_FORMAT, "unsafe", root=root)
                chats = os.path.join(root, "chats")
                if _regular_directory(chats, root):
                    try:
                        for name in os.listdir(chats)[:20]:
                            bucket = os.path.join(chats, name)
                            if not _regular_directory(bucket, root):
                                continue
                            for child in os.listdir(bucket)[:5]:
                                store = os.path.join(bucket, child, "store.db")
                                if os.path.isfile(store) and not os.path.islink(store):
                                    return CapabilityReport(
                                        self.key,
                                        LIVE_CLI_FORMAT,
                                        "partial",
                                        root=root,
                                        evidence=(LIVE_CLI_FORMAT,),
                                    )
                    except OSError:
                        pass
                for database in _database_paths(root):
                    try:
                        with private_sqlite_connection(database, root=root, provider=DESKTOP_FORMAT) as connection:
                            if _desktop_signature(connection):
                                return CapabilityReport(
                                    self.key, DESKTOP_FORMAT, "supported", root=root, evidence=(DESKTOP_FORMAT,)
                                )
                    except DiagnosticError as error:
                        if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY", "E_SQLITE_HOT_JOURNAL"}:
                            return CapabilityReport(self.key, DESKTOP_FORMAT, "unsafe", root=root)
            # Live desktop only when not pinned to a synthetic source_root fixture.
            if query.source_root is None:
                for storage in _desktop_app_storage_dirs():
                    database = os.path.join(storage, "state.vscdb")
                    if os.path.isfile(database):
                        return CapabilityReport(
                            self.key,
                            LIVE_DESKTOP_FORMAT,
                            "partial",
                            root=canonical_root(storage) if os.path.isdir(storage) else None,
                            evidence=(LIVE_DESKTOP_FORMAT,),
                        )
            return CapabilityReport(
                self.key,
                None,
                "unsupported" if root is not None else "unavailable",
                root=root,
            )
        except DiagnosticError as error:
            state = "unsafe" if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY", "E_SQLITE_HOT_JOURNAL"} else "unsupported"
            return CapabilityReport(self.key, None, state)

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = _existing_root(query)
        values: list[SessionSummary] = []
        if root is not None:
            for path in _metadata_paths(root, query):
                item = _cli_summary(path, root, query, budget)
                if item is not None:
                    values.append(item)
            values.extend(_list_live_cli_stores(root, query))
            if not values:
                for database in _database_paths(root):
                    supported, desktop_values = _desktop_summaries(database, root, query, budget)
                    if supported:
                        values.extend(desktop_values)
                        break
        if query.source_root is None:
            values.extend(_list_live_desktop(query))
        # Dedupe by session id (CLI preferred over desktop).
        dedup: dict[str, SessionSummary] = {}
        for item in values:
            prev = dedup.get(item.session_id)
            if prev is None or (item.provider or "") < (prev.provider or ""):
                dedup[item.session_id] = item
        return sorted(dedup.values(), key=lambda item: (item.updated_at or "", item.session_id), reverse=True)

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = _existing_root(query)
        if ref.provider == LIVE_CLI_FORMAT or (
            ref.source_path and ref.source_path.endswith("store.db")
        ):
            if ref.source_path is None:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=LIVE_CLI_FORMAT)
            show_root = root
            if show_root is None or not is_within(ref.source_path, show_root):
                # store under ~/.cursor only
                show_root = canonical_root(os.path.expanduser("~/.cursor"))
            return _show_live_cli_store(
                ref.source_path, show_root, ref.session_id, budget, max_tool_chars=query.max_tool_chars
            )
        if ref.provider == LIVE_DESKTOP_FORMAT or (
            ref.source_path
            and ref.source_path.endswith("state.vscdb")
            and "Cursor" in ref.source_path
        ):
            if ref.source_path is None:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=LIVE_DESKTOP_FORMAT)
            return _show_live_desktop(
                ref.source_path, ref.session_id, budget, max_tool_chars=query.max_tool_chars
            )
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
        if ref.provider == DESKTOP_FORMAT or (ref.source_path and ref.source_path.endswith(".vscdb")):
            if ref.source_path is None:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=DESKTOP_FORMAT)
            return _desktop_session(
                ref.source_path, root, ref.session_id, budget, max_tool_chars=query.max_tool_chars
            )
        path = ref.source_path
        if path is None:
            matches = []
            for candidate in _metadata_paths(root, query):
                try:
                    _, metadata = _metadata(candidate, root, budget)
                except DiagnosticError:
                    continue
                if metadata["id"] == ref.session_id:
                    matches.append(candidate)
            if len(matches) != 1:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=CLI_FORMAT)
            path = matches[0]
        metadata_read, metadata = _metadata(path, root, budget)
        if metadata["id"] != ref.session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=CLI_FORMAT)
        transcript_paths, index_warnings = _transcript_paths(path, metadata, root)
        all_warnings = list(index_warnings)
        turns: list[Turn] = []
        turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        updated = _rfc3339(metadata.get("updated_at")) or _mtime(metadata_read)
        for transcript in transcript_paths:
            records, warnings, transcript_updated = _parse_transcript(
                transcript, os.path.dirname(path), root, budget
            )
            all_warnings.extend(warnings)
            if transcript_updated > updated:
                updated = transcript_updated
                all_warnings.append("W_STALE_INDEX")
            for raw in records:
                turn, turn_warnings = sanitize_turn_record(raw, ordinal=len(turns), bounds=turn_bounds)
                all_warnings.extend(turn_warnings)
                if turn is not None:
                    budget.consume_turns()
                    turns.append(turn)
        return Session(
            source=self.key,
            session_id=ref.session_id,
            source_path=path,
            title=metadata["title"] if isinstance(metadata.get("title"), str) else next(
                (turn.content for turn in turns if turn.role == "user"), None
            ),
            cwd=metadata["cwd"],
            branch=metadata["git_branch"] if isinstance(metadata.get("git_branch"), str) else None,
            created_at=_rfc3339(metadata.get("created_at")),
            updated_at=updated,
            last_user_request=next((turn.content for turn in reversed(turns) if turn.role == "user"), None),
            last_assistant_action=next((turn.content for turn in reversed(turns) if turn.role == "assistant"), None),
            turns=tuple(turns),
            warnings=tuple(dict.fromkeys(all_warnings)),
        )


ADAPTER = CursorAdapter()
