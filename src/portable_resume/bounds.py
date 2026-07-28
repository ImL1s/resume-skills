"""Central, conservative resource bounds shared by every source adapter."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from threading import Lock

# Ceiling table is the single source for default values and no-raise checks.
# Using plain ints (not DEFAULT_BOUNDS) avoids import cycles with diagnostics.
_CEILINGS: dict[str, int] = {
    "listed_sessions": 50,
    "listing_age_minutes": 30 * 24 * 60,
    "scanned_records": 2_000,
    "transcript_records": 50_000,
    "record_bytes": 16 * 1024 * 1024,
    "sqlite_snapshot_bytes": 256 * 1024 * 1024,
    "source_read_bytes": 256 * 1024 * 1024,
    "normalized_turns": 2_000,
    "normalized_content_bytes": 8 * 1024 * 1024,
    # Complete serialized handoff Markdown (trusted framing + recovered quotes).
    # Separate from normalized_content_bytes so wrapper overhead cannot fail a
    # schema-valid session that already fits the recovered-content ceiling (#63).
    "handoff_output_bytes": 10 * 1024 * 1024,
    "title_chars": 200,
    "tool_output_chars": 8_000,
    "snapshot_attempts": 3,
    "request_bytes": 16 * 1024,
    "ref_chars": 1_024,
    "diagnostic_chars": 512,
    "family_members": 32,
}

# Fields that may be zero (disable work). snapshot_attempts must stay >= 1.
_ZERO_OK = frozenset(name for name in _CEILINGS if name != "snapshot_attempts")


def _minimum_for(name: str) -> int:
    return 0 if name in _ZERO_OK else 1


def validate_bounds(limits: "Bounds") -> "Bounds":
    """Reject non-int, negative, or raised ceilings before any source I/O.

    Callers may lower every field relative to the global defaults. Raised values
    fail closed with a content-free diagnostic (no silent clamp at construction).
    """

    if not isinstance(limits, Bounds):
        from .diagnostics import DiagnosticError

        raise DiagnosticError.invalid()
    for name, maximum in _CEILINGS.items():
        value = getattr(limits, name)
        minimum = _minimum_for(name)
        if type(value) is not int or value < minimum or value > maximum:
            from .diagnostics import DiagnosticError

            raise DiagnosticError.invalid()
    return limits


@dataclass(frozen=True, slots=True)
class Bounds:
    """V1 upper bounds. Callers may lower, but never raise, these defaults."""

    listed_sessions: int = _CEILINGS["listed_sessions"]
    listing_age_minutes: int = _CEILINGS["listing_age_minutes"]
    # Logical source rows (JSONL lines / SQLite rows). File open is not a record.
    scanned_records: int = _CEILINGS["scanned_records"]
    # Full transcript readers use a separate line budget so metadata discovery
    # remains conservative while large persisted sessions stay recoverable.
    transcript_records: int = _CEILINGS["transcript_records"]
    record_bytes: int = _CEILINGS["record_bytes"]
    sqlite_snapshot_bytes: int = _CEILINGS["sqlite_snapshot_bytes"]
    # Aggregate admitted source payload for one list/show (not output size).
    # Stability verification may re-read those same bytes without charging them again.
    source_read_bytes: int = _CEILINGS["source_read_bytes"]
    normalized_turns: int = _CEILINGS["normalized_turns"]
    # Cap for non-tool turn content (character count in sanitize_text; UTF-8 re-checked later).
    normalized_content_bytes: int = _CEILINGS["normalized_content_bytes"]
    # Serialized handoff document ceiling (not an alias of recovered-content budget).
    handoff_output_bytes: int = _CEILINGS["handoff_output_bytes"]
    title_chars: int = _CEILINGS["title_chars"]
    tool_output_chars: int = _CEILINGS["tool_output_chars"]
    snapshot_attempts: int = _CEILINGS["snapshot_attempts"]
    request_bytes: int = _CEILINGS["request_bytes"]
    ref_chars: int = _CEILINGS["ref_chars"]
    diagnostic_chars: int = _CEILINGS["diagnostic_chars"]
    family_members: int = _CEILINGS["family_members"]

    def __post_init__(self) -> None:
        validate_bounds(self)


DEFAULT_BOUNDS = Bounds()


@dataclass(slots=True)
class ReadBudget:
    """Thread-safe counters which fail before a shared read budget is exceeded.

    ``limits`` is validated at construction: every ceiling is at most the
    corresponding ``DEFAULT_BOUNDS`` value. Consume paths still take
    ``min(limits, DEFAULT_BOUNDS)`` as defense in depth if a Bounds instance
    is ever constructed outside normal validation.
    """

    limits: Bounds = DEFAULT_BOUNDS
    records: int = 0
    transcript_records_read: int = 0
    bytes_read: int = 0
    turns: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        validate_bounds(self.limits)

    def consume_records(self, amount: int = 1) -> None:
        self._consume(
            "records",
            amount,
            min(self.limits.scanned_records, DEFAULT_BOUNDS.scanned_records),
        )

    def consume_transcript_records(self, amount: int = 1) -> None:
        self._consume(
            "transcript_records_read",
            amount,
            min(self.limits.transcript_records, DEFAULT_BOUNDS.transcript_records),
        )

    def consume_bytes(self, amount: int) -> None:
        # Admitted source payload budget (distinct from verification I/O and output UTF-8).
        self._consume(
            "bytes_read",
            amount,
            min(self.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
        )

    def consume_turns(self, amount: int = 1) -> None:
        self._consume(
            "turns",
            amount,
            min(self.limits.normalized_turns, DEFAULT_BOUNDS.normalized_turns),
        )

    def _consume(self, field_name: str, amount: int, maximum: int) -> None:
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("budget increments must be non-negative integers")
        with self._lock:
            current = getattr(self, field_name)
            if current + amount > maximum:
                from .diagnostics import DiagnosticError

                raise DiagnosticError.limit_exceeded()
            setattr(self, field_name, current + amount)


# Ensure the dataclass field set matches the ceiling table (fail closed at import).
assert {item.name for item in fields(Bounds)} == set(_CEILINGS)
