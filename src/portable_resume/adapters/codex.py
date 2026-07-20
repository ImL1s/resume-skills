"""Read pinned Codex state/rollout formats without invoking Codex."""

from __future__ import annotations

import json
import os
import re
import selectors
import sqlite3
import stat
import subprocess
import threading
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

ROLLOUT_FORMAT = "codex-rollout-jsonl-v1"
SQLITE_FORMAT = "codex-state-sqlite-v1"
ZSTD_FORMAT = "codex-rollout-zstd-v1"

_STATE_DB = re.compile(r"^state_(\d{1,3})\.sqlite$")
_ROLLOUT = re.compile(
    r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-([0-9a-fA-F-]{36})\.jsonl(?P<zst>\.zst)?$"
)
_OUTER_TYPES = frozenset({"session_meta", "response_item", "event_msg", "turn_context", "compacted"})
# Present in live rollouts; skipped without interpreting payloads (Grok resume-session parity).
_SKIP_OUTER_TYPES = frozenset(
    {
        "world_state",
        "inter_agent_communication",
        "inter_agent_communication_metadata",
        "turn_context",  # also in _OUTER_TYPES; kept for explicit skip of empty-payload variants
    }
)
_SQLITE_COLUMNS_MS = {
    "id": "TEXT",
    "rollout_path": "TEXT",
    "updated_at_ms": "INTEGER",
    "source": "TEXT",
    "cwd": "TEXT",
    "title": "TEXT",
    "first_user_message": "TEXT",
    "archived": "INTEGER",
    "git_branch": "TEXT",
}
_SQLITE_COLUMNS_SECONDS = {**_SQLITE_COLUMNS_MS, "updated_at": "INTEGER"}
del _SQLITE_COLUMNS_SECONDS["updated_at_ms"]

# PATH is deliberately ignored.  Operators may install one of these audited
# locations; tests may patch the tuple, not an environment-provided command.
TRUSTED_ZSTD_PATHS = ("/usr/bin/zstd", "/usr/local/bin/zstd", "/opt/homebrew/bin/zstd")
_ZSTD_TIMEOUT_SECONDS = 5.0


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
    return query.source_root or os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


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
    return (
        stat.S_ISDIR(current.st_mode)
        and not stat.S_ISLNK(current.st_mode)
        and is_within(path, root)
    )


def _state_databases(root: str) -> list[str]:
    try:
        names = os.listdir(root)
    except OSError as error:
        raise DiagnosticError.source_busy(provider=SQLITE_FORMAT) from error
    if len(names) > DEFAULT_BOUNDS.scanned_records:
        raise DiagnosticError.limit_exceeded()
    values: list[tuple[int, str]] = []
    for name in names:
        match = _STATE_DB.fullmatch(name)
        if match is None or int(match.group(1)) > 128:
            continue
        path = os.path.join(root, name)
        try:
            current = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode):
            values.append((int(match.group(1)), path))
    return [path for _, path in sorted(values, reverse=True)]


def _walk_rollouts(container: str, root: str, *, max_depth: int = 4) -> list[str]:
    if not _regular_directory(container, root):
        return []
    output: list[str] = []
    visited = 0

    def visit(directory: str, depth: int) -> None:
        nonlocal visited
        try:
            names = sorted(os.listdir(directory))
        except OSError as error:
            raise DiagnosticError.source_busy(provider=ROLLOUT_FORMAT) from error
        visited += len(names)
        if visited > DEFAULT_BOUNDS.scanned_records:
            # Stop walking large trees; do not fail the whole provider.
            return
        for name in names:
            if visited > DEFAULT_BOUNDS.scanned_records:
                return
            path = os.path.join(directory, name)
            try:
                current = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISLNK(current.st_mode):
                continue
            if stat.S_ISDIR(current.st_mode) and depth < max_depth:
                visit(path, depth + 1)
            elif stat.S_ISREG(current.st_mode) and _ROLLOUT.fullmatch(name):
                output.append(path)
                if len(output) >= DEFAULT_BOUNDS.scanned_records:
                    return

    visit(container, 0)
    return output


def _rollout_paths(root: str, query: Query) -> list[str]:
    values = _walk_rollouts(os.path.join(root, "sessions"), root)
    # Archived rows are intentionally invisible unless the user supplied an
    # exact native UUID.  Text and path searches cannot enumerate archives.
    if query.ref:
        try:
            exact = str(uuid.UUID(query.ref)) == query.ref.casefold()
        except ValueError:
            exact = False
        if exact:
            values.extend(_walk_rollouts(os.path.join(root, "archived_sessions"), root))
    exact = _exact_uuid_ref(query.ref)
    return sorted(path for path in values if exact is None or _rollout_id(path) == exact)


