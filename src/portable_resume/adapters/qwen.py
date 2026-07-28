"""Read Qwen Code project chat JSONL transcripts without invoking Qwen.

The adapter recognizes only the documented
``projects/<project>/chats/<session-id>.jsonl`` layout.  Runtime sidecars are
not transcripts, source files are opened through the shared stable no-follow
reader, and recovered records remain inert and untrusted.
"""

from __future__ import annotations

import json
import math
import os
import stat
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .base import CapabilityReport, ResolvedRef
from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import stable_read_windows, stable_scan_lines

FORMAT_ID = "qwen-chat-jsonl-v1"

# List/probe metadata windows: keep discovery off the full transcript budget.
_METADATA_HEAD_BYTES = 4 * 1024 * 1024
_METADATA_TAIL_BYTES = 64 * 1024

_ALLOWED_TYPES = frozenset({"user", "assistant", "tool_result", "system"})
_LEGACY_TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})
_NON_TEXT_PART_KEYS = frozenset(
    {
        "functioncall",
        "functionresponse",
        "filedata",
        "inlinedata",
        "videometadata",
        "codeexecutionresult",
        "executablecode",
    }
)
_ARTIFACT_SUBTYPES = frozenset(
    {"session_artifact_event", "session_artifact_snapshot"}
)


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise _DuplicateKey(key)
        output[key] = value
    return output


def _reject_constant(value: str) -> None:
    raise ValueError(value)


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(value)
    return parsed


def _check_shape(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise DiagnosticError.limit_exceeded()
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise DiagnosticError.limit_exceeded()
        for item in value.values():
            _check_shape(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        for item in value:
            _check_shape(item, depth + 1)


def _decode_record(
    raw: str | bytes,
    *,
    terminal_partial: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            if terminal_partial:
                return None, "W_PARTIAL_TAIL"
            raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID) from error
    else:
        text = raw
    stripped = text.strip()
    if not stripped:
        return None, None
    try:
        value = json.loads(
            stripped,
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError) as error:
        if terminal_partial:
            return None, "W_PARTIAL_TAIL"
        raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID) from error
    _check_shape(value)
    if not isinstance(value, dict):
        raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID)
    kind = value.get("type")
    if not isinstance(kind, str):
        raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID)
    if kind.casefold() not in _ALLOWED_TYPES:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="qwen", provider=FORMAT_ID)
    return value, None


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > DEFAULT_BOUNDS.ref_chars:
        raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID)
    if value in {".", ".."} or "/" in value or "\\" in value or any(ord(char) < 0x20 for char in value):
        raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID)
    return value


