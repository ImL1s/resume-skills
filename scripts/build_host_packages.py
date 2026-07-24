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
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume import __version__  # noqa: E402
from portable_resume.install.catalog import HOST_KEYS  # noqa: E402
from portable_resume.install.render import materialize_plan  # noqa: E402

DESCRIPTION = "Offline, inert context migration across supported coding agents"
AUTHOR = {"name": "portable-resume-skills contributors"}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _prefixed_plan(host: str, prefix: str) -> dict[str, bytes]:
    return {f"{prefix}{path}": data for path, data in materialize_plan(host).items()}


def _plugin_files(host: str) -> tuple[str, dict[str, bytes], str] | None:
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
        files = _prefixed_plan(host, f"{plugin_root}skills/")
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
        return (
            "claude-marketplace",
            files,
            "claude plugin marketplace add <extracted-dir>; "
            "claude plugin install portable-resume@portable-resume",
        )
    if host == "codex":
        plugin_root = "plugins/portable-resume/"
        files = _prefixed_plan(host, f"{plugin_root}skills/")
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
        return (
            "codex-marketplace",
            files,
            "codex plugin marketplace add <extracted-dir>; "
            "codex plugin add portable-resume@portable-resume",
        )
    if host == "cursor":
        plugin_root = "plugins/portable-resume/"
        files = _prefixed_plan(host, f"{plugin_root}skills/")
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
        return (
            "cursor-marketplace",
            files,
            "copy or symlink <extracted-dir>/plugins/portable-resume to "
            "~/.cursor/plugins/local/portable-resume, or run "
            "cursor agent --plugin-dir <extracted-dir>/plugins/portable-resume",
        )
    if host == "antigravity":
        files = _prefixed_plan(host, "skills/")
        files["plugin.json"] = _json_bytes({"name": "portable-resume"})
        return (
            "antigravity-plugin",
            files,
            "agy plugin validate <extracted-dir>; agy plugin install <extracted-dir>",
        )
    if host == "grok":
        files = _prefixed_plan(host, "skills/")
        files["plugin.json"] = _json_bytes(common)
        return (
            "grok-plugin",
            files,
            "grok plugin validate <extracted-dir>; "
            "grok plugin install <extracted-dir> --trust",
        )
    if host == "qwen":
        files = _prefixed_plan(host, "skills/")
        files["qwen-extension.json"] = _json_bytes(
            {
                "name": "portable-resume",
                "version": __version__,
                "description": DESCRIPTION,
                "skills": "skills",
            }
        )
        return (
            "qwen-extension",
            files,
            "qwen extensions install <archive-or-url>",
        )
    if host == "kimi":
        files = _prefixed_plan(host, "skills/")
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
        return (
            "kimi-plugin",
            files,
            "/plugins install <extracted-dir-or-zip-url-or-github-url>; "
            "/plugins reload",
        )
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


def build(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output directory must be empty")
    artifacts: list[dict[str, Any]] = []
    for host in sorted(HOST_KEYS):
        direct_name = f"portable-resume-{__version__}-{host}-skills.zip"
        direct_path = output / direct_name
        direct_files = materialize_plan(host)
        artifacts.append(
            {
                "host": host,
                "type": "direct-skills",
                "file": direct_name,
                "sha256": _write_zip(direct_path, direct_files),
                "members": len(direct_files),
                "install": "extract into the host skill root documented in docs/install-hosts.md",
            }
        )
        plugin = _plugin_files(host)
        if plugin is not None:
            kind, files, install = plugin
            name = f"portable-resume-{__version__}-{kind}.zip"
            path = output / name
            artifacts.append(
                {
                    "host": host,
                    "type": kind,
                    "file": name,
                    "sha256": _write_zip(path, files),
                    "members": len(files),
                    "install": install,
                }
            )
    report = {
        "schema_version": "portable-resume/host-packages-v1",
        "version": __version__,
        "host_count": len(HOST_KEYS),
        "direct_package_count": len(HOST_KEYS),
        "plugin_package_count": sum(
            1 for item in artifacts if item["type"] != "direct-skills"
        ),
        "artifacts": artifacts,
        "live_host_installation": "not-run",
    }
    (output / "host-packages.json").write_bytes(_json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--json", action="store_true")
    namespace = parser.parse_args(argv)
    try:
        report = build(Path(namespace.output_dir))
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
