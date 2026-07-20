"""Dependency-free, closed-key runtime validation for portable-resume contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Mapping

from .bounds import DEFAULT_BOUNDS
from .diagnostics import DiagnosticError, ERROR_EXIT_CODES, SOURCE_KEYS, WARNING_CODES

ENVELOPE_KEYS = frozenset(
    {"schema_version", "operation", "inert", "untrusted_content", "generated_at", "query", "sessions", "candidates", "warnings"}
)
QUERY_KEYS = frozenset({"source", "ref", "cwd", "within_min"})
SESSION_KEYS = frozenset(
    {
        "source",
        "session_id",
        "source_path",
        "title",
        "cwd",
        "branch",
        "created_at",
        "updated_at",
        "source_repo_root",
        "inert",
        "untrusted_content",
        "last_user_request",
        "last_assistant_action",
        "turns",
        "warnings",
    }
)
TURN_KEYS = frozenset(
    {"ordinal", "role", "content", "timestamp", "tool_name", "truncated", "inert", "untrusted_content"}
)
CANDIDATE_KEYS = frozenset(
    {"source", "session_id", "title", "cwd", "branch", "updated_at", "inert", "untrusted_content"}
)
REQUEST_KEYS = frozenset({"schema_version", "source", "action", "resume_ref", "cwd"})
DIAGNOSTIC_KEYS = frozenset(
    {"schema_version", "code", "message", "exit_code", "source", "provider", "attempts", "family"}
)

_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


def _invariant(condition: bool) -> None:
    if not condition:
        raise DiagnosticError("E_INVARIANT")


def _closed(mapping: object, keys: frozenset[str]) -> Mapping[str, Any]:
    _invariant(isinstance(mapping, Mapping))
    assert isinstance(mapping, Mapping)
    _invariant(set(mapping) == keys)
    return mapping


def _nullable_string(value: object, *, limit: int) -> None:
    _invariant(value is None or (isinstance(value, str) and len(value) <= limit and _safe_text(value)))


def _safe_text(text: str) -> bool:
    return all(ch in "\n\t" or (ord(ch) >= 0x20 and not 0x7F <= ord(ch) <= 0x9F) for ch in text)


def _timestamp(value: object) -> None:
    if value is None:
        return
    _invariant(isinstance(value, str) and _RFC3339.fullmatch(value) is not None)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DiagnosticError("E_INVARIANT") from error


def _required_timestamp(value: object) -> None:
    _invariant(value is not None)
    _timestamp(value)


def _warnings(values: object) -> None:
    _invariant(isinstance(values, list) and len(values) <= 256)
    assert isinstance(values, list)
    _invariant(all(isinstance(item, str) and item in WARNING_CODES for item in values))


def validate_envelope(value: object) -> None:
    """Validate exact V1 keys, enums, bounds, ordering, and trust markers."""

    envelope = _closed(value, ENVELOPE_KEYS)
    _invariant(envelope["schema_version"] == "portable-resume/v1")
    _invariant(envelope["operation"] in {"list", "show"})
    _invariant(envelope["inert"] is True and envelope["untrusted_content"] is True)
    _required_timestamp(envelope["generated_at"])

    query = _closed(envelope["query"], QUERY_KEYS)
    _invariant(query["source"] in SOURCE_KEYS)
    _nullable_string(query["ref"], limit=DEFAULT_BOUNDS.ref_chars)
    _nullable_string(query["cwd"], limit=4096)
    _invariant(query["within_min"] is None or (type(query["within_min"]) is int and query["within_min"] >= 0))

    sessions = envelope["sessions"]
    _invariant(isinstance(sessions, list) and len(sessions) <= DEFAULT_BOUNDS.listed_sessions)
    assert isinstance(sessions, list)
    for session in sessions:
        validate_session(session, expected_source=query["source"])

    candidates = envelope["candidates"]
    _invariant(isinstance(candidates, list) and len(candidates) <= DEFAULT_BOUNDS.listed_sessions)
    assert isinstance(candidates, list)
    for candidate in candidates:
        validate_candidate(candidate)
    _invariant(candidates == sorted(candidates, key=_candidate_sort_key))
    _warnings(envelope["warnings"])


def validate_session(value: object, *, expected_source: object | None = None) -> None:
    session = _closed(value, SESSION_KEYS)
    _invariant(session["source"] in SOURCE_KEYS)
    if expected_source is not None:
        _invariant(session["source"] == expected_source)
    _invariant(isinstance(session["session_id"], str) and 0 < len(session["session_id"]) <= 1024 and _safe_text(session["session_id"]))
    for key, limit in (
        ("source_path", 4096),
        ("title", DEFAULT_BOUNDS.title_chars),
        ("cwd", 4096),
        ("branch", 512),
        ("source_repo_root", 4096),
        ("last_user_request", DEFAULT_BOUNDS.normalized_content_bytes),
        ("last_assistant_action", DEFAULT_BOUNDS.normalized_content_bytes),
    ):
        _nullable_string(session[key], limit=limit)
    _timestamp(session["created_at"])
    _timestamp(session["updated_at"])
    _invariant(session["inert"] is True and session["untrusted_content"] is True)
    turns = session["turns"]
    _invariant(isinstance(turns, list) and len(turns) <= DEFAULT_BOUNDS.normalized_turns)
    assert isinstance(turns, list)
    total = sum(
        len(value.encode("utf-8"))
        for value in (session["last_user_request"], session["last_assistant_action"])
        if isinstance(value, str)
    )
    _invariant(total <= DEFAULT_BOUNDS.normalized_content_bytes)
    for expected_ordinal, turn in enumerate(turns):
        total += validate_turn(turn, expected_ordinal=expected_ordinal)
    _invariant(total <= DEFAULT_BOUNDS.normalized_content_bytes)
    _warnings(session["warnings"])


def validate_turn(value: object, *, expected_ordinal: int | None = None) -> int:
    turn = _closed(value, TURN_KEYS)
    _invariant(type(turn["ordinal"]) is int and turn["ordinal"] >= 0)
    if expected_ordinal is not None:
        _invariant(turn["ordinal"] == expected_ordinal)
    _invariant(turn["role"] in {"user", "assistant", "tool"})
    _invariant(isinstance(turn["content"], str) and _safe_text(turn["content"]))
    _timestamp(turn["timestamp"])
    _nullable_string(turn["tool_name"], limit=256)
    _invariant(type(turn["truncated"]) is bool)
    _invariant(turn["inert"] is True and turn["untrusted_content"] is True)
    return len(turn["content"].encode("utf-8"))


def validate_candidate(value: object) -> None:
    candidate = _closed(value, CANDIDATE_KEYS)
    _invariant(candidate["source"] in SOURCE_KEYS)
    _invariant(isinstance(candidate["session_id"], str) and 0 < len(candidate["session_id"]) <= 1024)
    _nullable_string(candidate["title"], limit=DEFAULT_BOUNDS.title_chars)
    _nullable_string(candidate["cwd"], limit=4096)
    _nullable_string(candidate["branch"], limit=512)
    _timestamp(candidate["updated_at"])
    _invariant(candidate["inert"] is True and candidate["untrusted_content"] is True)


def validate_request(value: object, *, expected_source: str | None = None) -> None:
    request = _closed(value, REQUEST_KEYS)
    _invariant(request["schema_version"] == "portable-resume/request-v1")
    _invariant(request["source"] in SOURCE_KEYS)
    if expected_source is not None:
        _invariant(request["source"] == expected_source)
    _invariant(request["action"] == "show")
    _invariant(
        isinstance(request["resume_ref"], str)
        and 0 < len(request["resume_ref"]) <= DEFAULT_BOUNDS.ref_chars
        and _safe_inline(request["resume_ref"])
    )
    _invariant(isinstance(request["cwd"], str) and _safe_inline(request["cwd"]))


def validate_diagnostic(value: object) -> None:
    diagnostic = _closed(value, DIAGNOSTIC_KEYS)
    _invariant(diagnostic["schema_version"] == "portable-resume/diagnostic-v1")
    _invariant(diagnostic["code"] in ERROR_EXIT_CODES)
    _invariant(diagnostic["exit_code"] == int(ERROR_EXIT_CODES[diagnostic["code"]]))
    _invariant(
        isinstance(diagnostic["message"], str)
        and len(diagnostic["message"]) <= DEFAULT_BOUNDS.diagnostic_chars
        and _safe_inline(diagnostic["message"])
    )
    _invariant(diagnostic["source"] is None or diagnostic["source"] in SOURCE_KEYS)
    _invariant(diagnostic["provider"] is None or isinstance(diagnostic["provider"], str))
    _invariant(diagnostic["attempts"] is None or type(diagnostic["attempts"]) is int and diagnostic["attempts"] >= 0)
    _invariant(
        isinstance(diagnostic["family"], list)
        and len(diagnostic["family"]) <= DEFAULT_BOUNDS.family_members
        and all(isinstance(item, str) and _safe_inline(item) for item in diagnostic["family"])
    )


def _safe_inline(text: str) -> bool:
    return _safe_text(text) and "\n" not in text and "\t" not in text


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[bool, int, str, str]:
    value = candidate["updated_at"]
    micros = 0
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        micros = int(parsed.timestamp() * 1_000_000)
    return (value is None, -micros, str(candidate["source"]), str(candidate["session_id"]))


def assert_exact_keys(value: Mapping[str, Any], expected: Iterable[str]) -> None:
    """Small public helper used by strict request/diagnostic decoders."""

    if set(value) != set(expected):
        raise DiagnosticError.invalid()
