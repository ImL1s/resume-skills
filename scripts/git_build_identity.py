"""Git-aware build identity adapter for explicit build/release tooling only."""

from __future__ import annotations

import hashlib
import re
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume.build_identity import build_identity  # noqa: E402
from portable_resume.diagnostics import DiagnosticError  # noqa: E402
from portable_resume.snapshot import stable_read_bytes  # noqa: E402

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_ROOT_BUILD_INPUTS = (
    "LICENSE",
    "MANIFEST.in",
    "NOTICE",
    "README.md",
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "scripts/build_artifact_identity.py",
    "scripts/build_host_packages.py",
    "scripts/git_build_identity.py",
)
_GENERATED_IDENTITY = Path("resources/build-identity.json")
MAX_BUILD_INPUT_FILE_BYTES = 64 * 1024 * 1024
MAX_BUILD_INPUT_TOTAL_BYTES = 256 * 1024 * 1024


def _git(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def _relevant_other_files(
    output: str,
    *,
    package_relative: Path,
) -> tuple[str, ...]:
    """Filter untracked/ignored Git output to byte-affecting build inputs."""
    relevant: list[str] = []
    root_inputs = {Path(value) for value in _ROOT_BUILD_INPUTS}
    for raw in output.split("\0"):
        if not raw:
            continue
        candidate = Path(raw)
        if candidate in root_inputs:
            relevant.append(raw)
            continue
        try:
            relative = candidate.relative_to(package_relative)
        except ValueError:
            continue
        if (
            "__pycache__" in relative.parts
            or relative == _GENERATED_IDENTITY
            or relative.suffix in {".pyc", ".pyo"}
        ):
            continue
        relevant.append(raw)
    return tuple(relevant)


def build_inputs_sha256(repo_root: Path) -> str:
    """Hash all non-package inputs that can affect produced artifact bytes."""
    repository = repo_root.resolve()
    digest = hashlib.sha256()
    total_bytes = 0
    for relative_name in _ROOT_BUILD_INPUTS:
        relative = Path(relative_name)
        path = repository / relative
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            digest.update(b"missing\0")
            continue
        except OSError as error:
            raise ValueError("build input is unreadable") from error
        try:
            data = stable_read_bytes(
                path,
                root=repository,
                max_bytes=MAX_BUILD_INPUT_FILE_BYTES,
            ).data
        except DiagnosticError as error:
            raise ValueError("build input is not a bounded stable regular file") from error
        total_bytes += len(data)
        if total_bytes > MAX_BUILD_INPUT_TOTAL_BYTES:
            raise ValueError("build inputs exceed the aggregate bound")
        digest.update(b"present\0")
        digest.update(stat.S_IMODE(metadata.st_mode).to_bytes(4, "big"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def git_facts(
    repo_root: Path,
    *,
    package_root: Path,
    base_version: str,
) -> tuple[str | None, bool | None, bool, str | None]:
    """Collect bounded Git facts without discovering unrelated parent repos."""
    repository = repo_root.resolve()
    package = package_root.resolve()
    if not (repository / ".git").exists():
        return None, None, False, None
    try:
        package_relative = package.relative_to(repository)
    except ValueError:
        return None, None, False, None
    head = _git(repository, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0 or _HEX_40.fullmatch(head.stdout.strip()) is None:
        return None, None, False, None
    tracked = _git(repository, "status", "--porcelain=v1", "--untracked-files=no")
    if tracked.returncode != 0:
        return None, None, False, None
    pathspecs = [package_relative.as_posix(), *_ROOT_BUILD_INPUTS]
    ordinary = _git(
        repository,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        *pathspecs,
    )
    ignored = _git(
        repository,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        *pathspecs,
    )
    if ordinary.returncode != 0 or ignored.returncode != 0:
        return None, None, False, None
    commit_sha = head.stdout.strip()
    other_files = {
        *_relevant_other_files(
            ordinary.stdout,
            package_relative=package_relative,
        ),
        *_relevant_other_files(
            ignored.stdout,
            package_relative=package_relative,
        ),
    }
    dirty = bool(tracked.stdout or other_files)
    tag_ref = f"refs/tags/v{base_version}"
    tag_type = _git(repository, "cat-file", "-t", tag_ref)
    tag_commit = _git(repository, "rev-parse", f"{tag_ref}^{{commit}}")
    exact_tag = (
        tag_type.returncode == 0
        and tag_type.stdout.strip() == "tag"
        and tag_commit.returncode == 0
        and tag_commit.stdout.strip() == commit_sha
    )
    return commit_sha, dirty, exact_tag, build_inputs_sha256(repository)


def git_build_identity(
    *,
    repo_root: Path = REPO,
    package_root: Path = SRC / "portable_resume",
    base_version: str | None = None,
) -> dict[str, object]:
    """Build an identity using explicit Git facts when a checkout is present."""
    if base_version is None:
        from portable_resume import __version__

        base_version = __version__
    commit_sha, dirty, exact_tag, build_inputs_digest = git_facts(
        repo_root,
        package_root=package_root,
        base_version=base_version,
    )
    return build_identity(
        package_root=package_root,
        base_version=base_version,
        commit_sha=commit_sha,
        dirty=dirty,
        exact_tag=exact_tag,
        build_inputs_sha256=build_inputs_digest,
    )
