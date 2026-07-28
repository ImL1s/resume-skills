"""Read Pi agent versioned tree JSONL sessions without invoking Pi.

Discovery is limited to ``sessions/--<cwd-slug>--/*.jsonl`` under the agent root
(``~/.pi/agent`` by default).  Source files are scanned through
``stable_scan_lines``; stores are never mutated and no Pi runtime is imported.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .base import CapabilityReport, ResolvedRef
from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, require_regular_no_symlinks, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import stable_read_windows, stable_scan_lines

FORMAT_ID_V3 = "pi-session-jsonl-v3"
FORMAT_ID_V2 = "pi-session-jsonl-v2"
_SUPPORTED_VERSIONS = {2: FORMAT_ID_V2, 3: FORMAT_ID_V3}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,1023}$")


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


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


def _loads_line(text: str, *, provider: str, optional: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError, UnicodeEncodeError) as error:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT" if optional else "E_CORRUPT_RECORD", source="pi", provider=provider) from error
    _check_shape(value)
    if not isinstance(value, dict):
        raise DiagnosticError("E_CORRUPT_RECORD", source="pi", provider=provider)
    return value


def _identifier(value: object, *, provider: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None or value in {".", ".."}:
        raise DiagnosticError("E_CORRUPT_RECORD", source="pi", provider=provider)
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


def _cwd_slug(cwd: str) -> str:
    text = os.path.abspath(cwd)
    if text.startswith("/private/"):
        text = text[len("/private") :]
    text = text.strip("/")
    body = "".join(char if char.isalnum() else "-" for char in text)
    return f"--{body}--"


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


def _session_from(summary: SessionSummary, turns: list[Turn], warnings: list[str]) -> Session:
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


def _assistant_text(message: Mapping[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    warnings: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        return content, ()
    if not isinstance(content, list):
        return None, ("W_MISSING_BLOB",)
    pieces: list[str] = []
    for part in content:
        if not isinstance(part, Mapping):
            warnings.append("W_BINARY_OMITTED")
            continue
        part_type = part.get("type")
        if part_type == "text" and isinstance(part.get("text"), str):
            pieces.append(part["text"])
        elif part_type == "toolCall":
            warnings.append("W_MISSING_BLOB")
        else:
            warnings.append("W_BINARY_OMITTED")
    if not pieces:
        return None, tuple(dict.fromkeys(warnings)) if warnings else ("W_MISSING_BLOB",)
    return "\n".join(pieces), tuple(dict.fromkeys(warnings))


def _tool_result_text(message: Mapping[str, Any]) -> str | None:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "text" and isinstance(part.get("text"), str):
                pieces.append(part["text"])
        return "\n".join(pieces) if pieces else None
    return None


class PiAdapter:
    key = "pi"

    def __init__(self, *, root: str | None = None, read_hook: Any = None):
        self._configured_root = root
        self._read_hook = read_hook

    def _root(self, query: Query, *, required: bool = False) -> str | None:
        candidate = query.source_root or self._configured_root or os.path.expanduser("~/.pi/agent")
        if not os.path.isdir(candidate):
            if required:
                raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key)
            return None
        return canonical_root(candidate)

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = self._root(query)
        return (root,) if root is not None else ()

    def _session_paths(self, root: str, query: Query, budget: ReadBudget) -> list[str]:
        ref = query.ref.strip() if query.ref else None
        if ref and os.path.isabs(ref):
            # Lexical no-symlink validation before any realpath identity use.
            safe, _ = require_regular_no_symlinks(ref, root)
            path = canonicalize_cwd(safe)
            if path.endswith(".jsonl"):
                return [path]
            raise DiagnosticError("E_NO_MATCH", source=self.key)
        if query.cwd is None:
            return []
        bucket = os.path.join(root, "sessions", _cwd_slug(query.cwd))
        if os.path.islink(bucket):
            raise DiagnosticError.unsafe_path()
        if not os.path.isdir(bucket):
            return []
        if not is_within(bucket, root):
            raise DiagnosticError.unsafe_path()
        scanned = 0
        names: list[str] = []
        try:
            with os.scandir(bucket) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > DEFAULT_BOUNDS.scanned_records:
                        raise DiagnosticError.limit_exceeded()
                    names.append(entry.name)
        except DiagnosticError:
            raise
        except OSError as error:
            raise DiagnosticError.source_busy(provider=FORMAT_ID_V3) from error
        names.sort()
        paths: list[str] = []
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(bucket, name)
            try:
                mode = os.lstat(path).st_mode
            except OSError:
                continue
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                if stat.S_ISLNK(mode):
                    raise DiagnosticError.unsafe_path()
                continue
            if not is_within(path, root):
                raise DiagnosticError.unsafe_path()
            paths.append(path)

        def _mtime_key(item: str) -> float:
            try:
                return -os.lstat(item).st_mtime
            except OSError:
                return 0.0

        paths.sort(key=lambda item: (_mtime_key(item), item))
        return paths

    def probe(self, query: Query) -> CapabilityReport:
        root = self._root(query)
        if root is None:
            return CapabilityReport(self.key, None, "unavailable")
        budget = ReadBudget()
        paths = self._session_paths(root, query, budget)
        if not paths:
            return CapabilityReport(self.key, FORMAT_ID_V3, "unsupported", root=root)
        try:
            header, provider = self._read_header(paths[0], root, budget)
        except DiagnosticError as error:
            if error.code in {"E_UNSUPPORTED_FORMAT", "E_CORRUPT_RECORD"}:
                return CapabilityReport(self.key, FORMAT_ID_V3, "unsupported", root=root)
            raise
        return CapabilityReport(
            self.key,
            provider,
            "supported",
            root=root,
            evidence=("sessions:--cwd-slug--/*.jsonl",),
        )

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = self._root(query, required=True)
        assert root is not None
        paths = self._session_paths(root, query, budget)
        if not paths:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID_V3)
        output: list[SessionSummary] = []
        for path in paths:
            header, provider = self._read_header(path, root, budget)
            meta, meta_warnings = self._scan_metadata(path, root, budget, provider=provider)
            summary = SessionSummary(
                source=self.key,
                session_id=header["session_id"],
                source_path=path,
                cwd=header.get("cwd"),
                created_at=meta.get("created_at") or header.get("timestamp"),
                updated_at=meta.get("updated_at") or header.get("timestamp"),
                provider=provider,
                warnings=tuple(dict.fromkeys((*header.get("warnings", ()), *meta_warnings))),
            )
            if _eligible(summary, query):
                output.append(summary)
        return output

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = self._root(query, required=True)
        assert root is not None
        provider = ref.provider or FORMAT_ID_V3
        if provider not in {FORMAT_ID_V2, FORMAT_ID_V3}:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=provider)
        if ref.source_path is None or not is_within(ref.source_path, root):
            raise DiagnosticError.unsafe_path()
        header, detected = self._read_header(ref.source_path, root, budget)
        if detected != provider:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=provider)
        if header["session_id"] != ref.session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
        turns, scan_warnings = self._scan_turns(
            ref.source_path,
            root,
            budget,
            provider=provider,
            query=query,
        )
        summary = SessionSummary(
            source=self.key,
            session_id=ref.session_id,
            source_path=ref.source_path,
            cwd=header.get("cwd"),
            created_at=header.get("timestamp"),
            updated_at=turns[-1].timestamp if turns else header.get("timestamp"),
            provider=provider,
            warnings=tuple(dict.fromkeys((*header.get("warnings", ()), *scan_warnings))),
        )
        return _session_from(summary, turns, scan_warnings)

    def _read_header(self, path: str, root: str, budget: ReadBudget) -> tuple[dict[str, Any], str]:
        windows = stable_read_windows(
            path,
            root=root,
            head_bytes=64 * 1024,
            tail_bytes=0,
            budget=budget,
            hook=self._read_hook,
        )
        try:
            first = windows.head.split(b"\n", 1)[0].decode("utf-8")
        except UnicodeDecodeError as error:
            raise DiagnosticError(
                "E_CORRUPT_RECORD",
                source=self.key,
                provider=FORMAT_ID_V3,
            ) from error
        return self._parse_header_line(first)

    def _parse_header_line(self, first: str) -> tuple[dict[str, Any], str]:
        if not first.strip():
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID_V3)
        record = _loads_line(first, provider=FORMAT_ID_V3, optional=True)
        if record.get("type") != "session":
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID_V3)
        version = record.get("version")
        if not isinstance(version, int) or version not in _SUPPORTED_VERSIONS:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=FORMAT_ID_V3)
        provider = _SUPPORTED_VERSIONS[version]
        session_id = _identifier(record.get("id"), provider=provider)
        cwd = record.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
        if isinstance(cwd, str) and cwd:
            cwd = canonicalize_cwd(cwd)
        return {
            "session_id": session_id,
            "cwd": cwd,
            "timestamp": _timestamp(record.get("timestamp")),
            "warnings": (),
        }, provider

    def _scan_metadata(
        self,
        path: str,
        root: str,
        budget: ReadBudget,
        *,
        provider: str,
    ) -> tuple[dict[str, str | None], list[str]]:
        windows = stable_read_windows(
            path,
            root=root,
            head_bytes=64 * 1024,
            tail_bytes=64 * 1024,
            budget=budget,
            hook=self._read_hook,
        )
        timestamps: list[str] = []
        warnings: list[str] = []
        chunks: list[tuple[bytes, bool, bool]] = [(windows.head, False, windows.fingerprint.size <= len(windows.head))]
        if windows.tail and windows.fingerprint.size > len(windows.head):
            overlap = max(0, len(windows.head) - windows.tail_offset)
            tail = windows.tail[overlap:]
            if tail:
                # Mid-line only when the absolute byte before this fragment is not a
                # newline (exact record boundaries must keep the first tail record).
                abs_start = windows.tail_offset + overlap
                starts_mid = False
                if abs_start > 0:
                    if abs_start <= len(windows.head):
                        preceding = windows.head[abs_start - 1 : abs_start]
                    else:
                        preceding = windows.tail[abs_start - windows.tail_offset - 1 : abs_start - windows.tail_offset]
                    starts_mid = preceding not in (b"\n", b"\r")
                chunks.append((tail, starts_mid, True))
        first_line = True
        for chunk, starts_mid_line, ends_at_eof in chunks:
            # Only the first fragment of a mid-line tail window is partial; clear
            # the flag after handling it so later complete records are scanned.
            skip_leading_partial = starts_mid_line
            for raw in chunk.split(b"\n"):
                if not raw.strip():
                    continue
                if first_line:
                    first_line = False
                    if skip_leading_partial:
                        skip_leading_partial = False
                        continue
                    continue  # session header
                if skip_leading_partial:
                    skip_leading_partial = False
                    # Boundary-aligned tails can still be flagged mid-line; keep
                    # the fragment when it parses as a complete record.
                    try:
                        text = raw.decode("utf-8")
                        record = _loads_line(text, provider=provider)
                    except (UnicodeDecodeError, DiagnosticError):
                        continue
                    stamp = _timestamp(record.get("timestamp"))
                    if stamp is not None:
                        timestamps.append(stamp)
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    warnings.append("W_BROKEN_CHAIN")
                    continue
                try:
                    record = _loads_line(text, provider=provider)
                except DiagnosticError as error:
                    if error.code == "E_CORRUPT_RECORD":
                        warnings.append("W_BROKEN_CHAIN")
                        continue
                    raise
                stamp = _timestamp(record.get("timestamp"))
                if stamp is not None:
                    timestamps.append(stamp)
            if ends_at_eof:
                break
        if windows.tail and windows.fingerprint.size > len(windows.head):
            try:
                tail_line = windows.tail.rsplit(b"\n", 1)[-1].strip()
            except (IndexError, ValueError):
                tail_line = b""
            if tail_line:
                try:
                    record = _loads_line(tail_line.decode("utf-8"), provider=provider)
                except (DiagnosticError, UnicodeDecodeError):
                    pass
                else:
                    stamp = _timestamp(record.get("timestamp"))
                    if stamp is not None:
                        timestamps.append(stamp)
        return {
            "created_at": min(timestamps) if timestamps else None,
            "updated_at": max(timestamps) if timestamps else None,
        }, warnings

    def _scan_turns(
        self,
        path: str,
        root: str,
        budget: ReadBudget,
        *,
        provider: str,
        query: Query,
    ) -> tuple[list[Turn], list[str]]:
        entries: list[dict[str, Any]] = []
        warnings: list[str] = []
        first = True
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
                    continue
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            if first:
                first = False
                continue
            if not line.text.strip():
                continue
            try:
                record = _loads_line(line.text, provider=provider)
            except DiagnosticError as error:
                if error.code == "E_CORRUPT_RECORD" and not line.terminated:
                    warnings.append("W_PARTIAL_TAIL")
                    continue
                raise
            entries.append(record)
        if not entries:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=provider)
        active = self._active_path(entries, provider=provider)
        turns: list[Turn] = []
        for entry in active:
            emitted, found = self._entry_turns(
                entry,
                provider=provider,
                ordinal=len(turns),
                query=query,
                budget=budget,
                warnings=warnings,
            )
            warnings.extend(found)
            turns.extend(emitted)
        if not turns:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=provider)
        return turns, warnings

    def _active_path(self, entries: list[dict[str, Any]], *, provider: str) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for entry in entries:
            entry_id = entry.get("id")
            if not isinstance(entry_id, str):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            if entry_id in by_id:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            by_id[entry_id] = entry
        leaf = entries[-1]
        leaf_id = _identifier(leaf.get("id"), provider=provider)
        path_ids: list[str] = []
        current_id: str | None = leaf_id
        visited: set[str] = set()
        while current_id is not None:
            if current_id in visited:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            visited.add(current_id)
            path_ids.append(current_id)
            entry = by_id.get(current_id)
            if entry is None:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            if entry.get("type") == "compaction":
                first_kept = entry.get("firstKeptEntryId")
                if not isinstance(first_kept, str) or first_kept not in by_id:
                    raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
                current_id = first_kept
                continue
            parent = entry.get("parentId")
            if parent is None:
                break
            if not isinstance(parent, str):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            current_id = parent
        path_ids.reverse()
        return [by_id[item] for item in path_ids]

    def _entry_turns(
        self,
        entry: dict[str, Any],
        *,
        provider: str,
        ordinal: int,
        query: Query,
        budget: ReadBudget,
        warnings: list[str],
    ) -> tuple[list[Turn], list[str]]:
        kind = entry.get("type")
        timestamp = _timestamp(entry.get("timestamp"))
        found: list[str] = []
        if kind == "compaction":
            summary = entry.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                found.append("W_MISSING_BLOB")
                return [], found
            return self._append_turn({"role": "assistant", "content": summary, "timestamp": timestamp}, ordinal, query, budget, found), found
        if kind == "custom_message":
            if entry.get("display") is not True:
                return [], found
            content = entry.get("content")
            if not isinstance(content, str) or not content.strip():
                found.append("W_MISSING_BLOB")
                return [], found
            return self._append_turn({"role": "user", "content": content, "timestamp": timestamp}, ordinal, query, budget, found), found
        if kind == "branch_summary":
            return [], found
        if kind != "message":
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=provider)
        message = entry.get("message")
        if not isinstance(message, Mapping):
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
        role = message.get("role")
        if role == "user":
            content = message.get("content")
            if not isinstance(content, str):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            return self._append_turn({"role": "user", "content": content, "timestamp": timestamp or _timestamp(message.get("timestamp"))}, ordinal, query, budget, found), found
        if role == "assistant":
            text, text_warnings = _assistant_text(message)
            found.extend(text_warnings)
            if text is None:
                return [], found
            return self._append_turn(
                {"role": "assistant", "content": text, "timestamp": timestamp or _timestamp(message.get("timestamp"))},
                ordinal,
                query,
                budget,
                found,
            ), found
        if role == "toolResult":
            text = _tool_result_text(message)
            if text is None:
                found.append("W_MISSING_BLOB")
                return [], found
            tool_name = message.get("toolName")
            return self._append_turn(
                {
                    "role": "tool",
                    "content": text,
                    "tool_name": tool_name if isinstance(tool_name, str) else None,
                    "timestamp": timestamp or _timestamp(message.get("timestamp")),
                },
                ordinal,
                query,
                budget,
                found,
            ), found
        if role == "bashExecution":
            command = message.get("command")
            output = message.get("output")
            if not isinstance(command, str):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=provider)
            pieces = [f"$ {command}"]
            if isinstance(output, str) and output:
                pieces.append(output.rstrip("\n"))
            return self._append_turn(
                {
                    "role": "tool",
                    "content": "\n".join(pieces),
                    "tool_name": "bash",
                    "timestamp": timestamp or _timestamp(message.get("timestamp")),
                },
                ordinal,
                query,
                budget,
                found,
            ), found
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=self.key, provider=provider)

    def _append_turn(
        self,
        record: dict[str, Any],
        ordinal: int,
        query: Query,
        budget: ReadBudget,
        warnings: list[str],
    ) -> list[Turn]:
        bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        turn, found = sanitize_turn_record(record, ordinal=ordinal, bounds=bounds)
        warnings.extend(found)
        if turn is None:
            return []
        budget.consume_turns()
        return [turn]


ADAPTER = PiAdapter()


def get_adapter() -> PiAdapter:
    return ADAPTER
