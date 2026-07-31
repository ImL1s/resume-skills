#!/usr/bin/env python3
"""Deterministic self-verify for a checkout (no absolute home paths).

Stages are named and selectable via ``--profile`` / ``--only`` so local and CI
can share one source of truth without re-running the same expensive work twice
in a single matrix cell (issue #67).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]

# Closed allowlist of stage names (unknown names fail closed).
STAGE_NAMES = (
    "compile",
    "version_state",
    "docs",
    "secrets",
    "unit",
    "packaging",
    "reader_self_check",
    "installer_matrix",
    "fixture_list_show",
)

PROFILES: dict[str, tuple[str, ...]] = {
    # Comprehensive pre-commit verification (docs + secrets + suite).
    "local": STAGE_NAMES,
    # Per OS/Python matrix cell: interpreter-sensitive work only.
    "ci-compat": (
        "compile",
        "unit",
        "reader_self_check",
        "installer_matrix",
        "fixture_list_show",
    ),
    # Once per push/PR: version-independent quality gates.
    "ci-quality": ("version_state", "docs", "secrets"),
}


def run(argv: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(REPO),
        env=env or {**os.environ, "PYTHONPATH": str(REPO / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def _stage_compile() -> tuple[int, str]:
    completed = run([sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"])
    return completed.returncode, (completed.stderr or completed.stdout or "")[-400:]


def _stage_version_state() -> tuple[int, str]:
    completed = run(
        [
            sys.executable,
            str(REPO / "scripts" / "check_version_state.py"),
            "--require-git",
            "--json",
        ]
    )
    return completed.returncode, (completed.stdout or completed.stderr or "").strip()


def _stage_docs() -> tuple[int, str]:
    completed = run([sys.executable, str(REPO / "scripts" / "check_docs.py"), "--json"])
    return completed.returncode, (completed.stdout or "").strip()


def _stage_secrets() -> tuple[int, str]:
    completed = run([sys.executable, str(REPO / "scripts" / "check_secrets.py")])
    tail = ((completed.stdout or "") + (completed.stderr or ""))[-400:]
    return completed.returncode, tail.strip()


def _stage_unit() -> tuple[int, str]:
    details: list[str] = []
    for suite in ("adapters", "e2e", "integration", "security", "unit"):
        completed = run(
            [sys.executable, "-m", "unittest", "discover", "-s", f"tests/{suite}", "-q"]
        )
        details.append(completed.stderr or completed.stdout or "")
        if completed.returncode != 0:
            return completed.returncode, "".join(details)[-400:]
    return 0, "".join(details)[-400:]


def _stage_packaging() -> tuple[int, str]:
    completed = run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/packaging", "-q"]
    )
    return completed.returncode, (completed.stderr or completed.stdout or "")[-400:]


def _stage_reader_self_check() -> tuple[int, str]:
    completed = run(
        [sys.executable, str(REPO / "scripts" / "portable-resume"), "self-check", "--json"]
    )
    return completed.returncode, (completed.stdout or "").strip()


def _stage_installer_matrix() -> tuple[int, str]:
    completed = run(
        [sys.executable, str(REPO / "scripts" / "install-resume-skills"), "matrix"]
    )
    if completed.returncode != 0:
        return completed.returncode, (completed.stderr or completed.stdout or "")[-400:]
    matrix = json.loads(completed.stdout)
    # #32: install-result-v1 wraps matrix in results[]
    if isinstance(matrix, dict) and matrix.get("schema_version") == "portable-resume/install-result-v1":
        results = matrix.get("results") or []
        matrix = results[0] if results else {}
    summary = {
        "ok": matrix.get("ok"),
        "cell_count": matrix.get("cell_count"),
        "live_cells_supported": matrix.get("live_cells_supported"),
    }
    return completed.returncode, json.dumps(summary, sort_keys=True)


def _stage_fixture_list_show() -> tuple[int, str]:
    fixture = (
        REPO
        / "tests"
        / "fixtures"
        / "claude"
        / "s-cla-01-ordered-parent-chain"
        / "root"
    )
    list_run = run(
        [
            sys.executable,
            str(REPO / "scripts" / "portable-resume"),
            "claude",
            "list",
            "--cwd",
            "/workspace/project",
            "--source-root",
            str(fixture),
            "--json",
        ]
    )
    show_run = run(
        [
            sys.executable,
            str(REPO / "scripts" / "portable-resume"),
            "claude",
            "show",
            "latest",
            "--cwd",
            "/workspace/project",
            "--source-root",
            str(fixture),
            "--format",
            "handoff",
        ]
    )
    code = 0 if list_run.returncode == 0 and show_run.returncode == 0 else 1
    note = (
        f"list={list_run.returncode} show={show_run.returncode} "
        f"untrusted={'untrusted' in (show_run.stdout or '').lower()}"
    )
    return code, note


STAGE_RUNNERS: dict[str, Callable[[], tuple[int, str]]] = {
    "compile": _stage_compile,
    "version_state": _stage_version_state,
    "docs": _stage_docs,
    "secrets": _stage_secrets,
    "unit": _stage_unit,
    "packaging": _stage_packaging,
    "reader_self_check": _stage_reader_self_check,
    "installer_matrix": _stage_installer_matrix,
    "fixture_list_show": _stage_fixture_list_show,
}


def resolve_stages(*, profile: str | None, only: list[str] | None) -> list[str]:
    if only:
        unknown = [name for name in only if name not in STAGE_NAMES]
        if unknown:
            raise SystemExit(f"unknown stage(s): {', '.join(unknown)}")
        # Preserve allowlist order, not CLI order, for deterministic reports.
        selected = [name for name in STAGE_NAMES if name in set(only)]
        if not selected:
            raise SystemExit("no stages selected")
        return selected
    if profile is None:
        profile = "local"
    if profile not in PROFILES:
        raise SystemExit(
            f"unknown profile: {profile!r} (choose from {', '.join(sorted(PROFILES))})"
        )
    return list(PROFILES[profile])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=None,
        help="named stage set (default: local when --only is omitted)",
    )
    parser.add_argument(
        "--only",
        action="append",
        dest="only",
        metavar="STAGE",
        help="run only named stage(s); may be repeated; closed allowlist",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable stage results on stdout",
    )
    args = parser.parse_args(argv)
    if args.profile is not None and args.only:
        raise SystemExit("use either --profile or --only, not both")

    stages = resolve_stages(profile=args.profile, only=args.only)
    print("repo", REPO)
    print("profile", args.profile or ("only" if args.only else "local"))
    print("stages", " ".join(stages))

    results: list[dict[str, object]] = []
    overall_ok = True
    for name in stages:
        started = time.monotonic()
        code, detail = STAGE_RUNNERS[name]()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        ok = code == 0
        overall_ok = overall_ok and ok
        results.append(
            {
                "stage": name,
                "ok": ok,
                "exit_code": code,
                "elapsed_ms": elapsed_ms,
                "detail": detail[:2000],
            }
        )
        if name == "version_state":
            print(detail)
            print("version-state", code)
        elif name == "docs":
            print(detail)
            print("docs", code)
        elif name == "unit":
            print(detail)
            print("unittest", code)
        elif name == "packaging":
            print(detail)
            print("packaging", code)
        elif name == "reader_self_check":
            print(detail)
            print("self-check", code)
        elif name == "installer_matrix":
            print("matrix", code, detail)
        elif name == "fixture_list_show":
            print("fixture", detail)
        elif name == "secrets":
            print("secrets", code)
            if detail:
                print(detail)
        else:
            print(name, code)

    print("OVERALL_SELF_VERIFY", "PASS" if overall_ok else "FAIL")
    if args.json:
        report = {
            "schema_version": "portable-resume/self-verify-v1",
            "ok": overall_ok,
            "profile": args.profile or ("only" if args.only else "local"),
            "stages": results,
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
