"""Offline cross-source discover and read-only doctor pure functions.

Content-free diagnostics only: no recovered session bodies or tool outputs.
Source stores stay immutable; adapters are never invoked via source agent CLIs.
Failures are isolated per source so one bad probe/list cannot wipe others.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Sequence

from .adapters.base import CAPABILITY_STATES, SourceAdapter
from .bounds import DEFAULT_BOUNDS, ReadBudget
from .diagnostics import DiagnosticError, WARNING_CODES
from .model import Query, SessionSummary
from .paths import canonicalize_cwd
from .registry import (
    DESTINATION_PROFILES,
    SOURCE_PROFILES,
    enabled_destination_keys,
    enabled_source_keys,
    matrix_dimensions,
)
from .sanitize import sanitize_summary, validate_structural_summary
from .select import summary_sort_key

LoadAdapter = Callable[[str], SourceAdapter]

_CHECK_STATUSES = frozenset({"pass", "warn", "fail", "info"})


def _default_load_adapter(source: str) -> SourceAdapter:
    # Lazy import keeps discover/doctor usable without pulling reader CLI at import time.
    from .reader import _load_adapter

    return _load_adapter(source)


def _resolve_listed_limit(listed_limit: int | None) -> int:
    if listed_limit is None:
        return DEFAULT_BOUNDS.listed_sessions
    if type(listed_limit) is not int or listed_limit < 0 or listed_limit > DEFAULT_BOUNDS.listed_sessions:
        raise DiagnosticError.invalid()
    return listed_limit


def _resolve_source_keys(sources: Sequence[str] | None) -> tuple[str, ...]:
    enabled = enabled_source_keys()
    if sources is None:
        return tuple(sorted(enabled))
    if not isinstance(sources, (list, tuple)):
        raise DiagnosticError.invalid()
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in sources:
        if not isinstance(raw, str) or not raw:
            raise DiagnosticError.invalid()
        if raw not in enabled:
            # Explicit unknown filter key is invalid input (not a soft skip).
            raise DiagnosticError.invalid(source=raw if raw in SOURCE_PROFILES else None)
        if raw not in seen:
            seen.add(raw)
            resolved.append(raw)
    return tuple(sorted(resolved))


def _public_token(source: str, session_id: str) -> str:
    """Source-qualified public token; native session_id unchanged internally."""

    return f"{source}:{session_id}"


def _public_candidate(summary: SessionSummary) -> dict[str, Any]:
    return {
        "token": _public_token(summary.source, summary.session_id),
        "source": summary.source,
        "session_id": summary.session_id,
        "title": summary.title,
        "cwd": summary.cwd,
        "branch": summary.branch,
        "updated_at": summary.updated_at,
        "follow_up": f"portable-resume {summary.source} show {summary.session_id}",
    }


def _probe_source_row(
    source: str,
    *,
    resolved_cwd: str,
    load_adapter: LoadAdapter,
) -> dict[str, Any]:
    """Presence-style probe row (content-free), matching sources_report shape."""

    profile = SOURCE_PROFILES.get(source)
    supports_list = bool(profile.supports_list) if profile is not None else False
    supports_show = bool(profile.supports_show) if profile is not None else False
    row: dict[str, Any] = {
        "state": "error",
        "format_id": None,
        "warnings": [],
        "supports_list": supports_list,
        "supports_show": supports_show,
    }
    try:
        adapter = load_adapter(source)
        query = Query(source=source, ref=None, cwd=resolved_cwd)
        capability = adapter.probe(query)
        if capability.state not in CAPABILITY_STATES or capability.source != source:
            row["state"] = "error"
            row["code"] = "E_INVARIANT"
            return row
        warnings = [w for w in capability.warnings if w in WARNING_CODES]
        row["format_id"] = capability.format_id
        row["warnings"] = list(warnings)
        if capability.state in {"supported", "partial", "unavailable"}:
            row["state"] = capability.state
        elif capability.state == "unsupported":
            row["state"] = "skipped"
        elif capability.state == "unsafe":
            row["state"] = "error"
            row["code"] = "E_UNSAFE_PATH"
        else:
            row["state"] = "error"
            row["code"] = "E_INVARIANT"
    except DiagnosticError as error:
        row["state"] = "error"
        row["code"] = error.code
    except Exception as error:  # noqa: BLE001 - sweep must not abort
        row["state"] = "error"
        row["exception"] = type(error).__name__
    return row


def discover_report(
    *,
    cwd: str | None = None,
    sources: Sequence[str] | None = None,
    load_adapter: LoadAdapter | None = None,
    listed_limit: int | None = None,
) -> dict[str, Any]:
    """Cross-source session discovery (metadata only; no show/transcript bodies)."""

    loader = load_adapter if load_adapter is not None else _default_load_adapter
    resolved_cwd = canonicalize_cwd(cwd or os.getcwd())
    limit = _resolve_listed_limit(listed_limit)
    source_keys = _resolve_source_keys(sources)

    report: dict[str, Any] = {
        "schema_version": "portable-resume/discover-v1",
        "ok": True,
        "cwd": resolved_cwd,
        "sources": {},
        "candidates": [],
    }

    collected: list[SessionSummary] = []

    for source in source_keys:
        row = _probe_source_row(source, resolved_cwd=resolved_cwd, load_adapter=loader)
        report["sources"][source] = row
        if row.get("state") not in {"supported", "partial"}:
            continue

        # Fresh budget per source — one source cannot consume another's allowance.
        budget = ReadBudget()
        query = Query(source=source, ref=None, cwd=resolved_cwd)
        try:
            adapter = loader(source)
            raw_summaries = adapter.list(query, budget)
            if len(raw_summaries) > DEFAULT_BOUNDS.scanned_records:
                raise DiagnosticError.limit_exceeded()
        except DiagnosticError as error:
            row["state"] = "error"
            row["code"] = error.code
            continue
        except Exception as error:  # noqa: BLE001 - isolate list failures
            row["state"] = "error"
            row["exception"] = type(error).__name__
            continue

        accepted = 0
        for raw in raw_summaries:
            try:
                if not isinstance(raw, SessionSummary) or raw.source != source:
                    raise DiagnosticError("E_INVARIANT", source=source)
                structural = validate_structural_summary(raw)
                public, _warnings = sanitize_summary(structural)
                collected.append(public)
                accepted += 1
            except DiagnosticError:
                # Skip one bad summary; keep the rest of this source and others.
                continue
            except Exception:  # noqa: BLE001
                continue
        row["listed"] = accepted

    ordered = sorted(collected, key=summary_sort_key)
    if len(ordered) > limit:
        ordered = ordered[:limit]
    report["candidates"] = [_public_candidate(item) for item in ordered]
    return report


def doctor_report(
    *,
    cwd: str | None = None,
    load_adapter: LoadAdapter | None = None,
) -> dict[str, Any]:
    """Read-only offline health report (no recovered session bodies)."""

    loader = load_adapter if load_adapter is not None else _default_load_adapter
    resolved_cwd = canonicalize_cwd(cwd or os.getcwd())

    checks: list[dict[str, str]] = []
    ok = True

    # --- registry_valid ---
    registry_detail = "enabled sources and destinations present"
    try:
        source_set = enabled_source_keys()
        dest_set = enabled_destination_keys()
        if not source_set or not dest_set:
            ok = False
            checks.append(
                {
                    "id": "registry_valid",
                    "status": "fail",
                    "detail": "empty enabled source or destination set",
                }
            )
        else:
            # Profiles must exist for every enabled key.
            missing_src = sorted(k for k in source_set if k not in SOURCE_PROFILES)
            missing_dst = sorted(k for k in dest_set if k not in DESTINATION_PROFILES)
            if missing_src or missing_dst:
                ok = False
                checks.append(
                    {
                        "id": "registry_valid",
                        "status": "fail",
                        "detail": "profile missing for enabled key",
                    }
                )
            else:
                checks.append(
                    {
                        "id": "registry_valid",
                        "status": "pass",
                        "detail": registry_detail,
                    }
                )
    except Exception as error:  # noqa: BLE001 - content-free
        ok = False
        checks.append(
            {
                "id": "registry_valid",
                "status": "fail",
                "detail": type(error).__name__,
            }
        )

    # --- matrix_cells ---
    try:
        dims = matrix_dimensions()
        expected = int(dims["sources"]) * int(dims["destinations"])
        if (
            dims.get("cells") != expected
            or int(dims["sources"]) <= 0
            or int(dims["destinations"]) <= 0
        ):
            ok = False
            checks.append(
                {
                    "id": "matrix_cells",
                    "status": "fail",
                    "detail": "matrix dimensions inconsistent",
                }
            )
            matrix_dims = dims
        else:
            checks.append(
                {
                    "id": "matrix_cells",
                    "status": "pass",
                    "detail": f"{dims['sources']}x{dims['destinations']}={dims['cells']}",
                }
            )
            matrix_dims = dims
    except Exception as error:  # noqa: BLE001
        ok = False
        matrix_dims = {"sources": 0, "destinations": 0, "cells": 0}
        checks.append(
            {
                "id": "matrix_cells",
                "status": "fail",
                "detail": type(error).__name__,
            }
        )

    # --- schema_file_present ---
    schema_path = os.path.join(
        os.path.dirname(__file__),
        "resources",
        "portable-resume-v1.schema.json",
    )
    if os.path.isfile(schema_path):
        checks.append(
            {
                "id": "schema_file_present",
                "status": "pass",
                "detail": "portable-resume-v1.schema.json",
            }
        )
    else:
        ok = False
        checks.append(
            {
                "id": "schema_file_present",
                "status": "fail",
                "detail": "schema file missing",
            }
        )

    # --- sources probe (presence-style, isolated) ---
    source_rows: dict[str, Any] = {}
    probe_completed = True
    try:
        for source in sorted(enabled_source_keys()):
            source_rows[source] = _probe_source_row(
                source, resolved_cwd=resolved_cwd, load_adapter=loader
            )
    except Exception as error:  # noqa: BLE001 - unexpected abort only
        probe_completed = False
        ok = False
        checks.append(
            {
                "id": "sources_probe_completed",
                "status": "fail",
                "detail": type(error).__name__,
            }
        )
    if probe_completed:
        checks.append(
            {
                "id": "sources_probe_completed",
                "status": "pass",
                "detail": f"{len(source_rows)} sources probed",
            }
        )

    # --- windows_install_policy (fail-closed mutating install on nt) ---
    windows_mutating_install = os.name != "nt"
    if windows_mutating_install:
        checks.append(
            {
                "id": "windows_install_policy",
                "status": "pass",
                "detail": "mutating install supported on this platform",
            }
        )
    else:
        # Not a critical registry failure: doctor remains ok; note fail-closed.
        checks.append(
            {
                "id": "windows_install_policy",
                "status": "info",
                "detail": "mutating install unsupported on nt (fail-closed)",
            }
        )

    destinations: dict[str, Any] = {}
    for key in sorted(enabled_destination_keys()):
        profile = DESTINATION_PROFILES[key]
        destinations[key] = {
            "status": profile.status,
            "payload_profile": profile.payload_profile,
            "project_rel": profile.project_rel,
            "global_rel": profile.global_rel,
        }

    for check in checks:
        if check["status"] not in _CHECK_STATUSES:
            ok = False

    return {
        "schema_version": "portable-resume/doctor-v1",
        "ok": ok,
        "cwd": resolved_cwd,
        "matrix_dimensions": {
            "sources": matrix_dims.get("sources"),
            "destinations": matrix_dims.get("destinations"),
            "cells": matrix_dims.get("cells"),
        },
        "platform": {
            "os_name": os.name,
            "windows_mutating_install": windows_mutating_install,
        },
        "sources": source_rows,
        "destinations": destinations,
        "checks": checks,
    }


def discover_table(report: dict[str, Any]) -> str:
    """Simple TSV-ish rendering of a discover report (candidates + source states)."""

    lines = ["TOKEN\tSOURCE\tSESSION_ID\tUPDATED_AT\tTITLE"]
    for item in report.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "\t".join(
                [
                    str(item.get("token") or "-"),
                    str(item.get("source") or "-"),
                    str(item.get("session_id") or "-"),
                    str(item.get("updated_at") or "-"),
                    str(item.get("title") or "-"),
                ]
            )
        )
    lines.append("SOURCE\tSTATE\tFORMAT")
    sources = report.get("sources") or {}
    if isinstance(sources, dict):
        for key in sorted(sources):
            row = sources[key] if isinstance(sources[key], dict) else {}
            lines.append(
                f"{key}\t{row.get('state') or '-'}\t{row.get('format_id') or '-'}"
            )
    return "\n".join(lines) + "\n"


def doctor_table(report: dict[str, Any]) -> str:
    """Simple TSV-ish rendering of a doctor report (checks + source presence)."""

    lines = ["CHECK\tSTATUS\tDETAIL"]
    for check in report.get("checks") or []:
        if not isinstance(check, dict):
            continue
        lines.append(
            f"{check.get('id') or '-'}\t{check.get('status') or '-'}\t{check.get('detail') or '-'}"
        )
    lines.append("SOURCE\tSTATE\tFORMAT")
    sources = report.get("sources") or {}
    if isinstance(sources, dict):
        for key in sorted(sources):
            row = sources[key] if isinstance(sources[key], dict) else {}
            lines.append(
                f"{key}\t{row.get('state') or '-'}\t{row.get('format_id') or '-'}"
            )
    return "\n".join(lines) + "\n"
