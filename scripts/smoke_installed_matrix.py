#!/usr/bin/env python3
"""36-cell installed skill runner smoke (not host UI NL activation).

For each destination host and each source skill:
  1. install package into a temp project skill root
  2. run the installed resume-<source>/scripts/run_reader.py list + show
     against a synthetic fixture (source_root)

Exit 0 only when all 36 cells pass. Writes JSON summary to stdout with --json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
HOSTS = ("claude", "codex", "cursor", "opencode", "antigravity", "grok")
SOURCES = ("claude", "codex", "cursor", "opencode", "antigravity", "grok")

FIXTURES: dict[str, tuple[str, str]] = {
    "claude": (
        "tests/fixtures/claude/s-cla-01-ordered-parent-chain/root",
        "/workspace/project",
    ),
    "codex": (
        "tests/fixtures/codex/s-cod-01-state-generation-selection/root",
        "/workspace/project",
    ),
    "cursor": (
        "tests/fixtures/cursor/s-cur-01-cli-cwd-hash/root",
        "/workspace/project",
    ),
    "opencode": (
        "tests/fixtures/opencode/s-ope-01/root",
        "/workspace/project",
    ),
    "antigravity": (
        "tests/fixtures/antigravity/s-ant-01/root",
        "/workspace/project",
    ),
    "grok": (
        "tests/fixtures/grok/s-gro-01/root",
        "/workspace/project",
    ),
}


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    as_json = "--json" in (argv or sys.argv[1:])
    cells: list[dict[str, object]] = []
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    python = sys.executable
    install = str(ROOT / "scripts" / "install-resume-skills")

    with tempfile.TemporaryDirectory(prefix="portable-resume-smoke-") as tmp:
        project = Path(tmp) / "project"
        home = Path(tmp) / "home"
        project.mkdir()
        home.mkdir()
        for host in HOSTS:
            # Distinct roots: Codex/Antigravity share .agents/skills by default.
            skill_root = str(project / f"skills-{host}")
            Path(skill_root).mkdir(parents=True, exist_ok=True)
            planned = _run(
                [
                    python,
                    install,
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
                    skill_root,
                    "--json",
                ],
                env=env,
            )
            if planned.returncode != 0:
                for source in SOURCES:
                    cells.append(
                        {
                            "host": host,
                            "source": source,
                            "result": "fail",
                            "stage": "install",
                            "detail": (planned.stderr or planned.stdout)[-500:],
                        }
                    )
                continue
            for source in SOURCES:
                fixture_rel, cwd = FIXTURES[source]
                fixture = ROOT / fixture_rel
                runner = Path(skill_root) / f"resume-{source}" / "scripts" / "run_reader.py"
                if not runner.is_file():
                    cells.append(
                        {
                            "host": host,
                            "source": source,
                            "result": "fail",
                            "stage": "missing_runner",
                            "detail": str(runner),
                        }
                    )
                    continue
                # Synthetic fixtures use 2024–2026 timestamps; disable age filter.
                listed = _run(
                    [
                        python,
                        str(runner),
                        "list",
                        "--cwd",
                        cwd,
                        "--source-root",
                        str(fixture),
                        "--within-min",
                        "0",
                        "--json",
                    ],
                    env=env,
                )
                if listed.returncode != 0:
                    cells.append(
                        {
                            "host": host,
                            "source": source,
                            "result": "fail",
                            "stage": "list",
                            "detail": (listed.stderr or listed.stdout)[-500:],
                        }
                    )
                    continue
                shown = _run(
                    [
                        python,
                        str(runner),
                        "show",
                        "latest",
                        "--cwd",
                        cwd,
                        "--source-root",
                        str(fixture),
                        "--within-min",
                        "0",
                        "--format",
                        "handoff",
                    ],
                    env=env,
                )
                out = (shown.stdout or "") + (shown.stderr or "")
                ok = shown.returncode == 0 and (
                    "SECURITY BOUNDARY" in out
                    or "untrusted" in out.casefold()
                    or "Portable Resume" in out
                )
                cells.append(
                    {
                        "host": host,
                        "source": source,
                        "result": "pass" if ok else "fail",
                        "stage": "show" if not ok else "ok",
                        "detail": "" if ok else out[-500:],
                    }
                )

    passed = sum(1 for c in cells if c["result"] == "pass")
    failed = [c for c in cells if c["result"] != "pass"]
    report = {
        "schema_version": "portable-resume/installed-runner-smoke-v1",
        "cell_count": len(cells),
        "expected": 36,
        "passed": passed,
        "failed": len(failed),
        "ok": passed == 36 and len(cells) == 36,
        "note": "Installed skill runner smoke only — not host UI NL/picker activation",
        "failures": failed,
    }
    if as_json:
        report["cells"] = cells
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif failed:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"INSTALLED_RUNNER_SMOKE PASS cells={passed}/36")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
