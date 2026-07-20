"""Render portable skills and the owned runtime tree for one skill root."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from string import Template
from typing import Iterable

from ..diagnostics import SOURCE_KEYS
from .catalog import (
    BUNDLE_VERSION,
    HOST_PROFILES,
    SOURCE_TITLES,
    description_for,
    skill_name_for,
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_RESOURCES = _PACKAGE_ROOT / "resources"
_RUNTIME_SRC = _PACKAGE_ROOT


def _read_template(name: str) -> Template:
    path = _RESOURCES / "skill" / name
    return Template(path.read_text(encoding="utf-8"))


def render_skill_markdown(*, host: str, source: str) -> str:
    profile = HOST_PROFILES[host]
    tmpl = _read_template("SKILL.md.tmpl")
    return tmpl.safe_substitute(
        skill_name=skill_name_for(source),
        description=description_for(source),
        source_title=SOURCE_TITLES[source],
        source_key=source,
        host_profile=profile.profile_id,
        activation_help=profile.activation_help,
        arguments_note=profile.arguments_note,
    )


def render_run_reader(*, source: str) -> str:
    tmpl = _read_template("run_reader.py.tmpl")
    return tmpl.safe_substitute(source_key=source)


def materialize_plan(host: str) -> dict[str, bytes]:
    """Return relative path -> file bytes for one complete skill root."""
    if host not in HOST_PROFILES:
        raise KeyError(host)
    files: dict[str, bytes] = {}
    # support resources
    policy = (_RESOURCES / "handoff-policy.md").read_bytes()
    files[".portable-resume/resources/handoff-policy.md"] = policy
    # runtime package copy (source tree under runtime/)
    for path in _iter_runtime_files():
        rel = path.relative_to(_RUNTIME_SRC)
        dest = Path(".portable-resume") / "runtime" / "portable_resume" / rel
        files[dest.as_posix()] = path.read_bytes()
    # six skills
    for source in sorted(SOURCE_KEYS):
        skill = skill_name_for(source)
        files[f"{skill}/SKILL.md"] = render_skill_markdown(host=host, source=source).encode("utf-8")
        files[f"{skill}/scripts/run_reader.py"] = render_run_reader(source=source).encode("utf-8")
    return files


def _iter_runtime_files() -> Iterable[Path]:
    """Yield runtime modules needed by installed run_reader (exclude install/)."""
    skip_dirs = {"__pycache__", "install"}
    for root, dirs, names in os.walk(_RUNTIME_SRC):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        # Never ship the installer package into skill roots.
        rel_root = Path(root).relative_to(_RUNTIME_SRC)
        if rel_root.parts and rel_root.parts[0] == "install":
            dirs[:] = []
            continue
        for name in names:
            if name.endswith(".pyc") or name.startswith("."):
                continue
            path = Path(root) / name
            if not path.is_file():
                continue
            yield path


def package_identity(files: dict[str, bytes]) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(BUNDLE_VERSION.encode("utf-8"))
    for rel in sorted(files):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[rel])
        digest.update(b"\0")
    return digest.hexdigest()


def frontmatter_keys(skill_md: str) -> list[str]:
    lines = skill_md.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    keys: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys
