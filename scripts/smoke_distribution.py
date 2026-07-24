#!/usr/bin/env python3
"""Install the exact wheel and sdist in isolated venvs and smoke their CLIs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _venv_python(root: Path) -> Path:
    return root / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )


def _console(root: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return root / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def _json_stdout(completed: subprocess.CompletedProcess[str], stage: str) -> dict[str, Any]:
    if completed.returncode != 0:
        raise RuntimeError(f"{stage} failed: {(completed.stderr or completed.stdout)[-500:]}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{stage} returned non-JSON output") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{stage} returned the wrong JSON shape")
    return value


def smoke_artifact(artifact: Path, *, version: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="portable-resume-dist-") as temporary:
        base = Path(temporary)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        environment["PIP_NO_INPUT"] = "1"

        venv_root = base / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_root)
        python = _venv_python(venv_root)
        installed = _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                str(artifact.resolve()),
            ],
            cwd=base,
            env=environment,
        )
        if installed.returncode != 0:
            raise RuntimeError(
                f"install {artifact.name} failed: {(installed.stderr or installed.stdout)[-500:]}"
            )

        probe = _run(
            [
                str(python),
                "-I",
                "-c",
                (
                    "import json,portable_resume;"
                    "from importlib.metadata import version;"
                    "print(json.dumps({'module':portable_resume.__file__,"
                    "'source_version':portable_resume.__version__,"
                    "'metadata_version':version('portable-resume')}))"
                ),
            ],
            cwd=base,
            env=environment,
        )
        identity = _json_stdout(probe, "package identity")
        if identity.get("source_version") != version or identity.get("metadata_version") != version:
            raise RuntimeError("installed version does not match release version")
        module_path = str(identity.get("module", ""))
        if str(REPO) in module_path:
            raise RuntimeError("installed import leaked to source checkout")

        self_check = _json_stdout(
            _run(
                [str(_console(venv_root, "portable-resume")), "self-check", "--json"],
                cwd=base,
                env=environment,
            ),
            "installed self-check",
        )
        if not self_check.get("ok") or self_check.get("matrix", {}).get("cell_count") != 64:
            raise RuntimeError("installed self-check did not prove the 64-cell matrix")

        matrix = _json_stdout(
            _run(
                [str(_console(venv_root, "install-resume-skills")), "matrix", "--json"],
                cwd=base,
                env=environment,
            ),
            "installed matrix",
        )
        if not matrix.get("ok") or matrix.get("cell_count") != 64:
            raise RuntimeError("installed matrix did not contain 64 successful cells")

        home = base / "home"
        home.mkdir()
        quick = _json_stdout(
            _run(
                [
                    str(_console(venv_root, "install-resume-skills")),
                    "quick-install",
                    "qwen",
                    "--home",
                    str(home),
                    "--json",
                ],
                cwd=base,
                env=environment,
            ),
            "installed quick-install",
        )
        plan = quick.get("plan", {})
        if (
            not quick.get("ok")
            or plan.get("host") != "qwen"
            or plan.get("scope") != "global"
        ):
            raise RuntimeError("installed quick-install returned the wrong plan")
        verified = _json_stdout(
            _run(
                [
                    str(_console(venv_root, "install-resume-skills")),
                    "verify",
                    "--host",
                    "qwen",
                    "--scope",
                    "global",
                    "--home",
                    str(home),
                    "--json",
                ],
                cwd=base,
                env=environment,
            ),
            "installed quick-install verify",
        )
        if not verified.get("ok"):
            raise RuntimeError("installed quick-install did not verify")

        return {
            "artifact": artifact.name,
            "kind": "wheel" if artifact.suffix == ".whl" else "sdist",
            "version": version,
            "matrix_cells": matrix["cell_count"],
            "quick_install_verified": True,
            "module_outside_checkout": True,
            "ok": True,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", default="dist")
    parser.add_argument("--version", required=True)
    parser.add_argument("--json", action="store_true")
    namespace = parser.parse_args(argv)
    dist = Path(namespace.dist_dir)
    artifacts = sorted(
        [
            *dist.glob(f"portable_resume-{namespace.version}-*.whl"),
            *dist.glob(f"portable_resume-{namespace.version}.tar.gz"),
        ]
    )
    report: dict[str, Any] = {
        "schema_version": "portable-resume/distribution-smoke-v1",
        "version": namespace.version,
        "artifacts": [],
        "ok": False,
    }
    try:
        if len(artifacts) != 2:
            raise RuntimeError("expected exactly one wheel and one sdist")
        report["artifacts"] = [
            smoke_artifact(path, version=namespace.version) for path in artifacts
        ]
        report["ok"] = True
    except RuntimeError as error:
        report["error"] = str(error)

    if namespace.json or not report["ok"]:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "DISTRIBUTION_SMOKE PASS "
            + " ".join(item["artifact"] for item in report["artifacts"])
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
