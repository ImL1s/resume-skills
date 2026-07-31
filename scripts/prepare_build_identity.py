#!/usr/bin/env python3
"""Pin one Git-aware build identity before any artifact bytes are produced."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for candidate in (SRC, SCRIPTS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from build_artifact_identity import write_external_identity  # noqa: E402
from git_build_identity import git_build_identity  # noqa: E402
from portable_resume.build_identity import assert_identity_matches_package  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--require-release", action="store_true")
    parser.add_argument("--json", action="store_true")
    namespace = parser.parse_args(argv)
    try:
        identity = git_build_identity(
            repo_root=REPO,
            package_root=SRC / "portable_resume",
        )
        assert_identity_matches_package(
            identity,
            package_root=SRC / "portable_resume",
        )
        if (
            namespace.expected_commit is not None
            and identity.get("commit_sha") != namespace.expected_commit
        ):
            raise ValueError("build identity commit differs from the expected commit")
        if namespace.require_release and (
            identity.get("release_channel") != "release"
            or identity.get("dirty") is not False
        ):
            raise ValueError("release build identity must be exact and clean")
        output = Path(namespace.output).resolve()
        digest = write_external_identity(output, identity)
    except (OSError, ValueError) as error:
        print(f"BUILD_IDENTITY_PREPARE FAIL {type(error).__name__}", file=sys.stderr)
        return 1
    report = {
        "schema_version": "portable-resume/build-identity-pin-v1",
        "path": str(output),
        "sha256": digest,
        "build_identity": identity,
        "ok": True,
    }
    if namespace.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"BUILD_IDENTITY_PREPARE PASS sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
