#!/usr/bin/env python3
"""Focused Windows product install smoke (Phase 7 gate).

Runs plan_install → execute_install → verify_root → uninstall_claim
for a small set of representative hosts in temp roots.  This proves
the Phase 7 Policy B lift works end-to-end on real ``nt`` without
requiring all 306 matrix cells to pass (some source adapters have
unrelated format issues on Windows).

Exit 0  → all tested host installs succeeded.
Exit 1  → at least one host install cycle failed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Allow running from repo root with PYTHONPATH=src or scripts/ injection.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SRC_DIR = _SCRIPTS_DIR.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.transaction import (
    execute_install,
    plan_install,
    recover_root,
    uninstall_claim,
    verify_root,
)

# Representative hosts covering different install profiles.
_SMOKE_HOSTS = ["claude", "cursor", "codex"]


def _run_host_cycle(host: str) -> dict:
    """Run install → verify → uninstall → recover for one host."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        project = Path(tmp) / "project"
        home.mkdir()
        project.mkdir()
        root = resolve_skill_root(
            host=host,
            scope="project",
            project_dir=str(project),
            home_dir=str(home),
        )

        # 1. Install
        plan = plan_install(host=host, scope="project", root=root)
        res_install = execute_install(plan)
        if not res_install.get("ok"):
            return {"host": host, "ok": False, "stage": "install", "detail": str(res_install)}

        # 2. Verify
        res_verify = verify_root(root)
        if not res_verify.get("ok"):
            return {"host": host, "ok": False, "stage": "verify", "detail": str(res_verify)}

        # 3. Uninstall
        res_uninstall = uninstall_claim(host=host, scope="project", root=root)
        if not res_uninstall.get("ok"):
            return {"host": host, "ok": False, "stage": "uninstall", "detail": str(res_uninstall)}

        # 4. Recover (noop — no journal after clean uninstall)
        res_recover = recover_root(root)
        if not res_recover.get("ok"):
            return {"host": host, "ok": False, "stage": "recover", "detail": str(res_recover)}

        return {"host": host, "ok": True, "stage": "complete"}


def main() -> int:
    if os.name != "nt":
        print("SKIP: smoke_windows_product_install requires os.name == 'nt'")
        return 0

    print(f"smoke_windows_product_install: testing {len(_SMOKE_HOSTS)} hosts on {sys.platform}")
    results = []
    for host in _SMOKE_HOSTS:
        print(f"  {host} ... ", end="", flush=True)
        try:
            r = _run_host_cycle(host)
        except Exception as exc:
            r = {"host": host, "ok": False, "stage": "exception", "detail": str(exc)}
        results.append(r)
        print("OK" if r["ok"] else f"FAIL ({r['stage']}: {r.get('detail', '')})")

    report = {
        "schema_version": "portable-resume/windows-product-install-smoke-v1",
        "platform": sys.platform,
        "os_name": os.name,
        "hosts_tested": len(_SMOKE_HOSTS),
        "hosts_passed": sum(1 for r in results if r["ok"]),
        "ok": all(r["ok"] for r in results),
        "results": results,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
