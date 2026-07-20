#!/usr/bin/env python3
"""Fail if tracked product tree looks like it contains secrets or local home paths.

Synthetic credential *shapes* inside unit tests (built at runtime for redaction
tests) are allowed. Hard-coded home paths and real-looking keys in product
code/docs are not.

Scans `git ls-files` only (not git history). Release checklist may still run
gitleaks against history separately.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Product/docs must not contain these at all.
PRODUCT_FORBIDDEN = [
    (re.compile(r"/Users/[A-Za-z][A-Za-z0-9._-]{1,32}/"), "absolute macOS home path"),
    (re.compile(r"/home/[A-Za-z][A-Za-z0-9._-]{1,32}/"), "absolute Linux home path"),
    (re.compile(r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----"), "private key PEM"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub classic token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"), "Slack token"),
    (re.compile(r"hooks\.slack\.com/services/[A-Za-z0-9/]+"), "Slack webhook"),
]

# High-risk shapes; allowlisted test files may contain synthetic shapes for redaction tests.
# Pattern breadth matches runtime sanitize (sk- may include -/_).
SENSITIVE_SHAPES = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id shape"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "OpenAI-like secret shape"),
    (
        re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
        "assigned secret-like value",
    ),
]

# Relative paths allowed to embed synthetic secret *shapes* for redaction unit tests.
SENSITIVE_ALLOWLIST = frozenset(
    {
        "tests/unit/test_sanitize_handoff.py",
    }
)

SKIP_SUFFIX = {".sqlite", ".vscdb", ".zst", ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def tracked_files() -> list[str]:
    return subprocess.check_output(["git", "ls-files"], text=True).splitlines()


def main() -> int:
    hits: list[str] = []
    for rel in tracked_files():
        path = Path(rel)
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIX:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        under_tests = rel.startswith("tests/")
        for pat, label in PRODUCT_FORBIDDEN:
            if pat.search(text):
                hits.append(f"{rel}: {label}")
        if under_tests and rel in SENSITIVE_ALLOWLIST:
            continue
        if under_tests:
            # tests/ still scanned for SENSITIVE_SHAPES except allowlisted redaction fixtures
            for pat, label in SENSITIVE_SHAPES:
                if pat.search(text):
                    hits.append(f"{rel}: {label}")
            continue
        for pat, label in SENSITIVE_SHAPES:
            if pat.search(text):
                hits.append(f"{rel}: {label}")
    if hits:
        print("SECRET/PATH GATE FAILED:")
        for hit in hits[:80]:
            print(" -", hit)
        return 1
    print("SECRET/PATH GATE CLEAN")
    print(f"scanned_tracked_files={len(tracked_files())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
