#!/usr/bin/env python3
"""Run real verification right now; print evidence only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV = {**os.environ, "PYTHONPATH": str(REPO / "src")}


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(REPO), env=ENV, text=True, capture_output=True, check=False)


def main() -> int:
    print("=== cwd ===")
    print(REPO)
    print("=== git ===")
    g = run(["git", "log", "-1", "--oneline"])
    print(g.stdout.strip() or g.stderr.strip())
    gs = run(["git", "status", "--short", "--branch"])
    print(gs.stdout.strip())

    print("=== compileall ===")
    c = run([sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"])
    print("exit", c.returncode)

    print("=== unittest ===")
    t = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"])
    print((t.stderr or t.stdout)[-400:])
    print("exit", t.returncode)

    print("=== self-check ===")
    s = run([sys.executable, str(REPO / "scripts" / "portable-resume"), "self-check", "--json"])
    print(s.stdout.strip())
    print("exit", s.returncode)

    print("=== matrix summary ===")
    m = run([sys.executable, str(REPO / "scripts" / "install-resume-skills"), "matrix", "--json"])
    print("exit", m.returncode)
    try:
        d = json.loads(m.stdout)
        print(
            {
                "ok": d.get("ok"),
                "cell_count": d.get("cell_count"),
                "packaging_cells_supported": d.get("packaging_cells_supported"),
                "live_cells_supported": d.get("live_cells_supported"),
            }
        )
    except Exception as e:
        print("matrix parse fail", e, m.stdout[:200], m.stderr[:200])

    src = "claude"
    fx = REPO / "tests" / "fixtures" / src / "s-cla-01-ordered-parent-chain" / "root"
    print("=== list ===")
    lst = run(
        [
            sys.executable,
            str(REPO / "scripts" / "portable-resume"),
            src,
            "list",
            "--cwd",
            "/workspace/project",
            "--source-root",
            str(fx),
            "--json",
        ]
    )
    print("exit", lst.returncode)
    if lst.returncode == 0:
        body = json.loads(lst.stdout)
        print("schema", body.get("schema_version"), "inert", body.get("inert"), "n", len(body.get("sessions") or []))
    else:
        print(lst.stderr[:300])

    print("=== show handoff head ===")
    sh = run(
        [
            sys.executable,
            str(REPO / "scripts" / "portable-resume"),
            src,
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
    print("exit", sh.returncode)
    print("\n".join((sh.stdout or "").splitlines()[:10]))
    print("has_untrusted", "untrusted" in (sh.stdout or "").lower())

    print("=== install lifecycle temp ===")
    import tempfile

    sys.path.insert(0, str(REPO / "src"))
    from portable_resume.install.catalog import resolve_skill_root
    from portable_resume.install.transaction import execute_install, plan_install, verify_root, uninstall_claim

    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "h"
        proj = Path(td) / "p"
        home.mkdir()
        proj.mkdir()
        root = resolve_skill_root(host=src, scope="project", project_dir=str(proj), home_dir=str(home))
        before = sum(1 for _ in Path(root).rglob("*") if _.is_file()) if Path(root).exists() else 0
        dry = execute_install(plan_install(host=src, scope="project", root=root, dry_run=True))
        after = sum(1 for _ in Path(root).rglob("*") if _.is_file()) if Path(root).exists() else 0
        inst = execute_install(plan_install(host=src, scope="project", root=root))
        ver = verify_root(root)
        skill = Path(root) / "resume-claude" / "SKILL.md"
        skill.write_text(skill.read_text() + "\n#drift\n")
        drift_ok = False
        try:
            verify_root(root)
        except Exception as e:
            drift_ok = type(e).__name__ == "DiagnosticError" and getattr(e, "code", "") == "E_VERIFY_MISMATCH"
        # repair
        execute_install(plan_install(host=src, scope="project", root=root))
        un = uninstall_claim(host=src, scope="project", root=root)
        print(
            {
                "dry_run_ok": dry.get("ok"),
                "dry_files_before": before,
                "dry_files_after": after,
                "install_ok": inst.get("ok"),
                "verify_ok": ver.get("ok"),
                "drift_detected": drift_ok,
                "uninstall_ok": un.get("ok"),
                "skill_after_uninstall": skill.exists(),
            }
        )

    print("=== review files ===")
    research = REPO / ".omc" / "research"
    for name in [
        "dual-review-fable.md",
        "dual-review-grok.md",
        "dual-review-agy.md",
        "dual-review-codex.md",
        "dual-review-synthesis.md",
        "live-smoke-report.md",
        "linux-gate-report.md",
    ]:
        p = research / name
        if not p.exists():
            print("MISS", name)
            continue
        head = p.read_text(encoding="utf-8", errors="replace").splitlines()[:8]
        verd = next((ln for ln in head if "Verdict" in ln or "verdict" in ln or "BLOCKED" in ln), head[0] if head else "")
        print(f"HAVE {name} bytes={p.stat().st_size} | {verd[:120]}")

    print("=== honest non-claims ===")
    host = (REPO / "docs" / "host-support.md").read_text(encoding="utf-8")
    live_rows = [ln for ln in host.splitlines() if ln.startswith("| `") and "v1`" in ln]
    print("profile_rows", len(live_rows))
    print("all_not_run_live", all("`not-run`" in ln for ln in live_rows))
    print("linux_report", (research / "linux-gate-report.md").read_text(encoding="utf-8").split("## Verdict")[-1][:200].strip())

    ok = t.returncode == 0 and c.returncode == 0 and s.returncode == 0 and m.returncode == 0 and lst.returncode == 0 and sh.returncode == 0
    print("=== OVERALL_SELF_VERIFY ===", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
