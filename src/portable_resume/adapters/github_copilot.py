"""Read GitHub Copilot CLI local session events as inert context.

Pinned format: ``copilot-cli-events-jsonl-v1`` (local ``events.jsonl`` authority).

Layout (docs.github.com Copilot CLI config directory, 2026-07):

    $COPILOT_HOME/  or  ~/.copilot/
    ├── session-state/<session-id>/events.jsonl   # complete local session
    └── session-store.db                         # Chronicle index only (not authority)

Public turns: ``user.message`` and ``assistant.message`` string content.
Tool turns: ``tool.execution_start`` tool names only (no args/results).

Never invokes ``copilot`` CLI, Chronicle reindex, cloud session sync, or plugins.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from ..bounds import DEFAULT_BOUNDS, ReadBudget
from ..diagnostics import DiagnosticError
from ..model import Query, Session, SessionSummary, Turn
from ..paths import canonical_root, canonicalize_cwd, is_within, same_cwd
from ..sanitize import sanitize_turn_record
from ..snapshot import stable_read_windows, stable_scan_lines
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "copilot-cli-events-jsonl-v1"
_META_HEAD_BYTES = 256 * 1024
_META_HEAD_LINES = 64
_SESSION_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Known control / private / non-public event types (omit without fail-closed).
_OMIT_TYPES = frozenset(
    {
        "session.start",
        "session.shutdown",
        "session.model_change",
        "session.mode_changed",
        "session.compaction_start",
        "session.compaction_complete",
        "session.context_changed",
        "session.info",
        "session.warning",
        "session.error",
        "session.plan_changed",
        "session.task_complete",
        "assistant.turn_start",
        "assistant.turn_end",
        "assistant.reasoning",
        "tool.execution_complete",
        "hook.start",
        "hook.end",
        "subagent.started",
        "subagent.completed",
        "skill.invoked",
        "system.message",
        "abort",
    }
)
_PUBLIC_MESSAGE_TYPES = frozenset({"user.message", "assistant.message"})
_TOOL_START = "tool.execution_start"


class _DuplicateKey(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = item
    return value


def _regular_dir(path: str, root: str) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        return False
    try:
        return is_within(path, root)
    except DiagnosticError:
        return False


def _regular_file(path: str, root: str) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        return False
    try:
        return is_within(path, root)
    except DiagnosticError:
        return False


def _safe_listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


def _default_copilot_home() -> str:
    env = os.environ.get("COPILOT_HOME")
    if env and env.strip():
        path = env.strip()
        if not os.path.isabs(path):
            raise DiagnosticError(
                "E_UNSAFE_PATH", source="github-copilot", provider=FORMAT_ID
            )
        return path
    return os.path.expanduser("~/.copilot")


def _resolve_layout(query: Query) -> tuple[str, str] | None:
    """Return (session_state_dir, containment_root) or None.

    Exact file/session pins keep containment tight (session dir only) so path
    refs cannot jump to sibling sessions under the same Copilot home.
    """

    if query.source_root:
        candidate = query.source_root
        try:
            if os.path.isfile(candidate):
                path = os.path.abspath(candidate)
                if os.path.basename(path) != "events.jsonl":
                    return None
                session_dir = os.path.dirname(path)
                # Exact file: discovery + containment stay on this session only.
                root = canonical_root(session_dir)
                if not _regular_file(path, root):
                    return None
                return session_dir, root
            if not os.path.isdir(candidate):
                return None
            root = canonical_root(candidate)
        except DiagnosticError:
            return None
        # ~/.copilot
        state = os.path.join(root, "session-state")
        if _regular_dir(state, root):
            return state, root
        # .../session-state  (full store scan)
        if os.path.basename(root.rstrip(os.sep)) == "session-state":
            return root, root
        # .../session-state/<id> — keep this session only (tight containment)
        events = os.path.join(root, "events.jsonl")
        if _regular_file(events, root) or any(
            n == "events.jsonl" for n in _safe_listdir(root)
        ):
            if not _regular_file(events, root):
                return None
            return root, root
        return None
    try:
        home = _default_copilot_home()
        root = canonical_root(home) if os.path.isdir(home) else None
    except DiagnosticError:
        return None
    if root is None:
        return None
    state = os.path.join(root, "session-state")
    if not _regular_dir(state, root):
        return None
    return state, root


def _exact_ref(value: str | None) -> str | None:
    """Return UUID session id when *value* is an exact id (not a path)."""

    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    if _SESSION_ID_RE.fullmatch(text):
        return text
    return None


def _exact_path_session(
    value: str | None, root: str
) -> tuple[str, str] | None:
    """Return (session_id, events.jsonl) for an approved absolute path ref."""

    if not value:
        return None
    text = value.strip()
    if not text or not os.path.isabs(text):
        return None
    path = os.path.abspath(text)
    if os.path.basename(path) == "events.jsonl":
        if not _regular_file(path, root):
            return None
        session_dir = os.path.dirname(path)
        sid = os.path.basename(session_dir.rstrip(os.sep))
        if _SESSION_ID_RE.fullmatch(sid):
            return sid, path
        return None
    if _regular_dir(path, root):
        events = os.path.join(path, "events.jsonl")
        if _regular_file(events, root):
            sid = os.path.basename(path.rstrip(os.sep))
            if _SESSION_ID_RE.fullmatch(sid):
                return sid, events
    return None


def _stamp_iso(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return (
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    except ValueError:
        return None


def _discover_session_dirs(
    state_dir: str,
    root: str,
    *,
    scan_limit: int,
    prefer_id: str | None = None,
) -> list[tuple[str, str]]:
    """Return (session_id, events.jsonl path) under session-state.

    Exact UUID prefers a direct path hit (no full tree walk). Otherwise
    candidates are ordered by events.jsonl mtime (newest first) and capped.
    """

    if os.path.basename(state_dir.rstrip(os.sep)) != "session-state":
        # single session dir
        events = os.path.join(state_dir, "events.jsonl")
        if _regular_file(events, root):
            sid = os.path.basename(state_dir.rstrip(os.sep))
            if _SESSION_ID_RE.fullmatch(sid):
                return [(sid, events)]
        return []

    if prefer_id and _SESSION_ID_RE.fullmatch(prefer_id):
        # Directory names are lowercase UUIDs; accept mixed-case pasted refs.
        prefer = prefer_id.lower()
        events = os.path.join(state_dir, prefer, "events.jsonl")
        if _regular_file(events, root):
            return [(prefer, events)]
        # Case-sensitive FS miss on unusual mixed-case dir names: try raw.
        if prefer != prefer_id:
            events_raw = os.path.join(state_dir, prefer_id, "events.jsonl")
            if _regular_file(events_raw, root):
                return [(prefer_id, events_raw)]
        # Fall through only when the preferred id is absent.

    ranked: list[tuple[float, str, str]] = []
    examined = 0
    examine_cap = max(scan_limit * 8, 512)
    try:
        iterator = os.scandir(state_dir)
    except OSError:
        return []
    with iterator:
        for entry in iterator:
            examined += 1
            if examined > examine_cap:
                break
            name = entry.name
            if not _SESSION_ID_RE.fullmatch(name):
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            session_dir = entry.path
            if not _regular_dir(session_dir, root):
                continue
            events = os.path.join(session_dir, "events.jsonl")
            if not _regular_file(events, root):
                continue
            try:
                mtime = float(os.lstat(events).st_mtime)
            except OSError:
                mtime = 0.0
            ranked.append((mtime, name, events))
            if len(ranked) >= max(scan_limit * 4, scan_limit):
                break
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [(name, events) for _mtime, name, events in ranked[:scan_limit]]


def _message_turn(
    event_type: str,
    data: Mapping[str, Any],
    *,
    strict_unknown: bool,
) -> tuple[str, str] | None:
    if event_type in _PUBLIC_MESSAGE_TYPES:
        content = data.get("content")
        if isinstance(content, str) and content.strip():
            role = "user" if event_type == "user.message" else "assistant"
            return role, content.strip()
        return None
    if event_type == _TOOL_START:
        name = data.get("toolName")
        if isinstance(name, str) and name.strip():
            return "tool", name.strip()
        return None
    if event_type in _OMIT_TYPES or "reasoning" in event_type:
        # Omit reasoning* / control; never surface private chain-of-thought.
        return None
    # Unknown type: fail closed on show when content-bearing.
    content = data.get("content")
    if strict_unknown and (
        (isinstance(content, str) and content.strip())
        or (isinstance(content, (list, dict)) and content)
        or (isinstance(data.get("message"), str) and data["message"].strip())
    ):
        raise DiagnosticError(
            "E_UNSUPPORTED_FORMAT", source="github-copilot", provider=FORMAT_ID
        )
    return None


def _file_mtime_iso(path: str) -> str | None:
    try:
        mtime = os.lstat(path).st_mtime
    except OSError:
        return None
    return (
        datetime.fromtimestamp(mtime, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _active_lineage_ids(
    parent_of: Mapping[str, str | None],
    tip: str | None,
) -> set[str] | None:
    """Walk parentId chain from *tip*; None means lineage unavailable."""

    if tip is None or tip not in parent_of:
        return None
    active: set[str] = set()
    cur: str | None = tip
    while cur is not None and cur not in active:
        active.add(cur)
        if cur not in parent_of:
            break
        parent = parent_of[cur]
        if parent is None:
            break
        if not isinstance(parent, str) or not parent:
            break
        cur = parent
    return active


def _note_cwd(meta: dict[str, Any], cwd: str) -> None:
    text = cwd.strip()
    if not text:
        return
    meta["cwd"] = text
    seen = meta.setdefault("cwd_seen", [])
    if isinstance(seen, list) and text not in seen:
        seen.append(text)


def _cwd_matches(meta: Mapping[str, Any], query_cwd: str | None) -> bool:
    if query_cwd is None:
        return True
    seen = meta.get("cwd_seen")
    candidates: list[str] = []
    if isinstance(seen, list):
        candidates.extend(item for item in seen if isinstance(item, str))
    cwd = meta.get("cwd")
    if isinstance(cwd, str):
        candidates.append(cwd)
    if not candidates:
        return False
    return any(same_cwd(item, query_cwd) for item in candidates)


def _apply_session_control(
    event_type: str,
    data: Mapping[str, Any],
    meta: dict[str, Any],
    *,
    created_at: str | None,
) -> str | None:
    """Update meta from control events; return maybe-updated created_at."""

    if event_type == "session.start":
        sid = data.get("sessionId")
        if isinstance(sid, str):
            meta["sessionId"] = sid
        start = data.get("startTime")
        if isinstance(start, str):
            meta["startTime"] = start
            created_at = _stamp_iso(start) or created_at
        ctx = data.get("context")
        if isinstance(ctx, Mapping):
            cwd = ctx.get("cwd")
            if isinstance(cwd, str) and cwd.strip():
                _note_cwd(meta, cwd)
            branch = ctx.get("branch")
            if isinstance(branch, str) and branch.strip():
                meta["branch"] = branch.strip()
    elif event_type == "session.context_changed":
        cwd = data.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            _note_cwd(meta, cwd)
    return created_at


def _parse_metadata_line(
    raw: bytes,
    *,
    maximum_record: int,
    meta: dict[str, Any],
    created_at: str | None,
    updated_at: str | None,
    budget: ReadBudget,
) -> tuple[str | None, str | None]:
    budget.consume_records()
    body = raw[:-1] if raw.endswith(b"\n") else raw
    if body.endswith(b"\r"):
        body = body[:-1]
    if len(body) > maximum_record:
        raise DiagnosticError.limit_exceeded()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DiagnosticError(
            "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
        ) from error
    stripped = text.strip()
    if not stripped:
        return created_at, updated_at
    try:
        record = json.loads(stripped, object_pairs_hook=_object)
    except (json.JSONDecodeError, _DuplicateKey, RecursionError) as error:
        raise DiagnosticError(
            "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
        ) from error
    if not isinstance(record, Mapping):
        raise DiagnosticError(
            "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
        )
    stamp = _stamp_iso(record.get("timestamp"))
    if stamp is not None:
        if created_at is None:
            created_at = stamp
        if updated_at is None or stamp > updated_at:
            updated_at = stamp
    event_type = record.get("type")
    if not isinstance(event_type, str):
        raise DiagnosticError(
            "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
        )
    payload = record.get("data")
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise DiagnosticError(
            "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
        )
    # Sub-agent rows share the parent stream; skip for list metadata too.
    agent_id = record.get("agentId")
    if agent_id is not None and agent_id != "":
        return created_at, updated_at
    created_at = _apply_session_control(
        event_type, payload, meta, created_at=created_at
    )
    if event_type == "user.message":
        content = payload.get("content")
        if isinstance(content, str) and content.strip():
            meta["has_user"] = True
            if "title" not in meta:
                meta["title"] = content.strip().splitlines()[0][
                    : DEFAULT_BOUNDS.title_chars
                ]
    return created_at, updated_at


def _scan_session_metadata(
    path: str,
    root: str,
    budget: ReadBudget,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Bounded head+tail list metadata (charges scanned_records, not transcript).

    Head supplies session.start / first user title; tail re-applies late
    ``session.context_changed`` so list cwd matches show for long sessions.
    """

    maximum_record = min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes)
    scanned_ceiling = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
    remaining = scanned_ceiling - budget.records
    # Honor remaining aggregate budget so multi-session list can truncate cleanly.
    line_cap = min(_META_HEAD_LINES, remaining)
    if line_cap <= 0:
        raise DiagnosticError.limit_exceeded()
    windows = stable_read_windows(
        path,
        root=root,
        head_bytes=min(_META_HEAD_BYTES, 4 * 1024 * 1024),
        tail_bytes=min(64 * 1024, 64 * 1024),
        max_bytes=min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
        attempts=min(budget.limits.snapshot_attempts, DEFAULT_BOUNDS.snapshot_attempts),
        membership_limit=min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records),
        budget=budget,
        require_size_within_max=False,
    )
    head = windows.head
    tail = windows.tail
    full_in_head = windows.fingerprint.size <= len(head)
    head_lines = head.splitlines(keepends=True)
    if head_lines and not full_in_head:
        last = head_lines[-1]
        if not last.endswith((b"\n", b"\r")):
            head_lines = head_lines[:-1]

    meta: dict[str, Any] = {}
    created_at: str | None = None
    updated_at: str | None = None
    # Whole file inside the head window: parse every complete line (budget-capped).
    # Partial head: first N lines only; tail window supplies late context_changed.
    head_cap = (
        min(len(head_lines), remaining)
        if full_in_head
        else min(line_cap, len(head_lines))
    )
    lines_seen = 0
    for raw in head_lines:
        if lines_seen >= head_cap:
            break
        lines_seen += 1
        created_at, updated_at = _parse_metadata_line(
            raw,
            maximum_record=maximum_record,
            meta=meta,
            created_at=created_at,
            updated_at=updated_at,
            budget=budget,
        )

    # Tail: late context_changed / stamps (skip when entire file already in head).
    if not full_in_head and tail:
        tail_lines = tail.splitlines(keepends=True)
        if tail_lines and not tail.endswith((b"\n", b"\r")):
            tail_lines = tail_lines[:-1]
        # Walk all complete lines in the tail window so late context_changed
        # is not lost behind a trailing burst of assistant/tool events.
        for raw in tail_lines:
            remaining = scanned_ceiling - budget.records
            if remaining <= 0:
                break
            try:
                created_at, updated_at = _parse_metadata_line(
                    raw,
                    maximum_record=maximum_record,
                    meta=meta,
                    created_at=created_at,
                    updated_at=updated_at,
                    budget=budget,
                )
            except DiagnosticError as error:
                if error.code in {"E_CORRUPT_TAIL", "E_CORRUPT_RECORD"}:
                    # Mid-cut tail lines may be partial; skip quietly.
                    continue
                raise
    return meta, created_at, updated_at


