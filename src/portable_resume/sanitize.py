"""Deterministic removal of privileged records, controls, binary data, and obvious secrets."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from .bounds import DEFAULT_BOUNDS, Bounds
from .diagnostics import WARNING_CODES
from .model import Turn

_ANSI = re.compile(r"(?:\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\))")
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*"),
    re.compile(r"(?i)(\b(?:password|passwd|api[_-]?key|access[_-]?token|token|secret)\s*[:=]\s*)[^\s,;]+"),
)
_FORBIDDEN_ROLES = frozenset({"system", "developer", "reasoning", "thinking", "control", "internal"})
_FORBIDDEN_KEYS = (
    "system_prompt",
    "developer",
    "reasoning",
    "thinking",
    "signature",
    "encrypted",
    "ciphertext",
    "private_key",
    "credentials",
)
_BIDI_ZERO_WIDTH = frozenset(
    {
        "\u061c",
        "\u200b",
        "\u200c",
        "\u200d",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2060",
        "\u2061",
        "\u2062",
        "\u2063",
        "\u2064",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)


@dataclass(frozen=True, slots=True)
class SanitizedText:
    text: str
    warnings: tuple[str, ...] = ()
    truncated: bool = False


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value in WARNING_CODES))


def sanitize_text(value: str | bytes, *, max_chars: int, binary: bool = False) -> SanitizedText:
    """Return bounded printable NFC text; binary containers are omitted, never expanded."""

    warnings: list[str] = []
    if binary:
        return SanitizedText("", ("W_BINARY_OMITTED",), False)
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="replace")
        if "\ufffd" in decoded:
            warnings.append("W_CONTROLS_REMOVED")
        text = decoded
    elif isinstance(value, str):
        text = value
    else:
        return SanitizedText("", ("W_BINARY_OMITTED",), False)

    replaced = _ANSI.sub("", text)
    if replaced != text:
        warnings.append("W_CONTROLS_REMOVED")
    text = replaced.replace("\r\n", "\n").replace("\r", "\n")
    cleaned: list[str] = []
    controls_removed = False
    for char in text:
        point = ord(char)
        if char in _BIDI_ZERO_WIDTH or (point < 0x20 and char not in "\n\t") or 0x7F <= point <= 0x9F:
            controls_removed = True
            continue
        cleaned.append(char)
    if controls_removed:
        warnings.append("W_CONTROLS_REMOVED")
    text = unicodedata.normalize("NFC", "".join(cleaned))

    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(\\b"):
            redacted, count = pattern.subn(r"\1[REDACTED]", redacted)
        else:
            redacted, count = pattern.subn("[REDACTED]", redacted)
        if count:
            warnings.append("W_METADATA_REDACTED")
    truncated = len(redacted) > max_chars
    if truncated:
        redacted = redacted[:max_chars]
        warnings.append("W_TRUNCATED")
    return SanitizedText(redacted, _dedupe(warnings), truncated)


def sanitize_inline(value: str | bytes, *, max_chars: int) -> SanitizedText:
    """Sanitize one recovered metadata value into a single inert display line."""

    cleaned = sanitize_text(value, max_chars=max_chars)
    warnings = list(cleaned.warnings)
    single_line = " ".join(cleaned.text.replace("\t", " ").splitlines())
    if single_line != cleaned.text:
        warnings.append("W_CONTROLS_REMOVED")
    if len(single_line) > max_chars:
        single_line = single_line[:max_chars]
        warnings.append("W_TRUNCATED")
    return SanitizedText(single_line, _dedupe(warnings), cleaned.truncated or "W_TRUNCATED" in warnings)


def sanitize_metadata(value: Mapping[str, Any], *, max_depth: int = 8) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Allow printable scalar/list/map metadata while dropping privileged containers."""

    warnings: list[str] = []

    def walk(item: Any, depth: int) -> Any:
        if depth > max_depth:
            warnings.append("W_TRUNCATED")
            return None
        if isinstance(item, Mapping):
            output: dict[str, Any] = {}
            for raw_key in sorted(item, key=lambda entry: str(entry)):
                key = str(raw_key)
                lowered = key.casefold().replace("-", "_")
                if any(fragment in lowered for fragment in _FORBIDDEN_KEYS) or lowered in {
                    "password",
                    "passwd",
                    "api_key",
                    "access_token",
                    "secret",
                }:
                    warnings.append("W_METADATA_REDACTED")
                    continue
                output[key] = walk(item[raw_key], depth + 1)
            return output
        if isinstance(item, (list, tuple)):
            return [walk(entry, depth + 1) for entry in item[:256]]
        if isinstance(item, bytes):
            warnings.append("W_BINARY_OMITTED")
            return None
        if isinstance(item, str):
            cleaned = sanitize_text(item, max_chars=4096)
            warnings.extend(cleaned.warnings)
            return cleaned.text
        if item is None or isinstance(item, (bool, int, float)):
            return item
        warnings.append("W_BINARY_OMITTED")
        return None

    result = walk(value, 0)
    return (result if isinstance(result, dict) else {}), _dedupe(warnings)


