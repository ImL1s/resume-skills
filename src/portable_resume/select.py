"""Deterministic latest/ID/path/text selection with bounded ambiguity output."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .bounds import DEFAULT_BOUNDS
from .diagnostics import DiagnosticError
from .model import Candidate, SessionSummary
from .paths import canonicalize_cwd, require_regular_no_symlinks, same_cwd


@dataclass(frozen=True, slots=True)
class SelectionResult:
    selected: SessionSummary | None
    candidates: tuple[Candidate, ...] = ()


def _timestamp_micros(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000)
    except (ValueError, OverflowError):
        return 0


def summary_sort_key(summary: SessionSummary) -> tuple[bool, int, str, str, str]:
    return (
        summary.updated_at is None,
        -_timestamp_micros(summary.updated_at),
        summary.source,
        summary.session_id,
        summary.provider or "",
    )


def candidate_sort_key(candidate: Candidate) -> tuple[bool, int, str, str]:
    return (
        candidate.updated_at is None,
        -_timestamp_micros(candidate.updated_at),
        candidate.source,
        candidate.session_id,
    )


def bounded_candidates(values: Iterable[SessionSummary]) -> tuple[Candidate, ...]:
    candidates = sorted((value.candidate() for value in values), key=candidate_sort_key)
    return tuple(candidates[: DEFAULT_BOUNDS.listed_sessions])


def select_session(
    summaries: Iterable[SessionSummary],
    *,
    ref: str | None,
    cwd: str | None,
    approved_roots: Iterable[str] = (),
) -> SelectionResult:
    """Select one eligible summary or raise a stable no-match/ambiguous diagnostic."""

    values = list(summaries)
    if len(values) > DEFAULT_BOUNDS.scanned_records:
        raise DiagnosticError.limit_exceeded()
    eligible = [value for value in values if cwd is None or (value.cwd is not None and same_cwd(value.cwd, cwd))]
    normalized_ref = "latest" if ref is None or not ref.strip() else ref.strip()

    if normalized_ref == "latest":
        ordered = sorted(eligible, key=summary_sort_key)
        if not ordered:
            raise DiagnosticError("E_NO_MATCH")
        return SelectionResult(ordered[0])

    # Prefer canonical UUID equality (uppercase paste still matches).
    import uuid as _uuid

    ref_uuid: str | None = None
    try:
        ref_uuid = str(_uuid.UUID(normalized_ref))
    except ValueError:
        ref_uuid = None
    exact_id = [
        value
        for value in eligible
        if value.session_id == normalized_ref
        or (ref_uuid is not None and value.session_id == ref_uuid)
    ]
    # Dedupe if both branches matched the same row.
    if exact_id:
        seen: set[str] = set()
        unique: list[SessionSummary] = []
        for value in exact_id:
            key = f"{value.source}:{value.session_id}:{value.source_path or ''}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        exact_id = unique
    if len(exact_id) == 1:
        return SelectionResult(exact_id[0])
    if len(exact_id) > 1:
        candidates = bounded_candidates(exact_id)
        raise AmbiguousSelection(candidates)

    if os.path.isabs(normalized_ref):
        roots = tuple(approved_roots)
        if not roots:
            raise DiagnosticError.unsafe_path()
        canonical_match: str | None = None
        for root in roots:
            try:
                safe, _ = require_regular_no_symlinks(normalized_ref, root)
            except DiagnosticError:
                continue
            canonical_match = canonicalize_cwd(safe)
            break
        if canonical_match is None:
            raise DiagnosticError.unsafe_path()
        exact_path = [
            value
            for value in eligible
            if value.source_path is not None and canonicalize_cwd(value.source_path) == canonical_match
        ]
        if len(exact_path) == 1:
            return SelectionResult(exact_path[0])
        if len(exact_path) > 1:
            raise AmbiguousSelection(bounded_candidates(exact_path))
        raise DiagnosticError("E_NO_MATCH")

    if len(normalized_ref) > DEFAULT_BOUNDS.ref_chars:
        raise DiagnosticError.limit_exceeded()
    needle = normalized_ref.casefold()
    matches: list[SessionSummary] = []
    for value in eligible:
        fields = (value.session_id, value.title or "", value.cwd or "", value.branch or "")
        if any(needle in field.casefold() for field in fields):
            matches.append(value)
    if not matches:
        raise DiagnosticError("E_NO_MATCH")
    if len(matches) > 1:
        raise AmbiguousSelection(bounded_candidates(matches))
    return SelectionResult(matches[0])


class AmbiguousSelection(DiagnosticError):
    """Ambiguity preserves only safe, closed candidate summaries for stdout."""

    def __init__(self, candidates: tuple[Candidate, ...]):
        super().__init__("E_AMBIGUOUS")
        self.candidates = tuple(sorted(candidates, key=candidate_sort_key))[: DEFAULT_BOUNDS.listed_sessions]
