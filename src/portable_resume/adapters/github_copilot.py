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
    """Return (session_state_dir, containment_root) or None."""

    if query.source_root:
        candidate = query.source_root
        try:
            if os.path.isfile(candidate):
                path = os.path.abspath(candidate)
                if os.path.basename(path) != "events.jsonl":
                    return None
                session_dir = os.path.dirname(path)
                # Exact file: sole session dir (never widen to sibling sessions).
                parent = os.path.dirname(session_dir)
                try:
                    if os.path.basename(parent) == "session-state":
                        root = canonical_root(os.path.dirname(parent))
                    else:
                        root = canonical_root(session_dir)
                except DiagnosticError:
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
        # .../session-state/<id> — keep this session only (do not widen to state)
        events = os.path.join(root, "events.jsonl")
        if _regular_file(events, root) or any(
            n == "events.jsonl" for n in _safe_listdir(root)
        ):
            parent = os.path.dirname(root)
            try:
                if os.path.basename(parent) == "session-state":
                    contain = canonical_root(os.path.dirname(parent))
                else:
                    contain = root
            except DiagnosticError:
                contain = root
            if not _regular_file(events, contain) and not _regular_file(events, root):
                return None
            # layout root = this session dir so discovery cannot list siblings
            return root, contain if _regular_file(events, contain) else root
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
) -> list[tuple[str, str]]:
    """Return (session_id, events.jsonl path) under session-state."""

    if os.path.basename(state_dir.rstrip(os.sep)) != "session-state":
        # single session dir
        events = os.path.join(state_dir, "events.jsonl")
        if _regular_file(events, root):
            sid = os.path.basename(state_dir.rstrip(os.sep))
            if _SESSION_ID_RE.fullmatch(sid):
                return [(sid, events)]
        return []

    names = _safe_listdir(state_dir)
    out: list[tuple[str, str]] = []
    # Cap returned sessions; do not fail-closed on mature stores with many ids.
    for name in sorted(names):
        if not _SESSION_ID_RE.fullmatch(name):
            continue
        session_dir = os.path.join(state_dir, name)
        if not _regular_dir(session_dir, root):
            continue
        events = os.path.join(session_dir, "events.jsonl")
        if _regular_file(events, root):
            out.append((name, events))
            if len(out) >= scan_limit:
                break
    return out


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
                meta["cwd"] = cwd.strip()
            branch = ctx.get("branch")
            if isinstance(branch, str) and branch.strip():
                meta["branch"] = branch.strip()
    elif event_type == "session.context_changed":
        cwd = data.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            meta["cwd"] = cwd.strip()
    return created_at


def _scan_session_metadata(
    path: str,
    root: str,
    budget: ReadBudget,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Bounded head-window list metadata (charges scanned_records, not transcript)."""

    maximum_record = min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes)
    line_cap = min(_META_HEAD_LINES, budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
    if line_cap <= 0:
        return {}, None, None
    windows = stable_read_windows(
        path,
        root=root,
        head_bytes=min(_META_HEAD_BYTES, 4 * 1024 * 1024),
        tail_bytes=0,
        max_bytes=min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
        attempts=min(budget.limits.snapshot_attempts, DEFAULT_BOUNDS.snapshot_attempts),
        membership_limit=min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records),
        budget=budget,
        require_size_within_max=False,
    )
    data = windows.head
    full_in_head = windows.fingerprint.size <= len(data)
    raw_lines = data.splitlines(keepends=True)
    if raw_lines and not full_in_head:
        last = raw_lines[-1]
        if not last.endswith((b"\n", b"\r")):
            raw_lines = raw_lines[:-1]

    meta: dict[str, Any] = {}
    created_at: str | None = None
    updated_at: str | None = None
    lines_seen = 0
    for raw in raw_lines:
        if lines_seen >= line_cap:
            break
        lines_seen += 1
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
            continue
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
        # Do not early-exit after the first user turn: later session.context_changed
        # rows in the head window must update meta["cwd"] so list matches show.
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
    cwd = meta.get("cwd") if isinstance(meta.get("cwd"), str) else None
    if query.cwd is not None:
        if cwd is None or not same_cwd(cwd, query.cwd):
            return None
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
            sessions = _discover_session_dirs(
                state, root, scan_limit=min(DEFAULT_BOUNDS.scanned_records, 2_000)
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
        scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
        list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
        if not exact and list_limit <= 0:
            return []

        if exact_path is not None:
            sessions = [exact_path]
        else:
            sessions = _discover_session_dirs(state, root, scan_limit=scan_limit)
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
                if error.code in {"E_LIMIT_EXCEEDED", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
                    raise
                continue
            if item is None:
                continue
            values.append(item)
            budget.consume_records()
            if not exact and len(values) >= scan_limit:
                break

        values.sort(key=lambda item: item.session_id)
        values.sort(key=lambda item: item.updated_at or "", reverse=True)
        values.sort(key=lambda item: item.updated_at is None)
        if exact:
            return values
        return values[:list_limit]

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
        cwd = meta.get("cwd") if isinstance(meta.get("cwd"), str) else None
        if query.cwd is not None:
            if cwd is None or not same_cwd(cwd, query.cwd):
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

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
