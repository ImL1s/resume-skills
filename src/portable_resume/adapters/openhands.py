"""Read OpenHands CLI local conversation event stores as inert context.

Pinned format: ``openhands-cli-events-v1`` — one directory per conversation with
ordered ``events/event-*.json`` records (OpenHands CLI LocalFileStore, 2026-07).

Default roots (env precedence):

    OPENHANDS_CONVERSATIONS_DIR
    or OPENHANDS_PERSISTENCE_DIR/conversations
    or ~/.openhands/conversations

Authority: event files under the selected conversation. Never invokes OpenHands
CLI/SDK/ACP/cloud, never registers SDK tools, never imports SDK event classes.
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
from ..snapshot import stable_read_bytes
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "openhands-cli-events-v1"
_CONV_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_EVENT_NAME_RE = re.compile(r"^event-(\d{8})\.json$")
# Public message sources we normalize; everything else is control/private.
_PUBLIC_MESSAGE_SOURCES = frozenset({"user", "agent", "assistant"})
# Known control / private kinds: omit without failing closed.
_OMIT_KINDS = frozenset(
    {
        "SystemPromptEvent",
        "TokenEvent",
        "StreamingDeltaEvent",
        "ConversationStateUpdateEvent",
        "Condensation",
        "CondensationRequest",
        "CondensationSummaryEvent",
        "HookExecutionEvent",
        "LLMCompletionLogEvent",
        "InterruptEvent",
        "PauseEvent",
        "UserRejectObservation",
        "AgentErrorEvent",
        "ActionEvent",
        "ObservationEvent",
        "ACPToolCallEvent",
    }
)
# Content-bearing field names that must not hide unknown public turns.
_CONTENT_BEARING_KEYS = frozenset(
    {
        "message",
        "content",
        "prompt",
        "output",
        "text",
        "llm_message",
        "observation",
        "action",
    }
)


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


def _default_conversations_dir() -> str:
    env_conv = os.environ.get("OPENHANDS_CONVERSATIONS_DIR")
    if env_conv and env_conv.strip():
        return env_conv.strip()
    env_persist = os.environ.get("OPENHANDS_PERSISTENCE_DIR")
    if env_persist and env_persist.strip():
        return os.path.join(env_persist.strip(), "conversations")
    return os.path.expanduser("~/.openhands/conversations")


def _layout_from_root(candidate: str) -> tuple[str, str] | None:
    """Return (conversations_dir, containment_root) or None."""

    try:
        if os.path.isfile(candidate):
            base = os.path.basename(candidate)
            if not _EVENT_NAME_RE.fullmatch(base):
                return None
            events_dir = os.path.dirname(os.path.abspath(candidate))
            if os.path.basename(events_dir) != "events":
                return None
            conv_dir = os.path.dirname(events_dir)
            conversations = os.path.dirname(conv_dir)
            root = canonical_root(conversations)
            if not _regular_file(os.path.abspath(candidate), root):
                return None
            return conversations, root
        if not os.path.isdir(candidate):
            return None
        root = canonical_root(candidate)
    except DiagnosticError:
        return None

    # Direct conversations root (contains <id>/events/)
    names = _safe_listdir(root)
    if any(
        _regular_dir(os.path.join(root, name, "events"), root)
        or _regular_dir(os.path.join(root, name), root)
        for name in names
        if _CONV_ID_RE.fullmatch(name)
    ):
        return root, root

    # Persistence root: ~/.openhands
    conversations = os.path.join(root, "conversations")
    if _regular_dir(conversations, root):
        return conversations, root

    # Exact conversation directory: .../<id> with events/
    events = os.path.join(root, "events")
    if _regular_dir(events, root):
        parent = os.path.dirname(root)
        try:
            parent_root = canonical_root(parent)
        except DiagnosticError:
            parent_root = root
        return parent_root if _regular_dir(parent, parent_root) else root, parent_root

    return None


def _resolve_layout(query: Query) -> tuple[str, str] | None:
    if query.source_root:
        return _layout_from_root(query.source_root)
    return _layout_from_root(_default_conversations_dir())


def _exact_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    if _CONV_ID_RE.fullmatch(text):
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


def _event_names(events_dir: str, *, scan_limit: int) -> list[str]:
    names = [
        name
        for name in _safe_listdir(events_dir)
        if _EVENT_NAME_RE.fullmatch(name)
    ]
    if len(names) > scan_limit:
        raise DiagnosticError.limit_exceeded()
    names.sort()
    return names


def _load_event_json(
    path: str,
    root: str,
    budget: ReadBudget,
) -> Mapping[str, Any]:
    try:
        read = stable_read_bytes(
            path,
            root=root,
            max_bytes=min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes),
            budget=budget,
        )
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError.source_busy(provider=FORMAT_ID) from error
    try:
        payload = json.loads(read.data, object_pairs_hook=_object)
    except (
        json.JSONDecodeError,
        _DuplicateKey,
        RecursionError,
        UnicodeDecodeError,
    ) as error:
        raise DiagnosticError("E_CORRUPT_RECORD", source="openhands", provider=FORMAT_ID) from error
    if not isinstance(payload, Mapping):
        raise DiagnosticError("E_CORRUPT_RECORD", source="openhands", provider=FORMAT_ID)
    return payload


def _text_from_content(content: object) -> str | None:
    if isinstance(content, str) and content.strip():
        return content.strip()
    if not isinstance(content, list):
        return None
    chunks: list[str] = []
    for item in content:
        if isinstance(item, str) and item.strip():
            chunks.append(item.strip())
            continue
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind in {None, "text", "input_text", "output_text"}:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    if not chunks:
        return None
    return "\n".join(chunks)


def _message_turn(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return (role, text) for a public MessageEvent, else None."""

    kind = payload.get("kind")
    if kind != "MessageEvent":
        return None
    source = payload.get("source")
    if not isinstance(source, str) or source not in _PUBLIC_MESSAGE_SOURCES:
        return None
    llm_message = payload.get("llm_message")
    if not isinstance(llm_message, Mapping):
        return None
    role_raw = llm_message.get("role")
    if isinstance(role_raw, str) and role_raw in {"user", "assistant"}:
        role = role_raw
    elif source == "user":
        role = "user"
    else:
        role = "assistant"
    text = _text_from_content(llm_message.get("content"))
    if text is None:
        return None
    return role, text


