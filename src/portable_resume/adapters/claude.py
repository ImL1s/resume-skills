"""Read Claude Code JSONL sessions as inert context.

This adapter intentionally understands one pinned structural family only.  It
does not invoke Claude Code, follow symlinks, or infer a transcript from an
unknown record shape.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import (
    canonical_root,
    canonicalize_cwd,
    is_within,
    require_regular_no_symlinks,
    same_cwd,
)
from ..sanitize import sanitize_turn_record
from ..snapshot import FileSnapshot, StableWindows, snapshot_regular_file, stable_read_windows
from .base import CapabilityReport, ResolvedRef

FORMAT_ID = "claude-jsonl-v1"
# Grok-build style: prefer cwd slug project dir; allow large ~/.claude/projects trees.
_PROJECT_DIR_LIMIT = 1_024
_METADATA_HEAD_BYTES = 4 * 1024 * 1024
_METADATA_TAIL_BYTES = 64 * 1024
_UUID_RECORD_TYPES = frozenset({"user", "assistant", "system"})
# Structural families we understand or safely ignore without payload interpretation.
# Unknown types are skipped with W_UNKNOWN_RECORD_SKIPPED (Grok resume-session parity).
_KNOWN_RECORD_TYPES = frozenset(
    {
        "user",
        "assistant",
        "system",
        "summary",
        "custom-title",
        "ai-title",
        "meta",
        "queue-operation",
        "last-prompt",
        "tag",
        "agent-name",
        "agent-color",
        "agent-setting",
        "mode",
        "permission-mode",
        "worktree-state",
        "progress",
        "file-history-snapshot",
        "file-history-delta",
        "attribution-snapshot",
        "content-replacement",
        "context-collapse-commit",
        "context-collapse-snapshot",
        "attachment",
        "bridge-session",
        "pr-link",
    }
)
_COMPACTION_SUBTYPES = frozenset({"compact_boundary", "compaction", "compact"})
_REPLAY_ENVELOPE_FIELDS = frozenset(
    {"parentUuid", "cwd", "gitBranch", "slug", "promptId", "toolUseResult"}
)


def _slugify_cwd(cwd: str) -> str:
    """Match Claude Code project dir naming: non-alnum → '-' (same as Grok resume-session)."""
    return "".join(char if char.isalnum() else "-" for char in cwd)


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> Any:
    raise ValueError("non-finite JSON number")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


@dataclass(slots=True)
class _TranscriptMetadata:
    session_ids: set[str] = field(default_factory=set)
    cwds: list[str] = field(default_factory=list)
    custom_title: str | None = None
    ai_title: str | None = None
    summary: str | None = None
    last_prompt: str | None = None
    first_user: str | None = None
    branch: str | None = None
    created_at: str | None = None
    records_seen: int = 0

    def observe(self, record: Mapping[str, Any]) -> None:
        self.records_seen += 1
        session_id = record.get("sessionId")
        if isinstance(session_id, str):
            self.session_ids.add(session_id)
        raw_cwd = record.get("cwd")
        if isinstance(raw_cwd, str):
            try:
                cwd = canonicalize_cwd(raw_cwd)
            except DiagnosticError as error:
                raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
            if cwd not in self.cwds:
                self.cwds.append(cwd)
        if isinstance(record.get("customTitle"), str):
            self.custom_title = record["customTitle"]
        if isinstance(record.get("aiTitle"), str):
            self.ai_title = record["aiTitle"]
        if isinstance(record.get("summary"), str):
            self.summary = record["summary"]
        if isinstance(record.get("lastPrompt"), str):
            self.last_prompt = record["lastPrompt"]
        if isinstance(record.get("gitBranch"), str):
            self.branch = record["gitBranch"]
        stamp = _rfc3339(record.get("timestamp"))
        if stamp is not None and (self.created_at is None or stamp < self.created_at):
            self.created_at = stamp
        if self.first_user is None and record.get("type") == "user" and not record.get("isMeta"):
            message = record.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                candidate = message["content"]
                if not candidate.lstrip().startswith("<command-name>"):
                    self.first_user = candidate

    @property
    def title(self) -> str | None:
        return next(
            (
                item
                for item in (
                    self.custom_title,
                    self.ai_title,
                    self.summary,
                    self.last_prompt,
                    self.first_user,
                )
                if item and item.strip()
            ),
            None,
        )

    def selected_cwd(self, requested: str | None) -> str | None:
        primary = self.cwds[0] if self.cwds else None
        if requested is not None:
            canonical = canonicalize_cwd(requested)
            if primary is not None and same_cwd(canonical, primary):
                return canonical
            return None
        return primary


@dataclass(frozen=True, slots=True)
class _TranscriptNode:
    identifier: str
    index: int
    offset: int
    digest: str
    record: dict[str, Any]


@dataclass(slots=True)
class _TranscriptIndex:
    metadata: _TranscriptMetadata
    nodes: dict[str, _TranscriptNode]
    bridge: dict[str, str | None]
    warnings: tuple[str, ...]


def _root_candidate(query: Query) -> str:
    if query.source_root:
        return query.source_root
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return configured if configured else os.path.expanduser("~/.claude")


def _existing_root(query: Query) -> str | None:
    candidate = _root_candidate(query)
    try:
        if not os.path.isdir(candidate):
            return None
        return canonical_root(candidate)
    except DiagnosticError:
        if query.source_root:
            raise
        return None


def _regular_directory(path: str, root: str) -> bool:
    try:
        current = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISDIR(current.st_mode):
        return False
    canonical = canonicalize_cwd(path)
    try:
        return os.path.commonpath((canonical, root)) == root
    except ValueError:
        return False


def _bounded_names(directory: str, *, limit: int) -> list[str]:
    values: list[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(values) >= limit:
                    raise DiagnosticError.limit_exceeded()
                values.append(entry.name)
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    values.sort()
    return values


def _project_dirs(
    root: str,
    *,
    prefer_slugs: tuple[str, ...] = (),
    prefer_only: bool = False,
) -> list[str]:
    """Return project directories under ``<root>/projects``.

    When *prefer_only* is true, only the preferred cwd-slug directories are
    considered — the projects tree is not enumerated. This keeps exact UUID +
    cwd discovery off the broad ``_PROJECT_DIR_LIMIT`` / scandir path.
    """
    projects = os.path.join(root, "projects")
    if not _regular_directory(projects, root):
        return []
    preferred: list[str] = []
    seen: set[str] = set()
    for slug in prefer_slugs:
        if not slug or slug in seen:
            continue
        candidate = os.path.join(projects, slug)
        if _regular_directory(candidate, root):
            preferred.append(candidate)
            seen.add(slug)
    if prefer_only:
        return preferred
    names = _bounded_names(projects, limit=DEFAULT_BOUNDS.scanned_records)
    others: list[str] = []
    for name in names:
        if name in seen:
            continue
        candidate = os.path.join(projects, name)
        if _regular_directory(candidate, root):
            others.append(candidate)
            if len(preferred) + len(others) > _PROJECT_DIR_LIMIT:
                raise DiagnosticError.limit_exceeded()
    # Preferred (cwd slug) first — same discovery order as Grok resume-session.
    return preferred + others


def _session_layout_ok(path: str, root: str) -> bool:
    """True when *path* is ``projects/<slug>/<uuid>.jsonl`` under *root*."""

    if not is_within(path, root):
        return False
    relative = os.path.relpath(path, root)
    parts = relative.split(os.sep)
    if len(parts) != 3 or parts[0] != "projects" or not parts[1]:
        return False
    basename = parts[2]
    if not basename.endswith(".jsonl"):
        return False
    try:
        uuid.UUID(basename[:-6])
    except ValueError:
        return False
    return True


def _regular_session_file(path: str) -> bool:
    try:
        current = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode)


def _direct_uuid_under_slugs(
    root: str,
    exact_uuid: str,
    prefer_slugs: tuple[str, ...],
) -> list[str]:
    """Return existing ``projects/<slug>/<uuid>.jsonl`` paths without tree scans."""

    projects = os.path.join(root, "projects")
    if not _regular_directory(projects, root):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for slug in prefer_slugs:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        project = os.path.join(projects, slug)
        if not _regular_directory(project, root):
            continue
        candidate = os.path.join(project, f"{exact_uuid}.jsonl")
        if _regular_session_file(candidate):
            values.append(candidate)
    return values


def _lexical_under_root(path: str, root: str) -> bool:
    """True when *path* is lexically under *root* (abspath spellings only)."""

    try:
        relative = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:
        return False
    return relative != os.pardir and not relative.startswith(os.pardir + os.sep) and not os.path.isabs(relative)


def _lexical_session_shape(path: str, root: str) -> bool:
    """True when *path* is lexically ``projects/<slug>/<uuid>.jsonl`` under *root*."""

    absolute = os.path.abspath(path)
    abs_root = os.path.abspath(root)
    if not _lexical_under_root(absolute, abs_root):
        return False
    try:
        relative = os.path.relpath(absolute, abs_root)
    except ValueError:
        return False
    parts = [part for part in Path(relative).parts if part not in ("", ".")]
    if len(parts) != 3 or parts[0] != "projects" or not parts[1]:
        return False
    basename = parts[2]
    if not basename.endswith(".jsonl"):
        return False
    try:
        uuid.UUID(basename[:-6])
    except ValueError:
        return False
    return True


def _missing_under_safe_parents(path: str, root: str) -> bool:
    """True when a missing *path* is a valid under-root session shape with safe parents.

    Used to map ``E_UNSAFE_PATH`` from a missing leaf to ``E_NO_MATCH`` only when:

    - the path is lexically ``projects/<slug>/<uuid>.jsonl`` under *root*
    - the leaf does not exist
    - every existing parent under the root is a real (non-symlink) directory

    Symlinked parents, invalid layout, and non-ENOENT parent errors stay unsafe.
    """

    absolute = os.path.abspath(path)
    abs_root = os.path.abspath(root)
    if not _lexical_session_shape(absolute, abs_root):
        return False
    if os.path.lexists(absolute):
        return False
    try:
        relative = os.path.relpath(absolute, abs_root)
    except ValueError:
        return False
    current = abs_root
    parts = [part for part in Path(relative).parts if part not in ("", ".")]
    for part in parts[:-1]:
        if part == os.pardir:
            return False
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            # Intermediate component missing — under-root session shape no-match.
            return True
        except OSError:
            # EACCES / other errors must not be reclassified as ordinary no-match.
            return False
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            return False
    return True


def _exact_path_candidate(root: str, query: Query) -> str | None:
    """Resolve an absolute path ref without store-wide discovery when possible.

    Returns ``None`` when *query.ref* is not an absolute path. Raises
    ``E_NO_MATCH`` for a missing path that is still under the approved root
    with safe real parents, and ``E_UNSAFE_PATH`` for outside/symlink/layout
    failures (including a missing leaf under a symlinked parent).
    """

    ref = query.ref.strip() if query.ref else None
    if not ref or not os.path.isabs(ref):
        return None
    try:
        path, _ = require_regular_no_symlinks(ref, root)
    except DiagnosticError as error:
        if error.code == "E_UNSAFE_PATH":
            absolute = os.path.abspath(ref)
            # Missing under-root target with safe parents → no match.
            # Outside / symlink parents stay unsafe even when the leaf is absent.
            if _missing_under_safe_parents(absolute, root):
                raise DiagnosticError("E_NO_MATCH", source="claude", provider=FORMAT_ID) from error
        raise
    if not _session_layout_ok(path, root):
        raise DiagnosticError.unsafe_path()
    return path


def _paths_under_projects(
    project_dirs: list[str],
    *,
    exact_uuid: str | None = None,
) -> list[str]:
    """Collect session JSONL paths under the given project directories.

    Exact UUID lookups probe only ``<uuid>.jsonl`` per project (no session-dir
    scandir). Non-exact list still bounds directory membership.
    """

    values: list[str] = []
    if exact_uuid is not None:
        for project in project_dirs:
            candidate = os.path.join(project, f"{exact_uuid}.jsonl")
            if _regular_session_file(candidate):
                values.append(candidate)
                if len(values) > DEFAULT_BOUNDS.scanned_records:
                    raise DiagnosticError.limit_exceeded()
        return values

    for project in project_dirs:
        names = _bounded_names(project, limit=DEFAULT_BOUNDS.scanned_records)
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            stem = name[:-6]
            try:
                uuid.UUID(stem)
            except ValueError:
                continue
            candidate = os.path.join(project, name)
            if _regular_session_file(candidate):
                values.append(candidate)
                if len(values) > DEFAULT_BOUNDS.scanned_records:
                    raise DiagnosticError.limit_exceeded()
    return values


def _session_paths(
    root: str,
    *,
    prefer_slugs: tuple[str, ...] = (),
    exact_uuid: str | None = None,
    cwd_scoped: bool = False,
) -> list[str]:
    """Enumerate session JSONL paths.

    Fast paths (issue #19):

    - exact UUID + preferred cwd slug(s): construct
      ``projects/<slug>/<uuid>.jsonl`` and return it when present without
      enumerating unrelated project directories
    - cwd-scoped discovery uses preferred dirs only (no full projects scandir)
      when those dirs exist

    Exact UUID still falls back to a broader, basename-probed scan when the
    direct candidate is absent. Recorded-cwd validation remains in
    ``_summary`` / ``show`` — slug presence alone is never authority.
    """
    if exact_uuid is not None and prefer_slugs:
        # Prefer direct slug path(s) first, then remaining project buckets via
        # basename probe. Callers that can validate recorded cwd (list/show)
        # should use `_exact_uuid_paths` so a cwd-mismatched direct file does
        # not block an eligible relocated copy (Codex P2 on #19).
        return _exact_uuid_paths(root, exact_uuid, prefer_slugs=prefer_slugs)

    if cwd_scoped and prefer_slugs:
        paths, _fallback = _cwd_scoped_session_paths(root, prefer_slugs)
        return paths

    project_dirs = _project_dirs(root, prefer_slugs=prefer_slugs, prefer_only=False)
    return _paths_under_projects(project_dirs, exact_uuid=exact_uuid)


def _cwd_scoped_session_paths(
    root: str,
    prefer_slugs: tuple[str, ...],
) -> tuple[list[str], bool]:
    preferred_dirs = _project_dirs(root, prefer_slugs=prefer_slugs, prefer_only=True)
    if preferred_dirs:
        return _paths_under_projects(preferred_dirs, exact_uuid=None), False
    # Preferred slug dir missing: preserve legacy broad list so sessions whose
    # project bucket name differs can still match recorded cwd.
    project_dirs = _project_dirs(root, prefer_slugs=prefer_slugs, prefer_only=False)
    return _paths_under_projects(project_dirs, exact_uuid=None), True


def _exact_uuid_paths(
    root: str,
    exact_uuid: str,
    *,
    prefer_slugs: tuple[str, ...] = (),
) -> list[str]:
    """Ordered exact-UUID candidates: preferred slug files, then broad probe.

    Preferred direct files come first so callers can accept them without a full
    projects scandir when recorded-cwd validation succeeds. Broad basename
    probing still runs so a cwd-mismatched file under the guessed slug cannot
    hide an eligible copy in another project bucket.
    """

    direct = _direct_uuid_under_slugs(root, exact_uuid, prefer_slugs)
    project_dirs = _project_dirs(root, prefer_slugs=prefer_slugs, prefer_only=False)
    broad = _paths_under_projects(project_dirs, exact_uuid=exact_uuid)
    seen: set[str] = set()
    ordered: list[str] = []
    for path in (*direct, *broad):
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def _prefer_slugs_for(query: Query) -> tuple[str, ...]:
    if not query.cwd:
        return ()
    try:
        return (_slugify_cwd(canonicalize_cwd(query.cwd)),)
    except DiagnosticError:
        return (_slugify_cwd(query.cwd),)


def _exact_uuid_ref(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _decode_record(raw: bytes, *, terminal_partial: bool) -> tuple[dict[str, Any] | None, str | None]:
    stripped = raw.strip()
    if not stripped:
        return None, None
    try:
        text = stripped.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=_reject_json_constant,
            parse_float=_finite_json_float,
        )
    except (UnicodeDecodeError, ValueError, _DuplicateKey, RecursionError) as error:
        if terminal_partial:
            return None, "W_PARTIAL_TAIL"
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    if value["type"] not in _KNOWN_RECORD_TYPES:
        return None, "W_UNKNOWN_RECORD_SKIPPED"
    return value, None


def _parse_lines(data: bytes, budget: ReadBudget) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Parse a small in-memory Claude fixture; full transcripts use streaming."""

    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    lines = data.splitlines(keepends=True)
    for index, raw in enumerate(lines):
        budget.consume_records()
        terminal_partial = index == len(lines) - 1 and not raw.endswith((b"\n", b"\r"))
        value, warning = _decode_record(raw, terminal_partial=terminal_partial)
        if warning is not None:
            warnings.append(warning)
        if value is None:
            if terminal_partial and warning == "W_PARTIAL_TAIL":
                break
            continue
        records.append(value)
    if not records:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="claude", provider=FORMAT_ID)
    return records, tuple(dict.fromkeys(warnings))


