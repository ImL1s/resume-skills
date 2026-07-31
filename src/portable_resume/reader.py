"""Host-neutral reader CLI; concrete adapters are structural, local-only plugins."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Never, Sequence

from .build_identity import latest_release, runtime_identity
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
    def error(self, message: str) -> Never:
        raise DiagnosticError.invalid()


_MAX_RUNTIME_MANIFEST_BYTES = 1024 * 1024
_RUNTIME_DRIFT_WARNING = "W_RUNTIME_IDENTITY_DRIFT"


def runtime_install_identity() -> dict[str, object]:
    """Report the loaded tree and compare it with its recorded install root.

    The installed runtime intentionally excludes ``portable_resume.install``.
    This bounded, best-effort reader therefore understands only the two fixed
    manifest locations and the small subset of fields needed for runtime
    identity reporting. Missing manifests are a supported, silent state.
    """

    package_dir = Path(__file__).resolve().parent
    runtime_dir = package_dir.parent
    support_dir = runtime_dir.parent
    installed_layout = runtime_dir.name == "runtime" and support_dir.name == ".portable-resume"
    actual_root = support_dir.parent if installed_layout else package_dir.parent
    result: dict[str, object] = {
        "actual_root": os.path.realpath(actual_root),
        "recorded_root": None,
        "recorded_root_matches_actual": None,
        "package_identity": None,
        "manifest_present": False,
    }
    if not installed_layout:
        return result

    manifest_path: Path | None = None
    for candidate in (
        support_dir / ".state" / "manifest.json",
        support_dir / "manifest.json",
    ):
        if os.path.lexists(candidate):
            manifest_path = candidate
            break
    if manifest_path is None:
        return result
    result["manifest_present"] = True
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(manifest_path, flags)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > _MAX_RUNTIME_MANIFEST_BYTES
            ):
                return result
            chunks: list[bytes] = []
            remaining = _MAX_RUNTIME_MANIFEST_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(descriptor)
        raw = b"".join(chunks)
        if len(raw) > _MAX_RUNTIME_MANIFEST_BYTES:
            return result
        manifest = json.loads(raw.decode("utf-8"))
        claims = manifest.get("claims") if isinstance(manifest, dict) else None
        if not isinstance(claims, dict) or not claims:
            return result
        roots: set[str] = set()
        for value in claims.values():
            root = value.get("root") if isinstance(value, dict) else None
            if (
                not isinstance(root, str)
                or not os.path.isabs(root)
                or any(ord(character) < 32 or ord(character) == 127 for character in root)
            ):
                result["recorded_root_matches_actual"] = False
                return result
            roots.add(os.path.realpath(root))
        if len(roots) != 1:
            result["recorded_root_matches_actual"] = False
            return result
        recorded_root = roots.pop()
        result["recorded_root"] = recorded_root
        result["recorded_root_matches_actual"] = recorded_root == result["actual_root"]
        package_identity = manifest.get("package_identity")
        if (
            isinstance(package_identity, str)
            and len(package_identity) == 64
            and all(character in "0123456789abcdef" for character in package_identity)
        ):
            result["package_identity"] = package_identity
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        # Runtime identity is advisory only: it must never alter the exit code.
        return result
    return result


def _runtime_version_report(identity: dict[str, object], *, prog: str) -> str:
    first_line = f"{prog} {runtime_identity()['version']}"
    actual_root = json.dumps(str(identity["actual_root"]), ensure_ascii=True)
    recorded = identity["recorded_root"]
    recorded_root = json.dumps(str(recorded), ensure_ascii=True) if recorded else "unknown"
    package_identity = identity["package_identity"] or "unknown"
    agreement = identity["recorded_root_matches_actual"]
    agreement_text = "unknown" if agreement is None else str(agreement).lower()
    return (
        f"{first_line}\n"
        f"runtime-root: {actual_root}\n"
        f"recorded-root: {recorded_root}\n"
        f"recorded-root-match: {agreement_text}\n"
        f"package-identity: {package_identity}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticArgumentParser(
        prog="portable-resume",
        description="Read inert local session context without invoking a source CLI.",
        epilog="""examples:
  portable-resume claude list --cwd "$PWD"
  portable-resume claude show latest --cwd "$PWD" --format handoff
  portable-resume self-check        # packaging/runtime health (always JSON)""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="store_true",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="one of: " + "|".join(sorted(SOURCE_KEYS)),
    )
    parser.add_argument(
        "action",
        nargs="?",
        help="list|show; run 'portable-resume self-check' for a health report",
    )
    parser.add_argument("ref", nargs="?", help="latest, exact ID, approved exact path, or bounded text")
    parser.add_argument(
        "--cwd",
        help="project directory used for session matching (default: current directory)",
    )
    parser.add_argument(
        "--within-min",
        type=int,
        help=(
            "only consider sessions updated within this many minutes "
            "(0..5256000; 0 disables the age filter; default: adapter listing window)"
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "handoff", "table"),
        help="output format; default: handoff for show, table for list; show rejects table",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_alias",
        help="alias for --format json (conflicts with an explicit non-json --format)",
    )
    parser.add_argument(
        "--max-tool-chars",
        type=int,
        default=DEFAULT_BOUNDS.tool_output_chars,
        help=(
            f"per-tool-output character cap, 0..{DEFAULT_BOUNDS.tool_output_chars} "
            f"(default: {DEFAULT_BOUNDS.tool_output_chars})"
        ),
    )
    parser.add_argument(
        "--source-root",
        help=(
            "override the approved source store root "
            "(file or directory pinned by the adapter)"
        ),
    )
    parser.add_argument(
        "--request-file",
        help=(
            "read a portable-resume/request-v1 JSON file instead of positional args; "
            "requires --expected-source; excludes "
            "source/action/ref/--cwd/--within-min"
        ),
    )
    parser.add_argument(
        "--expected-source",
        choices=tuple(sorted(SOURCE_KEYS)),
        help=(
            "assert the source key this invocation must resolve to "
            "(required with --request-file)"
        ),
    )
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


def _table(
    summaries: Sequence[SessionSummary], *, warnings: Sequence[str] = ()
) -> str:
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
    if warnings:
        rows.extend(("", "# Warnings", *(f"# {warning}" for warning in warnings)))
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

    identity = runtime_identity()
    report: dict[str, Any] = {
        "schema_version": "portable-resume/self-check-v1",
        "ok": True,
        "build_identity": identity,
        "latest_release": latest_release(),
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

    install_identity = runtime_install_identity()
    parser = build_parser()
    source: str | None = None
    try:
        namespace = parser.parse_args(argv_list)
        if namespace.version:
            stdout.write(_runtime_version_report(install_identity, prog=parser.prog) + "\n")
            return 0
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
        if (
            install_identity["manifest_present"]
            and install_identity["recorded_root_matches_actual"] is not True
        ):
            envelope_warnings.append(_RUNTIME_DRIFT_WARNING)
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
                stdout.write(_table(public_sessions, warnings=envelope.warnings))
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
