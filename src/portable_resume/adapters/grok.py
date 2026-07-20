"""Clean-room parser for the public Grok Build ``updates.jsonl`` format.

Only explicitly allowlisted public envelope/update signatures are normalized.
Control, thought, system, and encrypted records are omitted.  Timeline-changing
records that this V1 parser cannot safely replay fail closed rather than
returning a plausible but stale branch.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import unquote

from .base import CapabilityReport, ResolvedRef
from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import stable_read_bytes

FORMAT_ID = "grok-updates-jsonl-v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,1023}$")
_PERCENT = re.compile(r"%(?:[0-9A-Fa-f]{2})")
_FILTERED_UPDATES = frozenset(
    {
        "agent_thought_chunk",
        "system_message_chunk",
        "developer_message_chunk",
        "available_commands_update",
        "current_mode_update",
        "plan",
        "config_option_update",
        "session_info_update",
        "git_branch_update",
        "usage_update",
        "turn_completed",
        "memory_flush_started",
        "memory_flush_completed",
        "hook_execution",
        "hook_annotation",
    }
)
_ESSENTIAL_UNSUPPORTED = frozenset({"rewind_marker", "compaction_checkpoint"})


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _loads(data: bytes, *, optional: bool = False) -> Any:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT" if optional else "E_CORRUPT_RECORD", source="grok") from error
    _shape(value)
    return value


def _shape(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise DiagnosticError.limit_exceeded()
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise DiagnosticError.limit_exceeded()
        for item in value.values():
            _shape(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        for item in value:
            _shape(item, depth + 1)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None or value in {".", ".."}:
        raise DiagnosticError("E_CORRUPT_RECORD", source="grok", provider=FORMAT_ID)
    return value


def _timestamp(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if abs(seconds) >= 100_000_000_000:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except (OSError, OverflowError, ValueError):
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
    if summary.updated_at is None:
        return False
    try:
        updated = datetime.fromisoformat(summary.updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return updated >= datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _contains_encrypted(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(token in normalized for token in ("encrypted", "ciphertext", "signature")):
                return True
            if _contains_encrypted(item):
                return True
    elif isinstance(value, list):
        return any(_contains_encrypted(item) for item in value)
    return False


def _session_from(summary: SessionSummary, turns: Iterable[Turn], warnings: Iterable[str]) -> Session:
    values = tuple(turns)
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
        last_user_request=next((turn.content for turn in reversed(values) if turn.role == "user"), None),
        last_assistant_action=next((turn.content for turn in reversed(values) if turn.role == "assistant"), None),
        turns=values,
        warnings=tuple(dict.fromkeys((*summary.warnings, *warnings))),
    )


class GrokAdapter:
    key = "grok"

    def __init__(self, *, root: str | None = None, read_hook: Any = None):
        self._configured_root = root
        self._read_hook = read_hook

    def _root(self, query: Query, *, required: bool = False) -> str | None:
        candidate = query.source_root or self._configured_root or os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok")
        if not os.path.isdir(candidate):
            if required:
                raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
            return None
        return canonical_root(candidate)

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = self._root(query)
        return (root,) if root is not None else ()

    def _session_paths(self, root: str) -> list[tuple[str, str]]:
        sessions = os.path.join(root, "sessions")
        if os.path.islink(sessions):
            raise DiagnosticError.unsafe_path()
        if not os.path.isdir(sessions):
            return []
        output: list[tuple[str, str]] = []
        observed = 0
        try:
            cwd_entries = sorted(os.scandir(sessions), key=lambda entry: entry.name)
        except OSError as error:
            raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
        for cwd_entry in cwd_entries:
            observed += 1
            if observed > DEFAULT_BOUNDS.scanned_records:
                raise DiagnosticError.limit_exceeded()
            if cwd_entry.is_symlink():
                raise DiagnosticError.unsafe_path()
            mode = cwd_entry.stat(follow_symlinks=False).st_mode
            if not stat.S_ISDIR(mode):
                if stat.S_ISREG(mode) and cwd_entry.name == ".DS_Store":
                    continue
                raise DiagnosticError.unsafe_path()
            try:
                session_entries = sorted(os.scandir(cwd_entry.path), key=lambda entry: entry.name)
            except OSError as error:
                raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
            for session_entry in session_entries:
                observed += 1
                if observed > DEFAULT_BOUNDS.scanned_records:
                    raise DiagnosticError.limit_exceeded()
                if session_entry.is_symlink():
                    raise DiagnosticError.unsafe_path()
                entry_mode = session_entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISREG(entry_mode) and session_entry.name == ".cwd":
                    continue
                if not stat.S_ISDIR(entry_mode):
                    raise DiagnosticError.unsafe_path()
                _identifier(session_entry.name)
                updates = os.path.join(session_entry.path, "updates.jsonl")
                if os.path.isfile(updates) and not os.path.islink(updates):
                    output.append((cwd_entry.path, updates))
        return output

    def probe(self, query: Query) -> CapabilityReport:
        root = self._root(query)
        if root is None:
            return CapabilityReport(self.key, None, "unavailable")
        paths = self._session_paths(root)
        if not paths:
            return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
        missing_summary = any(not os.path.isfile(os.path.join(os.path.dirname(path), "summary.json")) for _, path in paths)
        return CapabilityReport(
            self.key,
            FORMAT_ID,
            "partial" if missing_summary else "supported",
            root=root,
            evidence=("sessions:encoded-cwd/updates.jsonl",),
            warnings=("W_MISSING_BLOB",) if missing_summary else (),
        )

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = self._root(query, required=True)
        assert root is not None
        paths = self._session_paths(root)
        if not paths:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        output: list[SessionSummary] = []
        for cwd_dir, updates in paths:
            session_id = _identifier(os.path.basename(os.path.dirname(updates)))
            cwd = self._decode_cwd(cwd_dir, root, budget)
            event_meta, _, event_warnings = self._parse_updates(
                updates,
                root,
                query,
                budget,
                include_turns=False,
                expected_id=session_id,
            )
            summary, summary_warnings = self._summary(
                os.path.dirname(updates),
                root,
                budget,
                session_id=session_id,
                decoded_cwd=cwd,
            )
            title = summary.get("title") if isinstance(summary.get("title"), str) else None
            summary_cwd = summary.get("cwd") if isinstance(summary.get("cwd"), str) else cwd
            branch = summary.get("branch") if isinstance(summary.get("branch"), str) else None
            warnings = tuple(dict.fromkeys((*event_warnings, *summary_warnings)))
            item = SessionSummary(
                source=self.key,
                session_id=session_id,
                source_path=updates,
                title=title,
                cwd=summary_cwd,
                branch=branch,
                created_at=summary.get("created_at") if isinstance(summary.get("created_at"), str) else event_meta[0],
                updated_at=summary.get("updated_at") if isinstance(summary.get("updated_at"), str) else event_meta[1],
                source_repo_root=summary.get("source_repo_root") if isinstance(summary.get("source_repo_root"), str) else None,
                provider=FORMAT_ID,
                warnings=warnings,
            )
            if _eligible(item, query):
                output.append(item)
        return output

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = self._root(query, required=True)
        assert root is not None
        if ref.provider != FORMAT_ID:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=ref.provider)
        if ref.source_path is None or not is_within(ref.source_path, root):
            raise DiagnosticError.unsafe_path()
        session_dir = os.path.dirname(ref.source_path)
        cwd_dir = os.path.dirname(session_dir)
        if _identifier(os.path.basename(session_dir)) != ref.session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        cwd = self._decode_cwd(cwd_dir, root, budget)
        event_meta, turns, event_warnings = self._parse_updates(
            ref.source_path,
            root,
            query,
            budget,
            include_turns=True,
            expected_id=ref.session_id,
        )
        metadata, summary_warnings = self._summary(
            session_dir,
            root,
            budget,
            session_id=ref.session_id,
            decoded_cwd=cwd,
        )
        summary = SessionSummary(
            source=self.key,
            session_id=ref.session_id,
            source_path=ref.source_path,
            title=metadata.get("title") if isinstance(metadata.get("title"), str) else None,
            cwd=metadata.get("cwd") if isinstance(metadata.get("cwd"), str) else cwd,
            branch=metadata.get("branch") if isinstance(metadata.get("branch"), str) else None,
            created_at=metadata.get("created_at") if isinstance(metadata.get("created_at"), str) else event_meta[0],
            updated_at=metadata.get("updated_at") if isinstance(metadata.get("updated_at"), str) else event_meta[1],
            source_repo_root=metadata.get("source_repo_root") if isinstance(metadata.get("source_repo_root"), str) else None,
            provider=FORMAT_ID,
            warnings=tuple(dict.fromkeys((*event_warnings, *summary_warnings))),
        )
        return _session_from(summary, turns, (*event_warnings, *summary_warnings))

    def _decode_cwd(self, cwd_dir: str, root: str, budget: ReadBudget) -> str:
        name = os.path.basename(cwd_dir)
        # Reject malformed percent escapes rather than letting unquote silently
        # preserve them as plausible path characters.
        stripped = _PERCENT.sub("", name)
        if "%" not in stripped:
            try:
                decoded = unquote(name, errors="strict")
            except UnicodeDecodeError:
                decoded = ""
            if os.path.isabs(decoded):
                return canonicalize_cwd(decoded)
        marker = os.path.join(cwd_dir, ".cwd")
        if not os.path.isfile(marker):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        read = stable_read_bytes(marker, root=root, max_bytes=4096, budget=budget, hook=self._read_hook)
        try:
            value = read.data.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID) from error
        if not value or not os.path.isabs(value):
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        return canonicalize_cwd(value)

    def _summary(
        self,
        session_dir: str,
        root: str,
        budget: ReadBudget,
        *,
        session_id: str,
        decoded_cwd: str,
    ) -> tuple[dict[str, str | None], list[str]]:
        path = os.path.join(session_dir, "summary.json")
        warnings: list[str] = []
        empty: dict[str, str | None] = {}
        if not os.path.isfile(path):
            return empty, ["W_MISSING_BLOB"]
        try:
            read = stable_read_bytes(path, root=root, budget=budget, hook=self._read_hook)
            value = _loads(read.data, optional=True)
        except DiagnosticError as error:
            if error.code in {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD"}:
                return empty, ["W_MISSING_BLOB"]
            raise
        if not isinstance(value, Mapping):
            return empty, ["W_MISSING_BLOB"]
        info = value.get("info")
        if not isinstance(info, Mapping):
            return empty, ["W_MISSING_BLOB"]
        if info.get("id") != session_id:
            warnings.append("W_STALE_INDEX")
        raw_cwd = info.get("cwd")
        cwd = decoded_cwd
        if isinstance(raw_cwd, str):
            candidate = canonicalize_cwd(raw_cwd)
            if same_cwd(candidate, decoded_cwd):
                cwd = candidate
            else:
                warnings.append("W_STALE_INDEX")
        title = value.get("generated_title") if isinstance(value.get("generated_title"), str) else value.get("session_summary")
        created_at = _timestamp(value.get("created_at"))
        updated_at = _timestamp(value.get("last_active_at")) or _timestamp(value.get("updated_at"))
        result: dict[str, str | None] = {
            "title": title if isinstance(title, str) else None,
            "cwd": cwd,
            "branch": value.get("head_branch") if isinstance(value.get("head_branch"), str) else None,
            "created_at": created_at,
            "updated_at": updated_at,
            "source_repo_root": value.get("git_root_dir") if isinstance(value.get("git_root_dir"), str) else None,
        }
        return result, warnings

    def _parse_updates(
        self,
        path: str,
        root: str,
        query: Query,
        budget: ReadBudget,
        *,
        include_turns: bool,
        expected_id: str,
    ) -> tuple[tuple[str | None, str | None], list[Turn], list[str]]:
        read = stable_read_bytes(path, root=root, budget=budget, hook=self._read_hook)
        lines = read.data.split(b"\n")
        trailing_fragment = bool(lines and lines[-1])
        nonempty = [(index, raw.strip()) for index, raw in enumerate(lines) if raw.strip()]
        warnings: list[str] = []
        turns: list[Turn] = []
        timestamps: list[str] = []
        recognized = 0
        for position, (line_index, raw) in enumerate(nonempty):
            try:
                value = _loads(raw)
            except DiagnosticError:
                is_tail = position == len(nonempty) - 1 and trailing_fragment and line_index == len(lines) - 1
                if is_tail:
                    warnings.append("W_PARTIAL_TAIL")
                    continue
                raise
            if not isinstance(value, Mapping):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            budget.consume_records()
            timestamp = _timestamp(value.get("timestamp"))
            if timestamp is not None:
                timestamps.append(timestamp)
            method = value.get("method")
            params = value.get("params")
            if method not in {"session/update", "_x.ai/session/update"} or not isinstance(params, Mapping):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            if params.get("sessionId") != expected_id:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            update = params.get("update")
            if not isinstance(update, Mapping):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            kind = update.get("sessionUpdate")
            if not isinstance(kind, str):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            kind = kind.casefold()
            if _contains_encrypted(update):
                recognized += 1
                continue
            if kind in _ESSENTIAL_UNSUPPORTED:
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            if kind in _FILTERED_UPDATES:
                recognized += 1
                continue
            if kind in {"user_message_chunk", "agent_message_chunk"}:
                content = update.get("content")
                if not isinstance(content, Mapping):
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
                content_type = content.get("type")
                if content_type != "text":
                    warnings.append("W_BINARY_OMITTED")
                    recognized += 1
                    continue
                text = content.get("text")
                if not isinstance(text, str):
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
                recognized += 1
                if include_turns:
                    role = "user" if kind == "user_message_chunk" else "assistant"
                    self._append_chunk(turns, role, text, timestamp, query, budget, warnings)
                continue
            if kind == "tool_call":
                title = update.get("title")
                if not isinstance(title, str):
                    warnings.append("W_MISSING_BLOB")
                elif include_turns:
                    self._append_tool(turns, title, update.get("kind"), timestamp, query, budget, warnings)
                recognized += 1
                continue
            if kind in {"tool_result", "tool_call_update"}:
                text = self._tool_text(update)
                if text is None:
                    warnings.append("W_MISSING_BLOB")
                elif include_turns:
                    self._append_tool(turns, text, update.get("title") or update.get("toolCallId"), timestamp, query, budget, warnings)
                recognized += 1
                continue
            if any(token in kind for token in ("user_message", "agent_message", "rewind", "compaction")) or any(
                key in update for key in ("content", "message", "prompt")
            ):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            warnings.append("W_BROKEN_CHAIN")
        if recognized == 0:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        return ((min(timestamps) if timestamps else None, max(timestamps) if timestamps else None), turns, warnings)

    @staticmethod
    def _tool_text(update: Mapping[str, Any]) -> str | None:
        content = update.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            pieces: list[str] = []
            for item in content:
                if isinstance(item, Mapping) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    pieces.append(item["text"])
                elif isinstance(item, Mapping) and item.get("type") in {"image", "audio", "video"}:
                    continue
                else:
                    return None
            return "\n".join(pieces) if pieces else None
        for key in ("output", "result"):
            if isinstance(update.get(key), str):
                return update[key]
        return None

    @staticmethod
    def _append_chunk(
        turns: list[Turn],
        role: str,
        content: str,
        timestamp: str | None,
        query: Query,
        budget: ReadBudget,
        warnings: list[str],
    ) -> None:
        record = {"role": role, "content": content, "timestamp": timestamp}
        bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        turn, found = sanitize_turn_record(record, ordinal=len(turns), bounds=bounds)
        warnings.extend(found)
        if turn is None:
            return
        budget.consume_turns()
        if turns and turns[-1].role == role and turns[-1].tool_name is None:
            prior = turns[-1]
            turns[-1] = Turn(
                ordinal=prior.ordinal,
                role=role,
                content=prior.content + turn.content,
                timestamp=prior.timestamp or turn.timestamp,
                truncated=prior.truncated or turn.truncated,
            )
        else:
            turns.append(turn)

    @staticmethod
    def _append_tool(
        turns: list[Turn],
        content: str,
        tool_name: object,
        timestamp: str | None,
        query: Query,
        budget: ReadBudget,
        warnings: list[str],
    ) -> None:
        record = {
            "role": "tool",
            "content": content,
            "tool_name": tool_name if isinstance(tool_name, str) else None,
            "timestamp": timestamp,
        }
        bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        turn, found = sanitize_turn_record(record, ordinal=len(turns), bounds=bounds)
        warnings.extend(found)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)


ADAPTER = GrokAdapter()


def get_adapter() -> GrokAdapter:
    return ADAPTER
