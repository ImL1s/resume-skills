"""Central, conservative resource bounds shared by every source adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass(frozen=True, slots=True)
class Bounds:
    """V1 upper bounds. Callers may lower, but never raise, these defaults."""

    listed_sessions: int = 50
    listing_age_minutes: int = 30 * 24 * 60
    # Logical source rows (JSONL lines / SQLite rows). File open is not a record.
    scanned_records: int = 2_000
    record_bytes: int = 16 * 1024 * 1024
    sqlite_snapshot_bytes: int = 256 * 1024 * 1024
    # Aggregate raw bytes read from source stores for one list/show (not output size).
    source_read_bytes: int = 256 * 1024 * 1024
    normalized_turns: int = 2_000
    # Cap for non-tool turn content (character count in sanitize_text; UTF-8 re-checked later).
    normalized_content_bytes: int = 8 * 1024 * 1024
    title_chars: int = 200
    tool_output_chars: int = 8_000
    snapshot_attempts: int = 3
    request_bytes: int = 16 * 1024
    ref_chars: int = 1_024
    diagnostic_chars: int = 512
    family_members: int = 32


DEFAULT_BOUNDS = Bounds()


@dataclass(slots=True)
class ReadBudget:
    """Thread-safe counters which fail before a shared read budget is exceeded."""

    limits: Bounds = DEFAULT_BOUNDS
    records: int = 0
    bytes_read: int = 0
    turns: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def consume_records(self, amount: int = 1) -> None:
        self._consume("records", amount, self.limits.scanned_records)

    def consume_bytes(self, amount: int) -> None:
        # Aggregate raw-read budget for source store I/O (distinct from output UTF-8 budget).
        self._consume("bytes_read", amount, self.limits.source_read_bytes)

    def consume_turns(self, amount: int = 1) -> None:
        self._consume("turns", amount, self.limits.normalized_turns)

    def _consume(self, field_name: str, amount: int, maximum: int) -> None:
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("budget increments must be non-negative integers")
        with self._lock:
            current = getattr(self, field_name)
            if current + amount > maximum:
                from .diagnostics import DiagnosticError

                raise DiagnosticError.limit_exceeded()
            setattr(self, field_name, current + amount)
