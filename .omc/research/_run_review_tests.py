#!/usr/bin/env python3
"""One-shot compile + unittest runner for dual-review evidence (no product edits)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "unittest-tail.txt"
os.chdir(REPO)
env = {**os.environ, "PYTHONPATH": str(REPO / "src")}

results: list[str] = []
compile_p = subprocess.run(
    [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"],
    cwd=str(REPO),
    capture_output=True,
    text=True,
    env=env,
    check=False,
)
results.append(f"compileall_rc={compile_p.returncode}")
if compile_p.stderr:
    results.append("compileall_stderr=" + compile_p.stderr[:2000])

unit = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    cwd=str(REPO),
    capture_output=True,
    text=True,
    env=env,
    check=False,
)
combined = (unit.stdout or "") + (unit.stderr or "")
lines = combined.splitlines()
tail = "\n".join(lines[-40:])
results.append(f"unittest_rc={unit.returncode}")
results.append("---- tail ----")
results.append(tail)
# also count
ok = sum(1 for line in lines if line.endswith(" ... ok"))
fail = sum(1 for line in lines if " ... FAIL" in line or " ... ERROR" in line)
results.append(f"ok_count={ok} fail_or_error_count={fail}")
OUT.write_text("\n".join(results) + "\n", encoding="utf-8")
print("\n".join(results))
raise SystemExit(0 if compile_p.returncode == 0 and unit.returncode == 0 else 1)
