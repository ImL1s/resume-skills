"""Fail-closed reader for Antigravity CLI transcript JSONL files.

Transcript bytes are authoritative.  The optional ``brain/index.json`` is a
bounded discovery hint only: an absent, private, corrupt, or stale index never
fabricates a session and never blocks an exact ID/path lookup.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .base import CapabilityReport, ResolvedRef
from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import stable_read_bytes

FORMAT_ID = "antigravity-transcript-jsonl-v1"
INDEX_FORMAT = "antigravity-index-v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,1023}$")
_FILTERED_TYPES = frozenset(
    {
        "system",
        "developer",
        "thought",
        "thinking",
        "reasoning",
        "control",
        "internal",
        "policy",
    }
)
_BINARY_TYPES = frozenset({"image", "audio", "video", "attachment", "binary"})


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _loads(data: bytes, *, index: bool = False) -> Any:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT" if index else "E_CORRUPT_RECORD", source="antigravity") from error
    _bounded_shape(value)
    return value


def _bounded_shape(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise DiagnosticError.limit_exceeded()
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise DiagnosticError.limit_exceeded()
        for item in value.values():
            _bounded_shape(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        for item in value:
            _bounded_shape(item, depth + 1)


def _session_id(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None or value in {".", ".."}:
        raise DiagnosticError("E_CORRUPT_RECORD", source="antigravity", provider=FORMAT_ID)
    return value


def _rfc3339(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


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


class AntigravityAdapter:
    key = "antigravity"

    def __init__(self, *, root: str | None = None, read_hook: Any = None):
        self._configured_root = root
        self._read_hook = read_hook

    def _root(self, query: Query, *, required: bool = False) -> str | None:
        candidate = query.source_root or self._configured_root or os.path.expanduser("~/.gemini/antigravity-cli")
        if not os.path.isdir(candidate):
            if required:
                raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
            return None
        return canonical_root(candidate)

    def _brain(self, root: str) -> str:
        direct = os.path.join(root, ".system_generated", "logs", "transcript.jsonl")
        if os.path.isfile(direct):
            return os.path.dirname(root)
        brain = root if os.path.basename(root) == "brain" else os.path.join(root, "brain")
        if os.path.islink(brain):
            raise DiagnosticError.unsafe_path()
        return brain

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = self._root(query)
        return (root,) if root is not None else ()

    def _index_path(self, brain: str) -> str:
        return os.path.join(brain, "index.json")

    def _read_index(self, brain: str, root: str) -> tuple[list[Mapping[str, Any]] | None, bool]:
        path = self._index_path(brain)
        if not is_within(path, root) or os.path.islink(path):
            return None, True
        if not os.path.isfile(path):
            return None, True
        try:
            read = stable_read_bytes(path, root=root, budget=None, hook=self._read_hook)
            value = _loads(read.data, index=True)
            if not isinstance(value, Mapping) or value.get("format") != INDEX_FORMAT:
                return None, True
            entries = value.get("conversations")
            if not isinstance(entries, list) or not all(isinstance(item, Mapping) for item in entries):
                return None, True
            return entries, False
        except DiagnosticError as error:
            if error.code in {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD", "E_SOURCE_BUSY"}:
                return None, True
            raise

    @staticmethod
    def _conversation_path(brain: str, session_id: str) -> str:
        return os.path.join(brain, session_id, ".system_generated", "logs", "transcript.jsonl")

    def _scan_brain_transcripts(self, brain: str, root: str) -> list[str]:
        """When index is missing, discover fixed transcript paths under brain/<id>/…"""
        if not os.path.isdir(brain) or os.path.islink(brain):
            return []
        if not is_within(brain, root):
            return []
        try:
            names = sorted(os.listdir(brain))
        except OSError as error:
            raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
        # Cap name scan without hard-failing large live brain trees.
        names = names[: DEFAULT_BOUNDS.scanned_records]
        paths: list[str] = []
        for name in names:
            if name in {".", "..", "index.json"}:
                continue
            try:
                session_id = _session_id(name)
            except DiagnosticError:
                continue
            path = self._conversation_path(brain, session_id)
            if os.path.islink(path) or not is_within(path, root):
                continue
            if os.path.isfile(path):
                paths.append(path)
                if len(paths) >= DEFAULT_BOUNDS.scanned_records:
                    break
        # Newest transcript first so list/latest is not directory-name order.
        def _mtime_key(p: str) -> float:
            try:
                return -os.lstat(p).st_mtime
            except OSError:
                return 0.0

        paths.sort(key=lambda p: (_mtime_key(p), p))
        return paths

    def _direct_transcript(self, root: str, brain: str, query: Query) -> str | None:
        direct_root = os.path.join(root, ".system_generated", "logs", "transcript.jsonl")
        if os.path.isfile(direct_root):
            return direct_root
        ref = query.ref
        if not ref:
            return None
        if os.path.isabs(ref):
            path = ref
            if os.path.isdir(path):
                path = os.path.join(path, ".system_generated", "logs", "transcript.jsonl")
            if os.path.basename(path) != "transcript.jsonl":
                return None
            if not is_within(path, root) or os.path.islink(path):
                raise DiagnosticError.unsafe_path()
            return path if os.path.isfile(path) else None
        if _ID.fullmatch(ref) is None or ref in {"latest", ".", ".."}:
            return None
        path = self._conversation_path(brain, ref)
        return path if os.path.isfile(path) else None

    def probe(self, query: Query) -> CapabilityReport:
        root = self._root(query)
        if root is None:
            return CapabilityReport(self.key, None, "unavailable")
        brain = self._brain(root)
        entries, stale = self._read_index(brain, root)
        evidence: list[str] = []
        valid = 0
        if entries is not None:
            for entry in entries[: DEFAULT_BOUNDS.scanned_records]:
                try:
                    session_id = _session_id(entry.get("id"))
                except DiagnosticError:
                    stale = True
                    continue
                if os.path.isfile(self._conversation_path(brain, session_id)):
                    valid += 1
                else:
                    stale = True
            if valid:
                evidence.append("brain:index+transcript")
        direct = self._direct_transcript(root, brain, query)
        if direct is not None:
            valid += 1
            evidence.append("brain:exact-transcript")
        if not valid:
            if os.path.isdir(brain):
                return CapabilityReport(
                    self.key,
                    FORMAT_ID,
                    "partial",
                    root=root,
                    evidence=("brain:index-unavailable",),
                    warnings=("W_STALE_INDEX",),
                )
            return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
        return CapabilityReport(
            self.key,
            FORMAT_ID,
            "partial" if stale else "supported",
            root=root,
            evidence=tuple(dict.fromkeys(evidence)),
            warnings=("W_STALE_INDEX",) if stale else (),
        )

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = self._root(query, required=True)
        assert root is not None
        brain = self._brain(root)
        entries, stale = self._read_index(brain, root)
        candidates: list[tuple[str, Mapping[str, Any] | None]] = []
        if entries is not None:
            if len(entries) > DEFAULT_BOUNDS.scanned_records:
                raise DiagnosticError.limit_exceeded()
            for entry in entries:
                try:
                    session_id = _session_id(entry.get("id"))
                except DiagnosticError:
                    stale = True
                    continue
                path = self._conversation_path(brain, session_id)
                if not os.path.isfile(path):
                    stale = True
                    continue
                candidates.append((path, entry))
            # Newest transcript first (index order is not authoritative for latest).
            def _cand_mtime(item: tuple[str, Mapping[str, Any] | None]) -> float:
                try:
                    return -os.lstat(item[0]).st_mtime
                except OSError:
                    return 0.0

            candidates.sort(key=lambda item: (_cand_mtime(item), item[0]))
        elif not query.ref:
            # No valid index: bounded directory discovery (Grok/Codex-style).
            for path in self._scan_brain_transcripts(brain, root):
                candidates.append((path, None))
        direct = self._direct_transcript(root, brain, query)
        if direct is not None and all(path != direct for path, _ in candidates):
            candidates.append((direct, None))
        output: list[SessionSummary] = []
        scan_mode = entries is None and not query.ref
        for path, hint in candidates:
            try:
                summary, _, warnings = self._read_transcript(
                    path, root, query, budget, include_turns=False, hint=hint
                )
            except DiagnosticError as error:
                # Live AGY transcripts may use a different schema; skip only when
                # directory-scanning without a trusted index entry.
                if scan_mode and error.code in {
                    "E_UNSUPPORTED_FORMAT",
                    "E_CORRUPT_RECORD",
                    "E_UNSAFE_PATH",
                    "E_LIMIT_EXCEEDED",
                }:
                    continue
                raise
            merged = list(summary.warnings)
            merged.extend(warnings)
            if stale:
                merged.append("W_STALE_INDEX")
            summary = SessionSummary(
                source=summary.source,
                session_id=summary.session_id,
                source_path=summary.source_path,
                title=summary.title,
                cwd=summary.cwd,
                branch=summary.branch,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
                source_repo_root=summary.source_repo_root,
                provider=summary.provider,
                warnings=tuple(dict.fromkeys(merged)),
            )
            if _eligible(summary, query):
                output.append(summary)
        return output

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = self._root(query, required=True)
        assert root is not None
        if ref.provider != FORMAT_ID:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=ref.provider)
        if ref.source_path is None or not is_within(ref.source_path, root):
            raise DiagnosticError.unsafe_path()
        brain = self._brain(root)
        entries, stale = self._read_index(brain, root)
        hint: Mapping[str, Any] | None = None
        if entries is not None:
            for entry in entries:
                if entry.get("id") != ref.session_id:
                    continue
                if hint is not None:
                    stale = True
                    continue
                expected = self._conversation_path(brain, ref.session_id)
                if canonicalize_cwd(expected) == canonicalize_cwd(ref.source_path):
                    hint = entry
                else:
                    stale = True
        summary, turns, warnings = self._read_transcript(
            ref.source_path,
            root,
            query,
            budget,
            include_turns=True,
            hint=hint,
        )
        if summary.session_id != ref.session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        if stale:
            warnings.append("W_STALE_INDEX")
        return _session_from(summary, turns, warnings)

    def _read_transcript(
        self,
        path: str,
        root: str,
        query: Query,
        budget: ReadBudget,
        *,
        include_turns: bool,
        hint: Mapping[str, Any] | None,
    ) -> tuple[SessionSummary, list[Turn], list[str]]:
        read = stable_read_bytes(path, root=root, budget=budget, hook=self._read_hook)
        lines = read.data.split(b"\n")
        trailing_fragment = bool(lines and lines[-1])
        warnings: list[str] = []
        records: list[Mapping[str, Any]] = []
        nonempty = [(index, line.strip()) for index, line in enumerate(lines) if line.strip()]
        for position, (line_index, raw) in enumerate(nonempty):
            try:
                value = _loads(raw)
            except DiagnosticError:
                is_final = position == len(nonempty) - 1 and trailing_fragment and line_index == len(lines) - 1
                if is_final:
                    warnings.append("W_PARTIAL_TAIL")
                    continue
                raise
            if not isinstance(value, Mapping):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            records.append(value)
            budget.consume_records()
        if not records:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)

        # transcript.jsonl -> logs -> .system_generated -> <conversation-id>
        path_id = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))))
        path_id = _session_id(path_id)
        header: Mapping[str, Any] | None = None
        turns: list[Turn] = []
        created_values: list[str] = []
        updated_values: list[str] = []
        live_stream = False
        for record in records:
            kind = record.get("type")
            if not isinstance(kind, str):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            raw_kind = kind
            kind = kind.casefold()
            timestamp = _rfc3339(record.get("timestamp")) or _rfc3339(record.get("created_at"))
            if timestamp is not None:
                created_values.append(timestamp)
                updated_values.append(timestamp)
            if kind == "session":
                if header is not None:
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
                if _session_id(record.get("conversation_id")) != path_id:
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
                header = record
                continue
            # Live AGY step stream (uppercase USER_INPUT / PLANNER_RESPONSE / tools).
            if kind == "user_input":
                live_stream = True
                content = record.get("content")
                if not isinstance(content, str):
                    continue
                if include_turns:
                    self._append_turn(
                        turns,
                        {"role": "user", "content": content, "timestamp": timestamp},
                        query,
                        budget,
                        warnings,
                    )
                continue
            if kind == "planner_response":
                live_stream = True
                content = record.get("content")
                text = content if isinstance(content, str) else ""
                if not text:
                    tools = record.get("tool_calls")
                    if isinstance(tools, list) and tools:
                        names = []
                        for tool in tools[:8]:
                            if isinstance(tool, Mapping) and isinstance(tool.get("name"), str):
                                names.append(tool["name"])
                            elif isinstance(tool, Mapping) and isinstance(tool.get("tool"), str):
                                names.append(tool["tool"])
                        text = f"planned inert foreign tool(s): {', '.join(names)}" if names else ""
                if text and include_turns:
                    self._append_turn(
                        turns,
                        {"role": "assistant", "content": text, "timestamp": timestamp},
                        query,
                        budget,
                        warnings,
                    )
                continue
            if kind in {
                "system_message",
                "checkpoint",
                "error_message",
                "generic",
            }:
                live_stream = True
                continue
            if kind in {
                "view_file",
                "list_directory",
                "grep_search",
                "code_action",
                "run_command",
                "invoke_subagent",
            }:
                live_stream = True
                content = record.get("content")
                if include_turns and isinstance(content, str) and content.strip():
                    self._append_turn(
                        turns,
                        {
                            "role": "tool",
                            "content": content,
                            "tool_name": raw_kind,
                            "timestamp": timestamp,
                        },
                        query,
                        budget,
                        warnings,
                    )
                continue
            if kind in _FILTERED_TYPES:
                continue
            if kind in _BINARY_TYPES:
                warnings.append("W_BINARY_OMITTED")
                continue
            if kind == "message":
                role = record.get("role")
                content = record.get("content")
                if not isinstance(role, str) or role.casefold() not in {"user", "assistant", "system", "thought", "control"}:
                    raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
                if role.casefold() in {"system", "thought", "control"}:
                    continue
                if not isinstance(content, str):
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
                if include_turns:
                    self._append_turn(
                        turns,
                        {"role": role.casefold(), "content": content, "timestamp": timestamp},
                        query,
                        budget,
                        warnings,
                    )
                continue
            if kind == "tool":
                output = record.get("output")
                if not isinstance(output, str):
                    if output is None:
                        warnings.append("W_MISSING_BLOB")
                        continue
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
                if include_turns:
                    self._append_turn(
                        turns,
                        {
                            "role": "tool",
                            "content": output,
                            "tool_name": record.get("name") if isinstance(record.get("name"), str) else None,
                            "timestamp": timestamp,
                        },
                        query,
                        budget,
                        warnings,
                    )
                continue
            if live_stream:
                # Unknown live step types: skip without failing the whole transcript.
                continue
            if any(key in record for key in ("role", "content", "message", "prompt", "output")):
                raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
            warnings.append("W_BROKEN_CHAIN")

        header_id = path_id
        cwd: str | None = None
        title: str | None = None
        created_at: str | None = min(created_values) if created_values else None
        updated_at: str | None = max(updated_values) if updated_values else None
        if header is not None:
            raw_cwd = header.get("cwd")
            if isinstance(raw_cwd, str):
                cwd = canonicalize_cwd(raw_cwd)
            elif raw_cwd is not None:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            title = header.get("title") if isinstance(header.get("title"), str) else None
            created_at = _rfc3339(header.get("created_at")) or created_at
            updated_at = _rfc3339(header.get("updated_at")) or updated_at
        elif live_stream:
            # Live streams lack a session header; path id is authoritative.
            header = {"conversation_id": path_id}
            if query.cwd:
                try:
                    cwd = canonicalize_cwd(query.cwd)
                except DiagnosticError:
                    cwd = None
            title = f"antigravity:{path_id[:8]}"
        if hint is not None:
            if hint.get("id") != path_id:
                warnings.append("W_STALE_INDEX")
            if cwd is None and isinstance(hint.get("cwd"), str):
                cwd = canonicalize_cwd(hint["cwd"])
            elif cwd is not None and isinstance(hint.get("cwd"), str) and not same_cwd(cwd, hint["cwd"]):
                warnings.append("W_STALE_INDEX")
            if title is None and isinstance(hint.get("title"), str):
                title = hint["title"]
            created_at = created_at or _rfc3339(hint.get("created_at"))
            updated_at = updated_at or _rfc3339(hint.get("updated_at"))
        if cwd is None:
            warnings.append("W_STALE_INDEX")
        summary = SessionSummary(
            source=self.key,
            session_id=header_id,
            source_path=path,
            title=title,
            cwd=cwd,
            created_at=created_at,
            updated_at=updated_at,
            provider=FORMAT_ID,
            warnings=tuple(dict.fromkeys(warnings)),
        )
        return summary, turns, warnings

    @staticmethod
    def _append_turn(
        turns: list[Turn],
        record: Mapping[str, Any],
        query: Query,
        budget: ReadBudget,
        warnings: list[str],
    ) -> None:
        bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        turn, found = sanitize_turn_record(record, ordinal=len(turns), bounds=bounds)
        warnings.extend(found)
        if turn is not None:
            budget.consume_turns()
            turns.append(turn)


ADAPTER = AntigravityAdapter()


def get_adapter() -> AntigravityAdapter:
    return ADAPTER
