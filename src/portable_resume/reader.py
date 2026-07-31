"""Host-neutral reader CLI; concrete adapters are structural, local-only plugins."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Any, Sequence

from . import __version__
from .adapters.base import CAPABILITY_STATES, ResolvedRef, SourceAdapter
from .bounds import DEFAULT_BOUNDS, ReadBudget
from .contracts import validate_envelope
from .diagnostics import DiagnosticError, ExitCode, SOURCE_KEYS, WARNING_CODES, emit_diagnostic
from .handoff import render_candidates, render_handoff, render_no_match
from .model import Envelope, Query, SessionSummary
from .paths import canonical_root, canonical_source_root, canonicalize_cwd, reject_controls
from .request import load_request
from .sanitize import sanitize_session, sanitize_summary, validate_structural_summary
from .select import AmbiguousSelection, bounded_candidates, select_session, summary_sort_key


class DiagnosticArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DiagnosticError.invalid()


def build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticArgumentParser(prog="portable-resume", description="Read inert local session context without invoking a source CLI.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="one of: " + "|".join(sorted(SOURCE_KEYS)),
    )
    parser.add_argument("action", nargs="?", help="list|show")
    parser.add_argument("ref", nargs="?", help="latest, exact ID, approved exact path, or bounded text")
    parser.add_argument("--cwd")
    parser.add_argument("--within-min", type=int)
    parser.add_argument("--format", choices=("json", "handoff", "table"))
    parser.add_argument("--json", action="store_true", dest="json_alias")
    parser.add_argument("--max-tool-chars", type=int, default=DEFAULT_BOUNDS.tool_output_chars)
    parser.add_argument("--source-root")
    parser.add_argument("--request-file")
    parser.add_argument("--expected-source", choices=tuple(sorted(SOURCE_KEYS)))
    return parser


def build_self_check_parser() -> argparse.ArgumentParser:
    """Closed option set for ``self-check`` (JSON-only; no silent ignore)."""

    parser = DiagnosticArgumentParser(
        prog="portable-resume self-check",
        description="Deterministic packaging/runtime health report (always JSON).",
    )
    # Accepted for CI scripts that pass --json; output is always JSON.
    parser.add_argument(
        "--json",
        action="store_true",
        help="accepted for compatibility; self-check always writes JSON",
    )
    return parser


def _load_adapter(source: str) -> SourceAdapter:
    from .registry import SOURCE_PROFILES

    profile = SOURCE_PROFILES.get(source)
    if profile is None:
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=source)
    try:
        module = importlib.import_module(profile.adapter_module)
    except ModuleNotFoundError as error:
        if error.name != profile.adapter_module:
            raise
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=source) from error
    adapter: Any = getattr(module, "ADAPTER", None)
    if adapter is None and callable(getattr(module, "get_adapter", None)):
        adapter = module.get_adapter()
    if adapter is None or not isinstance(adapter, SourceAdapter):
        raise DiagnosticError("E_UNSUPPORTED_FORMAT", source=source)
    if adapter.key != source:
        raise DiagnosticError("E_INVARIANT", source=source)
    return adapter


def _resolve_invocation(namespace: argparse.Namespace) -> tuple[str, str, str | None, str, int | None]:
    if namespace.request_file:
        if namespace.source is not None or namespace.action is not None or namespace.ref is not None or namespace.cwd is not None:
            raise DiagnosticError.invalid()
        if namespace.expected_source is None:
            raise DiagnosticError.invalid()
        # request-v1 does not carry within_min; accepting it would silently drop it.
        if namespace.within_min is not None:
            raise DiagnosticError.invalid()
        request = load_request(namespace.request_file, expected_source=namespace.expected_source)
        return request.source, request.action, request.resume_ref, request.cwd, None
    # Grok-build style: skill-bound runners may pass --expected-source with
    # positional `source action [ref]` (source injected by the wrapper).
    if namespace.expected_source is not None and namespace.source != namespace.expected_source:
        raise DiagnosticError.invalid()
    if namespace.source not in SOURCE_KEYS or namespace.action not in {"list", "show"}:
        raise DiagnosticError.invalid()
    if namespace.action == "list" and namespace.ref is not None:
        raise DiagnosticError.invalid(source=namespace.source)
    if namespace.ref is not None:
        reject_controls(namespace.ref)
        if len(namespace.ref) > DEFAULT_BOUNDS.ref_chars:
            raise DiagnosticError.invalid(source=namespace.source)
    cwd = canonicalize_cwd(namespace.cwd or os.getcwd())
    return namespace.source, namespace.action, namespace.ref, cwd, namespace.within_min


def _format(namespace: argparse.Namespace, action: str) -> str:
    if namespace.json_alias and namespace.format not in (None, "json"):
        raise DiagnosticError.invalid()
    if namespace.json_alias:
        chosen = "json"
    elif namespace.format:
        chosen = namespace.format
    else:
        chosen = "handoff" if action == "show" else "table"
    # Explicit closed sets: list supports all three; show rejects table.
    if action == "show" and chosen == "table":
        raise DiagnosticError.invalid()
    if action == "list" and chosen not in {"table", "json", "handoff"}:
        raise DiagnosticError.invalid()
    if action == "show" and chosen not in {"json", "handoff"}:
        raise DiagnosticError.invalid()
    return chosen


def _approved_roots(adapter: SourceAdapter, query: Query) -> tuple[str, ...]:
    roots: list[str] = []
    if query.source_root is not None:
        roots.append(query.source_root)
    provider = getattr(adapter, "approved_roots", None)
    if callable(provider):
        for root in provider(query):
            roots.append(canonical_root(root))
    return tuple(dict.fromkeys(roots))


def _validated_value(envelope: Envelope) -> dict[str, Any]:
    value = envelope.to_dict()
    validate_envelope(value)
    return value


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _table(summaries: Sequence[SessionSummary]) -> str:
    rows = ["SOURCE\tSESSION_ID\tUPDATED_AT\tTITLE\tCWD"]
    for item in summaries:
        rows.append(
            "\t".join(
                (
                    item.source,
                    item.session_id,
                    item.updated_at or "-",
                    (item.title or "-").replace("\t", " ").replace("\n", " "),
                    (item.cwd or "-").replace("\t", " ").replace("\n", " "),
                )
            )
        )
    return "\n".join(rows) + "\n"


def self_check(*, stdout: Any = sys.stdout) -> int:
    """Deterministic packaging/runtime health report used by release gates."""
    from .install.transaction import matrix_report
    from .registry import (
        enabled_destination_keys,
        enabled_package_keys,
        enabled_source_keys,
        matrix_dimensions,
        validate_registries,
    )

    report: dict[str, Any] = {
        "schema_version": "portable-resume/self-check-v1",
        "ok": True,
        "sources": sorted(enabled_source_keys()),
        "destinations": sorted(enabled_destination_keys()),
        "package_surfaces": sorted(enabled_package_keys()),
        "matrix_dimensions": matrix_dimensions(),
        "actions": ["list", "show"],
        "adapters": {},
        "matrix": None,
        "warnings": [],
    }
    try:
        validate_registries()
    except Exception as error:  # noqa: BLE001 - self-check must stay content-free
        report["ok"] = False
        report["warnings"].append(f"W_REGISTRY_INVALID:{type(error).__name__}")
    for source in sorted(SOURCE_KEYS):
        try:
            adapter = _load_adapter(source)
            report["adapters"][source] = {"ok": True, "key": adapter.key}
        except Exception as error:  # noqa: BLE001 - self-check must stay content-free
            report["ok"] = False
            report["adapters"][source] = {"ok": False, "error": type(error).__name__}
    try:
        matrix = matrix_report()
        report["matrix"] = {
            "ok": bool(matrix.get("ok")),
            "cell_count": matrix.get("cell_count"),
            "expected": matrix.get("expected"),
        }
        if (
            not matrix.get("ok")
            or matrix.get("cell_count") != matrix.get("expected")
        ):
            report["ok"] = False
    except Exception as error:  # noqa: BLE001
        report["ok"] = False
        report["matrix"] = {"ok": False, "error": type(error).__name__}
    schema_path = os.path.join(
        os.path.dirname(__file__),
        "resources",
        "portable-resume-v1.schema.json",
    )
    if not os.path.isfile(schema_path):
        report["ok"] = False
        report["warnings"].append("W_SCHEMA_MISSING")
    stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if report["ok"] else ExitCode.CORRUPT_OR_LIMIT


def run(argv: Sequence[str] | None = None, *, stdout: Any = sys.stdout, stderr: Any = sys.stderr) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if argv_list and argv_list[0] == "self-check":
        # Real closed parser: unknown options / positionals fail (no silent ignore).
        self_parser = build_self_check_parser()
        try:
            self_parser.parse_args(argv_list[1:])
        except DiagnosticError as error:
            return emit_diagnostic(error, stream=stderr)
        return self_check(stdout=stdout)

    parser = build_parser()
    source: str | None = None
    try:
        namespace = parser.parse_args(argv_list)
        source, action, ref, cwd, within_min = _resolve_invocation(namespace)
        output_format = _format(namespace, action)
        if within_min is not None and (within_min < 0 or within_min > 10 * 365 * 24 * 60):
            raise DiagnosticError.invalid(source=source)
        if not 0 <= namespace.max_tool_chars <= DEFAULT_BOUNDS.tool_output_chars:
            raise DiagnosticError.invalid(source=source)
        # File or directory: adapters pin exact store files (events.jsonl, *.db).
        source_root = (
            canonical_source_root(namespace.source_root) if namespace.source_root else None
        )
        query = Query(
            source=source,
            ref=ref,
            cwd=cwd,
            within_min=within_min,
            source_root=source_root,
            max_tool_chars=namespace.max_tool_chars,
        )
        adapter = _load_adapter(source)
        capability = adapter.probe(query)
        if capability.state not in CAPABILITY_STATES or capability.source != source:
            raise DiagnosticError("E_INVARIANT", source=source)
        if any(warning not in WARNING_CODES for warning in capability.warnings):
            raise DiagnosticError("E_INVARIANT", source=source)
        if capability.state == "unsafe":
            raise DiagnosticError("E_UNSAFE_PATH", source=source, provider=capability.format_id)
        if capability.state not in {"supported", "partial"}:
            code = "E_CAPABILITY_UNAVAILABLE" if capability.state == "unavailable" else "E_UNSUPPORTED_FORMAT"
            raise DiagnosticError(code, source=source, provider=capability.format_id)

        budget = ReadBudget()
        raw_summaries = adapter.list(query, budget)
        if len(raw_summaries) > DEFAULT_BOUNDS.scanned_records:
            raise DiagnosticError.limit_exceeded()
        # Internal identity for selection / ResolvedRef; public projection later.
        internal: list[SessionSummary] = []
        envelope_warnings: list[str] = list(capability.warnings)
        for raw in raw_summaries:
            if raw.source != source:
                raise DiagnosticError("E_INVARIANT", source=source)
            internal.append(validate_structural_summary(raw))
        ordered_internal_all = sorted(internal, key=summary_sort_key)
        if len(ordered_internal_all) > DEFAULT_BOUNDS.listed_sessions:
            envelope_warnings.append("W_TRUNCATED")
        ordered_internal = ordered_internal_all[: DEFAULT_BOUNDS.listed_sessions]

        if action == "list":
            public_sessions: list[SessionSummary] = []
            for raw in ordered_internal:
                item, warnings = sanitize_summary(raw)
                public_sessions.append(item)
                envelope_warnings.extend(warnings)
            envelope = Envelope.create(
                operation="list",
                query=query,
                sessions=(item.empty_session() for item in public_sessions),
                warnings=tuple(dict.fromkeys(envelope_warnings)),
            )
            value = _validated_value(envelope)
            if output_format == "json":
                stdout.write(_json(value))
            elif output_format == "handoff":
                stdout.write(render_candidates(bounded_candidates(public_sessions), warnings=envelope.warnings))
            else:
                stdout.write(_table(public_sessions))
            return 0

        try:
            selection = select_session(
                internal,
                ref=ref,
                cwd=cwd,
                approved_roots=_approved_roots(adapter, query),
            )
        except AmbiguousSelection as error:
            # Project each candidate from its own fields (not first-match by ID):
            # duplicate native IDs with different title/cwd must stay distinguishable.
            public_candidates = []
            for candidate in error.candidates:
                stub = SessionSummary(
                    source=candidate.source,
                    session_id=candidate.session_id,
                    title=candidate.title,
                    cwd=candidate.cwd,
                    branch=candidate.branch,
                    updated_at=candidate.updated_at,
                )
                item, warnings = sanitize_summary(stub)
                envelope_warnings.extend(warnings)
                public_candidates.append(item.candidate())
            envelope = Envelope.create(
                operation="show",
                query=query,
                candidates=tuple(public_candidates),
                warnings=tuple(dict.fromkeys(envelope_warnings)),
            )
            value = _validated_value(envelope)
            stdout.write(
                _json(value)
                if output_format == "json"
                else render_candidates(tuple(public_candidates), warnings=envelope.warnings)
            )
            return emit_diagnostic(error, stream=stderr)
        except DiagnosticError as error:
            if error.code != "E_NO_MATCH":
                raise
            envelope = Envelope.create(
                operation="show",
                query=query,
                warnings=tuple(dict.fromkeys(envelope_warnings)),
            )
            value = _validated_value(envelope)
            stdout.write(
                _json(value)
                if output_format == "json"
                else render_no_match(warnings=envelope.warnings)
            )
            return emit_diagnostic(error, stream=stderr)
        assert selection.selected is not None
        selected_raw = selection.selected
        # Fresh budget for show: list already consumed scan/read counters on the
        # same large live transcripts (Grok-style real sessions often >1k records).
        raw_session = adapter.show(ResolvedRef.from_summary(selected_raw), query, ReadBudget())
        if raw_session.source != source or raw_session.session_id != selected_raw.session_id:
            raise DiagnosticError("E_INVARIANT", source=source)
        if raw_session.source_path is not None and selected_raw.source_path is not None:
            if raw_session.source_path != selected_raw.source_path:
                raise DiagnosticError("E_INVARIANT", source=source)
        session = sanitize_session(raw_session)
        # Public session_id remains the validated native token; paths are redacted.
        if session.session_id != selected_raw.session_id:
            raise DiagnosticError("E_INVARIANT", source=source)
        envelope = Envelope.create(
            operation="show",
            query=query,
            sessions=(session,),
            warnings=tuple(dict.fromkeys(envelope_warnings)),
        )
        value = _validated_value(envelope)
        stdout.write(_json(value) if output_format == "json" else render_handoff(envelope))
        return 0
    except DiagnosticError as error:
        if error.source is None and source in SOURCE_KEYS:
            error.source = source
        return emit_diagnostic(error, stream=stderr)
    except (KeyboardInterrupt, BrokenPipeError):
        raise
    except Exception:
        return emit_diagnostic(DiagnosticError("E_INVARIANT", source=source), stream=stderr)


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
