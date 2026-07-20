#!/usr/bin/env python3
"""Install six host packages into an isolated project and probe installed hosts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/iml1s/Documents/mine/resume-skills")
OUT = REPO / ".omc" / "research" / "live-smoke-report.md"
ENV = {**os.environ, "PYTHONPATH": str(REPO / "src")}

HOSTS = ("claude", "codex", "cursor", "opencode", "antigravity", "grok")


def run(argv: list[str], env: dict[str, str] | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(REPO),
        env=env or ENV,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def main() -> int:
    lines: list[str] = ["# Live / installed-host smoke report", "", f"Date machine: {os.uname().sysname}", ""]
    tmp = Path(tempfile.mkdtemp(prefix="resume-live-"))
    home = tmp / "home"
    project = tmp / "project"
    home.mkdir()
    project.mkdir()
    lines.append(f"Isolated HOME={home}")
    lines.append(f"Isolated project={project}")
    lines.append("")

    # Install all hosts into project-scoped roots under isolated home where needed
    for host in HOSTS:
        cmd = [
            sys.executable,
            str(REPO / "scripts" / "install-resume-skills"),
            "install",
            "--host",
            host,
            "--scope",
            "project",
            "--project",
            str(project),
            "--home",
            str(home),
            "--json",
        ]
        # antigravity/codex may conflict on .agents/skills — use explicit unique roots
        if host in {"codex", "antigravity"}:
            root = project / "skills-roots" / host
            cmd = [
                sys.executable,
                str(REPO / "scripts" / "install-resume-skills"),
                "install",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                str(project),
                "--home",
                str(home),
                "--root",
                str(root),
                "--json",
            ]
        proc = run(cmd)
        ok = proc.returncode == 0
        lines.append(f"## Install `{host}`")
        lines.append(f"- exit: {proc.returncode}")
        if ok:
            try:
                payload = json.loads(proc.stdout)
                lines.append(f"- ok: {payload.get('ok')}")
            except json.JSONDecodeError:
                lines.append(f"- stdout head: {proc.stdout[:200]!r}")
        else:
            lines.append(f"- stderr: {proc.stderr[:400]}")
        lines.append("")

    # Verify each install
    for host in HOSTS:
        if host in {"codex", "antigravity"}:
            root = project / "skills-roots" / host
            cmd = [
                sys.executable,
                str(REPO / "scripts" / "install-resume-skills"),
                "verify",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                str(project),
                "--home",
                str(home),
                "--root",
                str(root),
                "--json",
            ]
        else:
            cmd = [
                sys.executable,
                str(REPO / "scripts" / "install-resume-skills"),
                "verify",
                "--host",
                host,
                "--scope",
                "project",
                "--project",
                str(project),
                "--home",
                str(home),
                "--json",
            ]
        proc = run(cmd)
        lines.append(f"## Verify `{host}` → exit {proc.returncode}")
        lines.append("")

    # Probe host CLIs for skill discovery (best-effort; not full UI)
    probes = {
        "claude": ["claude", "--version"],
        "codex": ["codex", "--version"],
        "opencode": ["opencode", "--version"],
        "antigravity": ["agy", "--version"],
        "grok": ["grok", "--version"],
        "cursor": ["cursor-agent", "--version"],
    }
    lines.append("## Host binary presence")
    for host, argv in probes.items():
        path = shutil.which(argv[0])
        if not path:
            lines.append(f"- `{host}`: binary missing")
            continue
        proc = run(argv, env=os.environ.copy(), timeout=30)
        lines.append(f"- `{host}`: HAVE `{path}` exit={proc.returncode} out={(proc.stdout or proc.stderr).strip()[:120]!r}")
    lines.append("")

    # Structural live packaging proof: 36 skills materialize under installed roots
    cell = 0
    for host in HOSTS:
        if host in {"codex", "antigravity"}:
            root = project / "skills-roots" / host
        else:
            # resolve via catalog
            from portable_resume.install.catalog import resolve_skill_root

            root = Path(
                resolve_skill_root(
                    host=host,
                    scope="project",
                    project_dir=str(project),
                    home_dir=str(home),
                )
            )
        for source in HOSTS:  # same six keys
            skill = root / f"resume-{source}" / "SKILL.md"
            if skill.is_file():
                cell += 1
            else:
                lines.append(f"- MISSING skill file: {skill}")
    lines.append(f"## Materialized skill cells counted: {cell}/36")
    lines.append("")

    # Request→handoff via installed run_reader (filesystem installed-runtime proof)
    fixture = REPO / "tests" / "fixtures" / "claude" / "s-cla-01-ordered-parent-chain" / "root"
    root_claude = Path(
        __import__("portable_resume.install.catalog", fromlist=["resolve_skill_root"]).resolve_skill_root(
            host="claude",
            scope="project",
            project_dir=str(project),
            home_dir=str(home),
        )
    )
    runner = root_claude / "resume-claude" / "scripts" / "run_reader.py"
    req = tmp / "req.json"
    req.write_text(
        json.dumps(
            {
                "schema_version": "portable-resume/request-v1",
                "source": "claude",
                "action": "show",
                "resume_ref": "latest",
                "cwd": "/workspace/project",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = run(
        [
            sys.executable,
            str(runner),
            "--request-file",
            str(req),
            "--format",
            "handoff",
            "--source-root",
            str(fixture),
        ],
        env=env,
        timeout=60,
    )
    lines.append("## Installed runtime handoff (claude skill → fixture)")
    lines.append(f"- exit: {proc.returncode}")
    lines.append(f"- untrusted marker: {'yes' if 'untrusted' in (proc.stdout or '').lower() else 'no'}")
    lines.append(f"- stdout head: {(proc.stdout or '')[:240]!r}")
    lines.append(f"- stderr head: {(proc.stderr or '')[:240]!r}")
    lines.append("")
    lines.append("## Live UI activation")
    lines.append("- Full interactive host skill picker activation: **not-run** in this automated harness.")
    lines.append("- Binaries present are version-probed only; natural-language activation remains model-mediated.")
    lines.append("")
    lines.append("## Verdict")
    if cell == 36 and proc.returncode == 0 and "untrusted" in (proc.stdout or "").lower():
        lines.append("- Packaging+installed-runtime smoke: **PASS**")
        lines.append("- Host UI live activation: **not-run** (honest)")
    else:
        lines.append("- Packaging+installed-runtime smoke: **FAIL or partial** — see above")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT)
    print(f"cells={cell} handoff_exit={proc.returncode}")
    return 0 if cell == 36 else 1


if __name__ == "__main__":
    # ensure import path
    sys.path.insert(0, str(REPO / "src"))
    raise SystemExit(main())
