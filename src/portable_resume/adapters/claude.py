"""Read Claude Code JSONL sessions as inert context.

This adapter intentionally understands one pinned structural family only.  It
does not invoke Claude Code, follow symlinks, or infer a transcript from an
unknown record shape.
"""

from __future__ import annotations

import json
import os
import stat
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import StableRead, stable_read_bytes
from .base import CapabilityReport, ResolvedRef

FORMAT_ID = "claude-jsonl-v1"
# Grok-build style: prefer cwd slug project dir; allow large ~/.claude/projects trees.
_PROJECT_DIR_LIMIT = 1_024
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
        "attribution-snapshot",
        "content-replacement",
        "context-collapse-commit",
        "context-collapse-snapshot",
        "attachment",
    }
)
_COMPACTION_SUBTYPES = frozenset({"compact_boundary", "compaction", "compact"})


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


def _project_dirs(root: str, *, prefer_slugs: tuple[str, ...] = ()) -> list[str]:
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
    try:
        names = sorted(os.listdir(projects))
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    if len(names) > DEFAULT_BOUNDS.scanned_records:
        raise DiagnosticError.limit_exceeded()
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


def _session_paths(
    root: str,
    *,
    prefer_slugs: tuple[str, ...] = (),
    exact_uuid: str | None = None,
    cwd_scoped: bool = False,
) -> list[str]:
    """Enumerate session JSONL paths.

    When *cwd_scoped* and a preferred slug directory exists, only that project
    directory is scanned (Grok-build list behavior for a concrete cwd). Exact
    UUID lookup still falls back to a broader scan when the slug dir misses.
    """
    project_dirs = _project_dirs(root, prefer_slugs=prefer_slugs)
    if cwd_scoped and prefer_slugs:
        scoped = [path for path in project_dirs if os.path.basename(path) in prefer_slugs]
        if scoped:
            project_dirs = scoped
    values: list[str] = []
    for project in project_dirs:
        try:
            names = sorted(os.listdir(project))
        except OSError as error:
            raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
        if len(names) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            stem = name[:-6]
            try:
                uuid.UUID(stem)
            except ValueError:
                continue
            if exact_uuid is not None and stem != exact_uuid:
                continue
            candidate = os.path.join(project, name)
            try:
                current = os.lstat(candidate)
            except OSError:
                continue
            if stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode):
                values.append(candidate)
                if len(values) > DEFAULT_BOUNDS.scanned_records:
                    raise DiagnosticError.limit_exceeded()
    if cwd_scoped and prefer_slugs and exact_uuid is not None and not values:
        # UUID not under the cwd slug — scan remaining projects (Grok _find_claude_id).
        return _session_paths(root, prefer_slugs=prefer_slugs, exact_uuid=exact_uuid, cwd_scoped=False)
    return values


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


def _parse_lines(data: bytes, budget: ReadBudget) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    lines = data.splitlines(keepends=True)
    for index, raw in enumerate(lines):
        budget.consume_records()
        terminal_partial = index == len(lines) - 1 and not raw.endswith((b"\n", b"\r"))
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            text = stripped.decode("utf-8")
            value = json.loads(text, object_pairs_hook=_object)
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
            if terminal_partial:
                warnings.append("W_PARTIAL_TAIL")
                break
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
        if not isinstance(value, dict):
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
        record_type = value.get("type")
        if not isinstance(record_type, str):
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
        if record_type not in _KNOWN_RECORD_TYPES:
            # Skip unknown structural families; do not interpret payloads (Grok parity).
            warnings.append("W_UNKNOWN_RECORD_SKIPPED")
            continue
        records.append(value)
    if not records:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="claude", provider=FORMAT_ID)
    return records, tuple(dict.fromkeys(warnings))


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