def sanitize_turn_record(
    record: Mapping[str, Any],
    *,
    ordinal: int,
    bounds: Bounds = DEFAULT_BOUNDS,
) -> tuple[Turn | None, tuple[str, ...]]:
    """Convert an allowlisted record into an inert turn or drop privileged/binary records."""

    role = str(record.get("role", "")).casefold()
    if role in _FORBIDDEN_ROLES or role not in {"user", "assistant", "tool"}:
        return None, ()
    content = record.get("content", "")
    binary = bool(record.get("binary", False)) or str(record.get("content_type", "")).casefold().startswith(
        ("application/octet-stream", "image/", "audio/", "video/")
    )
    maximum = bounds.tool_output_chars if role == "tool" else bounds.normalized_content_bytes
    cleaned = sanitize_text(content, max_chars=maximum, binary=binary)
    if binary:
        return None, cleaned.warnings
    tool_name: str | None = None
    if role == "tool" and isinstance(record.get("tool_name"), str):
        tool_name = sanitize_text(record["tool_name"], max_chars=256).text or None
    timestamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
    turn = Turn(
        ordinal=ordinal,
        role=role,
        content=cleaned.text,
        timestamp=timestamp,
        tool_name=tool_name,
        truncated=cleaned.truncated,
    )
    return turn, cleaned.warnings


def sanitize_summary(summary: "SessionSummary", *, bounds: Bounds = DEFAULT_BOUNDS) -> tuple["SessionSummary", tuple[str, ...]]:
    """Sanitize all displayable summary text while preserving structural paths/IDs."""

    from .model import SessionSummary

    warnings: list[str] = []
    title = None
    if summary.title is not None:
        cleaned = sanitize_inline(summary.title, max_chars=bounds.title_chars)
        title = cleaned.text or None
        warnings.extend(cleaned.warnings)
    branch = None
    if summary.branch is not None:
        cleaned = sanitize_inline(summary.branch, max_chars=512)
        branch = cleaned.text or None
        warnings.extend(cleaned.warnings)
    session_id = sanitize_inline(summary.session_id, max_chars=bounds.ref_chars)
    warnings.extend(session_id.warnings)
    cwd = sanitize_inline(summary.cwd, max_chars=4096) if summary.cwd is not None else None
    source_path = sanitize_inline(summary.source_path, max_chars=4096) if summary.source_path is not None else None
    source_repo_root = (
        sanitize_inline(summary.source_repo_root, max_chars=4096)
        if summary.source_repo_root is not None
        else None
    )
    for cleaned_path in (cwd, source_path, source_repo_root):
        if cleaned_path is not None:
            warnings.extend(cleaned_path.warnings)
    result = SessionSummary(
        source=summary.source,
        session_id=session_id.text,
        source_path=source_path.text if source_path is not None else None,
        title=title,
        cwd=cwd.text if cwd is not None else None,
        branch=branch,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        source_repo_root=source_repo_root.text if source_repo_root is not None else None,
        provider=summary.provider,
        warnings=tuple(dict.fromkeys((*summary.warnings, *warnings))),
    )
    return result, _dedupe(warnings)


