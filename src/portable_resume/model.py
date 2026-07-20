"""Inert source-neutral data model used by all concrete adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

SOURCE_KEYS = frozenset({"claude", "codex", "cursor", "opencode", "antigravity", "grok"})
TURN_ROLES = frozenset({"user", "assistant", "tool"})
OPERATIONS = frozenset({"list", "show"})


def utc_now_rfc3339() -> str:
    """Return the sole time-varying envelope field in canonical UTC form."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Query:
    source: str
    ref: str | None = None
    cwd: str | None = None
    within_min: int | None = None
    source_root: str | None = None
    max_tool_chars: int = 8_000

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "ref": self.ref,
            "cwd": self.cwd,
            "within_min": self.within_min,
        }


@dataclass(frozen=True, slots=True)
class Turn:
    ordinal: int
    role: str
    content: str
    timestamp: str | None = None
    tool_name: str | None = None
    truncated: bool = False
    inert: bool = True
    untrusted_content: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "truncated": self.truncated,
            "inert": self.inert,
            "untrusted_content": self.untrusted_content,
        }


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """Adapter-facing bounded metadata used for selection before a full read."""

    source: str
    session_id: str
    source_path: str | None = None
    title: str | None = None
    cwd: str | None = None
    branch: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    source_repo_root: str | None = None
    provider: str | None = None
    warnings: tuple[str, ...] = ()

    def candidate(self) -> "Candidate":
        return Candidate(
            source=self.source,
            session_id=self.session_id,
            title=self.title,
            cwd=self.cwd,
            branch=self.branch,
            updated_at=self.updated_at,
        )

    def empty_session(self) -> "Session":
        return Session(
            source=self.source,
            session_id=self.session_id,
            source_path=self.source_path,
            title=self.title,
            cwd=self.cwd,
            branch=self.branch,
            created_at=self.created_at,
            updated_at=self.updated_at,
            source_repo_root=self.source_repo_root,
            warnings=self.warnings,
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    source: str
    session_id: str
    title: str | None = None
    cwd: str | None = None
    branch: str | None = None
    updated_at: str | None = None
    inert: bool = True
    untrusted_content: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "title": self.title,
            "cwd": self.cwd,
            "branch": self.branch,
            "updated_at": self.updated_at,
            "inert": self.inert,
            "untrusted_content": self.untrusted_content,
        }


@dataclass(frozen=True, slots=True)
class Session:
    source: str
    session_id: str
    source_path: str | None = None
    title: str | None = None
    cwd: str | None = None
    branch: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    source_repo_root: str | None = None
    inert: bool = True
    untrusted_content: bool = True
    last_user_request: str | None = None
    last_assistant_action: str | None = None
    turns: tuple[Turn, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "source_path": self.source_path,
            "title": self.title,
            "cwd": self.cwd,
            "branch": self.branch,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_repo_root": self.source_repo_root,
            "inert": self.inert,
            "untrusted_content": self.untrusted_content,
            "last_user_request": self.last_user_request,
            "last_assistant_action": self.last_assistant_action,
            "turns": [turn.to_dict() for turn in self.turns],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class Envelope:
    operation: str
    query: Query
    sessions: tuple[Session, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    warnings: tuple[str, ...] = ()
    generated_at: str = field(default_factory=utc_now_rfc3339)
    schema_version: str = "portable-resume/v1"
    inert: bool = True
    untrusted_content: bool = True

    @classmethod
    def create(
        cls,
        *,
        operation: str,
        query: Query,
        sessions: Iterable[Session] = (),
        candidates: Iterable[Candidate] = (),
        warnings: Iterable[str] = (),
        generated_at: str | None = None,
    ) -> "Envelope":
        values: dict[str, Any] = {
            "operation": operation,
            "query": query,
            "sessions": tuple(sessions),
            "candidates": tuple(candidates),
            "warnings": tuple(warnings),
        }
        if generated_at is not None:
            values["generated_at"] = generated_at
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "inert": self.inert,
            "untrusted_content": self.untrusted_content,
            "generated_at": self.generated_at,
            "query": self.query.to_dict(),
            "sessions": [session.to_dict() for session in self.sessions],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": list(self.warnings),
        }
