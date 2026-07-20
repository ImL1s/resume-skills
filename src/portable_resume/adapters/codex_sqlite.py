"""Codex state SQLite list/probe helpers (extracted from codex adapter)."""

from __future__ import annotations

import os
import sqlite3
import stat
import uuid
from pathlib import Path
from typing import Any

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, SessionSummary
from ..paths import canonicalize_cwd, is_within, same_cwd
from ..snapshot import private_sqlite_connection, query_only_live_sqlite

from . import codex as _codex

SQLITE_FORMAT = _codex.SQLITE_FORMAT
_exact_uuid_ref = _codex._exact_uuid_ref
_within = _codex._within
_numeric_time = _codex._numeric_time
_trusted_zstd = _codex._trusted_zstd
_rollout_id = _codex._rollout_id


def _table_signature(connection: sqlite3.Connection) -> tuple[bool, str | None]:
    """Accept pinned column *supersets* (live Codex adds optional columns).

    Required: id, rollout_path, source, cwd, archived, plus one of updated_at_ms
    / updated_at. Optional title/first_user_message/git_branch may be absent
    (SQL SELECT still names them — missing optional columns fail later; require
    the optional trio when present or use COALESCE-compatible fixed SELECT).
    """
    try:
        rows = connection.execute("PRAGMA table_info(threads)").fetchall()
    except sqlite3.Error:
        return False, None
    columns: dict[str, str] = {}
    for row in rows:
        if len(row) < 3 or not isinstance(row[1], str) or not isinstance(row[2], str):
            return False, None
        columns[row[1]] = row[2].upper().split("(", 1)[0]
    required = {"id", "rollout_path", "source", "cwd", "archived"}
    if not required.issubset(columns):
        return False, None
    # Prefer millisecond column when both exist (live state_5 has both).
    if "updated_at_ms" in columns and columns["updated_at_ms"] in {"INTEGER", "INT", "BIGINT", "NUM", "NUMERIC"}:
        updated = "updated_at_ms"
    elif "updated_at" in columns and columns["updated_at"] in {"INTEGER", "INT", "BIGINT", "NUM", "NUMERIC"}:
        updated = "updated_at"
    else:
        return False, None
    for name in ("id", "rollout_path", "source", "cwd"):
        if columns.get(name) not in {"TEXT", "VARCHAR", "CHAR", "NVARCHAR", "CLOB"}:
            # SQLite type affinity is loose; allow empty declared types.
            if columns.get(name) not in {"", "ANY"}:
                # Still accept common live TEXT-ish declarations only when present.
                if not str(columns.get(name, "")).startswith("TEXT"):
                    pass  # do not hard-fail on affinity; Grok only checks presence
    return True, updated


def _resolve_rollout_path(root: str, raw: str, identifier: str) -> str | None:
    if "\x00" in raw or any(part == ".." for part in Path(raw).parts):
        return None
    candidate = raw if os.path.isabs(raw) else os.path.join(root, raw)
    canonical = canonicalize_cwd(candidate)
    prefixes = [
        canonicalize_cwd(os.path.join(root, name))
        for name in ("sessions", "archived_sessions")
        if os.path.isdir(os.path.join(root, name))
    ]
    if not any(is_within(canonical, prefix) for prefix in prefixes):
        return None
    try:
        current = os.lstat(canonical)
    except OSError:
        return None
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
        return None
    if _rollout_id(canonical) != identifier:
        alternate = canonical + ".zst"
        try:
            current = os.lstat(alternate)
        except OSError:
            return None
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode) or _rollout_id(alternate) != identifier:
            return None
        canonical = alternate
    return canonical