def _scan_metadata_chunk(
    data: bytes,
    *,
    budget: ReadBudget,
    metadata: _TranscriptMetadata,
    warnings: list[str],
    starts_mid_line: bool,
    ends_at_eof: bool,
    stop_when_primary_ready: bool,
    stop_when_cwd_ready: bool = False,
) -> None:
    lines = data.splitlines(keepends=True)
    start = 1 if starts_mid_line and lines else 0
    for index in range(start, len(lines)):
        raw = lines[index]
        is_last = index == len(lines) - 1
        has_terminator = raw.endswith((b"\n", b"\r"))
        if is_last and not has_terminator and not ends_at_eof:
            break
        budget.consume_records()
        value, warning = _decode_record(
            raw,
            terminal_partial=is_last and not has_terminator and ends_at_eof,
        )
        if warning is not None:
            warnings.append(warning)
        if value is None:
            if warning == "W_PARTIAL_TAIL":
                break
            continue
        metadata.observe(value)
        if stop_when_cwd_ready and metadata.cwds:
            break
        if (
            stop_when_primary_ready
            and metadata.cwds
            and metadata.created_at is not None
            and metadata.title is not None
        ):
            break


def _metadata_windows(
    path: str,
    root: str,
    budget: ReadBudget,
    *,
    cwd_only: bool = False,
) -> tuple[StableWindows, _TranscriptMetadata, tuple[str, ...]]:
    _validate_claude_bounds(budget)
    observation = stable_read_windows(
        path,
        root=root,
        head_bytes=_METADATA_HEAD_BYTES,
        tail_bytes=_METADATA_TAIL_BYTES,
        max_bytes=min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
        attempts=min(budget.limits.snapshot_attempts, DEFAULT_BOUNDS.snapshot_attempts),
        membership_limit=min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records),
        budget=budget,
    )
    metadata = _TranscriptMetadata()
    warnings: list[str] = []
    full_in_head = observation.fingerprint.size <= len(observation.head)
    _scan_metadata_chunk(
        observation.head,
        budget=budget,
        metadata=metadata,
        warnings=warnings,
        starts_mid_line=False,
        ends_at_eof=full_in_head,
        stop_when_primary_ready=not full_in_head and not cwd_only,
        stop_when_cwd_ready=cwd_only,
    )
    if not full_in_head and observation.tail and not (cwd_only and metadata.cwds):
        tail = observation.tail
        starts_mid_line = observation.tail_offset > 0
        if observation.tail_offset < len(observation.head):
            overlap = len(observation.head) - observation.tail_offset
            tail = tail[min(overlap, len(tail)) :]
            starts_mid_line = bool(tail)
        _scan_metadata_chunk(
            tail,
            budget=budget,
            metadata=metadata,
            warnings=warnings,
            starts_mid_line=starts_mid_line,
            ends_at_eof=True,
            stop_when_primary_ready=False,
            stop_when_cwd_ready=cwd_only,
        )
    if metadata.records_seen == 0:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="claude", provider=FORMAT_ID)
    return observation, metadata, tuple(dict.fromkeys(warnings))


