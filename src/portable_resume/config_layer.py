"""Layered user/project configuration with named presets (#152).

stdlib only (tomllib). Config is data: no executable commands or secrets.
Precedence: CLI > env > preset > project > user > defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .diagnostics import DiagnosticError
from .paths import canonicalize_cwd, reject_controls

_ALLOWED_KEYS = frozenset(
    {
        "format",
        "within_min",
        "max_tool_chars",
        "workspace",
        "privacy",
        "sources",
        "match",
        "limit",
    }
)
_ENV_MAP = {
    "PORTABLE_RESUME_FORMAT": "format",
    "PORTABLE_RESUME_WITHIN_MIN": "within_min",
    "PORTABLE_RESUME_MAX_TOOL_CHARS": "max_tool_chars",
    "PORTABLE_RESUME_WORKSPACE": "workspace",
    "PORTABLE_RESUME_PRIVACY": "privacy",
}


@dataclass
class EffectiveConfig:
    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "portable-resume/config-effective-v1",
            "values": {
                key: {"value": self.values[key], "source": self.sources.get(key, "default")}
                for key in sorted(self.values)
            },
        }


def user_config_path(*, home: str | None = None) -> Path:
    base = home if home is not None else os.path.expanduser("~")
    return Path(base) / ".config" / "portable-resume" / "config.toml"


def project_config_path(project: str) -> Path:
    return Path(canonicalize_cwd(project)) / ".portable-resume.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise DiagnosticError.invalid() from error
    if not isinstance(data, dict):
        raise DiagnosticError.invalid()
    return data


def _sanitize_mapping(raw: Mapping[str, Any], *, origin: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "presets":
            continue
        if key not in _ALLOWED_KEYS:
            continue
        if isinstance(value, str):
            reject_controls(value)
            if len(value) > 1024:
                raise DiagnosticError.invalid()
        elif isinstance(value, bool):
            pass
        elif isinstance(value, int) and not isinstance(value, bool):
            if value < 0 or value > 10_000_000:
                raise DiagnosticError.invalid()
        elif isinstance(value, list) and all(isinstance(x, str) for x in value):
            for item in value:
                reject_controls(item)
        else:
            raise DiagnosticError.invalid()
        out[key] = value
    # origin reserved for future diagnostics
    _ = origin
    return out


def load_layers(
    *,
    project: str | None = None,
    home: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    """Return (user_defaults, project_defaults, presets)."""

    user_raw = _load_toml(user_config_path(home=home))
    project_raw: dict[str, Any] = {}
    if project is not None:
        project_raw = _load_toml(project_config_path(project))

    presets: dict[str, dict[str, Any]] = {}
    for origin, blob in (("user", user_raw), ("project", project_raw)):
        raw_presets = blob.get("presets") if isinstance(blob.get("presets"), dict) else {}
        assert isinstance(raw_presets, dict)
        for name, body in raw_presets.items():
            if not isinstance(name, str) or not name or not isinstance(body, dict):
                raise DiagnosticError.invalid()
            reject_controls(name)
            presets[name] = _sanitize_mapping(body, origin=f"preset:{name}")

    user_defaults = _sanitize_mapping(
        {k: v for k, v in user_raw.items() if k != "presets"}, origin="user"
    )
    project_defaults = _sanitize_mapping(
        {k: v for k, v in project_raw.items() if k != "presets"}, origin="project"
    )
    return user_defaults, project_defaults, presets


def resolve_effective(
    *,
    project: str | None = None,
    home: str | None = None,
    preset: str | None = None,
    env: Mapping[str, str] | None = None,
    cli: Mapping[str, Any] | None = None,
) -> EffectiveConfig:
    """Merge layers. ``cli`` should contain only explicitly provided values."""

    user_d, project_d, presets = load_layers(project=project, home=home)
    effective = EffectiveConfig()

    def put(key: str, value: Any, source: str) -> None:
        effective.values[key] = value
        effective.sources[key] = source

    for key, value in user_d.items():
        put(key, value, "user-config")
    for key, value in project_d.items():
        put(key, value, "project-config")

    if preset is not None:
        reject_controls(preset)
        if preset not in presets:
            raise DiagnosticError.invalid()
        for key, value in presets[preset].items():
            put(key, value, f"preset:{preset}")

    environ = env if env is not None else os.environ
    for env_key, conf_key in _ENV_MAP.items():
        if env_key in environ and environ[env_key] != "":
            raw = environ[env_key]
            reject_controls(raw)
            if conf_key in {"within_min", "max_tool_chars", "limit"}:
                try:
                    put(conf_key, int(raw), f"env:{env_key}")
                except ValueError as error:
                    raise DiagnosticError.invalid() from error
            else:
                put(conf_key, raw, f"env:{env_key}")

    if cli:
        for key, value in cli.items():
            if value is None:
                continue
            if key not in _ALLOWED_KEYS:
                continue
            put(key, value, "cli")

    return effective


def default_config_toml(*, scope: str) -> str:
    if scope not in {"user", "project"}:
        raise DiagnosticError.invalid()
    return (
        "# portable-resume config (data only; no shell/commands)\n"
        "# Allowed keys: format, within_min, max_tool_chars, workspace, privacy, sources, match, limit\n"
        "\n"
        "# format = \"handoff\"\n"
        "# within_min = 10080\n"
        "# workspace = \"exact\"\n"
        "\n"
        "[presets.daily]\n"
        "format = \"handoff\"\n"
        "within_min = 10080\n"
        "workspace = \"worktree\"\n"
    )


def init_config(*, scope: str, project: str | None = None, home: str | None = None) -> str:
    if scope == "user":
        path = user_config_path(home=home)
    elif scope == "project":
        if project is None:
            raise DiagnosticError.invalid()
        path = project_config_path(project)
    else:
        raise DiagnosticError.invalid()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise DiagnosticError.invalid()
    path.write_text(default_config_toml(scope=scope), encoding="utf-8")
    return str(path)


def validate_config(*, project: str | None = None, home: str | None = None) -> dict[str, Any]:
    user_d, project_d, presets = load_layers(project=project, home=home)
    return {
        "schema_version": "portable-resume/config-validate-v1",
        "ok": True,
        "user_keys": sorted(user_d),
        "project_keys": sorted(project_d),
        "presets": sorted(presets),
    }
