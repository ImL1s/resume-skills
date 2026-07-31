"""Read Gemini CLI local session JSONL as inert context.

Pinned format: ``gemini-cli-session-jsonl-v1`` (upstream chatRecordingService /
chatRecordingTypes, 2026).

Layout (official session management docs + Storage.getProjectTempDir):

    $GEMINI_CLI_HOME/.gemini/  or  ~/.gemini/
    └── tmp/<projectHash>/chats/
        ├── session-<timestamp>-<id8>.jsonl   # main agent
        └── <parentSessionId>/<subagent>.jsonl

JSONL records: session metadata, MessageRecord lines, optional ``$set`` /
``$rewindTo`` control lines.

**Not Antigravity.** Never searches Antigravity transcript roots or invokes
``gemini`` / Google APIs / MCP / agy.
"""

from __future__ import annotations

import hashlib
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
from ..paths import canonical_root, canonicalize_cwd, is_within
from ..sanitize import sanitize_turn_record
from ..snapshot import stable_scan_lines
from .base import CapabilityReport, ResolvedRef
from .common import within_age

FORMAT_ID = "gemini-cli-session-jsonl-v1"
_SESSION_FILE_RE = re.compile(
    r"^session-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-([A-Za-z0-9]{8})\.jsonl$"
)
_SUBAGENT_FILE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.jsonl$"
)
_SESSION_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$"
)
_HASH_RE = re.compile(r"^[a-f0-9]{16,64}$")
_PUBLIC_TYPES = frozenset({"user", "gemini"})
_OMIT_TYPES = frozenset({"info", "error", "warning"})


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


def _default_gemini_home() -> str:
    env = os.environ.get("GEMINI_CLI_HOME")
    if env and env.strip():
        path = env.strip()
        if not os.path.isabs(path):
            raise DiagnosticError("E_UNSAFE_PATH", source="gemini", provider=FORMAT_ID)
        # When GEMINI_CLI_HOME is the user home replacement, store is under .gemini
        # only if the env points at home root; upstream homedir() replaces os.homedir.
        return os.path.join(path, ".gemini") if os.path.basename(path) != ".gemini" else path
    return os.path.expanduser("~/.gemini")


def _layout_from_root(candidate: str) -> tuple[str, str] | None:
    """Return (gemini_home_or_chats_root, containment_root)."""

    try:
        if os.path.isfile(candidate):
            path = os.path.abspath(candidate)
            base = os.path.basename(path)
            if not (base.endswith(".jsonl") and base.startswith("session-") or base.endswith(".jsonl")):
                if not base.endswith(".jsonl"):
                    return None
            parent = os.path.dirname(path)
            # .../chats/session-*.jsonl or .../chats/<parent>/<sub>.jsonl
            if os.path.basename(parent) == "chats":
                root = canonical_root(os.path.dirname(os.path.dirname(parent)))  # tmp's parent = .gemini
                if not _regular_file(path, root):
                    # try chats as root
                    try:
                        root = canonical_root(parent)
                    except DiagnosticError:
                        return None
                    if not _regular_file(path, root):
                        return None
                return parent, root
            if os.path.basename(os.path.dirname(parent)) == "chats":
                chats = os.path.dirname(parent)
                root = canonical_root(os.path.dirname(os.path.dirname(chats)))
                if not _regular_file(path, root):
                    root = canonical_root(chats)
                    if not _regular_file(path, root):
                        return None
                return chats, root
            return None
        if not os.path.isdir(candidate):
            return None
        root = canonical_root(candidate)
    except DiagnosticError:
        return None

    # ~/.gemini
    tmp = os.path.join(root, "tmp")
    if _regular_dir(tmp, root):
        return root, root

    # ~/.gemini/tmp
    if os.path.basename(root.rstrip(os.sep)) == "tmp":
        parent = os.path.dirname(root)
        try:
            home = canonical_root(parent)
        except DiagnosticError:
            home = root
        return home if _regular_dir(root, home) else root, home

    # ~/.gemini/tmp/<hash>
    chats = os.path.join(root, "chats")
    if _regular_dir(chats, root) or any(
        name.startswith("session-") and name.endswith(".jsonl")
        for name in _safe_listdir(root)
    ):
        # containment: prefer parent tmp's parent
        parent = os.path.dirname(root)
        try:
            if os.path.basename(parent) == "tmp":
                home = canonical_root(os.path.dirname(parent))
                return home, home
        except DiagnosticError:
            pass
        return root, root

    # .../chats
    if os.path.basename(root.rstrip(os.sep)) == "chats":
        return root, root

    # bare tmp/<hash>/chats already handled
    if any(
        n.endswith(".jsonl") for n in _safe_listdir(root)
    ):
        return root, root
    return None


