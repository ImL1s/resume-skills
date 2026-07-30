"""Render portable skills and the owned runtime tree for one skill root."""

from __future__ import annotations

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

# Keep the installed reader runtime explicit and reviewable. Adding a new
# runtime dependency must update this list and the installed-runner smoke; the
# installer package itself is deliberately absent.
_RUNTIME_MODULES = (
    "__init__.py",
    "bounds.py",
    "contracts.py",
    "diagnostics.py",
    "handoff.py",
    "model.py",
    "paths.py",
    "reader.py",
    "registry.py",
    "request.py",
    "resources/portable-resume-v1.schema.json",
    "sanitize.py",
    "select.py",
    "snapshot.py",
    "adapters/__init__.py",
    "adapters/antigravity.py",
    "adapters/base.py",
    "adapters/claude.py",
    "adapters/codex.py",
    "adapters/codex_sqlite.py",
    "adapters/common.py",
    "adapters/cursor.py",
    "adapters/cursor_live.py",
    "adapters/grok.py",
    "adapters/kimi.py",
    "adapters/opencode.py",
    "adapters/openclaw.py",
    "adapters/pi.py",
    "adapters/qwen.py",
)


def _read_template(name: str) -> Template:
    path = _RESOURCES / "skill" / name
    return Template(path.read_text(encoding="utf-8"))


def render_skill_markdown(*, source: str, host: str | None = None) -> str:
    """Render one portable ``resume-<source>/SKILL.md`` body.

    ``host`` is accepted for API compatibility but is **not** baked into the
    Skill body (#25). Compatible destinations share byte-identical Skill trees;
    host-specific activation grammar lives in the catalog / hosts command / docs.
    """
    if host is not None and host not in HOST_PROFILES:
        raise KeyError(host)
    tmpl = _read_template("SKILL.md.tmpl")
    return tmpl.safe_substitute(
        skill_name=skill_name_for(source),
        description=description_for(source),
        source_title=SOURCE_TITLES[source],
        source_key=source,
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
    # Narrow ignore for machine-local control state only (#33 Option A).
    # Deterministic shareable bytes — package identity includes this file.
    files[".portable-resume/.gitignore"] = (
        b"# portable-resume: machine-local control state only (#33)\n"
        b"# Keep runtime/ and resources/ shareable; never commit locks/journals.\n"
        b".state/\n"
    )
    # runtime package copy (source tree under runtime/)
    for path in _iter_runtime_files():
        rel = path.relative_to(_RUNTIME_SRC)
        dest = Path(".portable-resume") / "runtime" / "portable_resume" / rel
        files[dest.as_posix()] = path.read_bytes()
    # one skill for every supported source
    for source in sorted(SOURCE_KEYS):
        skill = skill_name_for(source)
        files[f"{skill}/SKILL.md"] = render_skill_markdown(source=source, host=host).encode("utf-8")
        files[f"{skill}/scripts/run_reader.py"] = render_run_reader(source=source).encode("utf-8")
    return files


def _iter_runtime_files() -> Iterable[Path]:
    """Yield the audited stdlib-only installed runtime module allowlist."""
    for relative in _RUNTIME_MODULES:
        path = _RUNTIME_SRC / relative
        try:
            mode = path.lstat().st_mode
        except OSError as error:
            raise RuntimeError(f"missing installed runtime module: {relative}") from error
        if path.is_symlink() or not stat.S_ISREG(mode):
            raise RuntimeError(f"unsafe installed runtime module: {relative}")
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