def _recorded_cwd_matches(
    path: str,
    root: str,
    requested_cwd: str,
    budget: ReadBudget,
) -> bool:
    _observation, metadata, _warnings = _metadata_windows(
        path,
        root,
        budget,
        cwd_only=True,
    )
    return metadata.selected_cwd(requested_cwd) is not None


def _provisional_metadata_budget(budget: ReadBudget) -> ReadBudget:
    return ReadBudget(
        budget.limits,
        records=budget.records,
        transcript_records_read=budget.transcript_records_read,
        bytes_read=budget.bytes_read,
        turns=budget.turns,
    )


def _commit_metadata_budget(target: ReadBudget, admitted: ReadBudget) -> None:
    target.consume_records(admitted.records - target.records)
    target.consume_bytes(admitted.bytes_read - target.bytes_read)


def _validate_claude_bounds(budget: ReadBudget) -> None:
    limits = budget.limits
    bounded = (
        ("scanned_records", 0, DEFAULT_BOUNDS.scanned_records),
        ("transcript_records", 0, DEFAULT_BOUNDS.transcript_records),
        ("record_bytes", 0, DEFAULT_BOUNDS.record_bytes),
        ("source_read_bytes", 0, DEFAULT_BOUNDS.source_read_bytes),
        ("snapshot_attempts", 1, DEFAULT_BOUNDS.snapshot_attempts),
    )
    if any(not minimum <= getattr(limits, name) <= maximum for name, minimum, maximum in bounded):
        raise DiagnosticError.invalid(source="claude")


