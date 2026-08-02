"""Render portable skills and the owned runtime tree for one skill root."""

from __future__ import annotations

import stat
from pathlib import Path
from string import Template
from typing import Any, Iterable, Mapping, Sequence

from ..build_identity import (
    assert_identity_matches_package,
    identity_json_bytes,
    runtime_identity,
)
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
_PLAN_CACHE: dict[str, dict[str, bytes]] = {}

# Keep the installed reader runtime explicit and reviewable. Adding a new
# runtime dependency must update this list and the installed-runner smoke; the
# installer package itself is deliberately absent.
_RUNTIME_MODULES = (
    "__init__.py",
    "bounds.py",
    "build_identity.py",
    "contracts.py",
    "config_layer.py",
    "diagnostics.py",
    "discover_doctor.py",
    "handoff.py",
    "model.py",
    "output_write.py",
    "paths.py",
    "reader.py",
    "registry.py",
    "request.py",
    "resources/portable-resume-v1.schema.json",
    "resources/latest-release.json",
    "sanitize.py",
    "search_sessions.py",
    "select.py",
    "snapshot.py",
    "time_range.py",
    "workspace.py",
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
    "adapters/goose.py",
    "adapters/crush.py",
    "adapters/cline.py",
    "adapters/openhands.py",
    "adapters/hermes.py",
    "adapters/gemini.py",
    "adapters/github_copilot.py",
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


def materialize_plan(
    host: str,
    *,
    identity: Mapping[str, Any] | None = None,
    sources: Sequence[str] | None = None,
) -> dict[str, bytes]:
    """Return relative path -> file bytes for one complete skill root.

    ``sources`` (#151): when provided, only those enabled source Skills are
    emitted (shared runtime still always included). ``None`` means all enabled.
    """
    if host not in HOST_PROFILES:
        raise KeyError(host)
    selected_identity = runtime_identity() if identity is None else identity
    assert_identity_matches_package(selected_identity, package_root=_PACKAGE_ROOT)
    identity_bytes = identity_json_bytes(selected_identity)
    if sources is None:
        source_list = tuple(sorted(SOURCE_KEYS))
    else:
        enabled = set(SOURCE_KEYS)
        cleaned: list[str] = []
        seen: set[str] = set()
        for key in sources:
            if key not in enabled:
                raise KeyError(key)
            if key not in seen:
                seen.add(key)
                cleaned.append(key)
        if not cleaned:
            raise ValueError("empty sources")
        source_list = tuple(sorted(cleaned))
    cache_key = identity_bytes.decode("utf-8") + "|" + ",".join(source_list)
    cached = _PLAN_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
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
    files[
        ".portable-resume/runtime/portable_resume/resources/build-identity.json"
    ] = identity_bytes
    # one skill for each selected source
    for source in source_list:
        skill = skill_name_for(source)
        files[f"{skill}/SKILL.md"] = render_skill_markdown(source=source, host=host).encode("utf-8")
        files[f"{skill}/scripts/run_reader.py"] = render_run_reader(source=source).encode("utf-8")
    _PLAN_CACHE[cache_key] = files
    return dict(files)


def _reset_plan_cache() -> None:
    """Clear process-lifetime materialization state for isolated tests."""
    _PLAN_CACHE.clear()


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
