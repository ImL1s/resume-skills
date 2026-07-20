#!/usr/bin/env python3
"""Deterministic self-verify for a checkout (no absolute home paths)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(argv: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(REPO),
        env=env or {**os.environ, "PYTHONPATH": str(REPO / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    print("repo", REPO)
    c = run([sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"])
    print("compileall", c.returncode)
    t = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"])
    print((t.stderr or t.stdout)[-400:])
    print("unittest", t.returncode)
    s = run([sys.executable, str(REPO / "scripts" / "portable-resume"), "self-check", "--json"])
    print(s.stdout.strip())
    print("self-check", s.returncode)
    m = run([sys.executable, str(REPO / "scripts" / "install-resume-skills"), "matrix", "--json"])
    matrix = json.loads(m.stdout) if m.returncode == 0 else {}
    print(
        "matrix",
        m.returncode,
        {
            "ok": matrix.get("ok"),
            "cell_count": matrix.get("cell_count"),
            "live_cells_supported": matrix.get("live_cells_supported"),
        },
    )
    fx = REPO / "tests" / "fixtures" / "claude" / "s-cla-01-ordered-parent-chain" / "root"
    lst = run(
        [
            sys.executable,
            str(REPO / "scripts" / "portable-resume"),
            "claude",
            "list",
            "--cwd",
            "/workspace/project",
            "--source-root",
            str(fx),
            "--json",
        ]
    )
    print("list", lst.returncode)
    sh = run(
        [
            sys.executable,
            str(REPO / "scripts" / "portable-resume"),
            "claude",
            "show",
            "latest",
            "--cwd",
            "/workspace/project",
            "--source-root",
            str(fx),
            "--format",
            "handoff",
        ]
    )
    print("show", sh.returncode, "untrusted", "untrusted" in (sh.stdout or "").lower())
    ok = all(
        x == 0
        for x in (
            c.returncode,
            t.returncode,
            s.returncode,
            m.returncode,
            lst.returncode,
            sh.returncode,
        )
    )
    print("OVERALL_SELF_VERIFY", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
