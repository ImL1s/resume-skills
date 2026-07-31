#!/usr/bin/env python3
"""Fail closed when a checkout reuses or misrepresents a published version."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume import __version__  # noqa: E402
from portable_resume.build_identity import latest_release  # noqa: E402
from portable_resume.version_state import (  # noqa: E402
    baseline_tag_errors,
    evaluate_version_state,
)
from git_build_identity import git_build_identity  # noqa: E402


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def _metadata_version() -> str:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def check(*, require_git: bool) -> dict[str, object]:
    identity = git_build_identity(repo_root=REPO, package_root=SRC / "portable_resume")
    baseline = latest_release(SRC / "portable_resume")
    head = _git("rev-parse", "--verify", "HEAD")
    head_sha = head.stdout.strip() if head.returncode == 0 else None
    tags: dict[str, str] = {}
    tag_list = _git("tag", "--list", "v[0-9]*.[0-9]*.[0-9]*")
    if tag_list.returncode == 0:
        for tag in tag_list.stdout.splitlines():
            resolved = _git("rev-list", "-n", "1", tag)
            if resolved.returncode == 0 and resolved.stdout.strip():
                tags[tag] = resolved.stdout.strip()
    report = evaluate_version_state(
        identity,
        baseline,
        tag_commits=tags,
        head_sha=head_sha,
    )
    errors = list(report["errors"])
    if tag_list.returncode == 0:
        errors.extend(
            baseline_tag_errors(
                identity,
                baseline,
                tag_commits=tags,
                head_sha=head_sha,
            )
        )
    try:
        metadata_version = _metadata_version()
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        metadata_version = ""
        errors.append("project metadata version is unreadable")
    if metadata_version != __version__:
        errors.append("pyproject and source versions differ")
    if require_git and (head_sha is None or tag_list.returncode != 0):
        errors.append("Git metadata is required but unavailable")
    if require_git and identity.get("commit_sha") != head_sha:
        errors.append("build identity is not bound to checked-out HEAD")
    report.update(
        {
            "ok": not errors,
            "metadata_version": metadata_version,
            "identity": identity,
            "latest_release_identity": baseline,
            "errors": errors,
        }
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-git", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = check(require_git=args.require_git)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif report["ok"]:
        print(
            "VERSION_STATE PASS "
            f"version={report['base_version']} state={report['state']}"
        )
    else:
        print("VERSION_STATE FAIL " + "; ".join(report["errors"]), file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