def _scan_session(
    path: str,
    root: str,
    budget: ReadBudget,
    *,
    strict_unknown: bool,
) -> tuple[dict[str, Any], list[tuple[str, str]], str | None, str | None]:
    """Full transcript scan with active ``id``/``parentId`` lineage for show."""

    meta: dict[str, Any] = {}
    pending: list[tuple[str | None, str, str]] = []
    parent_of: dict[str, str | None] = {}
    last_public_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    count = 0
    limit = min(budget.limits.transcript_records, DEFAULT_BOUNDS.transcript_records)

    for line in stable_scan_lines(
        path,
        root=root,
        max_line_bytes=min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes),
        budget=budget,
        charge_transcript=True,
    ):
        count += 1
        if count > limit:
            raise DiagnosticError.limit_exceeded()
        text = line.text.strip()
        if not text:
            continue
        try:
            record = json.loads(text, object_pairs_hook=_object)
        except (
            json.JSONDecodeError,
            _DuplicateKey,
            RecursionError,
            UnicodeDecodeError,
        ) as error:
            raise DiagnosticError(
                "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
            ) from error
        if not isinstance(record, Mapping):
            raise DiagnosticError(
                "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
            )
        stamp = _stamp_iso(record.get("timestamp"))
        if stamp is not None:
            if created_at is None:
                created_at = stamp
            updated_at = stamp
        event_type = record.get("type")
        if not isinstance(event_type, str):
            raise DiagnosticError(
                "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
            )
        data = record.get("data")
        if data is None:
            data = {}
        if not isinstance(data, Mapping):
            raise DiagnosticError(
                "E_CORRUPT_RECORD", source="github-copilot", provider=FORMAT_ID
            )

        event_id = record.get("id")
        event_id_s = event_id if isinstance(event_id, str) and event_id else None
        parent_raw = record.get("parentId")
        if parent_raw is None:
            parent_s: str | None = None
        elif isinstance(parent_raw, str) and parent_raw:
            parent_s = parent_raw
        else:
            parent_s = None
        if event_id_s is not None:
            parent_of[event_id_s] = parent_s

        # Sub-agent rows share the parent stream; omit from parent handoff.
        agent_id = record.get("agentId")
        if agent_id is not None and agent_id != "":
            continue

        if event_type in {"session.start", "session.context_changed"}:
            created_at = _apply_session_control(
                event_type, data, meta, created_at=created_at
            )
            continue
        if event_type == "session.shutdown":
            continue

        parsed = _message_turn(event_type, data, strict_unknown=strict_unknown)
        if parsed is not None:
            role, content = parsed
            pending.append((event_id_s, role, content))
            if event_id_s is not None:
                last_public_id = event_id_s

    active = _active_lineage_ids(parent_of, last_public_id)
    turns: list[tuple[str, str]] = []
    if active is None:
        turns = [(role, content) for _eid, role, content in pending]
    else:
        for event_id_s, role, content in pending:
            # Orphan public rows without id stay (best-effort); id'd rows need lineage.
            if event_id_s is None or event_id_s in active:
                turns.append((role, content))

    return meta, turns, created_at, updated_at