def _handle_event(payload: Mapping[str, Any], *, strict_unknown: bool) -> tuple[str, str] | None:
    kind = payload.get("kind")
    if not isinstance(kind, str) or not kind:
        if strict_unknown:
            raise DiagnosticError("E_CORRUPT_RECORD", source="openhands", provider=FORMAT_ID)
        return None
    if kind == "MessageEvent":
        return _message_turn(payload)
    if kind in _OMIT_KINDS:
        return None
    # Unknown kind: fail closed if it looks content-bearing.
    if any(key in payload for key in _CONTENT_BEARING_KEYS):
        raise DiagnosticError(
            "E_UNSUPPORTED_FORMAT", source="openhands", provider=FORMAT_ID
        )
    if strict_unknown:
        # Non-content control unknown — omit.
        return None
    return None


def _conversation_paths(
    conversations: str,
    session_id: str,
    root: str,
) -> tuple[str, str] | None:
    conv_dir = os.path.join(conversations, session_id)
    events_dir = os.path.join(conv_dir, "events")
    if not _regular_dir(conv_dir, root) or not _regular_dir(events_dir, root):
        return None
    return conv_dir, events_dir


def _list_title_and_stamp(
    events_dir: str,
    root: str,
    budget: ReadBudget,
) -> tuple[str | None, str | None, str | None]:
    """Bounded early scan: first stamp + first user title + last stamp."""

    scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
    names = _event_names(events_dir, scan_limit=scan_limit)
    if not names:
        return None, None, None
    first_stamp: str | None = None
    last_stamp: str | None = None
    title: str | None = None
    # Only open a small prefix for list eligibility / title.
    prefix = names[: min(32, len(names))]
    for name in prefix:
        path = os.path.join(events_dir, name)
        if not _regular_file(path, root):
            continue
        try:
            payload = _load_event_json(path, root, budget)
        except DiagnosticError as error:
            if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
                raise
            continue
        budget.consume_records()
        stamp = _stamp_iso(payload.get("timestamp"))
        if first_stamp is None and stamp is not None:
            first_stamp = stamp
        if stamp is not None:
            last_stamp = stamp
        if title is None:
            turn = _message_turn(payload)
            if turn is not None and turn[0] == "user":
                title = turn[1].splitlines()[0][: DEFAULT_BOUNDS.title_chars]
    # Cheap last-file stamp when prefix did not include the last event.
    if names and names[-1] not in prefix:
        path = os.path.join(events_dir, names[-1])
        if _regular_file(path, root):
            try:
                payload = _load_event_json(path, root, budget)
                stamp = _stamp_iso(payload.get("timestamp"))
                if stamp is not None:
                    last_stamp = stamp
            except DiagnosticError:
                pass
    return title, first_stamp, last_stamp or first_stamp