def _timestamp(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if not math.isfinite(seconds):
            return None
        if abs(seconds) >= 100_000_000_000:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
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
    if minutes <= 0:
        return True
    if summary.updated_at is None:
        return False
    try:
        updated = datetime.fromisoformat(summary.updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return updated >= datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _message_text(message: object) -> tuple[str | None, tuple[str, ...]]:
    """Extract inert text from a GenAI ``Content`` object's ``parts``.

    Current Qwen recordings store ``message: {role, parts}``.  Direct strings
    and the former ``content`` array remain accepted only as safe legacy text
    containers; no function, thought, file, or binary part is expanded.
    """

    warnings: list[str] = []
    if message is None:
        return None, ("W_MISSING_BLOB",)
    content: object = message
    if isinstance(message, Mapping):
        if "parts" in message:
            content = message.get("parts")
        elif "content" in message:
            content = message.get("content")
        else:
            return None, ("W_MISSING_BLOB",)
    if isinstance(content, str):
        return content, ()
    if not isinstance(content, list):
        return None, ("W_MISSING_BLOB",)

    pieces: list[str] = []
    for part in content:
        if isinstance(part, str):
            pieces.append(part)
            continue
        if not isinstance(part, Mapping):
            warnings.append("W_BINARY_OMITTED")
            continue
        normalized_keys = {str(key).casefold().replace("_", "") for key in part}
        raw_type = part.get("type")
        part_type = raw_type.casefold() if isinstance(raw_type, str) else None
        if (
            part.get("thought") is True
            or any("thought" in key or "reasoning" in key for key in normalized_keys)
            or part_type in {"thinking", "reasoning", "analysis", "system"}
        ):
            continue
        if normalized_keys & _NON_TEXT_PART_KEYS:
            warnings.append("W_BINARY_OMITTED")
            continue
        text = part.get("text")
        if isinstance(text, str) and (part_type is None or part_type in _LEGACY_TEXT_PART_TYPES):
            pieces.append(text)
            continue
        warnings.append("W_UNKNOWN_RECORD_SKIPPED")
    return ("\n".join(pieces) if pieces else None), tuple(dict.fromkeys(warnings))


def _aggregate_fragments(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coalesce Qwen's repeated-UUID physical fragments without hiding conflicts."""

    ordered: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        uuid = _identifier(record.get("uuid"))
        existing = by_id.get(uuid)
        if existing is None:
            copied = dict(record)
            message = record.get("message")
            if isinstance(message, Mapping):
                copied_message = dict(message)
                parts = message.get("parts")
                if isinstance(parts, list):
                    copied_message["parts"] = list(parts)
                copied["message"] = copied_message
            by_id[uuid] = copied
            ordered.append(copied)
            continue

        if (
            existing.get("parentUuid") != record.get("parentUuid")
            or str(existing.get("type", "")).casefold()
            != str(record.get("type", "")).casefold()
            or existing.get("sessionId") != record.get("sessionId")
        ):
            raise DiagnosticError(
                "E_CORRUPT_RECORD",
                source="qwen",
                provider=FORMAT_ID,
            )

        previous_message = existing.get("message")
        next_message = record.get("message")
        if next_message is None:
            pass
        elif previous_message is None:
            copied_message = dict(next_message) if isinstance(next_message, Mapping) else next_message
            if isinstance(copied_message, dict) and isinstance(copied_message.get("parts"), list):
                copied_message["parts"] = list(copied_message["parts"])
            existing["message"] = copied_message
        elif isinstance(previous_message, Mapping) and isinstance(next_message, Mapping):
            previous_role = previous_message.get("role")
            next_role = next_message.get("role")
            if (
                isinstance(previous_role, str)
                and isinstance(next_role, str)
                and previous_role != next_role
            ):
                raise DiagnosticError(
                    "E_CORRUPT_RECORD",
                    source="qwen",
                    provider=FORMAT_ID,
                )
            previous_parts = previous_message.get("parts")
            next_parts = next_message.get("parts")
            if not isinstance(previous_parts, list) or not isinstance(next_parts, list):
                raise DiagnosticError(
                    "E_CORRUPT_RECORD",
                    source="qwen",
                    provider=FORMAT_ID,
                )
            merged = dict(previous_message)
            merged["parts"] = [*previous_parts, *next_parts]
            existing["message"] = merged
        elif previous_message != next_message:
            raise DiagnosticError(
                "E_CORRUPT_RECORD",
                source="qwen",
                provider=FORMAT_ID,
            )

        previous_timestamp = existing.get("timestamp")
        next_timestamp = record.get("timestamp")
        if (
            isinstance(next_timestamp, str)
            and (
                not isinstance(previous_timestamp, str)
                or next_timestamp > previous_timestamp
            )
        ):
            existing["timestamp"] = next_timestamp
    return ordered


def _is_artifact(record: Mapping[str, Any]) -> bool:
    return (
        str(record.get("type", "")).casefold() == "system"
        and record.get("subtype") in _ARTIFACT_SUBTYPES
    )


def _lineage(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Select the last complete parent-linked branch, falling back to file order."""

    records = [
        record
        for record in _aggregate_fragments(records)
        if not _is_artifact(record)
    ]
    with_ids = [record for record in records if isinstance(record.get("uuid"), str)]
    has_parent_links = any(isinstance(record.get("parentUuid"), str) and record.get("parentUuid") for record in records)
    if not with_ids or not has_parent_links:
        return records, ()

    warnings: list[str] = []
    by_id: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, record in enumerate(records):
        raw_uuid = record.get("uuid")
        if not isinstance(raw_uuid, str):
            warnings.append("W_BROKEN_CHAIN")
            continue
        uuid = _identifier(raw_uuid)
        by_id[uuid] = (index, record)

    parent_ids = {
        parent
        for _, record in by_id.values()
        if isinstance((parent := record.get("parentUuid")), str) and parent
    }
    leaf_ids = [identifier for identifier in by_id if identifier not in parent_ids]
    valid_paths: list[tuple[int, list[dict[str, Any]]]] = []
    for leaf_id in leaf_ids:
        leaf_index, _ = by_id[leaf_id]
        path: list[dict[str, Any]] = []
        seen: set[str] = set()
        current: str | None = leaf_id
        complete = True
        while current is not None:
            if current in seen:
                raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID)
            seen.add(current)
            found = by_id.get(current)
            if found is None:
                complete = False
                break
            _, record = found
            path.append(record)
            parent = record.get("parentUuid")
            if parent is None or parent == "":
                current = None
            elif isinstance(parent, str):
                current = parent
            else:
                raise DiagnosticError("E_CORRUPT_RECORD", source="qwen", provider=FORMAT_ID)
        if complete:
            valid_paths.append((leaf_index, list(reversed(path))))
        else:
            warnings.append("W_BROKEN_CHAIN")

    if not valid_paths:
        warnings.append("W_BROKEN_CHAIN")
        return [], tuple(dict.fromkeys(warnings))
    # A later leaf represents the currently persisted branch.  Path length is
    # a deterministic tie-breaker for unusual duplicate-position test data.
    _, selected = max(valid_paths, key=lambda item: (item[0], len(item[1])))
    return selected, tuple(dict.fromkeys(warnings))


class QwenAdapter:
    key = "qwen"

    def __init__(self, *, root: str | None = None, read_hook: Any = None):
        self._configured_root = root
        self._read_hook = read_hook

    def _root(self, query: Query, *, required: bool = False) -> str | None:
        candidate = (
            query.source_root
            or self._configured_root
            or os.environ.get("QWEN_RUNTIME_DIR")
            or os.environ.get("QWEN_HOME")
            or os.path.expanduser("~/.qwen")
        )
        if not os.path.isdir(candidate):
            if required:
                raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
            return None
        return canonical_root(candidate)

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = self._root(query)
        return (root,) if root is not None else ()

    @staticmethod
    def _chat_layout_ok(path: str, root: str) -> bool:
        """Return True when path is projects/*/chats/*.jsonl or archive shape."""

        if not is_within(path, root):
            return False
        relative = os.path.relpath(path, root)
        parts = relative.split(os.sep)
        active_shape = len(parts) == 4 and parts[0] == "projects" and parts[2] == "chats"
        archive_shape = (
            len(parts) == 5
            and parts[0] == "projects"
            and parts[2] == "chats"
            and parts[3] == "archive"
        )
        if not active_shape and not archive_shape:
            return False
        basename = os.path.basename(path)
        if not basename.endswith(".jsonl") or basename.endswith(".runtime.json"):
            return False
        try:
            _identifier(basename[:-6])
        except DiagnosticError:
            return False
        return True

    def _exact_chat_path(self, root: str, query: Query) -> str | None:
        """Resolve an absolute path ref without store-wide discovery when possible."""

        ref = query.ref.strip() if query.ref else None
        if not ref or not os.path.isabs(ref):
            return None
        path = os.path.abspath(ref)
        if os.path.islink(path):
            raise DiagnosticError.unsafe_path()
        if not is_within(path, root):
            raise DiagnosticError.unsafe_path()
        if not self._chat_layout_ok(path, root):
            raise DiagnosticError.unsafe_path()
        try:
            mode = os.lstat(path).st_mode
        except OSError as error:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID) from error
        if not stat.S_ISREG(mode):
            raise DiagnosticError.unsafe_path()
        return path

    def _session_paths(self, root: str) -> list[str]:
        """Discover chat JSONL paths under projects/*/chats{,/archive}.

        Directory membership is bounded *before* sorting or materializing an
        unbounded ``sorted(os.scandir(...))`` snapshot: each observed entry
        increments the counter and exceeding ``scanned_records`` fails closed.
        Only the admitted set is sorted; final ranking is mtime newest-first.
        """

        projects = os.path.join(root, "projects")
        if not os.path.exists(projects):
            return []
        if os.path.islink(projects) or not os.path.isdir(projects):
            raise DiagnosticError.unsafe_path()
        admitted_projects: list[Any] = []
        paths: list[str] = []
        observed = 0

        def _observe() -> None:
            nonlocal observed
            observed += 1
            if observed > DEFAULT_BOUNDS.scanned_records:
                raise DiagnosticError.limit_exceeded()

        try:
            with os.scandir(projects) as project_it:
                for project in project_it:
                    _observe()
                    admitted_projects.append(project)
        except OSError as error:
            raise DiagnosticError.source_busy(provider=FORMAT_ID) from error

        admitted_projects.sort(key=lambda entry: entry.name)
        for project in admitted_projects:
            if project.is_symlink():
                raise DiagnosticError.unsafe_path()
            mode = project.stat(follow_symlinks=False).st_mode
            if not stat.S_ISDIR(mode):
                if stat.S_ISREG(mode):
                    continue
                raise DiagnosticError.unsafe_path()
            chats = os.path.join(project.path, "chats")
            if not os.path.exists(chats):
                continue
            if os.path.islink(chats) or not os.path.isdir(chats):
                raise DiagnosticError.unsafe_path()
            for directory in (chats, os.path.join(chats, "archive")):
                if directory != chats:
                    if not os.path.exists(directory):
                        continue
                    if os.path.islink(directory) or not os.path.isdir(directory):
                        raise DiagnosticError.unsafe_path()
                chat_admitted: list[Any] = []
                try:
                    with os.scandir(directory) as chat_it:
                        for entry in chat_it:
                            _observe()
                            chat_admitted.append(entry)
                except OSError as error:
                    raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
                chat_admitted.sort(key=lambda entry: entry.name)
                for entry in chat_admitted:
                    if entry.is_symlink():
                        raise DiagnosticError.unsafe_path()
                    entry_mode = entry.stat(follow_symlinks=False).st_mode
                    if not stat.S_ISREG(entry_mode):
                        if stat.S_ISDIR(entry_mode):
                            # ``archive`` is scanned explicitly above.
                            continue
                        raise DiagnosticError.unsafe_path()
                    if entry.name.endswith(".runtime.json") or not entry.name.endswith(".jsonl"):
                        continue
                    _identifier(entry.name[:-6])
                    paths.append(entry.path)
        paths.sort(key=lambda path: (-os.lstat(path).st_mtime_ns, path))
        if len(paths) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        return paths

    def probe(self, query: Query) -> CapabilityReport:
        root = self._root(query)
        if root is None:
            return CapabilityReport(self.key, None, "unavailable")
        exact = None
        if query.ref and os.path.isabs(query.ref.strip()):
            try:
                exact = self._exact_chat_path(root, query)
            except DiagnosticError as error:
                if error.code == "E_NO_MATCH":
                    exact = None
                else:
                    raise
        paths = [exact] if exact is not None else self._session_paths(root)
        if not paths:
            return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
        return CapabilityReport(
            self.key,
            FORMAT_ID,
            "supported",
            root=root,
            evidence=("projects/<project>/chats/<session-id>.jsonl",),
        )

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = self._root(query, required=True)
        assert root is not None
        exact = self._exact_chat_path(root, query)
        if exact is not None:
            paths = [exact]
        else:
            paths = self._session_paths(root)
        if not paths:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        output: list[SessionSummary] = []
        for path in paths:
            session_id = _identifier(os.path.basename(path)[:-6])
            summary = self._list_summary_from_path(
                path,
                root,
                budget,
                expected_id=session_id,
            )
            if _eligible(summary, query):
                output.append(summary)
                if len(output) >= DEFAULT_BOUNDS.listed_sessions:
                    break
        return output

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = self._root(query, required=True)
        assert root is not None
        if ref.provider != FORMAT_ID:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=ref.provider)
        if ref.source_path is None or not is_within(ref.source_path, root):
            raise DiagnosticError.unsafe_path()
        if not self._chat_layout_ok(ref.source_path, root):
            raise DiagnosticError.unsafe_path()
        basename = os.path.basename(ref.source_path)
        if _identifier(basename[:-6]) != ref.session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        records, warnings = self._records(
            ref.source_path,
            root,
            budget,
            transcript=True,
            expected_id=ref.session_id,
        )
        summary = self._summary(ref.source_path, ref.session_id, records, warnings)
        turns: list[Turn] = []
        turn_warnings = list(warnings)
        bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        for record in records:
            kind = str(record["type"]).casefold()
            if kind == "system":
                continue
            text, found = _message_text(record.get("message"))
            turn_warnings.extend(found)
            if text is None:
                continue
            role = "tool" if kind == "tool_result" else kind
            normalized, found = sanitize_turn_record(
                {
                    "role": role,
                    "content": text,
                    "timestamp": _timestamp(record.get("timestamp")),
                    "tool_name": "tool_result" if role == "tool" else None,
                },
                ordinal=len(turns),
                bounds=bounds,
            )
            turn_warnings.extend(found)
            if normalized is not None:
                budget.consume_turns()
                turns.append(normalized)
        values = tuple(turns)
        return Session(
            source=self.key,
            session_id=summary.session_id,
            source_path=summary.source_path,
            title=summary.title,
            cwd=summary.cwd,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            source_repo_root=summary.source_repo_root,
            last_user_request=next((turn.content for turn in reversed(values) if turn.role == "user"), None),
            last_assistant_action=next((turn.content for turn in reversed(values) if turn.role == "assistant"), None),
            turns=values,
            warnings=tuple(dict.fromkeys(turn_warnings)),
        )

    def _scan_metadata_chunk(
        self,
        data: bytes,
        *,
        budget: ReadBudget,
        expected_id: str,
        timestamps: list[str],
        state: dict[str, Any],
        warnings: list[str],
        starts_mid_line: bool,
        ends_at_eof: bool,
        stop_when_primary_ready: bool,
    ) -> None:
        """Decode metadata lines from a head/tail window under scanned_records."""

        lines = data.splitlines(keepends=True)
        start = 1 if starts_mid_line and lines else 0
        for index in range(start, len(lines)):
            raw = lines[index]
            is_last = index == len(lines) - 1
            has_terminator = raw.endswith((b"\n", b"\r"))
            if is_last and not has_terminator and not ends_at_eof:
                # Incomplete mid-file boundary — not a terminal partial.
                break
            budget.consume_records()
            terminal_partial = is_last and not has_terminator and ends_at_eof
            record, warning = _decode_record(raw, terminal_partial=terminal_partial)
            if warning is not None:
                warnings.append(warning)
            if record is None:
                if terminal_partial and warning == "W_PARTIAL_TAIL":
                    break
                continue
            state["recognized"] = int(state.get("recognized", 0)) + 1
            record_session = record.get("sessionId")
            if record_session is not None and record_session != expected_id:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            if _is_artifact(record):
                continue
            stamp = _timestamp(record.get("timestamp"))
            if stamp is not None:
                timestamps.append(stamp)
            raw_cwd = record.get("cwd")
            if isinstance(raw_cwd, str) and os.path.isabs(raw_cwd):
                # Prefer later absolute cwd (tail windows update this).
                state["cwd"] = canonicalize_cwd(raw_cwd)
            if state.get("title") is None and str(record.get("type", "")).casefold() == "user":
                text, _ = _message_text(record.get("message"))
                if text:
                    state["title"] = text[: DEFAULT_BOUNDS.title_chars]
            if (
                stop_when_primary_ready
                and state.get("title") is not None
                and state.get("cwd") is not None
                and timestamps
            ):
                break

    def _list_summary_from_path(
        self,
        path: str,
        root: str,
        budget: ReadBudget,
        *,
        expected_id: str,
    ) -> SessionSummary:
        """Build a SessionSummary from bounded head/tail metadata only.

        Does not build the UUID lineage graph or charge ``transcript_records``.
        Aggregate file size uses ``source_read_bytes`` via ``stable_read_windows``;
        each decoded metadata line charges ``scanned_records``.
        """

        windows = stable_read_windows(
            path,
            root=root,
            head_bytes=_METADATA_HEAD_BYTES,
            tail_bytes=_METADATA_TAIL_BYTES,
            max_bytes=min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
            attempts=min(budget.limits.snapshot_attempts, DEFAULT_BOUNDS.snapshot_attempts),
            membership_limit=min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records),
            budget=budget,
            hook=self._read_hook,
        )
        timestamps: list[str] = []
        warnings: list[str] = []
        state: dict[str, Any] = {"recognized": 0, "cwd": None, "title": None}
        full_in_head = windows.fingerprint.size <= len(windows.head)
        self._scan_metadata_chunk(
            windows.head,
            budget=budget,
            expected_id=expected_id,
            timestamps=timestamps,
            state=state,
            warnings=warnings,
            starts_mid_line=False,
            ends_at_eof=full_in_head,
            # Large chats: stop once list fields are known so head lines do not
            # exhaust scanned_records; small files still scan to EOF for accuracy.
            stop_when_primary_ready=not full_in_head,
        )
        if not full_in_head and windows.tail:
            tail = windows.tail
            starts_mid_line = windows.tail_offset > 0
            if windows.tail_offset < len(windows.head):
                overlap = len(windows.head) - windows.tail_offset
                tail = tail[min(overlap, len(tail)) :]
                starts_mid_line = bool(tail)
            self._scan_metadata_chunk(
                tail,
                budget=budget,
                expected_id=expected_id,
                timestamps=timestamps,
                state=state,
                warnings=warnings,
                starts_mid_line=starts_mid_line,
                ends_at_eof=True,
                stop_when_primary_ready=False,
            )
        if int(state["recognized"]) == 0:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        known_times = timestamps
        return SessionSummary(
            source=self.key,
            session_id=expected_id,
            source_path=path,
            title=state.get("title") if isinstance(state.get("title"), str) else None,
            cwd=state.get("cwd") if isinstance(state.get("cwd"), str) else None,
            created_at=min(known_times) if known_times else None,
            updated_at=max(known_times) if known_times else None,
            source_repo_root=None,
            provider=FORMAT_ID,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _records(
        self,
        path: str,
        root: str,
        budget: ReadBudget,
        *,
        transcript: bool,
        expected_id: str,
    ) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
        """Stream JSONL under source_read_bytes + per-line record_bytes.

        When ``transcript`` is True (show), physical lines charge
        ``transcript_records``. List no longer uses this path for full files;
        callers pass ``transcript=True`` for show lineage parsing.
        """

        records: list[dict[str, Any]] = []
        warnings: list[str] = []
        recognized = 0
        for line in stable_scan_lines(
            path,
            root=root,
            budget=budget,
            charge_transcript=transcript,
            hook=self._read_hook,
        ):
            if not line.utf8_valid:
                if not line.terminated:
                    warnings.append("W_PARTIAL_TAIL")
                    continue
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            text = line.text.strip()
            if not text:
                continue
            record, warning = _decode_record(text, terminal_partial=not line.terminated)
            if warning is not None:
                warnings.append(warning)
            if record is None:
                if not line.terminated and warning == "W_PARTIAL_TAIL":
                    break
                continue
            recognized += 1
            record_session = record.get("sessionId")
            if record_session is not None and record_session != expected_id:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            records.append(record)
        if recognized == 0:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID)
        selected, lineage_warnings = _lineage(records)
        warnings.extend(lineage_warnings)
        return selected, tuple(dict.fromkeys(warnings))

    def _summary(
        self,
        path: str,
        session_id: str,
        records: list[dict[str, Any]],
        warnings: tuple[str, ...],
    ) -> SessionSummary:
        timestamps = [_timestamp(record.get("timestamp")) for record in records]
        known_times = [value for value in timestamps if value is not None]
        cwd: str | None = None
        for record in reversed(records):
            raw_cwd = record.get("cwd")
            if isinstance(raw_cwd, str) and os.path.isabs(raw_cwd):
                cwd = canonicalize_cwd(raw_cwd)
                break
        title: str | None = None
        for record in records:
            if str(record.get("type", "")).casefold() != "user":
                continue
            text, _ = _message_text(record.get("message"))
            if text:
                title = text[: DEFAULT_BOUNDS.title_chars]
                break
        return SessionSummary(
            source=self.key,
            session_id=session_id,
            source_path=path,
            title=title,
            cwd=cwd,
            created_at=min(known_times) if known_times else None,
            updated_at=max(known_times) if known_times else None,
            source_repo_root=None,
            provider=FORMAT_ID,
            warnings=warnings,
        )


ADAPTER = QwenAdapter()


def get_adapter() -> QwenAdapter:
    return ADAPTER