def _session_summary_from_path(
    session_id: str,
    path: str,
    root: str,
    query: Query,
    budget: ReadBudget,
    *,
    require_age: bool,
) -> SessionSummary | None:
    try:
        meta, created_at, updated_at = _scan_session_metadata(path, root, budget)
    except DiagnosticError as error:
        if error.code in {"E_LIMIT_EXCEEDED", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
            raise
        return None
    sid = meta.get("sessionId") if isinstance(meta.get("sessionId"), str) else session_id
    if not _SESSION_ID_RE.fullmatch(sid):
        return None
    if not meta.get("has_user"):
        return None
    if not _cwd_matches(meta, query.cwd):
        return None
    # Surface query.cwd when it matched any observed cwd so shared select_session
    # keeps the candidate (final meta cwd alone can diverge after context_changed).
    if query.cwd is not None:
        cwd = query.cwd
    else:
        cwd = meta.get("cwd") if isinstance(meta.get("cwd"), str) else None
    # Prefer content stamps; file mtime covers long sessions past the head window.
    stamp = updated_at or created_at or _stamp_iso(meta.get("startTime"))
    mtime_stamp = _file_mtime_iso(path)
    if mtime_stamp is not None and (stamp is None or mtime_stamp > stamp):
        stamp = mtime_stamp
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    title = meta.get("title") if isinstance(meta.get("title"), str) else None
    return SessionSummary(
        source="github-copilot",
        session_id=sid,
        source_path=path,
        title=title,
        cwd=cwd,
        branch=meta.get("branch") if isinstance(meta.get("branch"), str) else None,
        created_at=created_at or _stamp_iso(meta.get("startTime")),
        updated_at=stamp,
        provider=FORMAT_ID,
        warnings=(),
    )


class GitHubCopilotAdapter:
    key = "github-copilot"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        layout = _resolve_layout(query)
        return (layout[1],) if layout else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            layout = _resolve_layout(query)
            if layout is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            state, root = layout
            prefer = _exact_ref(query.ref)
            sessions = _discover_session_dirs(
                state,
                root,
                scan_limit=min(DEFAULT_BOUNDS.scanned_records, 2_000),
                prefer_id=prefer,
            )
            if not sessions:
                return CapabilityReport(
                    self.key, FORMAT_ID, "partial", root=root, evidence=(FORMAT_ID,)
                )
            budget = ReadBudget()
            for _sid, path in sessions[:8]:
                try:
                    meta, _c, _u = _scan_session_metadata(path, root, budget)
                except DiagnosticError as error:
                    if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                        return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                    if error.code == "E_LIMIT_EXCEEDED":
                        raise
                    continue
                if meta.get("sessionId") or meta.get("has_user"):
                    return CapabilityReport(
                        self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,)
                    )
            return CapabilityReport(
                self.key, FORMAT_ID, "partial", root=root, evidence=(FORMAT_ID,)
            )
        except DiagnosticError as error:
            state = (
                "unsafe"
                if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}
                else "unsupported"
            )
            return CapabilityReport(self.key, FORMAT_ID, state)

    def list(self, query: Query, budget: ReadBudget) -> list[SessionSummary]:
        layout = _resolve_layout(query)
        if layout is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        state, root = layout
        exact_id = _exact_ref(query.ref)
        exact_path = _exact_path_session(query.ref, root)
        exact = exact_id is not None or exact_path is not None
        # Absolute path ref outside containment / invalid shape → no match.
        if (
            query.ref
            and query.ref.strip()
            and os.path.isabs(query.ref.strip())
            and exact_path is None
            and exact_id is None
        ):
            return []
        scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
        list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
        if not exact and list_limit <= 0:
            return []

        truncated = False
        if exact_path is not None:
            sessions = [exact_path]
        else:
            sessions = _discover_session_dirs(
                state,
                root,
                scan_limit=scan_limit,
                prefer_id=exact_id,
            )
            if exact_id is not None:
                sessions = [
                    (sid, path)
                    for sid, path in sessions
                    if sid.lower() == exact_id.lower()
                ]
                if not sessions:
                    return []

        values: list[SessionSummary] = []
        for sid, path in sessions:
            try:
                item = _session_summary_from_path(
                    sid,
                    path,
                    root,
                    query,
                    budget,
                    require_age=not exact,
                )
            except DiagnosticError as error:
                if error.code == "E_LIMIT_EXCEEDED" and not exact:
                    # Aggregate discovery budget exhausted — return partial list.
                    truncated = True
                    break
                if error.code in {"E_LIMIT_EXCEEDED", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
                    raise
                continue
            if item is None:
                continue
            values.append(item)
            try:
                budget.consume_records()
            except DiagnosticError as error:
                if error.code == "E_LIMIT_EXCEEDED" and not exact:
                    truncated = True
                    break
                raise
            if not exact and len(values) >= list_limit:
                # More candidates may remain unexamined — mark incomplete.
                truncated = True
                break

        values.sort(key=lambda item: item.session_id)
        values.sort(key=lambda item: item.updated_at or "", reverse=True)
        values.sort(key=lambda item: item.updated_at is None)
        if exact:
            return values
        capped = values[:list_limit]
        if truncated or len(values) > list_limit:
            capped = [
                replace(item, warnings=tuple(dict.fromkeys((*item.warnings, "W_TRUNCATED"))))
                for item in capped
            ]
        return capped

    def show(self, ref: ResolvedRef, query: Query, budget: ReadBudget) -> Session:
        layout = _resolve_layout(query)
        if layout is None:
            raise DiagnosticError(
                "E_CAPABILITY_UNAVAILABLE", source=self.key, provider=FORMAT_ID
            )
        state, root = layout
        session_id = ref.session_id
        if not session_id or not _SESSION_ID_RE.fullmatch(session_id):
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        path = ref.source_path if ref.source_path else None
        if path and _regular_file(path, root):
            target = path
        else:
            sessions = _discover_session_dirs(
                state,
                root,
                scan_limit=min(
                    budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records
                ),
            )
            target = None
            for sid, candidate in sessions:
                if sid.lower() == session_id.lower():
                    target = candidate
                    break
            if target is None:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        meta, turns_raw, created_at, updated_at = _scan_session(
            target,
            root,
            budget,
            strict_unknown=True,
        )
        if not _cwd_matches(meta, query.cwd):
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
        cwd = meta.get("cwd") if isinstance(meta.get("cwd"), str) else None

        turns: list[Turn] = []
        warnings: list[str] = []
        turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        title = None
        for role, text in turns_raw:
            if title is None and role == "user":
                title = text.splitlines()[0][: DEFAULT_BOUNDS.title_chars]
            turn, turn_warnings = sanitize_turn_record(
                {"role": role, "content": text},
                ordinal=len(turns),
                bounds=turn_bounds,
            )
            warnings.extend(turn_warnings)
            if turn is not None:
                budget.consume_turns()
                turns.append(turn)
        if not turns or not any(t.role == "user" for t in turns):
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        sid = (
            meta.get("sessionId")
            if isinstance(meta.get("sessionId"), str)
            else session_id
        )
        last_user = next((t.content for t in reversed(turns) if t.role == "user"), None)
        last_assistant = next(
            (t.content for t in reversed(turns) if t.role == "assistant"), None
        )
        return Session(
            source="github-copilot",
            session_id=sid,
            source_path=target,
            title=title,
            cwd=cwd,
            branch=meta.get("branch") if isinstance(meta.get("branch"), str) else None,
            created_at=created_at or _stamp_iso(meta.get("startTime")),
            updated_at=updated_at or created_at,
            last_user_request=last_user,
            last_assistant_action=last_assistant,
            turns=tuple(turns),
            warnings=tuple(dict.fromkeys(warnings)),
        )


ADAPTER = GitHubCopilotAdapter()