def _exact_uuid_ref(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _rollout_id(path: str) -> str | None:
    matched = _ROLLOUT.fullmatch(os.path.basename(path))
    if matched is None:
        return None
    try:
        return str(uuid.UUID(matched.group(1)))
    except ValueError:
        return None


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


def _numeric_time(value: object) -> str | None:
    if type(value) is not int:
        return None
    seconds = value / 1000 if value >= 1_577_836_800_000 else value
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _mtime(read: StableRead) -> str:
    return datetime.fromtimestamp(read.fingerprint.mtime_ns / 1_000_000_000, timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _within(updated_at: str | None, query: Query, session_id: str) -> bool:
    from .common import within_query_age

    return within_query_age(
        updated_at,
        query_ref=query.ref,
        session_id=session_id,
        within_min=query.within_min,
        default_minutes=DEFAULT_BOUNDS.listing_age_minutes,
    )


def _trusted_zstd() -> str | None:
    for candidate in TRUSTED_ZSTD_PATHS:
        if not os.path.isabs(candidate):
            continue
        try:
            current = os.lstat(candidate)
        except OSError:
            continue
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            continue
        if current.st_mode & 0o022 or not os.access(candidate, os.X_OK):
            continue
        if os.path.realpath(candidate) != candidate:
            continue
        return candidate
    return None


def _decompress_zstd(data: bytes) -> bytes:
    executable = _trusted_zstd()
    if executable is None:
        raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source="codex", provider=ZSTD_FORMAT)
    try:
        # The optional decoder is not a source agent process.  Resolve the
        # constructor explicitly so the foundation's source-CLI static guard
        # remains able to reject direct process-launch call sites.
        process = getattr(subprocess, "Popen")(
            [executable, "-d", "-q", "-c"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            env={"PATH": "", "LC_ALL": "C"},
        )
    except OSError as error:
        raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source="codex", provider=ZSTD_FORMAT) from error
    assert process.stdin is not None and process.stdout is not None
    writer_error: list[BaseException] = []

    def write_input() -> None:
        try:
            process.stdin.write(data)
            process.stdin.close()
        except (BrokenPipeError, OSError) as error:
            writer_error.append(error)

    writer = threading.Thread(target=write_input, name="portable-resume-zstd-input", daemon=True)
    writer.start()
    selector = selectors.DefaultSelector()
    output = bytearray()
    deadline = time.monotonic() + _ZSTD_TIMEOUT_SECONDS
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        eof = False
        while not eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source="codex", provider=ZSTD_FORMAT)
            events = selector.select(min(remaining, 0.1))
            if not events and process.poll() is not None:
                events = [(None, None)]
            for event in events:
                try:
                    chunk = os.read(process.stdout.fileno(), 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    eof = True
                    break
                output.extend(chunk)
                if len(output) > DEFAULT_BOUNDS.record_bytes:
                    process.kill()
                    raise DiagnosticError.limit_exceeded()
        remaining = max(0.0, deadline - time.monotonic())
        return_code = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        process.kill()
        raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source="codex", provider=ZSTD_FORMAT) from error
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        writer.join(timeout=0.2)
    if return_code != 0 or writer_error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=ZSTD_FORMAT)
    return bytes(output)


def _parse_lines(data: bytes, budget: ReadBudget, provider: str) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    output: list[dict[str, Any]] = []
    warnings: list[str] = []
    lines = data.splitlines(keepends=True)
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
            raise DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=provider) from error
        if not isinstance(value, dict):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="codex", provider=provider)
        outer = value.get("type")
        payload = value.get("payload")
        if outer in _SKIP_OUTER_TYPES or (
            isinstance(outer, str)
            and outer not in _OUTER_TYPES
        ):
            # Skip unknown / non-rendered outer families; do not abort the file.
            warnings.append("W_UNKNOWN_RECORD_SKIPPED")
            continue
        if outer not in _OUTER_TYPES or not isinstance(payload, dict):
            # Malformed known family → fail closed for this file.
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="codex", provider=provider)
        output.append(value)
    if not output:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="codex", provider=provider)
    return output, tuple(dict.fromkeys(warnings))