def _resolve_layout(query: Query) -> tuple[str, str] | None:
    if query.source_root:
        return _layout_from_root(query.source_root)
    try:
        return _layout_from_root(_default_gemini_home())
    except DiagnosticError:
        return None


def _exact_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text or text == "latest":
        return None
    if _SESSION_ID_RE.fullmatch(text):
        return text
    return None


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _macos_path_aliases(path: str) -> list[str]:
    """Return macOS public/private path spellings for hash candidates.

    Gemini hashes the project-root *string* as given at session creation. Reader
    may canonicalize ``/tmp/...`` → ``/private/tmp/...`` before the adapter sees
    it; include both so fixtures and live stores still match.
    """

    aliases = [path]
    pairs = (
        ("/private/tmp", "/tmp"),
        ("/private/var", "/var"),
        ("/tmp", "/private/tmp"),
        ("/var", "/private/var"),
    )
    for source_prefix, dest_prefix in pairs:
        if path == source_prefix:
            aliases.append(dest_prefix)
        elif path.startswith(source_prefix + "/"):
            aliases.append(dest_prefix + path[len(source_prefix) :])
    return aliases


def _project_hashes_for_cwd(cwd: str | None) -> frozenset[str] | None:
    """Gemini stores project roots under tmp/<sha256(projectRoot)> (legacy).

    When *cwd* is set, return candidate hashes for that path. Includes trailing-
    slash variants, macOS path aliases, and a best-effort realpath spelling.
    Returns None when cwd is unset so discovery remains store-wide.
    """

    if not cwd or not isinstance(cwd, str):
        return None
    text = cwd.strip()
    if not text:
        return None
    spellings: list[str] = []
    for base in _macos_path_aliases(text):
        spellings.append(base)
        stripped = base.rstrip("/\\")
        if stripped and stripped != base:
            spellings.append(stripped)
        elif not base.endswith(("/", "\\")):
            spellings.append(base + "/")
    try:
        real = canonicalize_cwd(text)
        for base in _macos_path_aliases(real):
            spellings.append(base)
    except DiagnosticError:
        pass
    return frozenset(_sha256_hex(item) for item in dict.fromkeys(spellings))


def _path_project_hash(path: str) -> str | None:
    """Extract ``tmp/<hash>`` segment from a session path when present."""

    parts = path.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part == "tmp" and index + 1 < len(parts):
            candidate = parts[index + 1]
            if _HASH_RE.fullmatch(candidate):
                return candidate
    return None


def _matches_project(
    *,
    path: str,
    meta: Mapping[str, Any],
    project_hashes: frozenset[str] | None,
) -> bool:
    """True when the session belongs to *project_hashes*, or mapping is unknown.

    Unknown mapping (no path hash, no meta projectHash) is an intentional
    fallback so bare ``chats/`` roots remain listable.
    """

    if project_hashes is None:
        return True
    meta_hash = meta.get("projectHash")
    path_hash = _path_project_hash(path)
    if isinstance(meta_hash, str) and meta_hash:
        return meta_hash in project_hashes
    if path_hash is not None:
        return path_hash in project_hashes
    return True


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


def _part_text(content: object) -> str | None:
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
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    if not chunks:
        return None
    return "\n".join(chunks)


