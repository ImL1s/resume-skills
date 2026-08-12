"""Installer CLI: quick-install / install / verify / uninstall / matrix / recover / audit-host.

#32 contract (Option A for mutation/status commands):
- install, verify, uninstall, recover, matrix, quick-install, audit-host always emit
  one versioned JSON document on stdout (pretty-printed, sorted keys).
- Those commands do **not** accept a no-op ``--json`` flag (removed).
- ``hosts`` remains dual-mode: human by default, ``--json`` for machine output.
- ``verify`` does not accept ``--dry-run`` (already pure; flag was a silent no-op).
- ``install`` / ``uninstall`` / ``quick-install`` keep real ``--dry-run`` semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Sequence

from ..build_identity import runtime_identity
from ..diagnostics import SOURCE_KEYS, DiagnosticError, emit_diagnostic
from .catalog import HOST_KEYS, hosts_report, resolve_skill_root
from .discovery import audit_host_report, require_no_blocking_shadow, scan_skill_duplicates
from .manifest import claim_key
from .render import materialize_plan, package_identity
from .transaction import (
    install_multi_targets,
    matrix_report,
    recover_root,
    uninstall_claim,
    verify_root,
)

RESULT_SCHEMA = "portable-resume/install-result-v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="install-resume-skills")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {runtime_identity()['version']}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- install (JSON-only stdout) ---
    inst = sub.add_parser(
        "install",
        help="install resume-* Skills into a destination host root (JSON stdout)",
    )
    inst.add_argument(
        "--host",
        required=True,
        choices=(*sorted(HOST_KEYS), "all"),
        help="host key or 'all'",
    )
    inst.add_argument("--scope", choices=("project", "global"), required=True)
    inst.add_argument("--project", help="project directory (required for project scope)")
    inst.add_argument("--root", help="explicit skill root override")
    inst.add_argument("--home", default=os.path.expanduser("~"))
    inst.add_argument(
        "--dry-run",
        action="store_true",
        help="plan only; observationally pure (no mutation)",
    )
    inst.add_argument("--force-with-backup", action="store_true")
    inst.add_argument(
        "--sources",
        help=(
            "comma-separated enabled source keys to install (default: all); "
            "e.g. claude,codex,grok (#151)"
        ),
    )

    # --- verify (JSON-only; no dry-run — already read-only) ---
    ver = sub.add_parser(
        "verify",
        help="verify owned install under a host root (JSON stdout; always read-only)",
    )
    ver.add_argument(
        "--host",
        required=True,
        choices=(*sorted(HOST_KEYS), "all"),
        help="host key or 'all'",
    )
    ver.add_argument("--scope", choices=("project", "global"), required=True)
    ver.add_argument("--project")
    ver.add_argument("--root", help="explicit skill root override")
    ver.add_argument("--home", default=os.path.expanduser("~"))

    # --- uninstall ---
    un = sub.add_parser(
        "uninstall",
        help="remove one ownership claim (JSON stdout)",
    )
    un.add_argument(
        "--host",
        required=True,
        choices=(*sorted(HOST_KEYS), "all"),
        help="host key or 'all'",
    )
    un.add_argument("--scope", choices=("project", "global"), required=True)
    un.add_argument("--project")
    un.add_argument("--root", help="explicit skill root override")
    un.add_argument("--home", default=os.path.expanduser("~"))
    un.add_argument(
        "--dry-run",
        action="store_true",
        help="report removable paths without mutation",
    )

    # --- quick-install ---
    quick = sub.add_parser(
        "quick-install",
        help="install one host (or all) with safe defaults (JSON stdout)",
    )
    quick.add_argument(
        "host",
        nargs="?",
        default="all",
        choices=(*sorted(HOST_KEYS), "all"),
        help="host key; defaults to all",
    )
    quick.add_argument(
        "--project",
        help="install into this project's host root instead of user-global roots",
    )
    quick.add_argument("--root", help="explicit skill root override")
    quick.add_argument("--home", default=os.path.expanduser("~"))
    quick.add_argument("--dry-run", action="store_true")
    quick.add_argument("--force-with-backup", action="store_true")

    # --- matrix (JSON-only) ---
    sub.add_parser(
        "matrix",
        help="report packaging matrix status (JSON stdout)",
    )

    # --- hosts (human default + optional --json) ---
    h = sub.add_parser(
        "hosts",
        help="list destination host skill roots, install methods, and activation notes",
    )
    h.add_argument("--host", default="all", help="host key or 'all' (default)")
    h.add_argument("--project", default=None, help="resolve project roots against this path")
    h.add_argument("--home", default=os.path.expanduser("~"))
    h.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of the human report",
    )

    # --- recover (JSON-only) ---
    r = sub.add_parser(
        "recover",
        help="recover a root with a pending install journal (JSON stdout)",
    )
    r.add_argument("--root", required=True)
    # No --dry-run until a zero-mutation plan is implemented (#32).

    # --- audit-host (JSON-only) ---
    a = sub.add_parser(
        "audit-host",
        help="read-only scan for duplicate/shadow Portable Resume Skills (#34; JSON stdout)",
    )
    a.add_argument(
        "--host",
        required=True,
        choices=tuple(sorted(HOST_KEYS)),
        help="host key (not 'all')",
    )
    a.add_argument("--scope", choices=("project", "global"), required=True)
    a.add_argument("--project", default=None, help="project dir for project scope / alt roots")
    a.add_argument("--root", help="explicit skill root override")
    a.add_argument("--home", default=os.path.expanduser("~"))

    return parser


def _hosts(value: str) -> list[str]:
    if value == "all":
        return sorted(HOST_KEYS)
    if value not in HOST_KEYS:
        raise DiagnosticError.invalid()
    return [value]


def _parse_install_sources(raw: str | None) -> tuple[str, ...] | None:
    """Parse ``--sources`` for install (#151). ``None`` means all enabled."""

    if raw is None:
        return None
    from ..diagnostics import SOURCE_KEYS
    from ..paths import reject_controls

    reject_controls(raw)
    parts = [p.strip() for p in raw.split(",")]
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        if part == "all":
            return None
        if part not in SOURCE_KEYS:
            raise DiagnosticError.invalid()
        if part not in seen:
            seen.add(part)
            cleaned.append(part)
    if not cleaned:
        raise DiagnosticError.invalid()
    return tuple(sorted(cleaned))


def _root_for(host: str, scope: str, project: str | None, home: str, override: str | None) -> str:
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return resolve_skill_root(host=host, scope=scope, project_dir=project, home_dir=home)


def _reject_divergent_shared_roots(targets: list[tuple[str, str]]) -> None:
    """Reject host profiles that resolve to one directory but render differently."""
    groups: dict[str, list[str]] = {}
    for host, root in targets:
        groups.setdefault(os.path.realpath(root), []).append(host)
    for hosts in groups.values():
        if len(hosts) < 2:
            continue
        identities = {package_identity(materialize_plan(host)) for host in hosts}
        if len(identities) > 1:
            raise DiagnosticError("E_INSTALL_CONFLICT", family=tuple(sorted(hosts)))


def _print_json(value: Any, stream=None) -> None:
    out = sys.stdout if stream is None else stream
    out.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _envelope(
    *,
    command: str,
    results: list[dict[str, Any]],
    ok: bool | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Stable multi-target-first result document (#32).

    Always uses a ``results`` array (length 1 for single-target commands) so
    automation never has to special-case bare vs wrapped payloads.
    """

    if ok is None:
        ok = all(bool(item.get("ok", True)) for item in results) if results else True
    doc: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "command": command,
        "ok": bool(ok),
        "results": results,
    }
    for key, value in sorted(extra.items()):
        if value is not None:
            doc[key] = value
    return doc


def _print_hosts_human(report: dict[str, Any], stream=None) -> None:
    out = sys.stdout if stream is None else stream
    stream = out
    stream.write(f"Destination hosts: {report['host_count']}\n")
    stream.write(f"Full guide: {report.get('docs', 'docs/install-hosts.md')}\n\n")
    for pair in report.get("shared_root_pairs") or []:
        hosts = "+".join(pair.get("hosts") or [])
        stream.write(f"Shared-root warning ({hosts}): {pair.get('path')} — {pair.get('note')}\n")
    stream.write("\n")
    for rec in report.get("hosts") or []:
        stream.write(f"## {rec['host']} ({rec.get('display_name', '')})\n")
        defaults = rec.get("installer_defaults") or {}
        stream.write(f"  project: {defaults.get('project_rel')} → {defaults.get('project_root_resolved')}\n")
        stream.write(f"  global:  {defaults.get('global_rel')} → {defaults.get('global_root_resolved')}\n")
        layouts = rec.get("official_layouts") or {}
        if layouts.get("project"):
            stream.write(f"  layout:  {layouts['project']}\n")
        if layouts.get("global"):
            stream.write(f"  layout:  {layouts['global']}\n")
        for alt in rec.get("alternate_project_roots") or []:
            stream.write(f"  alt project: {alt}\n")
        for alt in rec.get("alternate_global_roots") or []:
            stream.write(f"  alt global:  {alt}\n")
        stream.write("  install:\n")
        for method in rec.get("install_methods") or []:
            stream.write(f"    - {method}\n")
        cmds = rec.get("installer_commands") or {}
        project_cmd = cmds.get("project")
        if isinstance(project_cmd, dict):
            if project_cmd.get("installed"):
                stream.write(f"  cmd: {project_cmd['installed']}\n")
            if project_cmd.get("source_checkout"):
                stream.write(f"  source_checkout: {project_cmd['source_checkout']}\n")
        elif project_cmd:
            stream.write(f"  cmd: {project_cmd}\n")
        stream.write(f"  activate: {rec.get('activation_help', '')}\n")
        for ex in rec.get("activation_examples") or []:
            stream.write(f"    e.g. {ex}\n")
        stream.write(f"  args: {rec.get('arguments_note', '')}\n")
        for caveat in rec.get("caveats") or []:
            stream.write(f"  caveat: {caveat}\n")
        docs = rec.get("official_docs") or []
        if docs:
            stream.write(f"  docs: {'; '.join(docs)}\n")
        stream.write(f"  packaging: {rec.get('evidence_level')} | live_ui: {rec.get('live_ui')}\n\n")


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        try:
            ns = parser.parse_args(list(argv) if argv is not None else None)
        except SystemExit as exit_error:
            # argparse prints usage prose; still return the structured diagnostic
            # contract for removed/unknown flags during the #32 transition.
            code = exit_error.code
            if code in (0, None):
                return 0
            return emit_diagnostic(DiagnosticError.invalid(), stream=sys.stderr)
        if ns.command == "quick-install":
            ns.command = "install"
            ns.scope = "project" if ns.project else "global"
        if (
            getattr(ns, "scope", None) == "project"
            and not getattr(ns, "project", None)
            and not getattr(ns, "root", None)
        ):
            raise DiagnosticError.invalid()
        if ns.command == "matrix":
            report = matrix_report()
            doc = _envelope(
                command="matrix",
                results=[report],
                ok=bool(report.get("ok")),
            )
            _print_json(doc)
            return 0 if report["ok"] else 7
        if ns.command == "hosts":
            selected = None if ns.host == "all" else _hosts(ns.host)
            report = hosts_report(
                project_dir=ns.project,
                home_dir=ns.home,
                hosts=selected,
            )
            if ns.json:
                doc = _envelope(
                    command="hosts",
                    results=[report],
                    ok=bool(report.get("ok", True)),
                )
                _print_json(doc)
            else:
                _print_hosts_human(report)
            return 0
        if ns.command == "recover":
            result = recover_root(ns.root)
            doc = _envelope(
                command="recover",
                results=[result],
                ok=bool(result.get("ok", True)),
            )
            _print_json(doc)
            return 0
        if ns.command == "audit-host":
            if ns.host == "all" or ns.host not in HOST_KEYS:
                raise DiagnosticError.invalid()
            if ns.scope == "project" and not ns.project and not ns.root:
                raise DiagnosticError.invalid()
            project_for_audit = ns.project
            if ns.scope == "global" and not project_for_audit:
                project_for_audit = os.getcwd()
            report = audit_host_report(
                host=ns.host,
                scope=ns.scope,
                project_dir=project_for_audit,
                home_dir=ns.home,
                root=ns.root,
            )
            doc = _envelope(
                command="audit-host",
                results=[report],
                ok=bool(report.get("ok", True)),
            )
            _print_json(doc)
            return 0 if report.get("ok", True) else 6
        hosts = _hosts(ns.host)
        targets = [
            (host, _root_for(host, ns.scope, ns.project, ns.home, ns.root))
            for host in hosts
        ]
        results: list[dict[str, Any]] = []
        dry_run = bool(getattr(ns, "dry_run", False))
        force = bool(getattr(ns, "force_with_backup", False))
        if ns.command == "install":
            _reject_divergent_shared_roots(targets)
            # #34: fail closed on known higher-precedence divergent shadows
            # before any mutation (and report scan on dry-run).
            project_for_scan = ns.project
            if ns.scope == "project" and not project_for_scan and not ns.root:
                raise DiagnosticError.invalid()
            if ns.scope == "global" and not project_for_scan:
                project_for_scan = os.getcwd()
            # Parse --sources before shadow scan so expanding a partial claim
            # still gates newly requested skills (#242 Codex P1).
            selected_sources = _parse_install_sources(getattr(ns, "sources", None))
            # Omitted/--sources all is plan-all-sources; do not fall back to a
            # partial claim's recorded set for the pre-install shadow gate.
            if selected_sources is None:
                shadow_sources = tuple(sorted(SOURCE_KEYS))
            else:
                shadow_sources = selected_sources
            discovery_by_host: dict[str, dict[str, Any]] = {}
            for host, root in targets:
                discovery_by_host[host] = require_no_blocking_shadow(
                    host=host,
                    selected_root=root,
                    project_dir=project_for_scan,
                    home_dir=ns.home,
                    selected_scope=ns.scope,
                    sources=shadow_sources,
                )
            results = install_multi_targets(
                targets,
                scope=ns.scope,
                dry_run=dry_run,
                force_with_backup=force,
                sources=selected_sources,
            )
            # Attach discovery + host identity to each result.
            for idx, (host, _root) in enumerate(targets):
                if idx < len(results) and isinstance(results[idx], dict):
                    results[idx] = {
                        **results[idx],
                        "host": host,
                        "discovery": discovery_by_host[host],
                    }
        else:
            for host, root in targets:
                if ns.command == "verify":
                    claim = claim_key(host=host, scope=ns.scope, root=root)
                    verified = verify_root(root, claim=claim)
                    project_for_verify = ns.project
                    if ns.scope == "global" and not project_for_verify:
                        project_for_verify = os.getcwd()
                    discovery = scan_skill_duplicates(
                        host=host,
                        selected_root=root,
                        project_dir=project_for_verify,
                        home_dir=ns.home,
                        selected_scope=ns.scope,
                    )
                    results.append(
                        {
                            **verified,
                            "host": host,
                            "discovery": {
                                "aggregate_status": discovery["aggregate_status"],
                                "aggregate_policy": discovery["aggregate_policy"],
                                "blocking_count": discovery["blocking_count"],
                                "warning_count": discovery["warning_count"],
                                "findings": discovery["findings"],
                            },
                        }
                    )
                elif ns.command == "uninstall":
                    results.append(
                        {
                            **uninstall_claim(
                                host=host,
                                scope=ns.scope,
                                root=root,
                                dry_run=dry_run,
                            ),
                            "host": host,
                        }
                    )
        doc = _envelope(
            command=ns.command,
            results=results,
            dry_run=dry_run if ns.command in {"install", "uninstall"} else None,
            scope=getattr(ns, "scope", None),
        )
        _print_json(doc)
        return 0
    except DiagnosticError as error:
        return emit_diagnostic(error, stream=sys.stderr)
    except (KeyboardInterrupt, BrokenPipeError):
        raise
    except Exception:
        return emit_diagnostic(DiagnosticError("E_INVARIANT"), stream=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
