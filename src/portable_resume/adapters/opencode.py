"""Read supported OpenCode stores without invoking OpenCode or opening a live DB.

The provider signatures in this module are deliberately structural and closed:

* ``opencode-sqlite-v1`` requires the ``session``/``message``/``part``
  relations and their documented join columns.
* ``opencode-file-store-v1`` requires the legacy
  ``storage/{session,message,part}`` tree and explicit ID fields.
* an explicit OpenCode export is accepted only when it has the closed
  ``info`` plus ``messages[].{info,parts}`` shape.  It is still reported as a
  file-store capability; the provider string distinguishes it.

Unknown schemas are never guessed.  SQLite is queried only after the common
snapshot primitive has copied a stable main/WAL family to private storage.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .base import CapabilityReport, ResolvedRef
from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import private_sqlite_connection, query_only_live_sqlite, stable_read_bytes

SQLITE_FORMAT = "opencode-sqlite-v1"
FILE_FORMAT = "opencode-file-store-v1"
EXPORT_PROVIDER = "opencode-export-file-v1"

_DATABASE_NAMES = ("opencode.db", "opencode.sqlite")
_REQUIRED_COLUMNS: dict[str, dict[str, str]] = {
    "session": {
        "id": "TEXT",
        "directory": "TEXT",
        "title": "TEXT",
        "time_created": "INTEGER",
        "time_updated": "INTEGER",
    },
    "message": {
        "id": "TEXT",
        "session_id": "TEXT",
        "time_created": "INTEGER",
        "data": "TEXT",
    },
    "part": {
        "id": "TEXT",
        "message_id": "TEXT",
        "session_id": "TEXT",
        "time_created": "INTEGER",
        "data": "TEXT",
    },
}
_CONTROL_PARTS = frozenset(
    {
        "reasoning",
        "thinking",
        "step-start",
        "step-finish",
        "snapshot",
        "patch",
        "control",
        "system",
    }
)
_BINARY_PARTS = frozenset({"file", "image", "audio", "video", "attachment"})


class _DuplicateKey(ValueError):
    pass


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = item
    return value


def _json_value(data: bytes, *, unsupported: bool = False) -> Any:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_closed_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
        code = "E_UNSUPPORTED_FORMAT" if unsupported else "E_CORRUPT_RECORD"
        raise DiagnosticError(code, source="opencode") from error
    _check_depth(value)
    return value


def _json_text(value: object, *, unsupported: bool = False) -> Mapping[str, Any]:
    if not isinstance(value, str):
        raise DiagnosticError("E_UNSUPPORTED_FORMAT" if unsupported else "E_CORRUPT_RECORD", source="opencode")
    parsed = _json_value(value.encode("utf-8"), unsupported=unsupported)
    if not isinstance(parsed, Mapping):
        raise DiagnosticError("E_UNSUPPORTED_FORMAT" if unsupported else "E_CORRUPT_RECORD", source="opencode")
    return parsed


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise DiagnosticError.limit_exceeded()
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise DiagnosticError.limit_exceeded()
        for item in value.values():
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        for item in value:
            _check_depth(item, depth + 1)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > DEFAULT_BOUNDS.ref_chars:
        raise DiagnosticError("E_CORRUPT_RECORD", source="opencode")
    if value in {".", ".."} or any(ord(char) < 0x20 for char in value):
        raise DiagnosticError("E_CORRUPT_RECORD", source="opencode")
    return value


def _timestamp(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if abs(seconds) >= 100_000_000_000:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    return None


def _time_container(value: object, field: str) -> str | None:
    return _timestamp(value.get(field)) if isinstance(value, Mapping) else None


def _within_window(updated_at: str | None, minutes: int) -> bool:
    if minutes is not None and minutes <= 0:
        return True
    if updated_at is None:
        return False
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed >= datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _eligible(summary: SessionSummary, query: Query) -> bool:
    if query.cwd is not None and (summary.cwd is None or not same_cwd(summary.cwd, query.cwd)):
        return False
    ref = query.ref.strip() if query.ref else None
    if ref == summary.session_id:
        return True
    if ref and os.path.isabs(ref) and summary.source_path is not None:
        if canonicalize_cwd(ref) == canonicalize_cwd(summary.source_path):
            return True
    minutes = query.within_min if query.within_min is not None else DEFAULT_BOUNDS.listing_age_minutes
    return _within_window(summary.updated_at, minutes)


def _regular_json_files(base: str, root: str) -> list[str]:
    """Return a bounded, no-symlink set of JSON files below ``base``."""

    if not os.path.isdir(base) or not is_within(base, root):
        return []
    pending = [base]
    files: list[str] = []
    observed = 0
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise DiagnosticError.source_busy(provider=FILE_FORMAT) from error
        for entry in entries:
            observed += 1
            if observed > DEFAULT_BOUNDS.scanned_records:
                raise DiagnosticError.limit_exceeded()
            if entry.is_symlink():
                raise DiagnosticError.unsafe_path()
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as error:
                raise DiagnosticError.source_busy(provider=FILE_FORMAT) from error
            if stat.S_ISDIR(mode):
                pending.append(entry.path)
            elif stat.S_ISREG(mode) and entry.name.endswith(".json"):
                files.append(entry.path)
            elif not stat.S_ISREG(mode):
                raise DiagnosticError.unsafe_path()
    return sorted(files)


class OpenCodeAdapter:
    key = "opencode"

    def __init__(self, *, root: str | None = None, read_hook: Any = None, sqlite_hook: Any = None):
        self._configured_root = root
        self._read_hook = read_hook
        self._sqlite_hook = sqlite_hook

    def _root(self, query: Query, *, required: bool = False) -> str | None:
        if query.source_root is not None:
            candidate = query.source_root
        elif self._configured_root is not None:
            candidate = self._configured_root
        else:
            data_home = os.environ.get("XDG_DATA_HOME")
            candidate = os.path.join(data_home, "opencode") if data_home else os.path.expanduser("~/.local/share/opencode")
        if not os.path.isdir(candidate):
            if required:
                raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
            return None
        return canonical_root(candidate)

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = self._root(query)
        return (root,) if root is not None else ()

    def _database_paths(self, root: str) -> list[str]:
        return [os.path.join(root, name) for name in _DATABASE_NAMES if os.path.isfile(os.path.join(root, name))]

    def _file_store(self, root: str) -> str | None:
        storage = os.path.join(root, "storage")
        required = tuple(os.path.join(storage, name) for name in ("session", "message", "part"))
        if all(os.path.isdir(path) and not os.path.islink(path) for path in required):
            return storage
        return None

    def _explicit_exports(self, root: str, query: Query) -> list[str]:
        values: list[str] = []
        if query.ref and os.path.isabs(query.ref) and query.ref.endswith(".json"):
            if not is_within(query.ref, root):
                raise DiagnosticError.unsafe_path()
            if os.path.isfile(query.ref):
                values.append(canonicalize_cwd(query.ref))
        export_root = os.path.join(root, "exports")
        if os.path.isdir(export_root) and not os.path.islink(export_root):
            values.extend(_regular_json_files(export_root, root))
        return list(dict.fromkeys(values))

    def _sqlite_supported(self, database: str, root: str) -> bool:
        try:
            size = os.path.getsize(database)
        except OSError:
            return False
        try:
            if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes:
                with query_only_live_sqlite(database, root=root, provider=SQLITE_FORMAT) as connection:
                    self._require_schema(connection)
            else:
                with private_sqlite_connection(
                    database,
                    root=root,
                    hook=self._sqlite_hook,
                    provider=SQLITE_FORMAT,
                ) as connection:
                    self._require_schema(connection)
            return True
        except sqlite3.DatabaseError:
            return False
        except DiagnosticError as error:
            if error.code in {"E_UNSUPPORTED_FORMAT", "E_LIMIT_EXCEEDED"}:
                return False
            raise

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        try:
            integrity = connection.execute("PRAGMA integrity_check(1)").fetchone()
            if integrity != ("ok",):
                raise DiagnosticError("E_CORRUPT_RECORD", source="opencode", provider=SQLITE_FORMAT)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('session','message','part')"
                )
            }
            if tables != set(_REQUIRED_COLUMNS):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="opencode", provider=SQLITE_FORMAT)
            for table, required in _REQUIRED_COLUMNS.items():
                columns = {
                    str(row[1]): str(row[2]).upper().split("(", 1)[0]
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                }
                if any(columns.get(name) != affinity for name, affinity in required.items()):
                    raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="opencode", provider=SQLITE_FORMAT)
        except sqlite3.DatabaseError as error:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="opencode", provider=SQLITE_FORMAT) from error

    def probe(self, query: Query) -> CapabilityReport:
        root = self._root(query)
        if root is None:
            return CapabilityReport(self.key, None, "unavailable")
        evidence: list[str] = []
        unsupported = False
        sqlite_ok = False
        for database in self._database_paths(root):
            if self._sqlite_supported(database, root):
                sqlite_ok = True
                evidence.append(f"sqlite:{os.path.basename(database)}")
            else:
                unsupported = True
        file_ok = self._file_store(root) is not None
        if file_ok:
            evidence.append("file-store:storage")
        export_ok = False
        export_budget = ReadBudget()
        for path in self._explicit_exports(root, query):
            try:
                self._read_export(path, root, budget=export_budget)
                export_ok = True
                evidence.append("export:explicit-json")
            except DiagnosticError as error:
                if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
                    unsupported = True
                else:
                    raise
        if not (sqlite_ok or file_ok or export_ok):
            return CapabilityReport(self.key, SQLITE_FORMAT if self._database_paths(root) else None, "unsupported", root=root)
        format_id = SQLITE_FORMAT if sqlite_ok else FILE_FORMAT
        state = "partial" if unsupported else "supported"
        return CapabilityReport(self.key, format_id, state, root=root, evidence=tuple(evidence))

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = self._root(query, required=True)
        assert root is not None
        output: list[SessionSummary] = []
        databases = self._database_paths(root)
        supported_database = False
        for database in databases:
            try:
                summaries = self._list_sqlite(database, root, budget, query=query)
                supported_database = True
                output.extend(item for item in summaries if _eligible(item, query))
            except DiagnosticError as error:
                if error.code != "E_UNSUPPORTED_FORMAT":
                    raise
        storage = self._file_store(root)
        if storage is not None:
            output.extend(item for item in self._list_file_store(storage, root, budget) if _eligible(item, query))
        for export in self._explicit_exports(root, query):
            summary, _ = self._read_export(export, root, budget=budget)
            if _eligible(summary, query):
                output.append(summary)
        if not output and databases and not supported_database and storage is None:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=SQLITE_FORMAT)
        if not (databases or storage is not None or self._explicit_exports(root, query)):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key)
        return output

    def _list_sqlite(
        self, database: str, root: str, budget: ReadBudget, *, query: Query | None = None
    ) -> list[SessionSummary]:
        def _fetch(connection: sqlite3.Connection) -> list[tuple]:
            self._require_schema(connection)
            # Prefer cwd-scoped list (Codex-style) so large live DBs stay bounded.
            limit = DEFAULT_BOUNDS.listed_sessions
            if query is not None and query.cwd:
                rows = connection.execute(
                    'SELECT id,directory,title,time_created,time_updated FROM "session" '
                    "WHERE directory = ? ORDER BY time_updated DESC,id ASC LIMIT ?",
                    (query.cwd, limit),
                ).fetchall()
                if not rows:
                    rows = connection.execute(
                        'SELECT id,directory,title,time_created,time_updated FROM "session" '
                        "ORDER BY time_updated DESC,id ASC LIMIT ?",
                        (DEFAULT_BOUNDS.scanned_records,),
                    ).fetchall()
                return rows
            return connection.execute(
                'SELECT id,directory,title,time_created,time_updated FROM "session" '
                "ORDER BY time_updated DESC,id ASC LIMIT ?",
                (limit,),
            ).fetchall()

        try:
            size = os.path.getsize(database)
        except OSError as error:
            raise DiagnosticError("E_SOURCE_BUSY", source=self.key, provider=SQLITE_FORMAT) from error
        try:
            if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes:
                # Avoid multi-GiB private copies for list; readonly live query.
                with query_only_live_sqlite(database, root=root, provider=SQLITE_FORMAT) as connection:
                    rows = _fetch(connection)
            else:
                with private_sqlite_connection(
                    database,
                    root=root,
                    hook=self._sqlite_hook,
                    provider=SQLITE_FORMAT,
                ) as connection:
                    rows = _fetch(connection)
        except sqlite3.DatabaseError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=SQLITE_FORMAT) from error
        # Do not hard-fail when the DB has more sessions than LIMIT (live homes).
        budget.consume_records(len(rows))
        output: list[SessionSummary] = []
        seen: set[str] = set()
        for row in rows:
            session_id = _identifier(row[0])
            if session_id in seen:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=SQLITE_FORMAT)
            seen.add(session_id)
            if not isinstance(row[1], str):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=SQLITE_FORMAT)
            try:
                cwd = canonicalize_cwd(row[1])
            except DiagnosticError:
                continue
            output.append(
                SessionSummary(
                    source=self.key,
                    session_id=session_id,
                    source_path=database,
                    title=row[2] if isinstance(row[2], str) else None,
                    cwd=cwd,
                    created_at=_timestamp(row[3]),
                    updated_at=_timestamp(row[4]),
                    provider=SQLITE_FORMAT,
                )
            )
        return output

    def _read_json_file(self, path: str, root: str, budget: ReadBudget | None) -> Mapping[str, Any]:
        read = stable_read_bytes(
            path,
            root=root,
            max_bytes=DEFAULT_BOUNDS.record_bytes,
            budget=budget,
            hook=self._read_hook,
        )
        value = _json_value(read.data)
        if not isinstance(value, Mapping):
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key)
        return value

    def _list_file_store(self, storage: str, root: str, budget: ReadBudget) -> list[SessionSummary]:
        output: list[SessionSummary] = []
        seen: set[str] = set()
        for path in _regular_json_files(os.path.join(storage, "session"), root):
            value = self._read_json_file(path, root, budget)
            summary = self._file_summary(path, value)
            if summary.session_id in seen:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FILE_FORMAT)
            seen.add(summary.session_id)
            output.append(summary)
        return output

    def _file_summary(self, path: str, value: Mapping[str, Any]) -> SessionSummary:
        session_id = _identifier(value.get("id"))
        directory = value.get("directory")
        times = value.get("time")
        if not isinstance(directory, str) or not isinstance(times, Mapping):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FILE_FORMAT)
        return SessionSummary(
            source=self.key,
            session_id=session_id,
            source_path=path,
            title=value.get("title") if isinstance(value.get("title"), str) else None,
            cwd=canonicalize_cwd(directory),
            created_at=_time_container(times, "created"),
            updated_at=_time_container(times, "updated"),
            provider=FILE_FORMAT,
        )

    @staticmethod
    def _export_shape(value: Mapping[str, Any]) -> tuple[Mapping[str, Any], list[Any]]:
        info = value.get("info")
        messages = value.get("messages")
        if not isinstance(info, Mapping) or not isinstance(messages, list):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="opencode", provider=EXPORT_PROVIDER)
        if not all(isinstance(item, Mapping) and isinstance(item.get("info"), Mapping) and isinstance(item.get("parts"), list) for item in messages):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="opencode", provider=EXPORT_PROVIDER)
        return info, messages

    def _read_export(
        self, path: str, root: str, *, budget: ReadBudget | None
    ) -> tuple[SessionSummary, tuple[Mapping[str, Any], list[Any]]]:
        value = self._read_json_file(path, root, budget)
        info, messages = self._export_shape(value)
        session_id = _identifier(info.get("id"))
        directory = info.get("directory")
        times = info.get("time")
        if not isinstance(directory, str) or not isinstance(times, Mapping):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=EXPORT_PROVIDER)
        summary = SessionSummary(
            source=self.key,
            session_id=session_id,
            source_path=path,
            title=info.get("title") if isinstance(info.get("title"), str) else None,
            cwd=canonicalize_cwd(directory),
            created_at=_time_container(times, "created"),
            updated_at=_time_container(times, "updated"),
            provider=EXPORT_PROVIDER,
        )
        return summary, (info, messages)

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = self._root(query, required=True)
        assert root is not None
        provider = ref.provider
        if provider == SQLITE_FORMAT:
            return self._show_sqlite(ref, query, root, budget)
        if provider == FILE_FORMAT:
            return self._show_file_store(ref, query, root, budget)
        if provider == EXPORT_PROVIDER:
            return self._show_export(ref, query, root, budget)
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=provider)

    def _show_sqlite(self, ref: ResolvedRef, query: Query, root: str, budget: ReadBudget) -> Session:
        if ref.source_path is None or not is_within(ref.source_path, root):
            raise DiagnosticError.unsafe_path()
        try:
            size = os.path.getsize(ref.source_path)
        except OSError as error:
            raise DiagnosticError("E_SOURCE_BUSY", source=self.key, provider=SQLITE_FORMAT) from error
        try:
            ctx = (
                query_only_live_sqlite(ref.source_path, root=root, provider=SQLITE_FORMAT)
                if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes
                else private_sqlite_connection(
                    ref.source_path,
                    root=root,
                    hook=self._sqlite_hook,
                    provider=SQLITE_FORMAT,
                )
            )
            with ctx as connection:
                self._require_schema(connection)
                summary_row = connection.execute(
                    'SELECT id,directory,title,time_created,time_updated FROM "session" WHERE id=?',
                    (ref.session_id,),
                ).fetchone()
                if summary_row is None:
                    raise DiagnosticError("E_NO_MATCH", source=self.key)
                rows = connection.execute(
                    'SELECT m.id,m.time_created,m.data,p.id,p.time_created,p.data '
                    'FROM "message" AS m LEFT JOIN "part" AS p '
                    "ON p.message_id=m.id AND p.session_id=m.session_id "
                    "WHERE m.session_id=? "
                    "ORDER BY m.time_created ASC,m.id ASC,p.time_created ASC,p.id ASC LIMIT ?",
                    (ref.session_id, DEFAULT_BOUNDS.scanned_records + 1),
                ).fetchall()
                orphan_count = connection.execute(
                    'SELECT COUNT(*) FROM "part" AS p LEFT JOIN "message" AS m '
                    "ON m.id=p.message_id AND m.session_id=p.session_id "
                    "WHERE p.session_id=? AND m.id IS NULL",
                    (ref.session_id,),
                ).fetchone()
        except sqlite3.DatabaseError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=SQLITE_FORMAT) from error
        if len(rows) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        budget.consume_records(len(rows))
        warnings: list[str] = []
        if orphan_count and int(orphan_count[0]) > 0:
            warnings.append("W_BROKEN_CHAIN")
        turns = self._turns_from_sql_rows(rows, query, budget, warnings)
        summary = SessionSummary(
            source=self.key,
            session_id=_identifier(summary_row[0]),
            source_path=ref.source_path,
            title=summary_row[2] if isinstance(summary_row[2], str) else None,
            cwd=canonicalize_cwd(summary_row[1]),
            created_at=_timestamp(summary_row[3]),
            updated_at=_timestamp(summary_row[4]),
            provider=SQLITE_FORMAT,
            warnings=tuple(dict.fromkeys(warnings)),
        )
        return _session_from(summary, turns, warnings)

    def _turns_from_sql_rows(
        self, rows: Iterable[tuple[Any, ...]], query: Query, budget: ReadBudget, warnings: list[str]
    ) -> list[Turn]:
        turns: list[Turn] = []
        seen_message: str | None = None
        message_values: dict[str, tuple[object, object]] = {}
        empty_messages: set[str] = set()
        seen_parts: set[str] = set()
        role = ""
        for message_id, message_time, message_data, part_id, part_time, part_data in rows:
            current = _identifier(message_id)
            fingerprint = (message_time, message_data)
            if current in message_values and message_values[current] != fingerprint:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=SQLITE_FORMAT)
            message_values[current] = fingerprint
            if current != seen_message:
                seen_message = current
                info = _json_text(message_data)
                role_value = info.get("role")
                if not isinstance(role_value, str):
                    raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=SQLITE_FORMAT)
                role = role_value.casefold()
            if part_id is None:
                if current in empty_messages:
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=SQLITE_FORMAT)
                empty_messages.add(current)
                warnings.append("W_MISSING_BLOB")
                continue
            current_part = _identifier(part_id)
            if current_part in seen_parts:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=SQLITE_FORMAT)
            seen_parts.add(current_part)
            part = _json_text(part_data)
            self._append_part(turns, part, role, _timestamp(part_time if part_time is not None else message_time), query, budget, warnings)
        return turns

    def _show_file_store(self, ref: ResolvedRef, query: Query, root: str, budget: ReadBudget) -> Session:
        storage = self._file_store(root)
        if storage is None or ref.source_path is None:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FILE_FORMAT)
        session_root = os.path.join(storage, "session")
        if not is_within(ref.source_path, session_root):
            raise DiagnosticError.unsafe_path()
        summary_value = self._read_json_file(ref.source_path, root, budget)
        summary = self._file_summary(ref.source_path, summary_value)
        if summary.session_id != ref.session_id:
            raise DiagnosticError("E_NO_MATCH", source=self.key)
        messages: dict[str, tuple[Mapping[str, Any], str]] = {}
        for path in _regular_json_files(os.path.join(storage, "message"), root):
            value = self._read_json_file(path, root, budget)
            if value.get("sessionID") != ref.session_id:
                continue
            message_id = _identifier(value.get("id"))
            role = value.get("role")
            if not isinstance(role, str):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FILE_FORMAT)
            if message_id in messages:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FILE_FORMAT)
            messages[message_id] = (value, path)
        parts: dict[str, list[Mapping[str, Any]]] = {message_id: [] for message_id in messages}
        warnings: list[str] = []
        seen_parts: set[str] = set()
        for path in _regular_json_files(os.path.join(storage, "part"), root):
            value = self._read_json_file(path, root, budget)
            if value.get("sessionID") != ref.session_id:
                continue
            message_id = _identifier(value.get("messageID"))
            part_id = _identifier(value.get("id"))
            if part_id in seen_parts:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FILE_FORMAT)
            seen_parts.add(part_id)
            if message_id not in parts:
                warnings.append("W_BROKEN_CHAIN")
                continue
            parts[message_id].append(value)
        turns: list[Turn] = []
        ordered_messages = sorted(
            messages.items(),
            key=lambda item: (_numeric_sort(_mapping_get(item[1][0], "time", "created")), item[0]),
        )
        for message_id, (message, _) in ordered_messages:
            role = str(message["role"]).casefold()
            ordered_parts = sorted(
                parts[message_id],
                key=lambda item: (_numeric_sort(_mapping_get(item, "time", "created")), str(item.get("id", ""))),
            )
            if not ordered_parts:
                warnings.append("W_MISSING_BLOB")
            for part in ordered_parts:
                self._append_part(
                    turns,
                    part,
                    role,
                    _time_container(part.get("time"), "created") or _time_container(message.get("time"), "created"),
                    query,
                    budget,
                    warnings,
                )
        return _session_from(summary, turns, warnings)

    def _show_export(self, ref: ResolvedRef, query: Query, root: str, budget: ReadBudget) -> Session:
        if ref.source_path is None:
            raise DiagnosticError.unsafe_path()
        summary, (_, messages) = self._read_export(ref.source_path, root, budget=budget)
        if summary.session_id != ref.session_id:
            raise DiagnosticError("E_NO_MATCH", source=self.key)
        turns: list[Turn] = []
        warnings: list[str] = []
        seen_messages: set[str] = set()
        seen_parts: set[str] = set()
        ordered = sorted(
            messages,
            key=lambda item: (
                _numeric_sort(_mapping_get(item["info"], "time", "created")),
                str(item["info"].get("id", "")),
            ),
        )
        for message in ordered:
            info = message["info"]
            if info.get("sessionID", ref.session_id) != ref.session_id:
                warnings.append("W_BROKEN_CHAIN")
                continue
            message_id = _identifier(info.get("id"))
            if message_id in seen_messages:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=EXPORT_PROVIDER)
            seen_messages.add(message_id)
            role = info.get("role")
            if not isinstance(role, str):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=EXPORT_PROVIDER)
            parts = sorted(
                message["parts"],
                key=lambda item: (_numeric_sort(_mapping_get(item, "time", "created")), str(item.get("id", ""))),
            )
            for part in parts:
                if not isinstance(part, Mapping):
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=EXPORT_PROVIDER)
                part_id = _identifier(part.get("id"))
                if part_id in seen_parts:
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=EXPORT_PROVIDER)
                seen_parts.add(part_id)
                self._append_part(
                    turns,
                    part,
                    role.casefold(),
                    _time_container(part.get("time"), "created") or _time_container(info.get("time"), "created"),
                    query,
                    budget,
                    warnings,
                )
        return _session_from(summary, turns, warnings)

    def _append_part(
        self,
        turns: list[Turn],
        part: Mapping[str, Any],
        message_role: str,
        timestamp: str | None,
        query: Query,
        budget: ReadBudget,
        warnings: list[str],
    ) -> None:
        kind = part.get("type")
        if not isinstance(kind, str):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key)
        kind = kind.casefold()
        if kind in _CONTROL_PARTS or message_role in {"system", "reasoning", "control"}:
            return
        if kind in _BINARY_PARTS:
            warnings.append("W_BINARY_OMITTED")
            return
        record: dict[str, Any]
        if kind == "text":
            text = part.get("text")
            if not isinstance(text, str) or message_role not in {"user", "assistant"}:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key)
            record = {"role": message_role, "content": text, "timestamp": timestamp}
        elif kind in {"tool", "tool-result", "tool_result"}:
            tool_name = part.get("tool") or part.get("name")
            content: object = part.get("content")
            state = part.get("state")
            if content is None and isinstance(state, Mapping):
                content = state.get("output")
            if not isinstance(content, str):
                if content is None:
                    warnings.append("W_MISSING_BLOB")
                    return
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key)
            record = {
                "role": "tool",
                "content": content,
                "timestamp": timestamp,
                "tool_name": tool_name if isinstance(tool_name, str) else None,
            }
        else:
            # Unknown content-bearing parts could hide a user/assistant turn.
            if any(key in part for key in ("text", "content", "output")):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key)
            warnings.append("W_BROKEN_CHAIN")
            return
        bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        turn, turn_warnings = sanitize_turn_record(record, ordinal=len(turns), bounds=bounds)
        warnings.extend(turn_warnings)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)


def _mapping_get(value: object, container: str, key: str) -> object:
    nested = value.get(container) if isinstance(value, Mapping) else None
    return nested.get(key) if isinstance(nested, Mapping) else None


def _numeric_sort(value: object) -> tuple[int, str]:
    if isinstance(value, bool):
        return (1, "")
    if isinstance(value, (int, float)):
        return (0, f"{float(value):030.6f}")
    if isinstance(value, str):
        return (0, value)
    return (1, "")


def _session_from(summary: SessionSummary, turns: Iterable[Turn], warnings: Iterable[str]) -> Session:
    values = tuple(turns)
    last_user = next((turn.content for turn in reversed(values) if turn.role == "user"), None)
    last_assistant = next((turn.content for turn in reversed(values) if turn.role == "assistant"), None)
    return Session(
        source=summary.source,
        session_id=summary.session_id,
        source_path=summary.source_path,
        title=summary.title,
        cwd=summary.cwd,
        branch=summary.branch,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        source_repo_root=summary.source_repo_root,
        last_user_request=last_user,
        last_assistant_action=last_assistant,
        turns=values,
        warnings=tuple(dict.fromkeys((*summary.warnings, *warnings))),
    )


ADAPTER = OpenCodeAdapter()


def get_adapter() -> OpenCodeAdapter:
    return ADAPTER
