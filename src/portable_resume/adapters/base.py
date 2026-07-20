"""Frozen interface between the shared reader and concrete source providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..bounds import ReadBudget
from ..model import Query, Session, SessionSummary

CAPABILITY_STATES = frozenset({"supported", "partial", "unavailable", "unsupported", "unsafe"})


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    source: str
    format_id: str | None
    state: str
    root: str | None = None
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedRef:
    session_id: str
    source_path: str | None = None
    provider: str | None = None

    @classmethod
    def from_summary(cls, summary: SessionSummary) -> "ResolvedRef":
        return cls(summary.session_id, summary.source_path, summary.provider)


@runtime_checkable
class SourceAdapter(Protocol):
    """Concrete adapters return typed records; shared code owns policy."""

    key: str

    def probe(self, query: Query) -> CapabilityReport: ...

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]: ...

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session: ...
