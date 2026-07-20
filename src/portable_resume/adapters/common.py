"""Shared adapter helpers (strict JSON, age windows, UUID refs)."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any


class DuplicateKey(ValueError):
    """Raised when a JSON object repeats a key (strict parse)."""


def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise DuplicateKey(key)
        output[key] = value
    return output


def exact_uuid_ref(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def within_age(updated_at: str | None, minutes: int | None, *, default_minutes: int) -> bool:
    """Return True if *updated_at* is within the age window.

    ``minutes is None`` → use *default_minutes*.
    ``minutes <= 0`` → no age filter (all timestamps eligible if parseable / non-null policy).
    """
    if minutes is None:
        minutes = default_minutes
    if minutes is not None and minutes <= 0:
        return True
    if updated_at is None:
        return False
    try:
        stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return stamp >= time.time() - minutes * 60