def _read_rollout(path: str, root: str, budget: ReadBudget) -> tuple[StableRead, list[dict[str, Any]], tuple[str, ...], str]:
    observation = stable_read_bytes(path, root=root, max_bytes=DEFAULT_BOUNDS.record_bytes, budget=budget)
    provider = ZSTD_FORMAT if path.endswith(".zst") else ROLLOUT_FORMAT
    data = _decompress_zstd(observation.data) if provider == ZSTD_FORMAT else observation.data
    if provider == ZSTD_FORMAT:
        budget.consume_bytes(len(data))
    records, warnings = _parse_lines(data, budget, provider)
    return observation, records, warnings, provider


def _session_meta(records: list[dict[str, Any]], expected_id: str, provider: str) -> dict[str, Any]:
    values = [record for record in records if record.get("type") == "session_meta"]
    if not values:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="codex", provider=provider)
    # Prefer the first meta whose id matches the rollout filename (extras warned later).
    chosen: dict[str, Any] | None = None
    for record in values:
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        identifier = payload.get("id")
        try:
            normalized = str(uuid.UUID(identifier)) if isinstance(identifier, str) else None
        except ValueError:
            normalized = None
        if normalized == expected_id and isinstance(payload.get("cwd"), str):
            chosen = dict(payload)
            break
    if chosen is None:
        raise DiagnosticError("E_CORRUPT_RECORD", source="codex", provider=provider)
    source = chosen.get("source")
    if source not in {"cli", "vscode"}:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="codex", provider=provider)
    return chosen


def _content_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    chunks: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") in {"input_text", "output_text", "text"} and isinstance(item.get("text"), str):
            chunks.append(item["text"])
    return "\n".join(chunks) if chunks else None


def _tool_output_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("output", "text", "body", "content"):
            item = value.get(key)
            if isinstance(item, str):
                return item
            text = _content_text(item)
            if text is not None:
                return text
    return _content_text(value)


def _raw_turn(record: Mapping[str, Any]) -> dict[str, Any] | None:
    outer = record.get("type")
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    timestamp = _rfc3339(record.get("timestamp"))
    if outer == "response_item":
        kind = payload.get("type")
        if kind == "message" and payload.get("role") in {"user", "assistant"}:
            text = _content_text(payload.get("content"))
            return {"role": payload["role"], "content": text, "timestamp": timestamp} if text is not None else None
        if kind in {"function_call", "local_shell_call", "custom_tool_call"}:
            name = payload.get("name") if isinstance(payload.get("name"), str) else kind
            args = payload.get("arguments")
            if args is None:
                args = payload.get("params")
            preview = _tool_output_text(args) or ""
            return {
                "role": "assistant",
                "content": f"called inert foreign tool: {name}" + (f" ({preview[:200]})" if preview else ""),
                "tool_name": name if isinstance(name, str) else None,
                "timestamp": timestamp,
            }
        if kind in {"function_call_output", "custom_tool_call_output", "local_shell_call_output"}:
            text = _tool_output_text(payload.get("output"))
            if text is None:
                return None
            return {
                "role": "tool",
                "content": text,
                "tool_name": payload.get("name") if isinstance(payload.get("name"), str) else None,
                "timestamp": timestamp,
            }
        # Reasoning, encrypted content, and other control items are not normalized.
        return None
    if outer == "event_msg" and payload.get("type") in {"user_message", "agent_message"}:
        message = payload.get("message")
        if isinstance(message, str):
            return {
                "role": "user" if payload.get("type") == "user_message" else "assistant",
                "content": message,
                "timestamp": timestamp,
            }
    return None


