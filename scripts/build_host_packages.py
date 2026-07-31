#!/usr/bin/env python3
"""Build deterministic direct-skill and supported plugin/marketplace archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume import __version__  # noqa: E402
from portable_resume.install.package_contracts import (  # noqa: E402
    PACKAGE_CONTRACTS_SCHEMA,
    contract_for_package_type,
    contracts_report,
    validate_archive_bytes,
)
from portable_resume.install.render import materialize_plan  # noqa: E402
from portable_resume.registry import (  # noqa: E402
    PACKAGE_SURFACES,
    enabled_destination_keys,
    enabled_package_keys,
)
from build_artifact_identity import (  # noqa: E402
    identity_sha256,
    resolve_build_identity,
)

DESCRIPTION = "Offline, inert context migration across supported coding agents"
AUTHOR = {"name": "portable-resume-skills contributors"}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _prefixed_plan(
    host: str,
    prefix: str,
    *,
    identity: Mapping[str, Any],
) -> dict[str, bytes]:
    return {
        f"{prefix}{path}": data
        for path, data in materialize_plan(host, identity=identity).items()
    }


def _plugin_files(
    host: str,
    *,
    identity: Mapping[str, Any],
) -> tuple[str, dict[str, bytes]] | None:
    common = {
        "name": "portable-resume",
        "version": __version__,
        "description": DESCRIPTION,
        "author": AUTHOR,
        "license": "Apache-2.0",
        "homepage": "https://github.com/ImL1s/resume-skills",
        "repository": "https://github.com/ImL1s/resume-skills",
        "keywords": ["context-migration", "agent-skills", "offline"],
    }
    if host == "claude":
        plugin_root = "plugins/portable-resume/"
        files = _prefixed_plan(host, f"{plugin_root}skills/", identity=identity)
        files[f"{plugin_root}.claude-plugin/plugin.json"] = _json_bytes(common)
        files[".claude-plugin/marketplace.json"] = _json_bytes(
            {
                "name": "portable-resume",
                "description": DESCRIPTION,
                "owner": AUTHOR,
                "plugins": [
                    {
                        "name": "portable-resume",
                        "description": DESCRIPTION,
                        "version": __version__,
                        "source": "./plugins/portable-resume",
                        "author": AUTHOR,
                    }
                ],
            }
        )
        return "claude-marketplace", files
    if host == "codex":
        plugin_root = "plugins/portable-resume/"
        files = _prefixed_plan(host, f"{plugin_root}skills/", identity=identity)
        files[f"{plugin_root}.codex-plugin/plugin.json"] = _json_bytes(
            {**common, "skills": "./skills/"}
        )
        files[".agents/plugins/marketplace.json"] = _json_bytes(
            {
                "name": "portable-resume",
                "interface": {"displayName": "Portable Resume"},
                "plugins": [
                    {
                        "name": "portable-resume",
                        "source": {
                            "source": "local",
                            "path": "./plugins/portable-resume",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Developer Tools",
                    }
                ],
            }
        )
        return "codex-marketplace", files
    if host == "cursor":
        plugin_root = "plugins/portable-resume/"
        files = _prefixed_plan(host, f"{plugin_root}skills/", identity=identity)
        files[f"{plugin_root}.cursor-plugin/plugin.json"] = _json_bytes(
            {
                "name": "portable-resume",
                "displayName": "Portable Resume",
                "version": __version__,
                "description": DESCRIPTION,
                "author": AUTHOR,
                "homepage": common["homepage"],
                "repository": common["repository"],
                "license": common["license"],
                "keywords": common["keywords"],
                "category": "developer-tools",
                "tags": ["agent-skills", "context-migration", "offline"],
                "skills": "./skills/",
            }
        )
        files[".cursor-plugin/marketplace.json"] = _json_bytes(
            {
                "name": "portable-resume",
                "owner": AUTHOR,
                "metadata": {"description": DESCRIPTION},
                "plugins": [
                    {
                        "name": "portable-resume",
                        "source": "plugins/portable-resume",
                        "description": DESCRIPTION,
                    }
                ],
            }
        )
        return "cursor-marketplace", files
    if host == "antigravity":
        files = _prefixed_plan(host, "skills/", identity=identity)
        files["plugin.json"] = _json_bytes({"name": "portable-resume"})
        return "antigravity-plugin", files
    if host == "grok":
        files = _prefixed_plan(host, "skills/", identity=identity)
        files["plugin.json"] = _json_bytes(common)
        return "grok-plugin", files
    if host == "qwen":
        files = _prefixed_plan(host, "skills/", identity=identity)
        files["qwen-extension.json"] = _json_bytes(
            {
                "name": "portable-resume",
                "version": __version__,
                "description": DESCRIPTION,
                "skills": "skills",
            }
        )
        return "qwen-extension", files
    if host == "kimi":
        files = _prefixed_plan(host, "skills/", identity=identity)
        files["kimi.plugin.json"] = _json_bytes(
            {
                **common,
                "skills": "./skills/",
                "interface": {
                    "displayName": "Portable Resume",
                    "shortDescription": "Resume inert local coding-agent context",
                },
            }
        )
        return "kimi-plugin", files
    return None


def _safe_files(files: dict[str, bytes]) -> None:
    for path, data in files.items():
        pure = Path(path)
        if (
            not path
            or pure.is_absolute()
            or "\\" in path
            or ".." in pure.parts
            or path.startswith("/")
            or not isinstance(data, bytes)
        ):
            raise ValueError(f"unsafe archive member: {path!r}")


def _write_zip(path: Path, files: dict[str, bytes]) -> str:
    _safe_files(files)
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative in sorted(files):
            info = zipfile.ZipInfo(relative, ZIP_TIMESTAMP)
            info.create_system = 3
            executable = relative.endswith("/scripts/run_reader.py")
            mode = 0o755 if executable else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                files[relative],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_zip(
    path: Path,
    files: dict[str, bytes],
    *,
    package_type: str,
    expected_identity: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Write zip, run offline contract validation (#27), return digest + report."""

    digest = _write_zip(path, files)
    validation = validate_archive_bytes(
        path.read_bytes(),
        package_type=package_type,
        expected_identity=expected_identity,
    )
    if not validation["ok"]:
        raise ValueError(
            f"package contract failed for {package_type}: {validation['failures'][:8]}"
        )
    contract = contract_for_package_type(package_type)
    return digest, {
        "contract_id": contract.contract_id,
        "package_contracts_schema": PACKAGE_CONTRACTS_SCHEMA,
        "native_evidence_status": contract.native_evidence_status,
        "last_native_evidence_ref": contract.last_native_evidence_ref,
        "offline_validation": "pass",
        "build_identity_sha256": validation["build_identity_sha256"],
    }