def sanitize_session(session: "Session", *, bounds: Bounds = DEFAULT_BOUNDS) -> "Session":
    """Re-sanitize typed adapter output so policy cannot diverge per provider."""

    from .model import Session

    warnings: list[str] = list(session.warnings)
    title = sanitize_inline(session.title or "", max_chars=bounds.title_chars)
    branch = sanitize_inline(session.branch or "", max_chars=512)
    session_id = sanitize_inline(session.session_id, max_chars=bounds.ref_chars)
    cwd = sanitize_inline(session.cwd, max_chars=4096) if session.cwd is not None else None
    source_path = sanitize_inline(session.source_path, max_chars=4096) if session.source_path is not None else None
    source_repo_root = (
        sanitize_inline(session.source_repo_root, max_chars=4096)
        if session.source_repo_root is not None
        else None
    )
    last_user = sanitize_text(session.last_user_request or "", max_chars=bounds.normalized_content_bytes)
    last_assistant = sanitize_text(session.last_assistant_action or "", max_chars=bounds.normalized_content_bytes)
    warnings.extend((*title.warnings, *branch.warnings, *session_id.warnings, *last_user.warnings, *last_assistant.warnings))
    for cleaned_path in (cwd, source_path, source_repo_root):
        if cleaned_path is not None:
            warnings.extend(cleaned_path.warnings)
    last_user_text, user_truncated = _take_utf8(last_user.text, bounds.normalized_content_bytes)
    remaining = bounds.normalized_content_bytes - len(last_user_text.encode("utf-8"))
    last_assistant_text, assistant_truncated = _take_utf8(last_assistant.text, remaining)
    if user_truncated or assistant_truncated:
        warnings.append("W_TRUNCATED")
    turns: list[Turn] = []
    total = len(last_user_text.encode("utf-8")) + len(last_assistant_text.encode("utf-8"))
    for source_turn in session.turns[: bounds.normalized_turns]:
        if total >= bounds.normalized_content_bytes:
            warnings.append("W_TRUNCATED")
            break
        if source_turn.role not in {"user", "assistant", "tool"}:
            continue
        maximum = bounds.tool_output_chars if source_turn.role == "tool" else bounds.normalized_content_bytes
        cleaned = sanitize_text(source_turn.content, max_chars=maximum)
        warnings.extend(cleaned.warnings)
        encoded = cleaned.text.encode("utf-8")
        if total + len(encoded) > bounds.normalized_content_bytes:
            remaining = max(0, bounds.normalized_content_bytes - total)
            bounded = encoded[:remaining]
            while True:
                try:
                    content = bounded.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    bounded = bounded[:-1]
            warnings.append("W_TRUNCATED")
            truncated = True
        else:
            content = cleaned.text
            truncated = cleaned.truncated or source_turn.truncated
        total += len(content.encode("utf-8"))
        tool_name = sanitize_inline(source_turn.tool_name, max_chars=256) if source_turn.tool_name else None
        if tool_name is not None:
            warnings.extend(tool_name.warnings)
        turns.append(
            Turn(
                ordinal=len(turns),
                role=source_turn.role,
                content=content,
                timestamp=source_turn.timestamp,
                tool_name=tool_name.text if tool_name is not None else None,
                truncated=truncated,
            )
        )
        if total >= bounds.normalized_content_bytes:
            break
    if len(session.turns) > len(turns):
        warnings.append("W_TRUNCATED")
    return Session(
        source=session.source,
        session_id=session_id.text,
        source_path=source_path.text if source_path is not None else None,
        title=title.text or None,
        cwd=cwd.text if cwd is not None else None,
        branch=branch.text or None,
        created_at=session.created_at,
        updated_at=session.updated_at,
        source_repo_root=source_repo_root.text if source_repo_root is not None else None,
        last_user_request=last_user_text or None,
        last_assistant_action=last_assistant_text or None,
        turns=tuple(turns),
        warnings=_dedupe(warnings),
    )


def _take_utf8(text: str, maximum_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return text, False
    bounded = encoded[: max(0, maximum_bytes)]
    while bounded:
        try:
            return bounded.decode("utf-8"), True
        except UnicodeDecodeError:
            bounded = bounded[:-1]
    return "", bool(encoded)