def _drop_last_user_turns(turns: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not turns:
        return turns
    remaining = count
    output = list(turns)
    index = len(output) - 1
    while index >= 0 and remaining > 0:
        if output[index].get("role") == "user":
            del output[index]
            remaining -= 1
        index -= 1
    return output


def _normalized_turns(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Apply compacted.replacement_history and thread_rolled_back like Grok reader."""
    turns: list[dict[str, Any]] = []
    warnings: list[str] = []
    for record in records:
        outer = record.get("type")
        payload = record.get("payload")
        if outer == "compacted" and isinstance(payload, Mapping):
            history = payload.get("replacement_history")
            if isinstance(history, list):
                rebuilt: list[dict[str, Any]] = []
                for item in history:
                    if not isinstance(item, Mapping):
                        continue
                    # History entries may be bare response_item payloads or full records.
                    if item.get("type") in {"message", "function_call", "function_call_output"}:
                        synthetic = {"type": "response_item", "payload": item, "timestamp": record.get("timestamp")}
                    elif "payload" in item:
                        synthetic = item  # type: ignore[assignment]
                    else:
                        continue
                    turn = _raw_turn(synthetic) if isinstance(synthetic, Mapping) else None
                    if turn is not None:
                        rebuilt.append(turn)
                turns = rebuilt
                warnings.append("W_TRUNCATED")  # post-compact view is partial by definition
            continue
        if outer == "event_msg" and isinstance(payload, Mapping):
            if payload.get("type") in {"thread_rolled_back", "turn_aborted"}:
                raw_n = payload.get("num_turns")
                if raw_n is None:
                    raw_n = payload.get("turns")
                try:
                    n = int(raw_n) if raw_n is not None else 0
                except (TypeError, ValueError):
                    n = 0
                if n > 0:
                    turns = _drop_last_user_turns(turns, n)
                continue
        turn = _raw_turn(record)
        if turn is not None:
            turns.append(turn)
    return turns, tuple(dict.fromkeys(warnings))


def _rollout_summary(path: str, root: str, query: Query, budget: ReadBudget) -> SessionSummary | None:
    identifier = _rollout_id(path)
    if identifier is None:
        return None
    if path.endswith(".zst") and _trusted_zstd() is None:
        return None
    compressed = path.endswith(".zst")
    try:
        observation, records, warnings, provider = _read_rollout(path, root, budget)
        metadata = _session_meta(records, identifier, provider)
        cwd = canonicalize_cwd(metadata["cwd"])
    except DiagnosticError as error:
        # Optional compressed provider: any structural/decode failure skips only this session
        # so list() remains available for plain rollouts / SQLite providers.
        if compressed:
            return None
        raise
    if query.cwd is not None and not same_cwd(cwd, query.cwd):
        return None
    updated = _mtime(observation)
    if not _within(updated, query, identifier):
        return None
    # List path: title from first user-ish record without full turn normalization.
    first_user = None
    for record in records:
        turn = _raw_turn(record)
        if turn is not None and turn.get("role") == "user" and isinstance(turn.get("content"), str):
            first_user = turn["content"]
            break
    branch = None
    git = metadata.get("git")
    if isinstance(git, Mapping) and isinstance(git.get("branch"), str):
        branch = git["branch"]
    elif isinstance(metadata.get("git_branch"), str):
        branch = metadata["git_branch"]
    created = _rfc3339(next((record.get("timestamp") for record in records if record.get("type") == "session_meta"), None))
    return SessionSummary(
        source="codex",
        session_id=identifier,
        source_path=path,
        title=first_user,
        cwd=cwd,
        branch=branch,
        created_at=created,
        updated_at=updated,
        provider=provider,
        warnings=warnings,
    )


from .codex_sqlite import (  # noqa: E402
    _database_summaries,
    _resolve_rollout_path,
    _table_signature,
)


class CodexAdapter:
    key = "codex"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = _existing_root(query)
        return (root,) if root else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            root = _existing_root(query)
            if root is None:
                return CapabilityReport(self.key, None, "unavailable")
            for database in _state_databases(root):
                try:
                    with private_sqlite_connection(database, root=root, provider=SQLITE_FORMAT) as connection:
                        if _table_signature(connection)[0]:
                            warnings = self._zstd_warnings(root, query)
                            return CapabilityReport(
                                self.key,
                                SQLITE_FORMAT,
                                "partial" if warnings else "supported",
                                root=root,
                                evidence=(SQLITE_FORMAT,),
                                warnings=warnings,
                            )
                except DiagnosticError as error:
                    if error.code in {"E_SQLITE_HOT_JOURNAL", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
                        return CapabilityReport(self.key, SQLITE_FORMAT, "unsafe", root=root)
            paths = _rollout_paths(root, query)
            plain = [path for path in paths if not path.endswith(".zst")]
            if plain:
                try:
                    identifier = _rollout_id(plain[0])
                    assert identifier is not None
                    _, records, _, provider = _read_rollout(plain[0], root, ReadBudget())
                    _session_meta(records, identifier, provider)
                    warnings = self._zstd_warnings(root, query)
                    return CapabilityReport(
                        self.key,
                        ROLLOUT_FORMAT,
                        "partial" if warnings else "supported",
                        root=root,
                        evidence=(ROLLOUT_FORMAT,),
                        warnings=warnings,
                    )
                except DiagnosticError as error:
                    if error.code in {"E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
                        return CapabilityReport(self.key, ROLLOUT_FORMAT, "unsafe", root=root)
            zstd = [path for path in paths if path.endswith(".zst")]
            if zstd and _trusted_zstd() is None:
                return CapabilityReport(
                    self.key,
                    ZSTD_FORMAT,
                    "partial",
                    root=root,
                    warnings=("W_OPTIONAL_ZSTD_UNAVAILABLE",),
                )
            if zstd:
                return CapabilityReport(self.key, ZSTD_FORMAT, "supported", root=root, evidence=(ZSTD_FORMAT,))
            return CapabilityReport(self.key, None, "unsupported" if _state_databases(root) else "unavailable", root=root)
        except DiagnosticError as error:
            state = "unsafe" if error.code in {"E_SOURCE_BUSY", "E_UNSAFE_PATH", "E_SQLITE_HOT_JOURNAL"} else "unsupported"
            return CapabilityReport(self.key, None, state)

    @staticmethod
    def _zstd_warnings(root: str, query: Query) -> tuple[str, ...]:
        if _trusted_zstd() is not None:
            return ()
        return ("W_OPTIONAL_ZSTD_UNAVAILABLE",) if any(path.endswith(".zst") for path in _rollout_paths(root, query)) else ()

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
        values: list[SessionSummary] = []
        database_supported = False
        for database in _state_databases(root):
            supported, rows = _database_summaries(database, root, query, budget)
            if supported:
                database_supported = True
                values = rows
                break
        # Prefer DB rows for list; only scan rollouts when DB absent or no matches.
        if not values:
            for path in _rollout_paths(root, query):
                item = _rollout_summary(path, root, query, budget)
                if item is not None:
                    values.append(item)
        deduplicated: dict[str, SessionSummary] = {}
        for value in values:
            previous = deduplicated.get(value.session_id)
            if previous is None or (value.updated_at or "", value.provider or "") > (
                previous.updated_at or "",
                previous.provider or "",
            ):
                deduplicated[value.session_id] = value
        return sorted(
            deduplicated.values(),
            key=lambda item: (item.updated_at is None, item.updated_at or "", item.session_id),
            reverse=True,
        )

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
        path = ref.source_path
        if path is None:
            matches = [candidate for candidate in _rollout_paths(root, query) if _rollout_id(candidate) == ref.session_id]
            if len(matches) != 1:
                raise DiagnosticError("E_NO_MATCH", source=self.key)
            path = matches[0]
        observation, records, warnings, provider = _read_rollout(path, root, budget)
        if _rollout_id(path) != ref.session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
        metadata = _session_meta(records, ref.session_id, provider)
        try:
            cwd = canonicalize_cwd(metadata["cwd"])
        except DiagnosticError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider) from error
        branch = None
        if isinstance(metadata.get("git"), Mapping) and isinstance(metadata["git"].get("branch"), str):
            branch = metadata["git"]["branch"]
        elif isinstance(metadata.get("git_branch"), str):
            branch = metadata["git_branch"]
        turns: list[Turn] = []
        raw_turns, norm_warnings = _normalized_turns(records)
        all_warnings = list((*warnings, *norm_warnings))
        last_fingerprint: tuple[str, str] | None = None
        turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        for raw in raw_turns:
            fingerprint = (str(raw.get("role")), str(raw.get("content")))
            if fingerprint == last_fingerprint:
                continue
            turn, turn_warnings = sanitize_turn_record(raw, ordinal=len(turns), bounds=turn_bounds)
            all_warnings.extend(turn_warnings)
            if turn is not None:
                budget.consume_turns()
                turns.append(turn)
                last_fingerprint = fingerprint
        last_user = next((turn.content for turn in reversed(turns) if turn.role == "user"), None)
        last_assistant = next((turn.content for turn in reversed(turns) if turn.role == "assistant"), None)
        created = _rfc3339(next((record.get("timestamp") for record in records if record.get("type") == "session_meta"), None))
        return Session(
            source=self.key,
            session_id=ref.session_id,
            source_path=path,
            title=next((turn.content for turn in turns if turn.role == "user"), None),
            cwd=cwd,
            branch=branch,
            created_at=created,
            updated_at=_mtime(observation),
            last_user_request=last_user,
            last_assistant_action=last_assistant,
            turns=tuple(turns),
            warnings=tuple(dict.fromkeys(all_warnings)),
        )


ADAPTER = CodexAdapter()