def _rfc3339(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _mtime(read: StableWindows | FileSnapshot) -> str:
    return datetime.fromtimestamp(read.fingerprint.mtime_ns / 1_000_000_000, timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _within(updated_at: str | None, minutes: int | None) -> bool:
    from .common import within_age

    return within_age(updated_at, minutes, default_minutes=DEFAULT_BOUNDS.listing_age_minutes)


def _record_cwd(records: Iterable[Mapping[str, Any]], requested: str | None = None) -> str | None:
    metadata = _TranscriptMetadata()
    for record in records:
        metadata.observe(record)
    return metadata.selected_cwd(requested)


def _session_id(path: str, records: Iterable[Mapping[str, Any]]) -> str:
    file_id = Path(path).stem
    values = {item for record in records if isinstance((item := record.get("sessionId")), str)}
    if len(values) > 1 or (values and next(iter(values)) != file_id):
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    return file_id


def _title_and_branch(records: Iterable[Mapping[str, Any]]) -> tuple[str | None, str | None]:
    custom: str | None = None
    ai: str | None = None
    summary: str | None = None
    last_prompt: str | None = None
    first_user: str | None = None
    branch: str | None = None
    for record in records:
        if isinstance(record.get("customTitle"), str):
            custom = record["customTitle"]
        if isinstance(record.get("aiTitle"), str):
            ai = record["aiTitle"]
        if isinstance(record.get("summary"), str):
            summary = record["summary"]
        if isinstance(record.get("lastPrompt"), str):
            last_prompt = record["lastPrompt"]
        if isinstance(record.get("gitBranch"), str):
            branch = record["gitBranch"]
        if first_user is None and record.get("type") == "user" and not record.get("isMeta"):
            message = record.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                candidate = message["content"]
                if not candidate.lstrip().startswith("<command-name>"):
                    first_user = candidate
    return next((item for item in (custom, ai, summary, last_prompt, first_user) if item and item.strip()), None), branch


def _parent_bridge_map(
    records: list[dict[str, Any]],
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Map every uuid → parentUuid for hop-through non-conversation nodes.

    Live Claude transcripts often parent user/assistant rows to *attachment*
    (hooks, skill listings, …). Those UUIDs are not conversation-renderable but
    must not break the walk (Grok-style main-line recovery).
    """
    bridge: dict[str, str | None] = {}
    digests: dict[str, str] = {}
    for record in records:
        _observe_replay_record(record, digests=digests, bridge=bridge)
    return bridge, digests


def _replay_digest(record: Mapping[str, Any]) -> str:
    semantic = {key: value for key, value in record.items() if key not in _REPLAY_ENVELOPE_FIELDS}
    message = semantic.get("message")
    if isinstance(message, Mapping):
        # Claude replay/bridge rows may zero usage accounting while preserving
        # the actual role/content/model/stop semantics of the message.
        semantic["message"] = {key: value for key, value in message.items() if key != "usage"}
    try:
        encoded = json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
    return hashlib.sha256(encoded).hexdigest()


def _observe_replay_record(
    record: Mapping[str, Any],
    *,
    digests: dict[str, str],
    bridge: dict[str, str | None],
) -> tuple[str, str] | None:
    identifier = record.get("uuid")
    if identifier is None:
        if record.get("type") in _UUID_RECORD_TYPES:
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
        return None
    if not isinstance(identifier, str):
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    try:
        uuid.UUID(identifier)
    except ValueError as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
    digest = _replay_digest(record)
    if identifier in digests and digests[identifier] != digest:
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    digests[identifier] = digest
    parent = record.get("parentUuid")
    if parent is not None:
        if not isinstance(parent, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
        try:
            uuid.UUID(parent)
        except ValueError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
    bridge[identifier] = parent
    logical = record.get("logicalParentUuid")
    if logical is not None:
        if not isinstance(logical, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
        try:
            uuid.UUID(logical)
        except ValueError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
    return identifier, digest


def _resolve_parent_id(
    parent: object,
    *,
    nodes: Mapping[str, tuple[int, dict[str, Any]]],
    bridge: Mapping[str, str | None],
    record: Mapping[str, Any],
) -> tuple[str | None, bool]:
    """Return (next_conversation_or_missing_id, broken).

    When *parent* is a non-conversation uuid present only in *bridge*, hop
    until a conversation node, a null parent, a cycle, or a truly missing id.
    """
    if parent is None:
        return None, False
    if not isinstance(parent, str):
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    hop_seen: set[str] = set()
    current: str | None = parent
    while current is not None:
        if current in nodes:
            return current, False
        if current in hop_seen:
            return current, True
        hop_seen.add(current)
        if current not in bridge:
            # Optional logicalParentUuid on the *current conversation record*
            # only applies once at the start; after hops we only use bridge.
            if current == parent:
                logical = record.get("logicalParentUuid")
                if isinstance(logical, str) and logical and logical != parent:
                    current = logical
                    continue
            return current, True
        current = bridge[current]
    return None, False


def _lineage_ids(
    nodes: Mapping[str, tuple[int, dict[str, Any]]],
    bridge: Mapping[str, str | None],
) -> tuple[list[str], tuple[str, ...]]:
    if not nodes:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="claude", provider=FORMAT_ID)
    # Leaf = conversation node never referenced as a *resolved* parent of another
    # conversation node (bridge hops through attachment/etc. first).
    parent_ids: set[str] = set()
    for _identifier, (_index, record) in nodes.items():
        parent = record.get("parentUuid")
        resolved, _ = _resolve_parent_id(parent, nodes=nodes, bridge=bridge, record=record)
        if resolved is not None:
            parent_ids.add(resolved)
        elif parent is None:
            logical = record.get("logicalParentUuid")
            resolved_logical, _ = _resolve_parent_id(
                logical, nodes=nodes, bridge=bridge, record=record
            )
            if resolved_logical is not None:
                parent_ids.add(resolved_logical)
    leaves = [(index, identifier, record) for identifier, (index, record) in nodes.items() if identifier not in parent_ids]
    if not leaves:
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    _, current_id, _ = max(
        leaves,
        key=lambda item: (_rfc3339(item[2].get("timestamp")) or "", item[0], item[1]),
    )
    reverse: list[str] = []
    seen: set[str] = set()
    warnings: list[str] = []
    while current_id:
        if current_id in seen:
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
        seen.add(current_id)
        found = nodes.get(current_id)
        if found is None:
            warnings.append("W_BROKEN_CHAIN")
            break
        record = found[1]
        if record.get("type") == "system" and record.get("subtype") in _COMPACTION_SUBTYPES:
            break
        reverse.append(current_id)
        parent = record.get("parentUuid")
        if parent is None and isinstance(record.get("logicalParentUuid"), str):
            parent = record.get("logicalParentUuid")
        if parent is None:
            break
        next_id, broken = _resolve_parent_id(parent, nodes=nodes, bridge=bridge, record=record)
        if broken:
            warnings.append("W_BROKEN_CHAIN")
            break
        if next_id is None:
            break
        current_id = next_id
    reverse.reverse()
    return reverse, tuple(dict.fromkeys(warnings))


def _logical_lineage(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    nodes: dict[str, tuple[int, dict[str, Any]]] = {}
    bridge, _digests = _parent_bridge_map(records)
    for index, record in enumerate(records):
        if record.get("type") not in _UUID_RECORD_TYPES:
            continue
        identifier = record.get("uuid")
        if not isinstance(identifier, str):
            continue
        try:
            uuid.UUID(identifier)
        except ValueError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
        if record.get("isSidechain") is True:
            continue
        # Claude bridge/replay blocks may repeat a semantic conversation node
        # with a new parent and envelope metadata. The latest physical version
        # is the authoritative graph edge; core-content conflicts still fail.
        nodes[identifier] = (index, record)
    identifiers, warnings = _lineage_ids(nodes, bridge)
    return [nodes[identifier][1] for identifier in identifiers], warnings


def _flatten_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, Mapping) and item.get("type") in {"text", "input_text", "output_text"}:
                if isinstance(item.get("text"), str):
                    chunks.append(item["text"])
        return "\n".join(chunks) if chunks else None
    return None


def _turn_records(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    record_type = record.get("type")
    if record_type not in {"user", "assistant"} or record.get("isMeta") is True:
        return []
    message = record.get("message")
    if not isinstance(message, Mapping):
        return []
    message_role = message.get("role") if isinstance(message.get("role"), str) else record_type
    if message_role not in {"user", "assistant"}:
        return []
    timestamp = _rfc3339(record.get("timestamp"))
    content = message.get("content")
    if isinstance(content, str):
        return [{"role": message_role, "content": content, "timestamp": timestamp}]
    if not isinstance(content, list):
        return []
    values: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind in {"thinking", "redacted_thinking", "signature", "tool_use"}:
            continue
        if kind in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
            values.append({"role": message_role, "content": item["text"], "timestamp": timestamp})
        elif kind == "tool_result":
            text = _flatten_text(item.get("content"))
            if text is not None:
                values.append(
                    {
                        "role": "tool",
                        "content": text,
                        "tool_name": item.get("tool_name") if isinstance(item.get("tool_name"), str) else None,
                        "timestamp": timestamp,
                    }
                )
    return values


def _metadata_session_id(path: str, metadata: _TranscriptMetadata) -> str:
    file_id = Path(path).stem
    if len(metadata.session_ids) > 1 or (
        metadata.session_ids and next(iter(metadata.session_ids)) != file_id
    ):
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    return file_id


def _graph_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "type",
            "uuid",
            "parentUuid",
            "logicalParentUuid",
            "timestamp",
            "subtype",
            "isSidechain",
        )
        if key in record
    }


def _index_snapshot(snapshot: FileSnapshot, budget: ReadBudget) -> _TranscriptIndex:
    _validate_claude_bounds(budget)
    metadata = _TranscriptMetadata()
    nodes: dict[str, _TranscriptNode] = {}
    bridge: dict[str, str | None] = {}
    digests: dict[str, str] = {}
    warnings: list[str] = []
    maximum_record = budget.limits.record_bytes
    with open(snapshot.path, "rb") as handle:
        index = 0
        while True:
            offset = handle.tell()
            raw = handle.readline(maximum_record + 1)
            if not raw:
                break
            budget.consume_transcript_records()
            if len(raw) > maximum_record:
                raise DiagnosticError.limit_exceeded()
            terminal_partial = not raw.endswith((b"\n", b"\r"))
            record, warning = _decode_record(raw, terminal_partial=terminal_partial)
            if warning is not None:
                warnings.append(warning)
            if record is None:
                if warning == "W_PARTIAL_TAIL":
                    break
                index += 1
                continue
            metadata.observe(record)
            observed = _observe_replay_record(record, digests=digests, bridge=bridge)
            if observed is not None and record.get("type") in _UUID_RECORD_TYPES:
                identifier, digest = observed
                if record.get("isSidechain") is not True:
                    nodes[identifier] = _TranscriptNode(
                        identifier=identifier,
                        index=index,
                        offset=offset,
                        digest=digest,
                        record=_graph_record(record),
                    )
            index += 1
    if metadata.records_seen == 0 or not nodes:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="claude", provider=FORMAT_ID)
    return _TranscriptIndex(
        metadata=metadata,
        nodes=nodes,
        bridge=bridge,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _indexed_lineage(index: _TranscriptIndex) -> tuple[list[_TranscriptNode], tuple[str, ...]]:
    graph = {
        identifier: (node.index, node.record)
        for identifier, node in index.nodes.items()
    }
    identifiers, warnings = _lineage_ids(graph, index.bridge)
    return [index.nodes[identifier] for identifier in identifiers], warnings


def _load_lineage_records(
    snapshot: FileSnapshot,
    nodes: Iterable[_TranscriptNode],
    *,
    maximum_record: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with open(snapshot.path, "rb") as handle:
        for node in nodes:
            handle.seek(node.offset)
            raw = handle.readline(maximum_record + 1)
            if not raw or len(raw) > maximum_record:
                raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
            record, warning = _decode_record(raw, terminal_partial=False)
            if warning is not None or record is None:
                raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
            if (
                record.get("uuid") != node.identifier
                or _replay_digest(record) != node.digest
                or _graph_record(record) != node.record
            ):
                raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
            records.append(record)
    return records


def _summary(path: str, root: str, query: Query, budget: ReadBudget) -> SessionSummary | None:
    observation, metadata, warnings = _metadata_windows(path, root, budget)
    identifier = _metadata_session_id(path, metadata)
    cwd = metadata.selected_cwd(query.cwd)
    if query.cwd is not None and (cwd is None or not same_cwd(cwd, query.cwd)):
        return None
    updated = _mtime(observation)
    if not _within(updated, query.within_min):
        return None
    # Title may be null; still list coherent sessions so exact-id/latest remain selectable.
    return SessionSummary(
        source="claude",
        session_id=identifier,
        source_path=path,
        title=metadata.title,
        cwd=cwd,
        branch=metadata.branch,
        created_at=metadata.created_at,
        updated_at=updated,
        provider=FORMAT_ID,
        warnings=warnings,
    )


class ClaudeAdapter:
    key = "claude"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        root = _existing_root(query)
        return (root,) if root else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            root = _existing_root(query)
            if root is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")

            def _probe_path(path: str) -> CapabilityReport | None:
                try:
                    _observation, metadata, _warnings = _metadata_windows(
                        path, root, ReadBudget()
                    )
                    _metadata_session_id(path, metadata)
                    return CapabilityReport(
                        self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,)
                    )
                except DiagnosticError as error:
                    if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                        return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                    return None

            # Exact absolute path / UUID must not depend on project-dir enumeration
            # (issue #19: 2k+ siblings or project buckets would fail probe first).
            try:
                exact_path = _exact_path_candidate(root, query)
            except DiagnosticError as error:
                if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                    return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                if (
                    error.code == "E_NO_MATCH"
                    and query.ref
                    and os.path.isabs(query.ref.strip())
                ):
                    # Missing approved session path: capability remains supported
                    # so list/show can surface E_NO_MATCH without sibling scandir.
                    projects = os.path.join(root, "projects")
                    if _regular_directory(projects, root):
                        return CapabilityReport(
                            self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,)
                        )
                    return CapabilityReport(self.key, FORMAT_ID, "unavailable", root=root)
                exact_path = None
            if exact_path is not None:
                report = _probe_path(exact_path)
                if report is not None:
                    return report

            exact = _exact_uuid_ref(query.ref)
            prefer = _prefer_slugs_for(query)
            if exact is not None:
                # Exact UUID: basename probe only (never scandir session siblings).
                if prefer:
                    for path in _direct_uuid_under_slugs(root, exact, prefer):
                        report = _probe_path(path)
                        if report is not None:
                            return report
                for path in _exact_uuid_paths(root, exact, prefer_slugs=prefer):
                    report = _probe_path(path)
                    if report is not None:
                        return report
                projects = os.path.join(root, "projects")
                if _regular_directory(projects, root):
                    return CapabilityReport(
                        self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,)
                    )
                return CapabilityReport(self.key, FORMAT_ID, "unavailable", root=root)

            paths = _session_paths(root, prefer_slugs=prefer, cwd_scoped=bool(prefer))
            if not paths:
                # Empty cwd-scoped dir is still a supported store layout if projects exists.
                projects = os.path.join(root, "projects")
                if _regular_directory(projects, root):
                    return CapabilityReport(self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,))
                return CapabilityReport(self.key, FORMAT_ID, "unavailable", root=root)
            for path in paths:
                report = _probe_path(path)
                if report is not None:
                    return report
            return CapabilityReport(self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,))
        except DiagnosticError as error:
            state = "unsafe" if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"} else "unsupported"
            return CapabilityReport(self.key, FORMAT_ID, state)

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        values: list[SessionSummary] = []
        cwd_fallback = False
        # Absolute approved path: validate/read that file only (#19).
        exact_path = _exact_path_candidate(root, query)
        if exact_path is not None:
            paths: list[str] = [exact_path]
        else:
            exact = _exact_uuid_ref(query.ref)
            prefer = _prefer_slugs_for(query)
            if exact is not None and prefer:
                # Fast path: try preferred slug file(s) first without broad
                # projects scandir. Only enumerate other buckets when none of
                # the direct candidates survive recorded-cwd validation.
                direct = _direct_uuid_under_slugs(root, exact, prefer)
                for path in direct:
                    item = _summary(path, root, query, budget)
                    if item is not None:
                        values.append(item)
                if values:
                    values.sort(
                        key=lambda item: (
                            item.updated_at is None,
                            item.updated_at or "",
                            item.session_id,
                        ),
                        reverse=True,
                    )
                    return values
                # Direct file missing or cwd-mismatched — broad basename probe.
                paths = _exact_uuid_paths(root, exact, prefer_slugs=prefer)
                # Already tried direct paths above; skip re-summarizing them.
                tried = set(direct)
                paths = [path for path in paths if path not in tried]
            else:
                # Non-exact list still cwd-scopes when a preferred slug exists.
                if prefer:
                    paths, cwd_fallback = _cwd_scoped_session_paths(root, prefer)
                else:
                    paths = _session_paths(root, exact_uuid=exact)
        for path in paths:
            if cwd_fallback and query.cwd is not None:
                prefilter_budget = _provisional_metadata_budget(budget)
                if not _recorded_cwd_matches(
                    path,
                    root,
                    query.cwd,
                    prefilter_budget,
                ):
                    _commit_metadata_budget(budget, prefilter_budget)
                    continue
            # List still needs recorded cwd/title for collision safety; show does lineage.
            item = _summary(path, root, query, budget)
            if item is not None:
                values.append(item)
        values.sort(key=lambda item: (item.updated_at is None, item.updated_at or "", item.session_id), reverse=True)
        return values

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        path = ref.source_path
        if path is None:
            prefer = _prefer_slugs_for(query)
            # Prefer direct slug file(s), then broad basename probe only if needed
            # (cwd-mismatched direct must not hide a relocated eligible copy).
            if prefer:
                ordered = _direct_uuid_under_slugs(root, ref.session_id, prefer)
            else:
                ordered = []
            if not ordered:
                ordered = _session_paths(
                    root,
                    prefer_slugs=prefer,
                    exact_uuid=ref.session_id,
                    cwd_scoped=False,
                )
            else:
                # Validate direct candidates; fall back to broad only on cwd miss
                # (summary is None). Limit/busy/corrupt diagnostics must propagate
                # (Codex P2 on #19) — do not swallow as soft no-match.
                chosen: str | None = None
                for candidate in ordered:
                    summary = _summary(candidate, root, query, budget)
                    if summary is not None and summary.session_id == ref.session_id:
                        chosen = candidate
                        break
                if chosen is not None:
                    path = chosen
                    ordered = []
                else:
                    tried = set(ordered)
                    ordered = [
                        item
                        for item in _exact_uuid_paths(
                            root, ref.session_id, prefer_slugs=prefer
                        )
                        if item not in tried
                    ]
            if path is None:
                if not ordered:
                    raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
                if len(ordered) == 1:
                    path = ordered[0]
                else:
                    for candidate in ordered:
                        summary = _summary(candidate, root, query, budget)
                        if summary is not None and summary.session_id == ref.session_id:
                            path = candidate
                            break
                    if path is None:
                        raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
        _validate_claude_bounds(budget)
        with snapshot_regular_file(
            path,
            root=root,
            bounds=budget.limits,
            attempts=budget.limits.snapshot_attempts,
            membership_limit=budget.limits.scanned_records,
            budget=budget,
            provider=FORMAT_ID,
        ) as observation:
            index = _index_snapshot(observation, budget)
            if _metadata_session_id(path, index.metadata) != ref.session_id:
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            cwd = index.metadata.selected_cwd(query.cwd)
            if query.cwd is not None and cwd is None:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
            lineage, lineage_warnings = _indexed_lineage(index)
            records = _load_lineage_records(
                observation,
                lineage,
                maximum_record=budget.limits.record_bytes,
            )
            turns: list[Turn] = []
            all_warnings = list((*index.warnings, *lineage_warnings))
            turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
            for record in records:
                for raw in _turn_records(record):
                    turn, turn_warnings = sanitize_turn_record(
                        raw,
                        ordinal=len(turns),
                        bounds=turn_bounds,
                    )
                    all_warnings.extend(turn_warnings)
                    if turn is not None:
                        budget.consume_turns()
                        turns.append(turn)
            last_user = next(
                (turn.content for turn in reversed(turns) if turn.role == "user"),
                None,
            )
            last_assistant = next(
                (turn.content for turn in reversed(turns) if turn.role == "assistant"),
                None,
            )
            return Session(
                source=self.key,
                session_id=ref.session_id,
                source_path=path,
                title=index.metadata.title,
                cwd=cwd,
                branch=index.metadata.branch,
                created_at=index.metadata.created_at,
                updated_at=_mtime(observation),
                last_user_request=last_user,
                last_assistant_action=last_assistant,
                turns=tuple(turns),
                warnings=tuple(dict.fromkeys(all_warnings)),
            )


ADAPTER = ClaudeAdapter()