def _discover_session_files(
    layout_root: str,
    containment: str,
    *,
    scan_limit: int,
    include_subagents: bool,
    project_hashes: frozenset[str] | None = None,
) -> list[str]:
    """Bounded discovery of session JSONL paths under gemini home or chats."""

    paths: list[str] = []
    # If layout_root is chats dir
    if os.path.basename(layout_root.rstrip(os.sep)) == "chats":
        path_hash = _path_project_hash(layout_root)
        if (
            project_hashes is not None
            and path_hash is not None
            and path_hash not in project_hashes
        ):
            return []
        chats_dirs = [layout_root]
    else:
        tmp = os.path.join(layout_root, "tmp")
        if not _regular_dir(tmp, containment):
            # layout_root may itself be tmp or project hash dir
            if _regular_dir(os.path.join(layout_root, "chats"), containment):
                path_hash = _path_project_hash(layout_root) or (
                    os.path.basename(layout_root.rstrip(os.sep))
                    if _HASH_RE.fullmatch(os.path.basename(layout_root.rstrip(os.sep)))
                    else None
                )
                if (
                    project_hashes is not None
                    and path_hash is not None
                    and path_hash not in project_hashes
                ):
                    return []
                chats_dirs = [os.path.join(layout_root, "chats")]
            elif any(
                n.endswith(".jsonl") for n in _safe_listdir(layout_root)
            ):
                chats_dirs = [layout_root]
            else:
                return []
        else:
            names = _safe_listdir(tmp)
            if len(names) > scan_limit:
                raise DiagnosticError.limit_exceeded()
            chats_dirs = []
            for name in sorted(names):
                if project_hashes is not None and name not in project_hashes:
                    # Skip other projects when cwd→hash filter is active.
                    # Non-hash migration slugs also miss the set → excluded
                    # (hash is the durable cross-store key for this adapter).
                    continue
                proj = os.path.join(tmp, name)
                chats = os.path.join(proj, "chats")
                if _regular_dir(chats, containment):
                    chats_dirs.append(chats)
                if len(chats_dirs) > scan_limit:
                    raise DiagnosticError.limit_exceeded()

    for chats in chats_dirs:
        names = _safe_listdir(chats)
        if len(names) > scan_limit:
            raise DiagnosticError.limit_exceeded()
        for name in sorted(names):
            path = os.path.join(chats, name)
            if name.endswith(".jsonl") and _regular_file(path, containment):
                if name.startswith("session-") or (
                    include_subagents and _SUBAGENT_FILE_RE.fullmatch(name)
                ):
                    paths.append(path)
                    if len(paths) > scan_limit:
                        raise DiagnosticError.limit_exceeded()
            elif include_subagents and _regular_dir(path, containment):
                # parent session id folder for subagents
                for child in sorted(_safe_listdir(path)):
                    cpath = os.path.join(path, child)
                    if child.endswith(".jsonl") and _regular_file(cpath, containment):
                        paths.append(cpath)
                        if len(paths) > scan_limit:
                            raise DiagnosticError.limit_exceeded()
    return paths


def _parse_jsonl_conversation(
    path: str,
    root: str,
    budget: ReadBudget,
    *,
    metadata_only: bool,
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    """Load session JSONL into metadata + ordered messages (with rewind)."""

    meta: dict[str, Any] = {}
    messages: dict[str, Mapping[str, Any]] = {}
    order: list[str] = []
    count = 0
    limit = min(budget.limits.transcript_records, DEFAULT_BOUNDS.transcript_records)
    meta_limit = min(64, limit)

    for line in stable_scan_lines(
        path,
        root=root,
        max_line_bytes=min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes),
        budget=budget,
    ):
        count += 1
        if metadata_only and count > meta_limit:
            break
        if not metadata_only and count > limit:
            raise DiagnosticError.limit_exceeded()
        if not metadata_only:
            budget.consume_transcript_records()
        else:
            budget.consume_records()
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
                "E_CORRUPT_RECORD", source="gemini", provider=FORMAT_ID
            ) from error
        if not isinstance(record, Mapping):
            raise DiagnosticError("E_CORRUPT_RECORD", source="gemini", provider=FORMAT_ID)

        if "$rewindTo" in record:
            target = record.get("$rewindTo")
            if isinstance(target, str) and target in messages:
                # Drop messages after target
                if target in order:
                    idx = order.index(target)
                    for mid in order[idx + 1 :]:
                        messages.pop(mid, None)
                    order = order[: idx + 1]
            continue
        if "$set" in record and isinstance(record.get("$set"), Mapping):
            updates = record["$set"]
            if "messages" in updates and isinstance(updates["messages"], list):
                messages.clear()
                order.clear()
                if not metadata_only:
                    for msg in updates["messages"]:
                        if isinstance(msg, Mapping) and isinstance(msg.get("id"), str):
                            messages[msg["id"]] = msg
                            order.append(msg["id"])
            else:
                meta.update({k: v for k, v in updates.items() if k != "messages"})
            continue

        # Full conversation dump (legacy path)
        if isinstance(record.get("messages"), list) and isinstance(
            record.get("sessionId"), str
        ):
            meta.update(
                {
                    k: record[k]
                    for k in (
                        "sessionId",
                        "projectHash",
                        "startTime",
                        "lastUpdated",
                        "summary",
                        "kind",
                    )
                    if k in record
                }
            )
            if not metadata_only:
                for msg in record["messages"]:
                    if isinstance(msg, Mapping) and isinstance(msg.get("id"), str):
                        messages[msg["id"]] = msg
                        order.append(msg["id"])
            continue

        # Metadata-only first line
        if isinstance(record.get("sessionId"), str) and "type" not in record:
            meta.update(dict(record))
            continue

        # Message record
        mid = record.get("id")
        if isinstance(mid, str) and mid:
            messages[mid] = record
            if mid not in order:
                order.append(mid)
            else:
                # update in place keeps order
                pass

    return meta, [messages[i] for i in order if i in messages]