def _mtime(read: StableRead) -> str:
    return datetime.fromtimestamp(read.fingerprint.mtime_ns / 1_000_000_000, timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _within(updated_at: str | None, minutes: int | None) -> bool:
    if minutes is None:
        minutes = DEFAULT_BOUNDS.listing_age_minutes
    if updated_at is None:
        return False
    try:
        stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return stamp >= time.time() - minutes * 60


def _record_cwd(records: Iterable[Mapping[str, Any]]) -> str | None:
    values: set[str] = set()
    for record in records:
        value = record.get("cwd")
        if isinstance(value, str):
            try:
                values.add(canonicalize_cwd(value))
            except DiagnosticError:
                raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    if len(values) > 1:
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    return next(iter(values), None)


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


def _parent_bridge_map(records: list[dict[str, Any]]) -> dict[str, str | None]:
    """Map every uuid → parentUuid for hop-through non-conversation nodes.

    Live Claude transcripts often parent user/assistant rows to *attachment*
    (hooks, skill listings, …). Those UUIDs are not conversation-renderable but
    must not break the walk (Grok-style main-line recovery).
    """
    bridge: dict[str, str | None] = {}
    for record in records:
        identifier = record.get("uuid")
        if not isinstance(identifier, str):
            continue
        try:
            uuid.UUID(identifier)
        except ValueError:
            continue
        parent = record.get("parentUuid")
        if parent is None:
            bridge[identifier] = None
        elif isinstance(parent, str):
            bridge[identifier] = parent
        # Non-string parentUuid is ignored for bridging only.
    return bridge


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


def _logical_lineage(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    nodes: dict[str, tuple[int, dict[str, Any]]] = {}
    bridge = _parent_bridge_map(records)
    for index, record in enumerate(records):
        if record.get("type") not in _UUID_RECORD_TYPES or record.get("isSidechain") is True:
            continue
        identifier = record.get("uuid")
        if not isinstance(identifier, str):
            continue
        try:
            uuid.UUID(identifier)
        except ValueError as error:
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID) from error
        if identifier in nodes:
            raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
        nodes[identifier] = (index, record)
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
    reverse: list[dict[str, Any]] = []
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
        reverse.append(record)
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


def _read(path: str, root: str, budget: ReadBudget) -> tuple[StableRead, list[dict[str, Any]], tuple[str, ...]]:
    observation = stable_read_bytes(
        path,
        root=root,
        max_bytes=DEFAULT_BOUNDS.record_bytes,
        budget=budget,
    )
    records, warnings = _parse_lines(observation.data, budget)
    return observation, records, warnings


def _summary(path: str, root: str, query: Query, budget: ReadBudget) -> SessionSummary | None:
    observation, records, warnings = _read(path, root, budget)
    identifier = _session_id(path, records)
    cwd = _record_cwd(records)
    if query.cwd is not None and (cwd is None or not same_cwd(cwd, query.cwd)):
        return None
    updated = _mtime(observation)
    if not _within(updated, query.within_min):
        return None
    title, branch = _title_and_branch(records)
    # Title may be null; still list coherent sessions so exact-id/latest remain selectable.
    timestamps = [_rfc3339(record.get("timestamp")) for record in records]
    created = min((stamp for stamp in timestamps if stamp), default=None)
    return SessionSummary(
        source="claude",
        session_id=identifier,
        source_path=path,
        title=title,
        cwd=cwd,
        branch=branch,
        created_at=created,
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
            prefer = _prefer_slugs_for(query)
            paths = _session_paths(root, prefer_slugs=prefer, cwd_scoped=bool(prefer))
            if not paths:
                # Empty cwd-scoped dir is still a supported store layout if projects exists.
                projects = os.path.join(root, "projects")
                if _regular_directory(projects, root):
                    return CapabilityReport(self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,))
                return CapabilityReport(self.key, FORMAT_ID, "unavailable", root=root)
            for path in paths:
                try:
                    _, records, _ = _read(path, root, ReadBudget())
                    _session_id(path, records)
                    _logical_lineage(records)
                    return CapabilityReport(self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,))
                except DiagnosticError as error:
                    if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                        return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                    continue
            return CapabilityReport(self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,))
        except DiagnosticError as error:
            state = "unsafe" if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"} else "unsupported"
            return CapabilityReport(self.key, FORMAT_ID, state)

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        root = _existing_root(query)
        if root is None:
            raise DiagnosticError("E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID)
        values: list[SessionSummary] = []
        exact = _exact_uuid_ref(query.ref)
        prefer = _prefer_slugs_for(query)
        for path in _session_paths(
            root,
            prefer_slugs=prefer,
            exact_uuid=exact,
            cwd_scoped=bool(prefer) and exact is None,
        ):
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
            matches = _session_paths(
                root,
                prefer_slugs=prefer,
                exact_uuid=ref.session_id,
                cwd_scoped=bool(prefer),
            )
            if len(matches) != 1:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
            path = matches[0]
        observation, records, warnings = _read(path, root, budget)
        if _session_id(path, records) != ref.session_id:
            raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
        cwd = _record_cwd(records)
        lineage, lineage_warnings = _logical_lineage(records)
        title, branch = _title_and_branch(records)
        turns: list[Turn] = []
        all_warnings = list((*warnings, *lineage_warnings))
        turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        for record in lineage:
            for raw in _turn_records(record):
                turn, turn_warnings = sanitize_turn_record(raw, ordinal=len(turns), bounds=turn_bounds)
                all_warnings.extend(turn_warnings)
                if turn is not None:
                    budget.consume_turns()
                    turns.append(turn)
        timestamps = [_rfc3339(record.get("timestamp")) for record in records]
        last_user = next((turn.content for turn in reversed(turns) if turn.role == "user"), None)
        last_assistant = next((turn.content for turn in reversed(turns) if turn.role == "assistant"), None)
        return Session(
            source=self.key,
            session_id=ref.session_id,
            source_path=path,
            title=title,
            cwd=cwd,
            branch=branch,
            created_at=min((stamp for stamp in timestamps if stamp), default=None),
            updated_at=_mtime(observation),
            last_user_request=last_user,
            last_assistant_action=last_assistant,
            turns=tuple(turns),
            warnings=tuple(dict.fromkeys(all_warnings)),
        )


ADAPTER = ClaudeAdapter()