def build(
    output: Path,
    *,
    identity_file: str | Path | None = None,
    identity_digest: str | None = None,
) -> dict[str, Any]:
    """Build direct-skill zips for every enabled destination + registry package surfaces.

    Direct Skills and native packages are independent axes (#36): destinations
    without a package surface still get a direct zip; package surfaces without
    ``buildable`` are skipped. Each artifact is offline-validated against a
    versioned package contract (#27); native host install remains ``not-run``
    unless separately recorded.
    """

    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output directory must be empty")
    hosts = tuple(sorted(enabled_destination_keys()))
    package_keys = tuple(sorted(enabled_package_keys()))
    identity = resolve_build_identity(
        repo_root=REPO,
        package_root=SRC / "portable_resume",
        identity_file=identity_file,
        expected_sha256=identity_digest,
    )
    canonical_identity_sha256 = identity_sha256(identity)
    artifact_version = str(identity["version"])
    artifacts: list[dict[str, Any]] = []
    for host in hosts:
        direct_name = f"portable-resume-{artifact_version}-{host}-skills.zip"
        direct_path = output / direct_name
        direct_files = materialize_plan(host, identity=identity)
        digest, meta = _validated_zip(
            direct_path,
            direct_files,
            package_type="direct-skills",
            expected_identity=identity,
        )
        artifacts.append(
            {
                "host": host,
                "type": "direct-skills",
                "file": direct_name,
                "sha256": digest,
                "members": len(direct_files),
                "install": contract_for_package_type("direct-skills").install_hint,
                **meta,
            }
        )
    for surface_key in package_keys:
        surface = PACKAGE_SURFACES[surface_key]
        plugin = _plugin_files(surface.destination, identity=identity)
        if plugin is None:
            raise ValueError(f"package surface not buildable: {surface_key}")
        kind, files = plugin
        if kind != surface.key:
            raise ValueError(
                f"package surface kind mismatch: registry={surface.key} builder={kind}"
            )
        name = f"portable-resume-{artifact_version}-{kind}.zip"
        path = output / name
        digest, meta = _validated_zip(
            path,
            files,
            package_type=kind,
            expected_identity=identity,
        )
        artifacts.append(
            {
                "host": surface.destination,
                "type": kind,
                "package_surface": surface.key,
                "file": name,
                "sha256": digest,
                "members": len(files),
                "install": contract_for_package_type(kind).install_hint,
                **meta,
            }
        )
    report = {
        "schema_version": "portable-resume/host-packages-v2",
        "version": __version__,
        "artifact_version": artifact_version,
        "build_identity": identity,
        "build_identity_sha256": canonical_identity_sha256,
        "package_contracts_schema": PACKAGE_CONTRACTS_SCHEMA,
        "host_count": len(hosts),
        "direct_package_count": len(hosts),
        "plugin_package_count": len(package_keys),
        "package_surfaces": list(package_keys),
        "artifacts": artifacts,
        # Honest native-layer status: offline contracts are not host CLI proof.
        "live_host_installation": "not-run",
        "native_package_activation": "not-run",
        "contracts": contracts_report()["contracts"],
    }
    (output / "host-packages.json").write_bytes(_json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--identity-file")
    parser.add_argument("--identity-sha256")
    parser.add_argument("--json", action="store_true")
    namespace = parser.parse_args(argv)
    try:
        report = build(
            Path(namespace.output_dir),
            identity_file=namespace.identity_file,
            identity_digest=namespace.identity_sha256,
        )
    except (OSError, ValueError, KeyError) as error:
        print(f"HOST_PACKAGE_BUILD FAIL {type(error).__name__}", file=sys.stderr)
        return 1
    if namespace.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "HOST_PACKAGE_BUILD PASS "
            f"direct={report['direct_package_count']} "
            f"plugin={report['plugin_package_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
