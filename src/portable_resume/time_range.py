"""Human-friendly time ranges and list continuation cursors (#157)."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .diagnostics import DiagnosticError
from .model import SessionSummary
from .select import _timestamp_micros, summary_sort_key

_REL = re.compile(r"^(?P<n>\d+)(?P<u>[mhdw])$")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
# Product policy: at most 2 years of relative history for a single query.
_MAX_RELATIVE_SECONDS = 2 * 365 * 24 * 3600


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time_token(raw: str, *, now: datetime | None = None) -> datetime:
    """Parse ``30m`` / ``2h`` / ``7d`` / ``2w`` or timezone-aware ISO-8601."""

    if not isinstance(raw, str) or not raw.strip():
        raise DiagnosticError.invalid()
    text = raw.strip()
    rel = _REL.fullmatch(text)
    if rel is not None:
        n = int(rel.group("n"))
        unit = rel.group("u")
        seconds = n * _UNIT_SECONDS[unit]
        if n < 1 or seconds > _MAX_RELATIVE_SECONDS:
            raise DiagnosticError.invalid()
        base = now if now is not None else utc_now()
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return base.astimezone(timezone.utc) - timedelta(seconds=seconds)
    # ISO-8601 with explicit timezone (reject naive).
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError as error:
        raise DiagnosticError.invalid() from error
    if dt.tzinfo is None:
        raise DiagnosticError.invalid()
    return dt.astimezone(timezone.utc)


def resolve_window(
    *,
    since: str | None,
    until: str | None,
    within_min: int | None,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime | None, dict[str, Any]]:
    """Return (since_dt, until_dt, echo) for listing filters.

    ``--within-min`` conflicts with ``--since``. ``within_min==0`` means no age
    filter (existing product semantics).
    """

    base = now if now is not None else utc_now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    base = base.astimezone(timezone.utc)

    if since is not None and within_min is not None:
        raise DiagnosticError.invalid()

    since_dt: datetime | None = None
    until_dt: datetime | None = None
    echo: dict[str, Any] = {
        "since": None,
        "until": None,
        "within_min": within_min,
    }

    if within_min is not None:
        if within_min < 0 or within_min > 10 * 365 * 24 * 60:
            raise DiagnosticError.invalid()
        if within_min > 0:
            since_dt = base - timedelta(minutes=within_min)
            echo["since"] = since_dt.isoformat().replace("+00:00", "Z")

    if since is not None:
        since_dt = parse_time_token(since, now=base)
        echo["since"] = since_dt.isoformat().replace("+00:00", "Z")
    if until is not None:
        until_dt = parse_time_token(until, now=base)
        echo["until"] = until_dt.isoformat().replace("+00:00", "Z")

    if since_dt is not None and until_dt is not None and since_dt > until_dt:
        raise DiagnosticError.invalid()
    return since_dt, until_dt, echo


def summary_in_window(
    summary: SessionSummary,
    *,
    since_dt: datetime | None,
    until_dt: datetime | None,
) -> bool:
    if since_dt is None and until_dt is None:
        return True
    micros = _timestamp_micros(summary.updated_at)
    if micros == 0 and summary.updated_at is None:
        # Unknown time: exclude when a time bound is active (fail closed).
        return False
    ts = datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc)
    if since_dt is not None and ts < since_dt:
        return False
    if until_dt is not None and ts > until_dt:
        return False
    return True


def encode_cursor(summary: SessionSummary) -> str:
    payload = {
        "u": summary.updated_at,
        "s": summary.source,
        "i": summary.session_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> dict[str, str | None]:
    if not isinstance(token, str) or not token.strip():
        raise DiagnosticError.invalid()
    text = token.strip()
    pad = "=" * (-len(text) % 4)
    try:
        raw = base64.urlsafe_b64decode(text + pad)
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DiagnosticError.invalid() from error
    if not isinstance(data, dict):
        raise DiagnosticError.invalid()
    u = data.get("u")
    s = data.get("s")
    i = data.get("i")
    if s is not None and not isinstance(s, str):
        raise DiagnosticError.invalid()
    if i is not None and not isinstance(i, str):
        raise DiagnosticError.invalid()
    if u is not None and not isinstance(u, str):
        raise DiagnosticError.invalid()
    return {"u": u, "s": s, "i": i}


def apply_cursor(
    summaries: list[SessionSummary],
    cursor: str | None,
) -> list[SessionSummary]:
    """Keyset continuation: return items strictly after the cursor in sort order."""

    ordered = sorted(summaries, key=summary_sort_key)
    if cursor is None:
        return ordered
    mark = decode_cursor(cursor)
    # Find first item strictly after cursor using the same sort key shape.
    marker = SessionSummary(
        source=str(mark["s"] or ""),
        session_id=str(mark["i"] or ""),
        updated_at=mark["u"],
    )
    marker_key = summary_sort_key(marker)
    return [row for row in ordered if summary_sort_key(row) > marker_key]


def page_summaries(
    summaries: list[SessionSummary],
    *,
    limit: int,
    cursor: str | None,
    since_dt: datetime | None,
    until_dt: datetime | None,
) -> tuple[list[SessionSummary], str | None, dict[str, Any]]:
    """Filter by time, apply cursor, take limit; return page + next_cursor + meta."""

    from .bounds import DEFAULT_BOUNDS

    if type(limit) is not int or limit < 1 or limit > DEFAULT_BOUNDS.listed_sessions:
        raise DiagnosticError.invalid()
    filtered = [
        row
        for row in summaries
        if summary_in_window(row, since_dt=since_dt, until_dt=until_dt)
    ]
    after = apply_cursor(filtered, cursor)
    page = after[:limit]
    next_cursor = encode_cursor(page[-1]) if len(after) > limit and page else None
    meta = {
        "limit": limit,
        "returned": len(page),
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
    }
    return page, next_cursor, meta
