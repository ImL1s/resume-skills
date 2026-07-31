#!/usr/bin/env python3
"""Fail-closed release metadata and Git tag validation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SEMVER_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
VERSION_ASSIGNMENT = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
DEVELOPMENT_VERSION = re.compile(r"\.dev\d+(?:\+|$)")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def _versions() -> tuple[str, str]:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = str(project["project"]["version"])
    source = (REPO / "src" / "portable_resume" / "__init__.py").read_text(
        encoding="utf-8"
    )
    match = VERSION_ASSIGNMENT.search(source)
    if match is None:
        raise ValueError("source version assignment missing")
    return pyproject_version, match.group(1)


def validate_release(
    *,
    tag: str,
    require_git: bool,
    main_ref: str,
) -> dict[str, Any]:
    errors: list[str] = []
    if SEMVER_TAG.fullmatch(tag) is None:
        errors.append("tag must be strict vMAJOR.MINOR.PATCH")

    try:
        metadata_version, source_version = _versions()
    except (KeyError, OSError, tomllib.TOMLDecodeError, ValueError):
        metadata_version = source_version = ""
        errors.append("version metadata is unreadable")

    if metadata_version != source_version:
        errors.append("pyproject and source versions differ")
    if source_version and DEVELOPMENT_VERSION.search(source_version):
        errors.append("development versions cannot be released")
    expected_tag = f"v{source_version}" if source_version else ""
    if tag != expected_tag:
        errors.append("tag does not match package version")

    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    if source_version and re.search(
        rf"^## \[{re.escape(source_version)}\](?:\s|$)",
        changelog,
        re.MULTILINE,
    ) is None:
        errors.append("CHANGELOG release heading is missing")

    git_evidence: dict[str, Any] = {"checked": False}
    if require_git:
        git_evidence["checked"] = True
        tag_type = _git("cat-file", "-t", f"refs/tags/{tag}")
        if tag_type.returncode != 0 or tag_type.stdout.strip() != "tag":
            errors.append("release tag must exist and be annotated")

        head = _git("rev-parse", "HEAD")
        tagged = _git("rev-list", "-n", "1", tag)
        head_sha = head.stdout.strip() if head.returncode == 0 else ""
        tag_sha = tagged.stdout.strip() if tagged.returncode == 0 else ""
        git_evidence.update({"head_sha": head_sha, "tag_sha": tag_sha})
        if not head_sha or head_sha != tag_sha:
            errors.append("annotated tag must resolve to checked-out HEAD")

        main = _git("rev-parse", "--verify", f"{main_ref}^{{commit}}")
        main_sha = main.stdout.strip() if main.returncode == 0 else ""
        git_evidence["main_sha"] = main_sha
        if not main_sha:
            errors.append("protected main reference is unavailable")
        elif tag_sha:
            ancestor = _git("merge-base", "--is-ancestor", tag_sha, main_sha)
            if ancestor.returncode != 0:
                errors.append("release commit is not reachable from main")

        status = _git("status", "--porcelain")
        if status.returncode != 0 or status.stdout.strip():
            errors.append("tracked checkout must be clean")

    identity: dict[str, Any] | None = None
    try:
        src = str(REPO / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from git_build_identity import git_build_identity

        identity = git_build_identity(
            repo_root=REPO,
            package_root=REPO / "src" / "portable_resume",
            base_version=source_version,
        )
        if require_git and identity["release_channel"] != "release":
            errors.append("release checkout does not have a clean exact-tag identity")
    except (ImportError, OSError, ValueError):
        errors.append("build identity is unreadable")

    return {
        "schema_version": "portable-resume/release-check-v1",
        "ok": not errors,
        "tag": tag,
        "version": source_version,
        "metadata_version": metadata_version,
        "changelog": "present" if not any("CHANGELOG" in item for item in errors) else "missing",
        "git": git_evidence,
        "build_identity": identity,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--require-git", action="store_true")
    parser.add_argument("--json", action="store_true")
    namespace = parser.parse_args(argv)
    report = validate_release(
        tag=namespace.tag,
        require_git=namespace.require_git,
        main_ref=namespace.main_ref,
    )
    if namespace.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"RELEASE_CHECK PASS tag={report['tag']} version={report['version']}")
    else:
        print("RELEASE_CHECK FAIL " + "; ".join(report["errors"]), file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
