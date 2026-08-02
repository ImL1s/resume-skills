"""Repository / worktree aware workspace matching (#154).

Uses filesystem inspection of ``.git`` only — no subprocess and no source
agent CLIs (security isolation contract).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from .diagnostics import DiagnosticError
from .model import SessionSummary
from .paths import canonicalize_cwd, same_cwd

WorkspaceMode = Literal["exact", "worktree", "repository"]
WORKSPACE_MODES: tuple[str, ...] = ("exact", "worktree", "repository")


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    cwd: str
    worktree_root: str | None
    git_common_dir: str | None
    mode: str


def _read_git_dir(start: str) -> tuple[str | None, str | None]:
    """Return (worktree_root, git_common_dir) by walking parents for ``.git``.

    - ``.git`` directory → worktree root is parent; common dir is ``.git``
    - ``.git`` file with ``gitdir: ...`` → worktree root is parent; resolve gitdir
    """

    current = canonicalize_cwd(start)
    for _ in range(64):
        git_entry = os.path.join(current, ".git")
        if os.path.isdir(git_entry) and not os.path.islink(git_entry):
            return current, canonicalize_cwd(git_entry)
        if os.path.isfile(git_entry) and not os.path.islink(git_entry):
            try:
                text = open(git_entry, "r", encoding="utf-8").read().strip()
            except OSError:
                return current, None
            if text.lower().startswith("gitdir:"):
                raw = text.split(":", 1)[1].strip()
                if not raw:
                    return current, None
                gitdir = raw if os.path.isabs(raw) else os.path.join(current, raw)
                try:
                    return current, canonicalize_cwd(gitdir)
                except DiagnosticError:
                    return current, None
            return current, None
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None, None


def resolve_workspace(cwd: str, *, mode: str = "exact") -> WorkspaceIdentity:
    if mode not in WORKSPACE_MODES:
        raise DiagnosticError.invalid()
    resolved = canonicalize_cwd(cwd)
    worktree, common = _read_git_dir(resolved)
    return WorkspaceIdentity(
        cwd=resolved,
        worktree_root=worktree,
        git_common_dir=common,
        mode=mode,
    )


def _candidate_under(root: str | None, candidate_cwd: str | None) -> bool:
    if root is None or candidate_cwd is None:
        return False
    try:
        cand = canonicalize_cwd(candidate_cwd)
        base = canonicalize_cwd(root)
    except DiagnosticError:
        return False
    try:
        return os.path.commonpath((cand, base)) == base
    except ValueError:
        return False


def workspace_match(
    summary: SessionSummary,
    identity: WorkspaceIdentity,
) -> tuple[bool, str]:
    """Return (matched, reason) for explainable selection."""

    mode = identity.mode
    if mode == "exact":
        if summary.cwd is None:
            return True, "no-cwd-eligible"
        if same_cwd(summary.cwd, identity.cwd):
            return True, "exact-cwd"
        return False, "cwd-mismatch"
    if mode == "worktree":
        if identity.worktree_root is None:
            if summary.cwd is None or same_cwd(summary.cwd, identity.cwd):
                return True, "worktree-fallback-exact"
            return False, "not-a-git-worktree"
        if summary.cwd is None:
            return True, "no-cwd-eligible"
        if _candidate_under(identity.worktree_root, summary.cwd):
            return True, "same-worktree"
        return False, "other-worktree-or-repo"
    if mode == "repository":
        if identity.git_common_dir is None:
            if summary.cwd is None or same_cwd(summary.cwd, identity.cwd):
                return True, "repository-fallback-exact"
            return False, "not-a-git-repository"
        if summary.cwd is None:
            return True, "no-cwd-eligible"
        try:
            cand_root = canonicalize_cwd(summary.cwd)
        except DiagnosticError:
            return False, "invalid-candidate-cwd"
        _wt, cand_common = _read_git_dir(cand_root)
        if cand_common is None:
            return False, "candidate-not-git"
        if cand_common == identity.git_common_dir:
            return True, "same-repository"
        return False, "other-repository"
    raise DiagnosticError.invalid()


def filter_by_workspace(
    summaries: list[SessionSummary],
    identity: WorkspaceIdentity,
) -> list[tuple[SessionSummary, str]]:
    out: list[tuple[SessionSummary, str]] = []
    for row in summaries:
        ok, reason = workspace_match(row, identity)
        if ok:
            out.append((row, reason))
    return out


def explain_project(cwd: str | None = None) -> dict[str, object]:
    resolved = canonicalize_cwd(cwd or os.getcwd())
    identity = resolve_workspace(resolved, mode="repository")
    return {
        "schema_version": "portable-resume/project-explain-v1",
        "cwd": identity.cwd,
        "worktree_root": identity.worktree_root,
        "git_common_dir": identity.git_common_dir,
        "is_git": identity.git_common_dir is not None,
        "modes": {
            "exact": "canonical cwd equality (default isolation)",
            "worktree": "match sessions under the current git worktree root",
            "repository": "match sessions sharing the same git common dir (all worktrees)",
        },
    }
