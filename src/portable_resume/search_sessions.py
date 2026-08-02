"""Bounded offline full-text search across public session content (#156)."""

from __future__ import annotations

import os
from typing import Any, Callable, Sequence

from .adapters.base import CAPABILITY_STATES, ResolvedRef, SourceAdapter
from .bounds import DEFAULT_BOUNDS, ReadBudget
from .diagnostics import DiagnosticError, WARNING_CODES
from .model import Query, SessionSummary
from .paths import canonicalize_cwd, reject_controls
from .registry import enabled_source_keys
from .sanitize import sanitize_session, sanitize_summary, validate_structural_summary
from .select import summary_sort_key
from .time_range import resolve_window, summary_in_window

LoadAdapter = Callable[[str], SourceAdapter]


def _default_load(source: str) -> SourceAdapter:
    from .reader import _load_adapter

    return _load_adapter(source)


def _public_excerpt(text: str, needle: str, *, radius: int = 80) -> str:
    lower = text.casefold()
    idx = lower.find(needle)
    if idx < 0:
        return text[: radius * 2]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    chunk = text[start:end].replace("\n", " ")
    if start > 0:
        chunk = "…" + chunk
    if end < len(text):
        chunk = chunk + "…"
    return chunk


def search_report(
    query_text: str,
    *,
    cwd: str | None = None,
    sources: Sequence[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    within_min: int | None = None,
    mode: str = "phrase",
    max_sessions_per_source: int = 20,
    load_adapter: LoadAdapter | None = None,
) -> dict[str, Any]:
    """Search public user/assistant turns for a substring/phrase.

    Default surface excludes tool payloads and system/reasoning roles (handled
    by sanitize_session). Bounds: limited sessions per source, ReadBudget per
    source, no source CLI.
    """

    if not isinstance(query_text, str) or not query_text.strip():
        raise DiagnosticError.invalid()
    reject_controls(query_text)
    if len(query_text) > DEFAULT_BOUNDS.ref_chars:
        raise DiagnosticError.invalid()
    if mode not in {"phrase", "all-terms"}:
        raise DiagnosticError.invalid()
    if (
        type(max_sessions_per_source) is not int
        or max_sessions_per_source < 1
        or max_sessions_per_source > DEFAULT_BOUNDS.listed_sessions
    ):
        raise DiagnosticError.invalid()

    loader = load_adapter if load_adapter is not None else _default_load
    resolved_cwd = canonicalize_cwd(cwd or os.getcwd())
    since_dt, until_dt, time_echo = resolve_window(
        since=since, until=until, within_min=within_min
    )

    enabled = enabled_source_keys()
    if sources is None:
        source_keys = tuple(sorted(enabled))
    else:
        source_keys = tuple(sorted(dict.fromkeys(sources)))
        for key in source_keys:
            if key not in enabled:
                raise DiagnosticError.invalid(source=key if key in enabled else None)

    needle = query_text.casefold().strip()
    terms = [t for t in needle.split() if t] if mode == "all-terms" else [needle]
    if not terms:
        raise DiagnosticError.invalid()

    report: dict[str, Any] = {
        "schema_version": "portable-resume/search-v1",
        "ok": True,
        "cwd": resolved_cwd,
        "query": {"mode": mode, "length": len(query_text)},
        "time": time_echo,
        "sources": {},
        "hits": [],
        "warnings": [],
    }

    hits: list[dict[str, Any]] = []

    for source in source_keys:
        row: dict[str, Any] = {"state": "error", "scanned": 0, "hits": 0}
        report["sources"][source] = row
        budget = ReadBudget()
        query = Query(source=source, ref=None, cwd=resolved_cwd, within_min=within_min)
        try:
            adapter = loader(source)
            capability = adapter.probe(query)
            if capability.state not in CAPABILITY_STATES or capability.source != source:
                row["state"] = "error"
                row["code"] = "E_INVARIANT"
                continue
            if capability.state not in {"supported", "partial"}:
                row["state"] = capability.state
                continue
            row["state"] = capability.state
            raw_list = adapter.list(query, budget)
            if len(raw_list) > DEFAULT_BOUNDS.scanned_records:
                raise DiagnosticError.limit_exceeded()
            summaries: list[SessionSummary] = []
            for raw in raw_list:
                if not isinstance(raw, SessionSummary) or raw.source != source:
                    continue
                structural = validate_structural_summary(raw)
                if not summary_in_window(structural, since_dt=since_dt, until_dt=until_dt):
                    continue
                summaries.append(structural)
            summaries = sorted(summaries, key=summary_sort_key)[:max_sessions_per_source]
            row["scanned"] = len(summaries)
            if len(raw_list) > max_sessions_per_source:
                report["warnings"].append("W_TRUNCATED")
            for summary in summaries:
                try:
                    session = adapter.show(
                        ResolvedRef.from_summary(summary),
                        query,
                        ReadBudget(),
                    )
                    public = sanitize_session(session)
                except DiagnosticError:
                    continue
                except Exception:  # noqa: BLE001
                    continue
                texts: list[str] = []
                for turn in public.turns:
                    if turn.role in {"user", "assistant"} and turn.content:
                        texts.append(turn.content)
                blob = "\n".join(texts)
                blob_cf = blob.casefold()
                if mode == "phrase":
                    matched = needle in blob_cf
                else:
                    matched = all(term in blob_cf for term in terms)
                if not matched:
                    continue
                pub_sum, _w = sanitize_summary(summary)
                excerpt = _public_excerpt(blob, terms[0])
                hits.append(
                    {
                        "token": f"{source}:{summary.session_id}",
                        "source": source,
                        "session_id": summary.session_id,
                        "title": pub_sum.title,
                        "cwd": pub_sum.cwd,
                        "updated_at": pub_sum.updated_at,
                        "excerpt": excerpt,
                        "follow_up": f"portable-resume {source} show {summary.session_id}",
                    }
                )
                row["hits"] = int(row["hits"]) + 1
        except DiagnosticError as error:
            row["state"] = "error"
            row["code"] = error.code
        except Exception as error:  # noqa: BLE001
            row["state"] = "error"
            row["exception"] = type(error).__name__

    hits.sort(key=lambda h: (h.get("updated_at") is None, h.get("updated_at") or "", h["source"], h["session_id"]), reverse=True)
    # Cap total hits
    if len(hits) > DEFAULT_BOUNDS.listed_sessions:
        hits = hits[: DEFAULT_BOUNDS.listed_sessions]
        report["warnings"].append("W_TRUNCATED")
    report["hits"] = hits
    report["warnings"] = list(dict.fromkeys(w for w in report["warnings"] if w in WARNING_CODES or w == "W_TRUNCATED"))
    return report


def search_table(report: dict[str, Any]) -> str:
    lines = ["TOKEN\tSOURCE\tUPDATED_AT\tTITLE\tEXCERPT"]
    for hit in report.get("hits") or []:
        title = (hit.get("title") or "-").replace("\t", " ").replace("\n", " ")
        excerpt = (hit.get("excerpt") or "-").replace("\t", " ").replace("\n", " ")
        lines.append(
            f"{hit.get('token')}\t{hit.get('source')}\t{hit.get('updated_at') or '-'}\t{title}\t{excerpt}"
        )
    warnings = report.get("warnings") or []
    if warnings:
        lines.extend(("", "# Warnings", *(f"# {w}" for w in warnings)))
    return "\n".join(lines) + "\n"
