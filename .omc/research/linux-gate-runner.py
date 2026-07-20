#!/usr/bin/env python3
"""Attempt Linux clean-runner gate; record honest failure if unavailable."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/iml1s/Documents/mine/resume-skills")
OUT = REPO / ".omc" / "research" / "linux-gate-report.md"


def main() -> int:
    lines = ["# Linux peer OS gate report", "", f"Host OS: {platform.platform()}", ""]
    docker = shutil.which("docker")
    lines.append(f"docker binary: {docker or 'missing'}")
    linux_ran = False
    if docker:
        info = subprocess.run([docker, "info"], capture_output=True, text=True, check=False)
        lines.append(f"docker info exit: {info.returncode}")
        if info.returncode == 0:
            # run suite inside python linux container with bind mount
            cmd = [
                docker,
                "run",
                "--rm",
                "-v",
                f"{REPO}:/work",
                "-w",
                "/work",
                "-e",
                "PORTABLE_RESUME_EXPECT_OS=linux",
                "-e",
                "PYTHONPATH=src",
                "python:3.12-slim",
                "bash",
                "-lc",
                "python3 -m compileall -q src scripts tests && python3 -m unittest discover -s tests -q && python3 scripts/portable-resume self-check --json && python3 scripts/install-resume-skills matrix --json",
            ]
            lines.append("$ " + " ".join(cmd))
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
            lines.append(f"container exit: {proc.returncode}")
            lines.append("```")
            lines.append((proc.stdout or "")[-4000:])
            lines.append((proc.stderr or "")[-2000:])
            lines.append("```")
            linux_ran = proc.returncode == 0
        else:
            lines.append("docker daemon unavailable; stderr head:")
            lines.append((info.stderr or info.stdout or "")[:500])
    else:
        lines.append("No docker binary.")

    lines.append("")
    if linux_ran:
        lines.append("## Verdict: Linux deterministic gate **PASS**")
        lines.append("AC-18 peer OS evidence captured.")
    else:
        lines.append("## Verdict: Linux deterministic gate **NOT RUN / FAILED TO START**")
        lines.append("Do **not** claim AC-18 dual-OS release. macOS deterministic bar remains separately proven.")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT.read_text())
    return 0 if linux_ran else 2


if __name__ == "__main__":
    raise SystemExit(main())
