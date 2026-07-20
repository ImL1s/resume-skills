"""Bounded machine diagnostics and stable process exit codes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, NoReturn

from .bounds import DEFAULT_BOUNDS


class ExitCode(IntEnum):
    OK = 0
    INVALID_INPUT = 2
    NO_MATCH = 3
    AMBIGUOUS = 4
    UNSUPPORTED = 5
    UNSAFE_OR_BUSY = 6
    CORRUPT_OR_LIMIT = 7
    INVARIANT = 8


ERROR_EXIT_CODES: dict[str, ExitCode] = {
    "E_INVALID_INPUT": ExitCode.INVALID_INPUT,
    "E_NO_MATCH": ExitCode.NO_MATCH,
    "E_AMBIGUOUS": ExitCode.AMBIGUOUS,
    "E_UNSUPPORTED_FORMAT": ExitCode.UNSUPPORTED,
    "E_CAPABILITY_UNAVAILABLE": ExitCode.UNSUPPORTED,
    "E_UNSAFE_PATH": ExitCode.UNSAFE_OR_BUSY,
    "E_SOURCE_BUSY": ExitCode.UNSAFE_OR_BUSY,
    "E_SQLITE_HOT_JOURNAL": ExitCode.UNSAFE_OR_BUSY,
    "E_LIMIT_EXCEEDED": ExitCode.CORRUPT_OR_LIMIT,
    "E_CORRUPT_RECORD": ExitCode.CORRUPT_OR_LIMIT,
    "E_INVARIANT": ExitCode.INVARIANT,
    "E_INSTALL_BUSY": ExitCode.UNSAFE_OR_BUSY,
    "E_INSTALL_CONFLICT": ExitCode.UNSAFE_OR_BUSY,
    "E_RECOVERY_REQUIRED": ExitCode.UNSAFE_OR_BUSY,
    "E_VERIFY_MISMATCH": ExitCode.CORRUPT_OR_LIMIT,
}

WARNING_CODES = frozenset(
    {
        "W_TRUNCATED",
        "W_PARTIAL_TAIL",
        "W_BROKEN_CHAIN",
        "W_MISSING_BLOB",
        "W_STALE_INDEX",
        "W_OPTIONAL_ZSTD_UNAVAILABLE",
        "W_METADATA_REDACTED",
        "W_CONTROLS_REMOVED",
        "W_BINARY_OMITTED",
        "W_HOST_DISCOVERY_UNPROVEN",
        "W_LIVE_SMOKE_NOT_RUN",
    }
)

_DEFAULT_MESSAGES = {
    "E_INVALID_INPUT": "The request is invalid.",
    "E_NO_MATCH": "No eligible session matched the request.",
    "E_AMBIGUOUS": "More than one eligible session matched the request.",
    "E_UNSUPPORTED_FORMAT": "No supported persisted-session format was detected.",
    "E_CAPABILITY_UNAVAILABLE": "The requested source capability is unavailable.",
    "E_UNSAFE_PATH": "The requested path is outside an approved safe root or is not a regular file.",
    "E_SOURCE_BUSY": "The source changed during bounded stable-read attempts.",
    "E_SQLITE_HOT_JOURNAL": "The SQLite family contains an unproven rollback journal.",
    "E_LIMIT_EXCEEDED": "A configured resource bound was exceeded.",
    "E_CORRUPT_RECORD": "A persisted record is corrupt or invalid.",
    "E_INVARIANT": "An internal contract invariant failed.",
    "E_INSTALL_BUSY": "Another install operation holds the destination root lock.",
    "E_INSTALL_CONFLICT": "A destination path conflicts with a non-owned or incompatible file.",
    "E_RECOVERY_REQUIRED": "A durable install journal requires recovery before mutation.",
    "E_VERIFY_MISMATCH": "Installed files do not match the owned manifest.",
}


@dataclass(slots=True)
class DiagnosticError(Exception):
    """Expected, content-free failure crossing the CLI boundary."""

    code: str
    message: str | None = None
    source: str | None = None
    provider: str | None = None
    attempts: int | None = None
    family: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.code not in ERROR_EXIT_CODES:
            self.code = "E_INVARIANT"
        # English prose is intentionally fixed by code.  Adapter-supplied or
        # recovered text can therefore never leak through an exception message.
        self.message = _bounded_message(_DEFAULT_MESSAGES[self.code])
        self.family = tuple(_safe_family_name(name) for name in self.family[: DEFAULT_BOUNDS.family_members])
        Exception.__init__(self, self.message)

    @property
    def exit_code(self) -> ExitCode:
        return ERROR_EXIT_CODES[self.code]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "portable-resume/diagnostic-v1",
            "code": self.code,
            "message": self.message,
            "exit_code": int(self.exit_code),
            "source": self.source if self.source in SOURCE_KEYS else None,
            "provider": _bounded_identifier(self.provider),
            "attempts": self.attempts if isinstance(self.attempts, int) and self.attempts >= 0 else None,
            "family": list(self.family),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def invalid(cls, message: str | None = None, *, source: str | None = None) -> "DiagnosticError":
        return cls("E_INVALID_INPUT", message, source=source)

    @classmethod
    def unsafe_path(cls) -> "DiagnosticError":
        return cls("E_UNSAFE_PATH")

    @classmethod
    def source_busy(
        cls, *, attempts: int | None = None, family: tuple[str, ...] = (), provider: str | None = None
    ) -> "DiagnosticError":
        return cls("E_SOURCE_BUSY", attempts=attempts, family=family, provider=provider)

    @classmethod
    def limit_exceeded(cls) -> "DiagnosticError":
        return cls("E_LIMIT_EXCEEDED")


SOURCE_KEYS = frozenset({"claude", "codex", "cursor", "opencode", "antigravity", "grok"})


def _bounded_message(message: object) -> str:
    text = str(message).replace("\r", " ").replace("\n", " ")
    text = "".join(ch for ch in text if ch == "\t" or ord(ch) >= 0x20)
    return text[: DEFAULT_BOUNDS.diagnostic_chars]


def _bounded_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    safe = "".join(ch for ch in value if ch.isalnum() or ch in "-_.")
    return safe[:128] or None


def _safe_family_name(value: object) -> str:
    # Diagnostics expose only a bounded basename-like token, never recovered text or paths.
    text = str(value).replace("\\", "/").rsplit("/", 1)[-1]
    safe = "".join(ch for ch in text if ch.isalnum() or ch in "-_.")
    return (safe or "member")[:128]


def emit_diagnostic(error: DiagnosticError, *, stream: Any) -> int:
    stream.write(error.to_json() + "\n")
    return int(error.exit_code)


def fail(code: str, message: str | None = None, **kwargs: Any) -> NoReturn:
    raise DiagnosticError(code, message, **kwargs)
