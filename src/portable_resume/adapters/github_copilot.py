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
from ..snapshot import stable_scan_lines
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "copilot-cli-events-jsonl-v1"
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
                if not path.endswith("events.jsonl"):
                    return None
                session_dir = os.path.dirname(path)
                state = os.path.dirname(session_dir)
                if os.path.basename(state) != "session-state":
                    # source-root is events.jsonl under session dir; contain under parent
                    root = canonical_root(session_dir)
                    if not _regular_file(path, root):
                        return None
                    return session_dir, root
                home = os.path.dirname(state)
                root = canonical_root(home)
                if not _regular_file(path, root):
                    root = canonical_root(state)
                    if not _regular_file(path, root):
                        return None
                return state, root
            if not os.path.isdir(candidate):
                return None
            root = canonical_root(candidate)
        except DiagnosticError:
            return None
        # ~/.copilot
        state = os.path.join(root, "session-state")
        if _regular_dir(state, root):
            return state, root
        # .../session-state
        if os.path.basename(root.rstrip(os.sep)) == "session-state":
            return root, root
        # .../session-state/<id>
        events = os.path.join(root, "events.jsonl")
        if _regular_file(events, root) or any(
            n == "events.jsonl" for n in _safe_listdir(root)
        ):
            parent = os.path.dirname(root)
            try:
                if os.path.basename(parent) == "session-state":
                    home = canonical_root(os.path.dirname(parent))
                    return parent, home
            except DiagnosticError:
                pass
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
    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    if _SESSION_ID_RE.fullmatch(text):
        return text
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
    if len(names) > scan_limit:
        raise DiagnosticError.limit_exceeded()
    out: list[tuple[str, str]] = []
    for name in sorted(names):
        if not _SESSION_ID_RE.fullmatch(name):
            continue
        session_dir = os.path.join(state_dir, name)
        if not _regular_dir(session_dir, root):
            continue
        events = os.path.join(session_dir, "events.jsonl")
        if _regular_file(events, root):
            out.append((name, events))
            if len(out) > scan_limit:
                raise DiagnosticError.limit_exceeded()
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
    if event_type in _OMIT_TYPES:
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


def _scan_session(
    path: str,
    root: str,
    budget: ReadBudget,
    *,
    metadata_only: bool,
    strict_unknown: bool,
) -> tuple[dict[str, Any], list[tuple[str, str]], str | None, str | None]:
    """Return meta, turns (role,text), created_at, updated_at."""

    meta: dict[str, Any] = {}
    turns: list[tuple[str, str]] = []
    created_at: str | None = None
    updated_at: str | None = None
    count = 0
    limit = min(budget.limits.transcript_records, DEFAULT_BOUNDS.transcript_records)
    meta_limit = min(64, limit)

    for line in stable_scan_lines(
        path,
        root=root,
        max_line_bytes=min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes),
        budget=budget,
        charge_transcript=True,
    ):
        count += 1
        if metadata_only and count > meta_limit:
            break
        if not metadata_only and count > limit:
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
            continue
        if event_type == "session.context_changed":
            cwd = data.get("cwd")
            if isinstance(cwd, str) and cwd.strip():
                meta["cwd"] = cwd.strip()
            continue
        if event_type == "session.shutdown":
            continue

        if metadata_only:
            # Need only enough to know a public user turn exists + stamps/cwd.
            if event_type == "user.message":
                content = data.get("content")
                if isinstance(content, str) and content.strip():
                    meta["has_user"] = True
                    if "title" not in meta:
                        meta["title"] = content.strip().splitlines()[0][
                            : DEFAULT_BOUNDS.title_chars
                        ]
            continue

        parsed = _message_turn(event_type, data, strict_unknown=strict_unknown)
        if parsed is not None:
            turns.append(parsed)

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
        meta, turns, created_at, updated_at = _scan_session(
            path,
            root,
            budget,
            metadata_only=False,
            strict_unknown=False,
        )
    except DiagnosticError as error:
        if error.code in {"E_LIMIT_EXCEEDED", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
            raise
        return None
    sid = meta.get("sessionId") if isinstance(meta.get("sessionId"), str) else session_id
    if not _SESSION_ID_RE.fullmatch(sid):
        return None
    has_user = any(role == "user" for role, _ in turns)
    if not has_user:
        return None
    cwd = meta.get("cwd") if isinstance(meta.get("cwd"), str) else None
    if query.cwd is not None:
        if cwd is None or not same_cwd(cwd, query.cwd):
            return None
    stamp = updated_at or created_at or _stamp_iso(meta.get("startTime"))
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    title = None
    for role, text in turns:
        if role == "user":
            title = text.splitlines()[0][: DEFAULT_BOUNDS.title_chars]
            break
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
                state, root, scan_limit=min(DEFAULT_BOUNDS.scanned_records, 64)
            )
            if not sessions:
                return CapabilityReport(
                    self.key, FORMAT_ID, "partial", root=root, evidence=(FORMAT_ID,)
                )
            budget = ReadBudget()
            for _sid, path in sessions[:8]:
                try:
                    meta, _turns, _c, _u = _scan_session(
                        path,
                        root,
                        budget,
                        metadata_only=True,
                        strict_unknown=False,
                    )
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
        exact = _exact_ref(query.ref)
        scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
        list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
        if exact is None and list_limit <= 0:
            return []

        sessions = _discover_session_dirs(state, root, scan_limit=scan_limit)
        if exact is not None:
            sessions = [
                (sid, path)
                for sid, path in sessions
                if sid.lower() == exact.lower()
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
                    require_age=exact is None,
                )
            except DiagnosticError as error:
                if error.code in {"E_LIMIT_EXCEEDED", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
                    raise
                continue
            if item is None:
                continue
            values.append(item)
            budget.consume_records()
            if exact is None and len(values) >= scan_limit:
                break

        values.sort(key=lambda item: item.session_id)
        values.sort(key=lambda item: item.updated_at or "", reverse=True)
        values.sort(key=lambda item: item.updated_at is None)
        if exact is not None:
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
            metadata_only=False,
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