def _has_public_turn(
    events_dir: str,
    root: str,
    budget: ReadBudget,
    *,
    raise_on_bad: bool,
) -> bool:
    scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
    try:
        names = _event_names(events_dir, scan_limit=scan_limit)
    except DiagnosticError:
        if raise_on_bad:
            raise
        return False
    # Bound list eligibility work.
    for name in names[: min(64, len(names))]:
        path = os.path.join(events_dir, name)
        if not _regular_file(path, root):
            continue
        try:
            payload = _load_event_json(path, root, budget)
            turn = _handle_event(payload, strict_unknown=True)
        except DiagnosticError as error:
            if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
                if raise_on_bad:
                    raise
                return False
            continue
        budget.consume_records()
        if turn is not None:
            return True
    return False


class OpenHandsAdapter:
    key = "openhands"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        layout = _resolve_layout(query)
        return (layout[1],) if layout else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            layout = _resolve_layout(query)
            if layout is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            conversations, root = layout
            # Empty store is partial (layout recognized).
            names = [
                name
                for name in _safe_listdir(conversations)
                if _CONV_ID_RE.fullmatch(name)
                and _regular_dir(os.path.join(conversations, name, "events"), root)
            ]
            if not names:
                return CapabilityReport(
                    self.key, FORMAT_ID, "partial", root=root, evidence=(FORMAT_ID,)
                )
            # Spot-check one event file header shape when present.
            sample = sorted(names)[0]
            events_dir = os.path.join(conversations, sample, "events")
            event_names = [
                n for n in _safe_listdir(events_dir) if _EVENT_NAME_RE.fullmatch(n)
            ]
            if not event_names:
                return CapabilityReport(
                    self.key, FORMAT_ID, "partial", root=root, evidence=(FORMAT_ID,)
                )
            path = os.path.join(events_dir, sorted(event_names)[0])
            budget = ReadBudget()
            try:
                payload = _load_event_json(path, root, budget)
            except DiagnosticError as error:
                if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                    return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
            if not isinstance(payload.get("kind"), str) or "timestamp" not in payload:
                return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
            return CapabilityReport(
                self.key, FORMAT_ID, "supported", root=root, evidence=(FORMAT_ID,)
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
        conversations, root = layout
        exact = _exact_ref(query.ref)
        scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
        list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
        if exact is None and list_limit <= 0:
            return []

        if exact is not None:
            candidates = [exact]
            require_age = False
        else:
            names = sorted(_safe_listdir(conversations))
            if len(names) > scan_limit:
                raise DiagnosticError.limit_exceeded()
            candidates = [n for n in names if _CONV_ID_RE.fullmatch(n)]
            require_age = True

        values: list[SessionSummary] = []
        for session_id in candidates:
            paths = _conversation_paths(conversations, session_id, root)
            if paths is None:
                continue
            _conv_dir, events_dir = paths
            try:
                if not _has_public_turn(
                    events_dir, root, budget, raise_on_bad=exact is not None
                ):
                    continue
            except DiagnosticError as error:
                if exact is not None:
                    raise
                if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
                    continue
                continue
            try:
                title, created_at, updated_at = _list_title_and_stamp(
                    events_dir, root, budget
                )
            except DiagnosticError as error:
                if exact is not None:
                    raise
                if error.code in {"E_CORRUPT_RECORD", "E_UNSUPPORTED_FORMAT"}:
                    continue
                continue
            # Event v1 has no durable cwd field; leave cwd unset and do not
            # exclude on query.cwd (no false negatives for cwd-only filters).
            if require_age and not within_age(
                updated_at, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
            ):
                continue
            values.append(
                SessionSummary(
                    source="openhands",
                    session_id=session_id,
                    source_path=events_dir,
                    title=title,
                    cwd=None,
                    branch=None,
                    created_at=created_at,
                    updated_at=updated_at,
                    provider=FORMAT_ID,
                    warnings=(),
                )
            )
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
        conversations, root = layout
        session_id = ref.session_id
        if not session_id or not _CONV_ID_RE.fullmatch(session_id):
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
        paths = _conversation_paths(conversations, session_id, root)
        if paths is None:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
        _conv_dir, events_dir = paths
        # No durable cwd in events v1 — ignore query.cwd rather than fail closed.

        scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
        names = _event_names(events_dir, scan_limit=scan_limit)
        if not names:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        # Stable set: capture membership, read, re-check names.
        membership = tuple(names)
        turns: list[Turn] = []
        warnings: list[str] = []
        created_at: str | None = None
        updated_at: str | None = None
        title: str | None = None
        turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        transcript_limit = budget.limits.transcript_records
        count = 0
        seen_ids: set[str] = set()
        for name in membership:
            path = os.path.join(events_dir, name)
            if not _regular_file(path, root):
                raise DiagnosticError("E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID)
            count += 1
            if count > transcript_limit:
                raise DiagnosticError.limit_exceeded()
            budget.consume_transcript_records()
            payload = _load_event_json(path, root, budget)
            event_id = payload.get("id")
            if isinstance(event_id, str) and event_id:
                if event_id in seen_ids:
                    raise DiagnosticError(
                        "E_CORRUPT_RECORD", source=self.key, provider=FORMAT_ID
                    )
                seen_ids.add(event_id)
            stamp = _stamp_iso(payload.get("timestamp"))
            if created_at is None and stamp is not None:
                created_at = stamp
            if stamp is not None:
                updated_at = stamp
            parsed = _handle_event(payload, strict_unknown=True)
            if parsed is None:
                continue
            role, text = parsed
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

        # Revalidate membership after scan (stable set).
        after = tuple(_event_names(events_dir, scan_limit=scan_limit))
        if after != membership:
            raise DiagnosticError.source_busy(provider=FORMAT_ID)

        if not turns:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        last_user = next((t.content for t in reversed(turns) if t.role == "user"), None)
        last_assistant = next(
            (t.content for t in reversed(turns) if t.role == "assistant"), None
        )
        return Session(
            source="openhands",
            session_id=session_id,
            source_path=events_dir,
            title=title,
            cwd=None,
            branch=None,
            created_at=created_at,
            updated_at=updated_at or created_at,
            last_user_request=last_user,
            last_assistant_action=last_assistant,
            turns=tuple(turns),
            warnings=tuple(dict.fromkeys(warnings)),
        )


ADAPTER = OpenHandsAdapter()
