"""Bounded discovery-root policy and duplicate/shadow Skill scan (#34).

Machine-readable ordered discovery locations replace prose-only
``alternate_*_roots`` for install dry-run, verify, and ``audit-host``.

Rules:
- Inspect only known candidate roots (never whole-home traversal).
- Only ``resume-*`` skill names from the enabled source registry.
- Read-only: never mutate or execute discovered runners.
- Symlinked skill dirs / SKILL.md are reported unsafe and not content-hashed.
- Unknown host precedence is ``None`` — never invented.
- Same physical root (shared claims) is not a harmful duplicate.
"""

from __future__ import annotations

import hashlib
import os
import stat as stat_mod
from dataclasses import dataclass
from typing import Any, Iterable

from ..diagnostics import DiagnosticError, SOURCE_KEYS
from .catalog import BUNDLE_VERSION, HOST_PROFILES, SOURCE_SKILL_NAMES, skill_name_for
from .control_schema import OWNER_MARKER
from .render import materialize_plan, package_identity

# Bounded SKILL.md body read for fingerprinting foreign/owned copies.
_MAX_SKILL_MD_BYTES = 256 * 1024
_MAX_RUNNER_BYTES = 256 * 1024

# realpath(selected_root) -> precedence for the selected install root.
_SELECTED_PRECEDENCE: dict[str, int | None] = {}

# Classification statuses (#34).
STATUS_UNIQUE = "unique"
STATUS_SAME_PHYSICAL = "same_physical_root_multi_claim"
STATUS_DUP_IDENTICAL = "duplicate_identical_payload"
STATUS_DUP_DIFFERENT = "duplicate_different_version"
STATUS_DUP_FOREIGN = "duplicate_foreign_or_unverifiable"
STATUS_HIGHER_SHADOW = "higher_precedence_shadow"
STATUS_PLUGIN_COEXIST = "plugin_and_direct_coexistence"
STATUS_PRECEDENCE_UNKNOWN = "precedence_unknown"
STATUS_UNSAFE = "unsafe_or_unreadable"

# Action policy codes for machine-readable reports.
POLICY_ALLOW = "allow"
POLICY_WARN = "warn"
POLICY_BLOCK = "block"
POLICY_REPORT_ONLY = "report_only"


@dataclass(frozen=True, slots=True)
class DiscoveryRoot:
    """One host-documented Skill discovery location."""

    root_id: str
    scope: str  # project | user | plugin | compat
    base: str  # project | home
    rel: str  # relative path under base (posix-ish, no leading slash)
    precedence: int | None  # lower wins when known; None = unknown
    managed_by: str  # portable-resume | host | foreign
    role: str  # primary | alternate | plugin
    detectable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "scope": self.scope,
            "base": self.base,
            "rel": self.rel,
            "precedence": self.precedence,
            "managed_by": self.managed_by,
            "role": self.role,
            "detectable": self.detectable,
        }


def discovery_roots_for_host(host: str) -> tuple[DiscoveryRoot, ...]:
    """Return executable discovery policy for *host* (primary + known alts)."""

    if host not in HOST_PROFILES:
        raise DiagnosticError.invalid()
    profile = HOST_PROFILES[host]
    # Project roots outrank user-global when both are documented first-class
    # (lower number = higher precedence). Equal-tier alternates share the
    # primary's tier; unproven compat roots use precedence=None.
    roots: list[DiscoveryRoot] = [
        DiscoveryRoot(
            root_id=f"{host}.project.primary",
            scope="project",
            base="project",
            rel=profile.project_rel.replace("\\", "/"),
            precedence=5,
            managed_by="portable-resume",
            role="primary",
        ),
        DiscoveryRoot(
            root_id=f"{host}.user.primary",
            scope="user",
            base="home",
            rel=profile.global_rel.replace("\\", "/"),
            precedence=10,
            managed_by="portable-resume",
            role="primary",
        ),
    ]
    # Host-specific alternates with honest precedence (None when unproven).
    roots.extend(_host_alternate_roots(host))
    return tuple(roots)


