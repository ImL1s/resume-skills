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
from ..snapshot import stable_read_bytes, stable_scan_lines

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
        "auto_compact_started",
        "auto_compact_completed",
    }
)
# Timeline-changing events that V1 cannot safely replay. Compaction v1 is
# handled by an allowlisted checkpoint reducer (#238); rewind stays unsupported.
_ESSENTIAL_UNSUPPORTED = frozenset({"rewind_marker"})
_CHECKPOINT_EVENT_KEYS = frozenset(
    {
        "sessionupdate",
        "checkpoint_id",
        "schema_version",
        "prompt_index_at_compaction",
        "checkpoint_file",
    }
)
_CHECKPOINT_SIDECAR_KEYS = frozenset(
    {
        "checkpoint_id",
        "schema_version",
        "prompt_index_at_compaction",
        "created_at",
        "compacted_history",
        "original_user_info",
        "reread_file_paths",
    }
)
_COMPACTION_SCHEMA_V1 = 1
_CHECKPOINT_DIRNAME = "compaction_checkpoints"


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


def _shape(
    value: Any,
    depth: int = 0,
    *,
    path: tuple[str, ...] = (),
    ignored_list_cardinality: bool = False,
) -> None:
    if depth > 32:
        raise DiagnosticError.limit_exceeded()
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise DiagnosticError.limit_exceeded()
        for key, item in value.items():
            child_path = (*path, str(key))
            # ``rawOutput`` is provider-private and never normalized. Its JSONL
            # record is already byte-bounded, while depth and map-width checks
            # still recurse through it. Do not borrow the discovery-row ceiling
            # for ignored provider arrays (#178).
            child_ignored = ignored_list_cardinality or child_path == (
                "params",
                "update",
                "rawOutput",
            )
            _shape(
                item,
                depth + 1,
                path=child_path,
                ignored_list_cardinality=child_ignored,
            )
    elif isinstance(value, list):
        if not ignored_list_cardinality and len(value) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        for item in value:
            _shape(
                item,
                depth + 1,
                path=path,
                ignored_list_cardinality=ignored_list_cardinality,
            )


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
    if minutes is not None and minutes <= 0:
        return True
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

    def _session_paths(self, root: str, *, prefer_cwd: str | None = None) -> list[tuple[str, str]]:
        sessions = os.path.join(root, "sessions")
        if os.path.islink(sessions):
            raise DiagnosticError.unsafe_path()
        if not os.path.isdir(sessions):
            return []
        output: list[tuple[str, str]] = []
        scanned = [0]

        def bounded_names(directory: str) -> list[str]:
            names: list[str] = []
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        scanned[0] += 1
                        if scanned[0] > DEFAULT_BOUNDS.scanned_records:
                            # A partial lexical prefix cannot prove "latest".
                            raise DiagnosticError.limit_exceeded()
                        names.append(entry.name)
            except DiagnosticError:
                raise
            except OSError as error:
                raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
            names.sort()
            return names

        preferred_name = None
        if prefer_cwd:
            from urllib.parse import quote

            preferred_name = quote(prefer_cwd, safe="")
        preferred_path = os.path.join(sessions, preferred_name) if preferred_name else None
        # Exact encoded cwd buckets are addressable without scanning unrelated
        # projects. Fall back to a bounded scan for legacy/non-canonical names.
        if preferred_path is not None and os.path.isdir(preferred_path) and not os.path.islink(preferred_path):
            cwd_names = [preferred_name]
        else:
            cwd_names = bounded_names(sessions)
        for cwd_name in cwd_names:
            cwd_path = os.path.join(sessions, cwd_name)
            try:
                cwd_mode = os.lstat(cwd_path).st_mode
            except OSError:
                continue
            if stat.S_ISLNK(cwd_mode):
                raise DiagnosticError.unsafe_path()
            if not stat.S_ISDIR(cwd_mode):
                # Live Grok co-locates session_search.sqlite and similar files next
                # to cwd buckets — skip regular files; only dirs are session trees.
                if stat.S_ISREG(cwd_mode):
                    continue
                raise DiagnosticError.unsafe_path()
            for session_name in bounded_names(cwd_path):
                session_path = os.path.join(cwd_path, session_name)
                try:
                    entry_mode = os.lstat(session_path).st_mode
                except OSError:
                    continue
                if stat.S_ISLNK(entry_mode):
                    raise DiagnosticError.unsafe_path()
                # Skip .cwd markers and prompt_history.jsonl / other co-located files.
                if not stat.S_ISDIR(entry_mode):
                    if stat.S_ISREG(entry_mode):
                        continue
                    raise DiagnosticError.unsafe_path()
                try:
                    _identifier(session_name)
                except DiagnosticError:
                    continue
                updates = os.path.join(session_path, "updates.jsonl")
                if os.path.isfile(updates) and not os.path.islink(updates):
                    output.append((cwd_path, updates))
            if preferred_name is not None and cwd_name == preferred_name and output:
                break
        # Rank by updates.jsonl mtime (newest first) so latest is not name-order capped.
        def _mtime_key(item: tuple[str, str]) -> float:
            try:
                return -os.lstat(item[1]).st_mtime
            except OSError:
                return 0.0

        output.sort(key=lambda item: (_mtime_key(item), item[1]))
        return output

    def probe(self, query: Query) -> CapabilityReport:
        root = self._root(query)
        if root is None:
            return CapabilityReport(self.key, None, "unavailable")
        prefer = query.cwd
        paths = self._session_paths(root, prefer_cwd=prefer)
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
        paths = self._session_paths(root, prefer_cwd=query.cwd)
        if not paths:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        output: list[SessionSummary] = []
        for cwd_dir, updates in paths:
            session_id = _identifier(os.path.basename(os.path.dirname(updates)))
            cwd = self._decode_cwd(cwd_dir, root, budget)
            # Metadata-first list (#15): prefer summary.json + path/mtime. Do not
            # parse every update line merely to list a session.
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
            created = summary.get("created_at") if isinstance(summary.get("created_at"), str) else None
            # List freshness always prefers updates.jsonl mtime so a stale
            # summary.json last_active_at cannot hide active sessions (#15).
            event_warnings: list[str] = []
            updated: str | None = None
            try:
                st = os.lstat(updates)
                stamp = datetime.fromtimestamp(
                    st.st_mtime, timezone.utc
                ).isoformat(timespec="microseconds").replace("+00:00", "Z")
            except OSError:
                stamp = None
            if stamp is not None:
                updated = stamp
                if created is None:
                    created = stamp
            elif "W_MISSING_BLOB" in summary_warnings:
                # No mtime: fall back to a bounded updates stream only when
                # metadata is otherwise unusable.
                try:
                    event_meta, _, event_warnings = self._parse_updates(
                        updates,
                        root,
                        query,
                        budget,
                        include_turns=False,
                        expected_id=session_id,
                    )
                    if created is None and isinstance(event_meta, tuple) and len(event_meta) > 0:
                        created = event_meta[0]
                    if isinstance(event_meta, tuple) and len(event_meta) > 1:
                        updated = event_meta[1]
                except DiagnosticError as error:
                    if error.code != "E_LIMIT_EXCEEDED":
                        raise
                    event_warnings = ["W_TRUNCATED"]
            if updated is None and isinstance(summary.get("updated_at"), str):
                updated = summary["updated_at"]
            warnings = tuple(dict.fromkeys((*event_warnings, *summary_warnings)))
            item = SessionSummary(
                source=self.key,
                session_id=session_id,
                source_path=updates,
                title=title,
                cwd=summary_cwd,
                branch=branch,
                created_at=created,
                updated_at=updated,
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
            session_dir=session_dir,
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
        session_dir: str | None = None,
    ) -> tuple[tuple[str | None, str | None], list[Turn], list[str]]:
        # Stream via stable_scan_lines under source_read_bytes + transcript_records
        # so large updates.jsonl is not whole-file buffered (#10).
        warnings: list[str] = []
        turns: list[Turn] = []
        timestamps: list[str] = []
        recognized = 0
        resolved_session_dir = session_dir if session_dir is not None else os.path.dirname(path)
        for line in stable_scan_lines(
            path,
            root=root,
            budget=budget,
            charge_transcript=True,
            hook=self._read_hook,
        ):
            if not line.utf8_valid:
                if not line.terminated:
                    warnings.append("W_PARTIAL_TAIL")
                    break
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            raw = line.text.strip()
            if not raw:
                continue
            try:
                value = _loads(raw.encode("utf-8"))
            except DiagnosticError:
                if not line.terminated:
                    warnings.append("W_PARTIAL_TAIL")
                    continue
                raise
            if not isinstance(value, Mapping):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
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
            public_update = {key: item for key, item in update.items() if key != "rawOutput"}
            if kind in _ESSENTIAL_UNSUPPORTED:
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            # Timeline controls must not be soft-skipped when encrypted-looking keys appear
            # on the control object (#238 Codex P1): fail closed instead of keeping
            # superseded pre-checkpoint turns.
            if kind == "compaction_checkpoint":
                if _contains_encrypted(public_update):
                    raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
                # list/metadata path: recognize without sidecar load (#238).
                if not include_turns:
                    recognized += 1
                    continue
                self._apply_compaction_checkpoint(
                    update,
                    turns=turns,
                    root=root,
                    session_dir=resolved_session_dir,
                    query=query,
                    budget=budget,
                    warnings=warnings,
                    event_timestamp=timestamp,
                )
                recognized += 1
                continue
            if _contains_encrypted(public_update):
                recognized += 1
                continue
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

    def _apply_compaction_checkpoint(
        self,
        update: Mapping[str, Any],
        *,
        turns: list[Turn],
        root: str,
        session_dir: str,
        query: Query,
        budget: ReadBudget,
        warnings: list[str],
        event_timestamp: str | None,
    ) -> None:
        """Replace active public projection with qualified compaction v1 sidecar history (#238)."""
        keys = {str(key).casefold() for key in update.keys()}
        if keys != _CHECKPOINT_EVENT_KEYS:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        checkpoint_id = _identifier(update.get("checkpoint_id"))
        schema_version = update.get("schema_version")
        # bool is a subclass of int — require exact int type.
        if type(schema_version) is not int or schema_version != _COMPACTION_SCHEMA_V1:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        prompt_index = update.get("prompt_index_at_compaction")
        if type(prompt_index) is not int or prompt_index < 0:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        checkpoint_file = update.get("checkpoint_file")
        if not isinstance(checkpoint_file, str) or not checkpoint_file:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        # Basename only — reject absolute paths, traversal, and nested segments.
        if checkpoint_file in {".", ".."} or "/" in checkpoint_file or "\\" in checkpoint_file:
            raise DiagnosticError.unsafe_path()
        if os.path.basename(checkpoint_file) != checkpoint_file:
            raise DiagnosticError.unsafe_path()
        # Allow `.json` suffix while reusing identifier charset on the stem.
        stem, ext = os.path.splitext(checkpoint_file)
        if ext not in {"", ".json"} or not stem or _ID.fullmatch(stem) is None:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        checkpoint_dir = os.path.join(session_dir, _CHECKPOINT_DIRNAME)
        sidecar_path = os.path.join(checkpoint_dir, checkpoint_file)
        if not is_within(sidecar_path, root) or not is_within(sidecar_path, session_dir):
            raise DiagnosticError.unsafe_path()
        if not os.path.isfile(sidecar_path) or os.path.islink(sidecar_path):
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        try:
            read = stable_read_bytes(
                sidecar_path,
                root=root,
                budget=budget,
                hook=self._read_hook,
            )
            sidecar = _loads(read.data)
        except DiagnosticError:
            raise
        except OSError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID) from error
        if not isinstance(sidecar, Mapping):
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        side_keys = {str(key).casefold() for key in sidecar.keys()}
        if not _CHECKPOINT_SIDECAR_KEYS.issubset(side_keys):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        # Reject unknown top-level sidecar keys outside the allowlist (exact surface).
        if side_keys - _CHECKPOINT_SIDECAR_KEYS:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        if _identifier(sidecar.get("checkpoint_id")) != checkpoint_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        side_schema = sidecar.get("schema_version")
        if type(side_schema) is not int or side_schema != _COMPACTION_SCHEMA_V1:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        side_index = sidecar.get("prompt_index_at_compaction")
        if type(side_index) is not int or side_index != prompt_index:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        history = sidecar.get("compacted_history")
        if not isinstance(history, list):
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        if _contains_encrypted(sidecar):
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        # Replace superseded pre-checkpoint projection; re-append public entries only.
        # Reset turn charges so rebuilt projection does not double-count superseded
        # history against normalized_turns (#238 Codex P1).
        turns.clear()
        budget.turns = 0
        for item in history:
            if not isinstance(item, Mapping):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            role = item.get("role")
            if not isinstance(role, str):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            role_cf = role.casefold()
            if role_cf not in {"user", "assistant"}:
                # system / developer / reasoning / tool / unknown: omit (privacy).
                continue
            text = self._compaction_entry_text(item)
            if text is None:
                continue
            self._append_chunk(turns, role_cf, text, event_timestamp, query, budget, warnings)

    @staticmethod
    def _compaction_entry_text(item: Mapping[str, Any]) -> str | None:
        content = item.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, Mapping) and content.get("type") == "text" and isinstance(content.get("text"), str):
            return content["text"]
        return None

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
        limit = DEFAULT_BOUNDS.normalized_content_bytes
        if turns and turns[-1].role == role and turns[-1].tool_name is None:
            prior = turns[-1]
            room = limit - len(prior.content)
            if room <= 0:
                if not prior.truncated:
                    turns[-1] = Turn(
                        ordinal=prior.ordinal,
                        role=role,
                        content=prior.content,
                        timestamp=prior.timestamp or turn.timestamp,
                        truncated=True,
                    )
                return
            chunk = turn.content[:room] if room < len(turn.content) else turn.content
            turns[-1] = Turn(
                ordinal=prior.ordinal,
                role=role,
                content=prior.content + chunk,
                timestamp=prior.timestamp or turn.timestamp,
                truncated=prior.truncated or turn.truncated or len(turn.content) > room,
            )
            return
        budget.consume_turns()
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
