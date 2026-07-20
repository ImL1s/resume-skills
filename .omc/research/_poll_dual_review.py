#!/usr/bin/env python3
"""Poll dual-review report files for Verdict; kill via PID files only after timeout."""
from __future__ import annotations

import os
import re
import signal
import time
from pathlib import Path

REPO = Path("/Users/iml1s/Documents/mine/resume-skills")
RESEARCH = REPO / ".omc" / "research"
PID_DIR = Path("/tmp/dual-review-pids")
TIMEOUT_SEC = 12 * 60
POLL_SEC = 15

REPORTS = {
    "codex": RESEARCH / "dual-review-codex.md",
    "fable": RESEARCH / "dual-review-fable.md",
    "grok": RESEARCH / "dual-review-grok.md",
    "agy": RESEARCH / "dual-review-agy.md",
}

VERDICT_RE = re.compile(r"(?im)^\s*Verdict\s*[:：]\s*(.+)$")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_pid(name: str) -> int | None:
    p = PID_DIR / f"{name}.pid"
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def kill_pidfile(name: str) -> str:
    pid = read_pid(name)
    if pid is None:
        return f"{name}: no pidfile"
    if not pid_alive(pid):
        return f"{name}: already dead pid={pid}"
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        if pid_alive(pid):
            os.kill(pid, signal.SIGKILL)
            return f"{name}: SIGKILL pid={pid}"
        return f"{name}: SIGTERM pid={pid}"
    except ProcessLookupError:
        return f"{name}: gone pid={pid}"
    except Exception as e:
        return f"{name}: kill error {e}"


def extract_verdict(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    m = VERDICT_RE.search(text)
    if m:
        return m.group(1).strip()
    # also accept Chinese heading style
    if re.search(r"(?im)^\s*##?\s*Verdict\b", text) and "APPROVE" in text.upper():
        m2 = re.search(r"(?i)\b(APPROVE WITH MINOR FIXES|REQUEST CHANGES|APPROVE|REJECT)\b", text)
        if m2:
            return m2.group(1)
    return None


def main() -> None:
    start = time.time()
    names = [n for n in REPORTS if (PID_DIR / f"{n}.pid").exists() or REPORTS[n].exists()]
    # Always watch codex+fable; others if pid or file appears
    watch = {"codex", "fable"}
    for n in ("grok", "agy"):
        if (PID_DIR / f"{n}.pid").exists():
            watch.add(n)

    print(f"polling {sorted(watch)} for up to {TIMEOUT_SEC}s...")
    done: dict[str, str] = {}

    while time.time() - start < TIMEOUT_SEC:
        for name in list(watch):
            if name in done:
                continue
            v = extract_verdict(REPORTS[name])
            if v:
                done[name] = v
                print(f"DONE {name}: Verdict={v} size={REPORTS[name].stat().st_size}")
                continue
            pid = read_pid(name)
            if pid is not None and not pid_alive(pid):
                # process exited without Verdict yet — give a short grace then mark incomplete
                size = REPORTS[name].stat().st_size if REPORTS[name].exists() else 0
                if size > 0:
                    # re-check verdict once more after tiny wait
                    time.sleep(1)
                    v2 = extract_verdict(REPORTS[name])
                    if v2:
                        done[name] = v2
                        print(f"DONE {name}: Verdict={v2} size={REPORTS[name].stat().st_size}")
                        continue
                print(f"EXIT_NO_VERDICT {name} size={size}")
                done[name] = "NO_VERDICT"
        if all(n in done for n in watch):
            break
        elapsed = int(time.time() - start)
        pending = [n for n in watch if n not in done]
        sizes = {n: (REPORTS[n].stat().st_size if REPORTS[n].exists() else 0) for n in pending}
        print(f"t={elapsed}s pending={pending} sizes={sizes}")
        time.sleep(POLL_SEC)

    # Timeout kills
    timed_out = [n for n in watch if n not in done]
    kill_notes = []
    for n in timed_out:
        kill_notes.append(kill_pidfile(n))
        v = extract_verdict(REPORTS[n])
        done[n] = v if v else "TIMEOUT"
        print(f"TIMEOUT {n}: status={done[n]}")

    # Summary
    print("--- SUMMARY ---")
    blocked = []
    for name, path in REPORTS.items():
        if name not in watch and not path.exists():
            continue
        size = path.stat().st_size if path.exists() else 0
        verdict = done.get(name) or extract_verdict(path) or "MISSING"
        print(f"{name}: path={path} size={size} verdict={verdict}")
        if verdict in {"TIMEOUT", "NO_VERDICT", "MISSING", "BLOCKED"} or str(verdict).startswith("BLOCKED"):
            blocked.append(f"{name}: {verdict}")
        # also scan report for BLOCKED sections
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"(?im)^\s*#+\s*BLOCKED\b|\bBLOCKED\b", text) and "Verdict" not in text[:200]:
                blocked.append(f"{name}: report mentions BLOCKED")

    summary_path = RESEARCH / "dual-review-orchestrator-summary.md"
    lines = ["# Dual-review orchestrator summary", ""]
    for name, path in REPORTS.items():
        if name not in watch and not path.exists():
            continue
        size = path.stat().st_size if path.exists() else 0
        verdict = done.get(name) or extract_verdict(path) or "MISSING"
        lines.append(f"- **{name}**: `{path}` size={size} Verdict={verdict}")
    lines.append("")
    lines.append("## BLOCKED")
    if blocked:
        for b in blocked:
            lines.append(f"- {b}")
    else:
        lines.append("- (none)")
    if kill_notes:
        lines.append("")
        lines.append("## Timeout kills")
        for k in kill_notes:
            lines.append(f"- {k}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
