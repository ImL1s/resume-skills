"""Installer CLI: install / verify / uninstall / matrix / recover."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Sequence

from ..diagnostics import DiagnosticError, SOURCE_KEYS, emit_diagnostic
from .catalog import HOST_KEYS, hosts_report, resolve_skill_root
from .transaction import (
    execute_install,
    matrix_report,
    plan_install,
    recover_root,
    uninstall_claim,
    verify_root,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="install-resume-skills")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("install", "verify", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--host", required=True, help="host key or 'all'")
        p.add_argument("--scope", choices=("project", "global"), required=True)
        p.add_argument("--project")
        p.add_argument("--root", help="explicit skill root override")
        p.add_argument("--home", default=os.path.expanduser("~"))
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--json", action="store_true")
        if name == "install":
            p.add_argument("--force-with-backup", action="store_true")

    m = sub.add_parser("matrix")
    m.add_argument("--json", action="store_true")

    h = sub.add_parser(
        "hosts",
        help="list each destination host's skill roots, install methods, and activation notes",
    )
    h.add_argument("--host", default="all", help="host key or 'all' (default)")
    h.add_argument("--project", default=None, help="resolve project roots against this path")
    h.add_argument("--home", default=os.path.expanduser("~"))
    h.add_argument("--json", action="store_true")

    r = sub.add_parser("recover")
    r.add_argument("--root", required=True)
    r.add_argument("--json", action="store_true")

    return parser


def _hosts(value: str) -> list[str]:
    if value == "all":
        return sorted(HOST_KEYS)
    if value not in HOST_KEYS:
        raise DiagnosticError.invalid()
    return [value]


def _root_for(host: str, scope: str, project: str | None, home: str, override: str | None) -> str:
    if override:
        return os.path.realpath(override)
    return resolve_skill_root(host=host, scope=scope, project_dir=project, home_dir=home)


def _print(value: Any, *, as_json: bool, stream=None) -> None:
    out = sys.stdout if stream is None else stream
    if as_json:
        out.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    else:
        out.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


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
        if cmds.get("project"):
            stream.write(f"  cmd: {cmds['project']}\n")
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
        ns = parser.parse_args(list(argv) if argv is not None else None)
        if ns.command == "matrix":
            report = matrix_report()
            _print(report, as_json=True)
            return 0 if report["ok"] else 7
        if ns.command == "hosts":
            selected = None if ns.host == "all" else _hosts(ns.host)
            report = hosts_report(
                project_dir=ns.project,
                home_dir=ns.home,
                hosts=selected,
            )
            if ns.json:
                _print(report, as_json=True)
            else:
                _print_hosts_human(report)
            return 0
        if ns.command == "recover":
            result = recover_root(ns.root)
            _print(result, as_json=bool(ns.json) or True)
            return 0
        results = []
        for host in _hosts(ns.host):
            root = _root_for(host, ns.scope, ns.project, ns.home, ns.root)
            if ns.command == "install":
                plan = plan_install(
                    host=host,
                    scope=ns.scope,
                    root=root,
                    dry_run=ns.dry_run,
                    force_with_backup=ns.force_with_backup,
                )
                results.append(execute_install(plan, force_with_backup=ns.force_with_backup))
            elif ns.command == "verify":
                results.append(verify_root(root))
            elif ns.command == "uninstall":
                results.append(
                    uninstall_claim(host=host, scope=ns.scope, root=root, dry_run=ns.dry_run)
                )
        payload: Any = results[0] if len(results) == 1 else {"results": results}
        _print(payload, as_json=True)
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