def _message_turn(msg: Mapping[str, Any]) -> tuple[str, str] | None:
    kind = msg.get("type")
    if kind not in _PUBLIC_TYPES:
        return None
    text = _part_text(msg.get("content"))
    if text is None and kind == "gemini":
        # tool-only gemini row: use tool names as bounded tool turn
        tools = msg.get("toolCalls")
        if isinstance(tools, list):
            names = []
            for tc in tools[:8]:
                if isinstance(tc, Mapping):
                    name = tc.get("name")
                    if isinstance(name, str) and name.strip():
                        names.append(name.strip())
            if names:
                return "tool", ", ".join(names)
        return None
    if text is None:
        return None
    role = "user" if kind == "user" else "assistant"
    return role, text


def _session_summary_from_file(
    path: str,
    root: str,
    query: Query,
    budget: ReadBudget,
    *,
    require_age: bool,
    include_subagent: bool,
) -> SessionSummary | None:
    try:
        meta, messages = _parse_jsonl_conversation(
            path, root, budget, metadata_only=False
        )
    except DiagnosticError as error:
        if error.code in {"E_LIMIT_EXCEEDED", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
            raise
        return None
    kind = meta.get("kind")
    if not include_subagent and kind == "subagent":
        return None
    session_id = meta.get("sessionId")
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        # filename fallback for short ids
        base = os.path.basename(path)
        m = _SESSION_FILE_RE.fullmatch(base)
        if m:
            session_id = m.group(1)
        else:
            return None
    # Require a public user turn
    has_user = False
    title = None
    for msg in messages:
        turn = _message_turn(msg)
        if turn is None:
            continue
        if turn[0] == "user":
            has_user = True
            if title is None:
                title = turn[1].splitlines()[0][: DEFAULT_BOUNDS.title_chars]
            break
    if not has_user:
        return None
    # Durable project key is projectHash (sha256 of project root), not a path.
    project_hashes = _project_hashes_for_cwd(query.cwd)
    if not _matches_project(path=path, meta=meta, project_hashes=project_hashes):
        return None
    stamp = _stamp_iso(meta.get("lastUpdated")) or _stamp_iso(meta.get("startTime"))
    if require_age and not within_age(
        stamp, query.within_min, default_minutes=DEFAULT_BOUNDS.listing_age_minutes
    ):
        return None
    if isinstance(meta.get("summary"), str) and meta["summary"].strip() and title is None:
        title = meta["summary"].strip()[: DEFAULT_BOUNDS.title_chars]
    # Surface requested cwd when the session maps to it (path/meta hash match).
    cwd = query.cwd if project_hashes is not None else None
    return SessionSummary(
        source="gemini",
        session_id=session_id,
        source_path=path,
        title=title,
        cwd=cwd,
        branch=None,
        created_at=_stamp_iso(meta.get("startTime")),
        updated_at=stamp,
        provider=FORMAT_ID,
        warnings=(),
    )


class GeminiAdapter:
    key = "gemini"

    def approved_roots(self, query: Query) -> tuple[str, ...]:
        layout = _resolve_layout(query)
        return (layout[1],) if layout else ()

    def probe(self, query: Query) -> CapabilityReport:
        try:
            layout = _resolve_layout(query)
            if layout is None:
                return CapabilityReport(self.key, FORMAT_ID, "unavailable")
            base, root = layout
            project_hashes = _project_hashes_for_cwd(query.cwd)
            files = _discover_session_files(
                base,
                root,
                scan_limit=min(DEFAULT_BOUNDS.scanned_records, 64),
                include_subagents=False,
                project_hashes=project_hashes,
            )
            if not files:
                return CapabilityReport(
                    self.key, FORMAT_ID, "partial", root=root, evidence=(FORMAT_ID,)
                )
            # Spot-check first file has session metadata or message line
            budget = ReadBudget()
            try:
                meta, _msgs = _parse_jsonl_conversation(
                    files[0], root, budget, metadata_only=True
                )
            except DiagnosticError as error:
                if error.code in {"E_UNSAFE_PATH", "E_SOURCE_BUSY"}:
                    return CapabilityReport(self.key, FORMAT_ID, "unsafe", root=root)
                return CapabilityReport(self.key, FORMAT_ID, "unsupported", root=root)
            if not meta.get("sessionId") and not meta.get("projectHash"):
                # still may be valid if messages-only; treat partial
                return CapabilityReport(
                    self.key, FORMAT_ID, "partial", root=root, evidence=(FORMAT_ID,)
                )
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
        base, root = layout
        exact = _exact_ref(query.ref)
        project_hashes = _project_hashes_for_cwd(query.cwd)
        scan_limit = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
        list_limit = min(budget.limits.listed_sessions, DEFAULT_BOUNDS.listed_sessions)
        if exact is None and list_limit <= 0:
            return []

        files = _discover_session_files(
            base,
            root,
            scan_limit=scan_limit,
            include_subagents=exact is not None,
            project_hashes=project_hashes,
        )
        if exact is not None:
            # Prefer paths whose metadata sessionId matches
            matched: list[str] = []
            for path in files:
                try:
                    meta, _ = _parse_jsonl_conversation(
                        path, root, budget, metadata_only=True
                    )
                except DiagnosticError as error:
                    if error.code in {
                        "E_LIMIT_EXCEEDED",
                        "E_SOURCE_BUSY",
                        "E_UNSAFE_PATH",
                    }:
                        raise
                    continue
                sid = meta.get("sessionId")
                if isinstance(sid, str) and (
                    sid == exact or sid.lower() == exact.lower() or sid.startswith(exact)
                ):
                    matched.append(path)
            files = matched if matched else files

        values: list[SessionSummary] = []
        for path in files:
            try:
                item = _session_summary_from_file(
                    path,
                    root,
                    query,
                    budget,
                    require_age=exact is None,
                    include_subagent=exact is not None,
                )
            except DiagnosticError as error:
                if error.code in {"E_LIMIT_EXCEEDED", "E_SOURCE_BUSY", "E_UNSAFE_PATH"}:
                    raise
                continue
            if item is None:
                continue
            if exact is not None:
                if item.session_id != exact and not item.session_id.startswith(exact):
                    # short id prefix from filename
                    if exact not in item.session_id and item.session_id not in exact:
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
        base, root = layout
        session_id = ref.session_id
        project_hashes = _project_hashes_for_cwd(query.cwd)
        path = ref.source_path if ref.source_path else None
        if path and _regular_file(path, root):
            target = path
        else:
            files = _discover_session_files(
                base,
                root,
                scan_limit=min(
                    budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records
                ),
                include_subagents=True,
                project_hashes=project_hashes,
            )
            target = None
            for candidate in files:
                try:
                    meta, _ = _parse_jsonl_conversation(
                        candidate, root, budget, metadata_only=True
                    )
                except DiagnosticError as error:
                    if error.code in {
                        "E_LIMIT_EXCEEDED",
                        "E_SOURCE_BUSY",
                        "E_UNSAFE_PATH",
                    }:
                        raise
                    continue
                if not _matches_project(
                    path=candidate, meta=meta, project_hashes=project_hashes
                ):
                    continue
                sid = meta.get("sessionId")
                if isinstance(sid, str) and (
                    sid == session_id
                    or sid.lower() == session_id.lower()
                    or sid.startswith(session_id)
                    or session_id.startswith(sid[:8])
                ):
                    target = candidate
                    break
            if target is None:
                raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        meta, messages = _parse_jsonl_conversation(
            target, root, budget, metadata_only=False
        )
        if not _matches_project(path=target, meta=meta, project_hashes=project_hashes):
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)
        turns: list[Turn] = []
        warnings: list[str] = []
        turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
        title = None
        for msg in messages:
            parsed = _message_turn(msg)
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
        if not turns:
            raise DiagnosticError("E_NO_MATCH", source=self.key, provider=FORMAT_ID)

        sid = meta.get("sessionId") if isinstance(meta.get("sessionId"), str) else session_id
        last_user = next((t.content for t in reversed(turns) if t.role == "user"), None)
        last_assistant = next(
            (t.content for t in reversed(turns) if t.role == "assistant"), None
        )
        return Session(
            source="gemini",
            session_id=sid,
            source_path=target,
            title=title or (
                meta.get("summary")
                if isinstance(meta.get("summary"), str)
                else None
            ),
            cwd=query.cwd if project_hashes is not None else None,
            branch=None,
            created_at=_stamp_iso(meta.get("startTime")),
            updated_at=_stamp_iso(meta.get("lastUpdated"))
            or _stamp_iso(meta.get("startTime")),
            last_user_request=last_user,
            last_assistant_action=last_assistant,
            turns=tuple(turns),
            warnings=tuple(dict.fromkeys(warnings)),
        )


ADAPTER = GeminiAdapter()
