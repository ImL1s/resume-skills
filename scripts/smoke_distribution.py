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
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

from portable_resume.build_identity import load_identity_file  # noqa: E402
from portable_resume.registry import matrix_dimensions  # noqa: E402

EXPECTED_MATRIX_CELLS = matrix_dimensions()["cells"]
EXPECTED_PROJECT_URLS = {
    "Homepage": "https://github.com/ImL1s/resume-skills",
    "Documentation": "https://github.com/ImL1s/resume-skills/tree/main/docs",
    "Repository": "https://github.com/ImL1s/resume-skills",
    "Issues": "https://github.com/ImL1s/resume-skills/issues",
    "Changelog": "https://github.com/ImL1s/resume-skills/blob/main/CHANGELOG.md",
}


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


def _install_result_payload(doc: dict[str, Any]) -> dict[str, Any]:
    """Unwrap portable-resume/install-result-v1 envelope (#32)."""

    if doc.get("schema_version") == "portable-resume/install-result-v1":
        results = doc.get("results") or []
        if not results or not isinstance(results[0], dict):
            raise RuntimeError("install-result-v1 missing results[0]")
        return results[0]
    return doc


def smoke_artifact(
    artifact: Path,
    *,
    version: str,
    expected_identity: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="portable-resume-dist-") as temporary:
        base = Path(temporary)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PORTABLE_RESUME_BUILD_IDENTITY_FILE", None)
        environment.pop("PORTABLE_RESUME_BUILD_IDENTITY_SHA256", None)
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
                    "from portable_resume.build_identity import runtime_identity;"
                    "from importlib.metadata import metadata,version;"
                    "m=metadata('portable-resume');"
                    "print(json.dumps({'module':portable_resume.__file__,"
                    "'source_version':portable_resume.__version__,"
                    "'metadata_version':version('portable-resume'),"
                    "'build_identity':runtime_identity(),"
                    "'project_urls':m.get_all('Project-URL') or []}))"
                ),
            ],
            cwd=base,
            env=environment,
        )
        identity = _json_stdout(probe, "package identity")
        if identity.get("source_version") != version or identity.get("metadata_version") != version:
            raise RuntimeError("installed version does not match release version")
        build = identity.get("build_identity") or {}
        if build != expected_identity:
            raise RuntimeError("installed build identity differs from the build pin")
        module_path = str(identity.get("module", ""))
        if str(REPO) in module_path:
            raise RuntimeError("installed import leaked to source checkout")
        project_urls: dict[str, str] = {}
        for item in identity.get("project_urls") or []:
            name, separator, url = str(item).partition(", ")
            if not separator:
                raise RuntimeError("installed project URL metadata is malformed")
            project_urls[name] = url
        if project_urls != EXPECTED_PROJECT_URLS:
            raise RuntimeError("installed project URL metadata is incomplete")

        for command in ("portable-resume", "install-resume-skills"):
            version_output = _run(
                [str(_console(venv_root, command)), "--version"],
                cwd=base,
                env=environment,
            )
            if (
                version_output.returncode != 0
                or version_output.stdout.strip()
                != f"{command} {expected_identity['version']}"
                or version_output.stderr
            ):
                raise RuntimeError(f"installed {command} version output is invalid")

        self_check = _json_stdout(
            _run(
                [str(_console(venv_root, "portable-resume")), "self-check", "--json"],
                cwd=base,
                env=environment,
            ),
            "installed self-check",
        )
        if (
            not self_check.get("ok")
            or self_check.get("matrix", {}).get("cell_count") != EXPECTED_MATRIX_CELLS
            or self_check.get("build_identity") != build
        ):
            raise RuntimeError(
                f"installed self-check did not prove the {EXPECTED_MATRIX_CELLS}-cell matrix"
            )

        matrix_doc = _json_stdout(
            _run(
                [str(_console(venv_root, "install-resume-skills")), "matrix"],
                cwd=base,
                env=environment,
            ),
            "installed matrix",
        )
        matrix = _install_result_payload(matrix_doc)
        if not matrix.get("ok") or matrix.get("cell_count") != EXPECTED_MATRIX_CELLS:
            raise RuntimeError(
                f"installed matrix did not contain {EXPECTED_MATRIX_CELLS} successful cells"
            )

        home = base / "home"
        home.mkdir()
        quick_doc = _json_stdout(
            _run(
                [
                    str(_console(venv_root, "install-resume-skills")),
                    "quick-install",
                    "qwen",
                    "--home",
                    str(home),
                ],
                cwd=base,
                env=environment,
            ),
            "installed quick-install",
        )
        quick = _install_result_payload(quick_doc)
        plan = quick.get("plan", {})
        if (
            not quick_doc.get("ok")
            or not quick.get("ok")
            or plan.get("host") != "qwen"
            or plan.get("scope") != "global"
        ):
            raise RuntimeError("installed quick-install returned the wrong plan")
        verified_doc = _json_stdout(
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
                ],
                cwd=base,
                env=environment,
            ),
            "installed quick-install verify",
        )
        verified = _install_result_payload(verified_doc)
        if not verified_doc.get("ok") or not verified.get("ok"):
            raise RuntimeError("installed quick-install did not verify")

        return {
            "artifact": artifact.name,
            "kind": "wheel" if artifact.suffix == ".whl" else "sdist",
            "version": version,
            "build_identity": build,
            "matrix_cells": matrix["cell_count"],
            "quick_install_verified": True,
            "module_outside_checkout": True,
            "ok": True,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", default="dist")
    parser.add_argument("--version", required=True)
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--identity-sha256", required=True)
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
        expected_identity = load_identity_file(
            namespace.identity_file,
            expected_sha256=namespace.identity_sha256,
        )
        if expected_identity.get("base_version") != namespace.version:
            raise RuntimeError("expected identity base version differs from --version")
        if len(artifacts) != 2:
            raise RuntimeError("expected exactly one wheel and one sdist")
        report["artifacts"] = [
            smoke_artifact(
                path,
                version=namespace.version,
                expected_identity=expected_identity,
            )
            for path in artifacts
        ]
        report["build_identity"] = expected_identity
        report["build_identity_sha256"] = namespace.identity_sha256
        report["ok"] = True
    except (OSError, RuntimeError, ValueError) as error:
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