def _host_alternate_roots(host: str) -> list[DiscoveryRoot]:
    """Fixed alternate roots derived from catalog evidence notes (not prose only)."""

    if host == "cursor":
        # Cursor docs: .agents/skills is first-class with .cursor/skills (equal tier).
        # Claude/Codex roots are compatibility — precedence vs native unproven.
        return [
            DiscoveryRoot(
                root_id="cursor.project.agents",
                scope="project",
                base="project",
                rel=".agents/skills",
                precedence=5,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="cursor.user.agents",
                scope="user",
                base="home",
                rel=".agents/skills",
                precedence=10,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="cursor.project.claude_compat",
                scope="compat",
                base="project",
                rel=".claude/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="cursor.user.claude_compat",
                scope="compat",
                base="home",
                rel=".claude/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="cursor.project.codex_compat",
                scope="compat",
                base="project",
                rel=".codex/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="cursor.user.codex_compat",
                scope="compat",
                base="home",
                rel=".codex/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
        ]
    if host == "opencode":
        return [
            DiscoveryRoot(
                root_id="opencode.project.claude_compat",
                scope="compat",
                base="project",
                rel=".claude/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="opencode.project.agents_compat",
                scope="compat",
                base="project",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="opencode.user.claude_compat",
                scope="compat",
                base="home",
                rel=".claude/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="opencode.user.agents_compat",
                scope="compat",
                base="home",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
        ]
    if host == "antigravity":
        return [
            DiscoveryRoot(
                root_id="antigravity.project.legacy_agent",
                scope="compat",
                base="project",
                rel=".agent/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="antigravity.user.agents_interop",
                scope="compat",
                base="home",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
        ]
    if host == "grok":
        return [
            DiscoveryRoot(
                root_id="grok.project.agents",
                scope="compat",
                base="project",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="grok.user.agents",
                scope="compat",
                base="home",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="grok.project.claude_compat",
                scope="compat",
                base="project",
                rel=".claude/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="grok.user.claude_compat",
                scope="compat",
                base="home",
                rel=".claude/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="grok.project.cursor_compat",
                scope="compat",
                base="project",
                rel=".cursor/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="grok.user.cursor_compat",
                scope="compat",
                base="home",
                rel=".cursor/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
        ]
    if host == "kimi":
        return [
            DiscoveryRoot(
                root_id="kimi.project.agents",
                scope="compat",
                base="project",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="kimi.user.agents",
                scope="compat",
                base="home",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="kimi.user.config_agents_legacy",
                scope="compat",
                base="home",
                rel=".config/agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
        ]
    if host == "pi":
        return [
            DiscoveryRoot(
                root_id="pi.project.agents",
                scope="compat",
                base="project",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
            DiscoveryRoot(
                root_id="pi.user.agents",
                scope="compat",
                base="home",
                rel=".agents/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
        ]
    if host == "codex":
        # Legacy community layout; precedence vs .agents unproven.
        return [
            DiscoveryRoot(
                root_id="codex.user.legacy_codex_skills",
                scope="compat",
                base="home",
                rel=".codex/skills",
                precedence=None,
                managed_by="host",
                role="alternate",
            ),
        ]
    if host == "qwen":
        # Extension-provided skills use dynamic extension ids — not fixed roots.
        # Plugin coexistence is report-only without scanning extension trees.
        return []
    if host == "claude":
        return []
    return []


def resolve_discovery_path(
    entry: DiscoveryRoot,
    *,
    project_dir: str | None,
    home_dir: str,
) -> str | None:
    """Resolve *entry* to an absolute path, or None when base is unavailable."""

    if entry.base == "project":
        if not project_dir:
            return None
        base = os.path.realpath(project_dir)
        return os.path.join(base, *entry.rel.split("/"))
    if entry.base == "home":
        base = os.path.realpath(home_dir)
        return os.path.join(base, *entry.rel.split("/"))
    return None


def _safe_display_path(path: str, *, project_dir: str | None, home_dir: str) -> str:
    """Prefer project-relative or home-relative display; never invent tilde expansion."""

    try:
        real = os.path.realpath(path)
    except OSError:
        return path
    if project_dir:
        try:
            pref = os.path.realpath(project_dir)
            if real == pref or real.startswith(pref + os.sep):
                rel = os.path.relpath(real, pref)
                return rel if rel != "." else "."
        except (OSError, ValueError):
            pass
    try:
        home = os.path.realpath(home_dir)
        if real == home or real.startswith(home + os.sep):
            rel = os.path.relpath(real, home)
            return f"$HOME/{rel}" if rel != "." else "$HOME"
    except (OSError, ValueError):
        pass
    # Fallback: basename chain only (avoid leaking full unrelated paths).
    return os.path.basename(real) or real


def _read_regular_capped(path: str, *, max_bytes: int) -> bytes | None:
    """Read a regular non-symlink file up to *max_bytes*; None if unsafe/missing."""

    try:
        st = os.lstat(path)
    except OSError:
        return None
    if stat_mod.S_ISLNK(st.st_mode) or not stat_mod.S_ISREG(st.st_mode):
        return None
    if st.st_size > max_bytes:
        return None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        if os.path.islink(path):
            return None
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        except OSError:
            return None
    try:
        st = os.fstat(fd)
        if not stat_mod.S_ISREG(st.st_mode):
            return None
        if st.st_size > max_bytes:
            return None
        chunks: list[bytes] = []
        remaining = max_bytes
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def inspect_skill_copy(
    skill_root: str,
    skill_name: str,
    *,
    expected_payload_digest: str | None = None,
) -> dict[str, Any]:
    """Bounded read-only inspection of ``<skill_root>/<skill_name>``."""

    skill_dir = os.path.join(skill_root, skill_name)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    runner = os.path.join(skill_dir, "scripts", "run_reader.py")
    result: dict[str, Any] = {
        "skill": skill_name,
        "present": False,
        "owned": False,
        "unsafe": False,
        "skill_md_sha256": None,
        "runner_sha256": None,
        "payload_fingerprint": None,
        "bundle_version": None,
        "package_identity": None,
        "matches_expected": None,
    }
    try:
        st_dir = os.lstat(skill_dir)
    except OSError:
        return result
    if stat_mod.S_ISLNK(st_dir.st_mode):
        result["present"] = True
        result["unsafe"] = True
        return result
    if not stat_mod.S_ISDIR(st_dir.st_mode):
        result["present"] = True
        result["unsafe"] = True
        return result
    try:
        st_md = os.lstat(skill_md)
    except OSError:
        # Directory exists without SKILL.md — treat as foreign/unverifiable present.
        result["present"] = True
        return result
    if stat_mod.S_ISLNK(st_md.st_mode) or not stat_mod.S_ISREG(st_md.st_mode):
        result["present"] = True
        result["unsafe"] = True
        return result
    result["present"] = True
    body = _read_regular_capped(skill_md, max_bytes=_MAX_SKILL_MD_BYTES)
    if body is None:
        result["unsafe"] = True
        return result
    result["skill_md_sha256"] = hashlib.sha256(body).hexdigest()
    runner_body = _read_regular_capped(runner, max_bytes=_MAX_RUNNER_BYTES)
    if runner_body is not None:
        result["runner_sha256"] = hashlib.sha256(runner_body).hexdigest()
    # Fingerprint = skill.md (+ runner when present); not full package identity.
    fp = hashlib.sha256()
    fp.update(result["skill_md_sha256"].encode("ascii"))
    if result["runner_sha256"]:
        fp.update(result["runner_sha256"].encode("ascii"))
    result["payload_fingerprint"] = fp.hexdigest()

    # Ownership / package identity from sibling support tree when present.
    # Lazy import: load_manifest lives in transaction (avoids import cycle).
    from .transaction import load_manifest

    manifest = load_manifest(skill_root)
    if manifest is not None and manifest.claims:
        result["owned"] = True
        result["bundle_version"] = manifest.bundle_version
        result["package_identity"] = manifest.package_identity
        if expected_payload_digest is not None:
            result["matches_expected"] = manifest.package_identity == expected_payload_digest
    elif expected_payload_digest is not None and result["payload_fingerprint"]:
        # Foreign/unowned copy cannot claim full package identity match.
        result["matches_expected"] = False
    return result


def _expected_skill_fingerprint(host: str, skill_name: str) -> tuple[str, str]:
    """Return (package_identity, skill_pair_fingerprint) for current bundle."""

    files = materialize_plan(host)
    identity = package_identity(files)
    skill_md = files.get(f"{skill_name}/SKILL.md", b"")
    runner = files.get(f"{skill_name}/scripts/run_reader.py", b"")
    fp = hashlib.sha256()
    fp.update(hashlib.sha256(skill_md).hexdigest().encode("ascii"))
    if runner:
        fp.update(hashlib.sha256(runner).hexdigest().encode("ascii"))
    return identity, fp.hexdigest()


def scan_skill_duplicates(
    *,
    host: str,
    selected_root: str,
    project_dir: str | None,
    home_dir: str,
    skill_names: Iterable[str] | None = None,
    selected_scope: str | None = None,
) -> dict[str, Any]:
    """Scan known discovery roots for same-name ``resume-*`` Skills vs *selected_root*.

    Read-only. Does not create support dirs. Does not follow skill-dir symlinks
    into content hashing.
    """

    if host not in HOST_PROFILES:
        raise DiagnosticError.invalid()
    names = tuple(skill_names) if skill_names is not None else SOURCE_SKILL_NAMES
    for name in names:
        if not name.startswith("resume-") or name not in SOURCE_SKILL_NAMES:
            raise DiagnosticError.invalid()

    selected_real = os.path.realpath(selected_root)
    expected_identity, _ = _expected_skill_fingerprint(
        host, names[0] if names else skill_name_for(sorted(SOURCE_KEYS)[0])
    )
    skill_fps = {name: _expected_skill_fingerprint(host, name)[1] for name in names}

    roots = discovery_roots_for_host(host)
    findings: list[dict[str, Any]] = []
    root_rows: list[dict[str, Any]] = []
    seen_physical: dict[str, str] = {}  # realpath -> first root_id

    # Record selected root precedence from policy (best matching entry).
    selected_prec: int | None = None
    for entry in roots:
        path = resolve_discovery_path(entry, project_dir=project_dir, home_dir=home_dir)
        if path is None:
            continue
        try:
            if os.path.realpath(path) == selected_real:
                selected_prec = entry.precedence
                break
        except OSError:
            continue
    if selected_prec is None and selected_scope == "project":
        selected_prec = 5
    elif selected_prec is None and selected_scope == "global":
        selected_prec = 10
    _SELECTED_PRECEDENCE[selected_real] = selected_prec

    try:
        return _scan_skill_duplicates_body(
            host=host,
            selected_real=selected_real,
            selected_root=selected_root,
            project_dir=project_dir,
            home_dir=home_dir,
            selected_scope=selected_scope,
            names=names,
            expected_identity=expected_identity,
            skill_fps=skill_fps,
            roots=roots,
            findings=findings,
            root_rows=root_rows,
            seen_physical=seen_physical,
        )
    finally:
        _SELECTED_PRECEDENCE.pop(selected_real, None)


def _scan_skill_duplicates_body(
    *,
    host: str,
    selected_real: str,
    selected_root: str,
    project_dir: str | None,
    home_dir: str,
    selected_scope: str | None,
    names: tuple[str, ...],
    expected_identity: str,
    skill_fps: dict[str, str],
    roots: tuple[DiscoveryRoot, ...],
    findings: list[dict[str, Any]],
    root_rows: list[dict[str, Any]],
    seen_physical: dict[str, str],
) -> dict[str, Any]:
    for entry in roots:
        path = resolve_discovery_path(entry, project_dir=project_dir, home_dir=home_dir)
        row: dict[str, Any] = {
            **entry.to_dict(),
            "resolved": path is not None,
            "path_display": None,
            "exists": False,
            "is_selected": False,
            "physical_key": None,
        }
        if path is None:
            root_rows.append(row)
            continue
        display = _safe_display_path(path, project_dir=project_dir, home_dir=home_dir)
        row["path_display"] = display
        try:
            real = os.path.realpath(path)
        except OSError:
            root_rows.append(row)
            continue
        row["physical_key"] = hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]
        row["is_selected"] = real == selected_real
        try:
            st = os.lstat(path)
            row["exists"] = stat_mod.S_ISDIR(st.st_mode) and not stat_mod.S_ISLNK(st.st_mode)
            if stat_mod.S_ISLNK(st.st_mode):
                row["exists"] = True
                row["symlink_root"] = True
        except OSError:
            row["exists"] = False
        # Dedupe identical physical roots under different policy ids.
        if row["exists"] and not row.get("symlink_root"):
            prior = seen_physical.get(real)
            if prior is None:
                seen_physical[real] = entry.root_id
            else:
                row["same_physical_as"] = prior
        root_rows.append(row)

        if not row["exists"] or row.get("symlink_root"):
            if row.get("symlink_root"):
                for skill in names:
                    findings.append(
                        {
                            "skill": skill,
                            "root_id": entry.root_id,
                            "path_display": display,
                            "status": STATUS_UNSAFE,
                            "policy": POLICY_WARN,
                            "detail": "symlink_skill_root",
                            "is_selected": row["is_selected"],
                        }
                    )
            continue

        for skill in names:
            inspection = inspect_skill_copy(
                path,
                skill,
                expected_payload_digest=expected_identity,
            )
            if not inspection["present"]:
                continue
            status, policy, detail = _classify_copy(
                inspection=inspection,
                entry=entry,
                is_selected=row["is_selected"],
                selected_real=selected_real,
                root_real=real,
                expected_fp=skill_fps[skill],
                same_physical_prior=row.get("same_physical_as"),
            )
            if status is None:
                continue
            findings.append(
                {
                    "skill": skill,
                    "root_id": entry.root_id,
                    "role": entry.role,
                    "scope": entry.scope,
                    "precedence": entry.precedence,
                    "path_display": display,
                    "status": status,
                    "policy": policy,
                    "detail": detail,
                    "is_selected": row["is_selected"],
                    "owned": inspection["owned"],
                    "unsafe": inspection["unsafe"],
                    "payload_fingerprint": inspection["payload_fingerprint"],
                    "package_identity": inspection["package_identity"],
                    "bundle_version": inspection["bundle_version"],
                    "matches_expected": inspection["matches_expected"],
                }
            )

    # Aggregate worst status for the selected install target.
    blocking = [f for f in findings if f["policy"] == POLICY_BLOCK and not f.get("is_selected")]
    warnings = [f for f in findings if f["policy"] == POLICY_WARN and not f.get("is_selected")]
    selected_findings = [f for f in findings if f.get("is_selected")]

    if blocking:
        aggregate = STATUS_HIGHER_SHADOW
        aggregate_policy = POLICY_BLOCK
    elif any(f["status"] == STATUS_PRECEDENCE_UNKNOWN for f in findings if not f.get("is_selected")):
        aggregate = STATUS_PRECEDENCE_UNKNOWN
        aggregate_policy = POLICY_WARN
    elif any(f["status"] == STATUS_DUP_DIFFERENT for f in findings if not f.get("is_selected")):
        aggregate = STATUS_DUP_DIFFERENT
        aggregate_policy = POLICY_WARN
    elif any(f["status"] == STATUS_DUP_FOREIGN for f in findings if not f.get("is_selected")):
        aggregate = STATUS_DUP_FOREIGN
        aggregate_policy = POLICY_WARN
    elif any(f["status"] == STATUS_DUP_IDENTICAL for f in findings if not f.get("is_selected")):
        aggregate = STATUS_DUP_IDENTICAL
        aggregate_policy = POLICY_ALLOW
    elif any(f["status"] == STATUS_SAME_PHYSICAL for f in findings if not f.get("is_selected")):
        aggregate = STATUS_SAME_PHYSICAL
        aggregate_policy = POLICY_ALLOW
    elif selected_findings or any(f.get("is_selected") for f in findings):
        aggregate = STATUS_UNIQUE
        aggregate_policy = POLICY_ALLOW
    else:
        # No selected skill present yet (pre-install) and no alternate copies.
        aggregate = STATUS_UNIQUE
        aggregate_policy = POLICY_ALLOW

    return {
        "schema_version": "portable-resume/discovery-scan-v1",
        "host": host,
        "profile_id": HOST_PROFILES[host].profile_id,
        "bundle_version": BUNDLE_VERSION,
        "selected_root_display": _safe_display_path(
            selected_root, project_dir=project_dir, home_dir=home_dir
        ),
        "selected_scope": selected_scope,
        "expected_package_identity": expected_identity,
        "skills_scanned": list(names),
        "discovery_roots": root_rows,
        "findings": findings,
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "aggregate_status": aggregate,
        "aggregate_policy": aggregate_policy,
        "ok": aggregate_policy != POLICY_BLOCK,
    }


def _classify_copy(
    *,
    inspection: dict[str, Any],
    entry: DiscoveryRoot,
    is_selected: bool,
    selected_real: str,
    root_real: str,
    expected_fp: str,
    same_physical_prior: str | None,
) -> tuple[str | None, str, str]:
    """Return (status, policy, detail). None status = skip (selected-only bookkeeping)."""

    if inspection.get("unsafe"):
        return STATUS_UNSAFE, POLICY_WARN, "symlink_or_non_regular"

    fp = inspection.get("payload_fingerprint")
    owned = bool(inspection.get("owned"))
    matches_pkg = inspection.get("matches_expected")
    identical = False
    if owned and matches_pkg is True:
        identical = True
    elif fp is not None and fp == expected_fp:
        identical = True

    if is_selected:
        # Selected root presence is informational for audit; not a duplicate of itself.
        if identical or owned:
            return "selected_present", POLICY_ALLOW, "selected_root"
        return "selected_present", POLICY_ALLOW, "selected_foreign_or_partial"

    if same_physical_prior or root_real == selected_real:
        return STATUS_SAME_PHYSICAL, POLICY_ALLOW, "same_physical_root"

    if identical:
        if entry.scope == "plugin":
            return STATUS_PLUGIN_COEXIST, POLICY_REPORT_ONLY, "identical_plugin"
        return STATUS_DUP_IDENTICAL, POLICY_ALLOW, "identical_payload"

    # Divergent or foreign at non-selected root.
    if entry.role == "plugin" or entry.scope == "plugin":
        return STATUS_PLUGIN_COEXIST, POLICY_WARN, "plugin_divergent_or_foreign"

    # Selected root tier: project primary/alt = 5, user primary/alt = 10.
    # Callers attach selected_scope via scan; fall back using path equality.
    selected_prec = _selected_precedence_hint(selected_real, entry, root_real)
    other_prec = entry.precedence

    if other_prec is not None and selected_prec is not None and other_prec < selected_prec:
        # Strictly higher precedence (lower number) with divergent content → block.
        if not identical:
            return STATUS_HIGHER_SHADOW, POLICY_BLOCK, "higher_precedence_divergent"
    if other_prec is None or selected_prec is None:
        if owned or fp:
            return STATUS_PRECEDENCE_UNKNOWN, POLICY_WARN, "unknown_precedence_divergent"
        return STATUS_DUP_FOREIGN, POLICY_WARN, "foreign_unverifiable"
    if other_prec == selected_prec and not identical:
        # Equal first-class roots (e.g. Cursor .cursor vs .agents) — warn, do not block.
        if owned:
            return STATUS_DUP_DIFFERENT, POLICY_WARN, "equal_precedence_divergent"
        return STATUS_DUP_FOREIGN, POLICY_WARN, "equal_precedence_foreign"
    # Lower precedence alternate with divergent content: warn only.
    if owned:
        return STATUS_DUP_DIFFERENT, POLICY_WARN, "lower_precedence_divergent"
    return STATUS_DUP_FOREIGN, POLICY_WARN, "lower_precedence_foreign"


def _selected_precedence_hint(
    selected_real: str,
    entry: DiscoveryRoot,
    root_real: str,
) -> int | None:
    """Infer selected root precedence from scan context.

    Discovery scan compares each *other* root against the selected path. The
    selected path's precedence is not carried on *entry* (which is the other
    root). We reconstruct it from the selected path's known policy rows via a
    module-level hint set by ``scan_skill_duplicates``.
    """

    hint = _SELECTED_PRECEDENCE.get(selected_real)
    if hint is not None:
        return hint
    # Fallback: if comparing within same scope tier as entry, treat equal.
    return entry.precedence if root_real == selected_real else 10





def require_no_blocking_shadow(
    *,
    host: str,
    selected_root: str,
    project_dir: str | None,
    home_dir: str,
    selected_scope: str | None = None,
) -> dict[str, Any]:
    """Run discovery scan; raise ``E_INSTALL_SHADOW`` when policy is block."""

    report = scan_skill_duplicates(
        host=host,
        selected_root=selected_root,
        project_dir=project_dir,
        home_dir=home_dir,
        selected_scope=selected_scope,
    )
    if report["aggregate_policy"] == POLICY_BLOCK:
        blockers = [
            f["root_id"]
            for f in report["findings"]
            if f.get("policy") == POLICY_BLOCK and not f.get("is_selected")
        ]
        raise DiagnosticError("E_INSTALL_SHADOW", family=tuple(blockers[:8]))
    return report


def audit_host_report(
    *,
    host: str,
    scope: str,
    project_dir: str | None,
    home_dir: str,
    root: str | None = None,
) -> dict[str, Any]:
    """Full read-only audit for one host/scope (CLI ``audit-host``)."""

    from .catalog import resolve_skill_root

    if host not in HOST_PROFILES:
        raise DiagnosticError.invalid()
    if scope not in ("project", "global"):
        raise DiagnosticError.invalid()
    if root is None:
        selected = resolve_skill_root(
            host=host, scope=scope, project_dir=project_dir, home_dir=home_dir
        )
    else:
        selected = os.path.realpath(root)
    report = scan_skill_duplicates(
        host=host,
        selected_root=selected,
        project_dir=project_dir,
        home_dir=home_dir,
        selected_scope=scope,
    )
    report["command"] = "audit-host"
    report["discovery_policy"] = [r.to_dict() for r in discovery_roots_for_host(host)]
    return report