def _database_summaries(path: str, root: str, query: Query, budget: ReadBudget) -> tuple[bool, list[SessionSummary]]:
    def _fetch_rows(connection: sqlite3.Connection) -> tuple[bool, str | None, list[tuple]]:
        supported, updated_column = _table_signature(connection)
        if not supported or updated_column is None:
            return False, None, []
        try:
            info = connection.execute("PRAGMA table_info(threads)").fetchall()
            present = {row[1] for row in info if isinstance(row[1], str)}
            title_expr = "title" if "title" in present else "NULL"
            first_expr = "first_user_message" if "first_user_message" in present else "NULL"
            branch_expr = "git_branch" if "git_branch" in present else "NULL"
            select = (
                f"SELECT id, rollout_path, {updated_column}, source, cwd, "
                f"{title_expr}, {first_expr}, archived, {branch_expr} "
                "FROM threads"
            )
            params: list[Any] = []
            clauses: list[str] = []
            exact = _exact_uuid_ref(query.ref)
            if exact is not None:
                clauses.append("id = ?")
                params.append(exact)
            elif query.cwd:
                clauses.append("cwd = ?")
                params.append(query.cwd)
            if clauses:
                select += " WHERE " + " AND ".join(clauses)
            select += f" ORDER BY {updated_column} DESC, id ASC LIMIT ?"
            params.append(DEFAULT_BOUNDS.listed_sessions)
            rows = connection.execute(select, tuple(params)).fetchall()
            if not rows and query.cwd and exact is None:
                rows = connection.execute(
                    f"SELECT id, rollout_path, {updated_column}, source, cwd, "
                    f"{title_expr}, {first_expr}, archived, {branch_expr} "
                    f"FROM threads ORDER BY {updated_column} DESC, id ASC LIMIT ?",
                    (DEFAULT_BOUNDS.scanned_records,),
                ).fetchall()
        except sqlite3.Error as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=SQLITE_FORMAT) from error
        return True, updated_column, rows

    try:
        size = os.path.getsize(path)
    except OSError as error:
        raise DiagnosticError("E_SOURCE_BUSY", source="codex", provider=SQLITE_FORMAT) from error
    if size > DEFAULT_BOUNDS.sqlite_snapshot_bytes:
        with query_only_live_sqlite(path, root=root, provider=SQLITE_FORMAT) as connection:
            supported, _updated_column, rows = _fetch_rows(connection)
    else:
        with private_sqlite_connection(path, root=root, provider=SQLITE_FORMAT) as connection:
            supported, _updated_column, rows = _fetch_rows(connection)
    if not supported:
        return False, []

    values: list[SessionSummary] = []
    exact = _exact_uuid_ref(query.ref)
    for row in rows:
        budget.consume_records()
        if len(row) != 9:
            raise DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=SQLITE_FORMAT)
        identifier, rollout_raw, updated_raw, source, cwd_raw, title, first_user, archived, branch = row
        if not all(isinstance(value, str) for value in (identifier, rollout_raw, source, cwd_raw)):
            raise DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=SQLITE_FORMAT)
        optional_text = (title, first_user, branch)
        if any(value is not None and not isinstance(value, str) for value in optional_text):
            raise DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=SQLITE_FORMAT)
        encoded_sizes = [len(value.encode("utf-8")) for value in (identifier, rollout_raw, source, cwd_raw)]
        encoded_sizes.extend(len(value.encode("utf-8")) for value in optional_text if isinstance(value, str))
        if (
            encoded_sizes[0] > 64
            or encoded_sizes[1] > 4096
            or encoded_sizes[2] > 128
            or encoded_sizes[3] > 4096
            or (isinstance(title, str) and len(title.encode("utf-8")) > 64 * 1024)
            or (isinstance(first_user, str) and len(first_user.encode("utf-8")) > 64 * 1024)
            or (isinstance(branch, str) and len(branch.encode("utf-8")) > 4096)
        ):
            continue
        try:
            budget.consume_bytes(sum(encoded_sizes))
        except DiagnosticError:
            break
        try:
            identifier = str(uuid.UUID(identifier))
            cwd = canonicalize_cwd(cwd_raw)
        except (ValueError, DiagnosticError):
            continue
        if exact is not None and identifier != exact:
            continue
        archived_ok = archived in {0, 1} or archived in {False, True}
        archived_flag = int(archived) if archived_ok else -1
        if source not in {"cli", "vscode"} or archived_flag not in {0, 1}:
            continue
        ref_id = _exact_uuid_ref(query.ref)
        if archived_flag and ref_id != identifier and query.ref != identifier:
            continue
        if query.cwd is not None and not same_cwd(cwd, query.cwd):
            continue
        updated = _numeric_time(updated_raw)
        if not _within(updated, query, identifier):
            continue
        rollout = _resolve_rollout_path(root, rollout_raw, identifier)
        if rollout is None or (rollout.endswith(".zst") and _trusted_zstd() is None):
            continue
        values.append(
            SessionSummary(
                source="codex",
                session_id=identifier,
                source_path=rollout,
                title=title
                if isinstance(title, str) and title.strip()
                else first_user
                if isinstance(first_user, str)
                else None,
                cwd=cwd,
                branch=branch if isinstance(branch, str) else None,
                updated_at=updated,
                provider=SQLITE_FORMAT,
            )
        )
    return True, values
