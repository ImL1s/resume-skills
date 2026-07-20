#!/usr/bin/env python3
"""Launch dual-review CLIs in parallel; PID files only (no pkill -f)."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path("/Users/iml1s/Documents/mine/resume-skills")
RESEARCH = REPO / ".omc" / "research"
SAFE = RESEARCH / "dual-review-brief-safe.md"
EMPTY_MCP = RESEARCH / "empty.json"
PID_DIR = Path("/tmp/dual-review-pids")
PID_DIR.mkdir(parents=True, exist_ok=True)

os.environ["OMG_ALLOW_EXTERNAL_CLI"] = "1"
os.environ["PWD"] = str(REPO)
os.chdir(REPO)

brief = SAFE.read_text(encoding="utf-8")

PROMPT_BODY = f"""You are an independent code reviewer.

Read ONLY this brief file first:
{SAFE}

Brief contents (for convenience; prefer re-reading the file if needed):
---
{brief}
---

Instructions:
1. READ-ONLY review of the working tree at {REPO}. Do NOT edit product code.
2. Follow all review dimensions and required verify commands in the brief.
3. Write your full report in 繁體中文 to the assigned output path below.
4. Output format MUST include a line starting with "Verdict:" using one of:
   APPROVE | APPROVE WITH MINOR FIXES | REQUEST CHANGES | REJECT
5. Cover Critical / Important / Minor / verified commands / residual risks.

Assigned output path:
"""


def which(name: str) -> str | None:
    return shutil.which(name)


def start(name: str, cmd: list[str], out_log: Path) -> int | None:
    log_f = out_log.open("w", encoding="utf-8")
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(REPO),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
            start_new_session=True,
        )
    except FileNotFoundError as e:
        log_f.write(f"LAUNCH_ERROR: {e}\n")
        log_f.close()
        print(f"{name}: BLOCKED launch FileNotFoundError: {e}")
        return None
    except OSError as e:
        log_f.write(f"LAUNCH_ERROR: {e}\n")
        log_f.close()
        print(f"{name}: BLOCKED launch OSError: {e}")
        return None
    pid_path = PID_DIR / f"{name}.pid"
    pid_path.write_text(str(p.pid), encoding="utf-8")
    print(f"{name}: launched pid={p.pid} log={out_log} pidfile={pid_path}")
    return p.pid


launched: dict[str, int] = {}
status: dict[str, str] = {}

# 1) Codex
codex = which("codex")
if codex:
    report = RESEARCH / "dual-review-codex.md"
    prompt = PROMPT_BODY + f"{report}\nWrite the report file yourself. Do not modify lib/ or product sources.\n"
    cmd = [
        codex,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "-s",
        "workspace-write",
        "-m",
        "gpt-5.6-sol",
        "-c",
        "model_reasoning_effort=max",
        "--cd",
        str(REPO),
        prompt,
    ]
    pid = start("codex", cmd, RESEARCH / "dual-review-codex.stdout.log")
    if pid:
        launched["codex"] = pid
        status["codex"] = "running"
    else:
        status["codex"] = "BLOCKED"
else:
    status["codex"] = "BLOCKED (codex not found)"
    print("codex: BLOCKED not found")

# 2) Claude Fable
claude = which("claude")
if claude:
    report = RESEARCH / "dual-review-fable.md"
    prompt = PROMPT_BODY + f"{report}\nUse the Write tool to write the report. Do not modify product sources.\n"
    cmd = [
        claude,
        "-p",
        prompt,
        "--model",
        "claude-fable-5",
        "--effort",
        "xhigh",
        "--dangerously-skip-permissions",
        "--strict-mcp-config",
        "--mcp-config",
        str(EMPTY_MCP),
        "--no-session-persistence",
    ]
    pid = start("fable", cmd, RESEARCH / "dual-review-fable.stdout.log")
    if pid:
        launched["fable"] = pid
        status["fable"] = "running"
    else:
        status["fable"] = "BLOCKED"
else:
    status["fable"] = "BLOCKED (claude not found)"
    print("fable: BLOCKED claude not found")

# 3) Grok (optional)
grok = which("grok")
if grok:
    report = RESEARCH / "dual-review-grok.md"
    prompt = PROMPT_BODY + f"{report}\nWrite the report file yourself. Do not modify product sources.\n"
    cmd = [grok, "-p", prompt]
    pid = start("grok", cmd, RESEARCH / "dual-review-grok.stdout.log")
    if pid:
        launched["grok"] = pid
        status["grok"] = "running"
    else:
        status["grok"] = "BLOCKED"
else:
    status["grok"] = "SKIPPED (grok not found)"
    print("grok: SKIPPED not found")

# 4) agy (optional)
agy = which("agy")
if agy:
    report = RESEARCH / "dual-review-agy.md"
    prompt = PROMPT_BODY + f"{report}\nWrite the report file yourself. Do not modify product sources.\n"
    cmd = [agy, "-p", prompt]
    pid = start("agy", cmd, RESEARCH / "dual-review-agy.stdout.log")
    if pid:
        launched["agy"] = pid
        status["agy"] = "running"
    else:
        status["agy"] = "BLOCKED"
else:
    status["agy"] = "SKIPPED (agy not found)"
    print("agy: SKIPPED not found")

meta = RESEARCH / "dual-review-launch-meta.txt"
lines = [f"launched_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", f"repo={REPO}", f"safe={SAFE}"]
for k, v in status.items():
    lines.append(f"{k}: {v}" + (f" pid={launched[k]}" if k in launched else ""))
meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("---")
print(meta.read_text(encoding="utf-8"))
