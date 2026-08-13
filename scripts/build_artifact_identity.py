"""Resolve and stage one canonical identity for every artifact builder."""

from __future__ import annotations

import hashlib
import gzip
import os
import re
import stat
import tarfile
import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Iterator, Mapping

from portable_resume.build_identity import (
    assert_identity_matches_package,
    identity_json_bytes,
    load_identity_file,
    validate_current_identity,
)
try:
    from scripts.git_build_identity import git_build_identity
except ModuleNotFoundError:  # setup.py adds scripts/ directly during PEP 517 builds
    from git_build_identity import git_build_identity

IDENTITY_FILE_ENV = "PORTABLE_RESUME_BUILD_IDENTITY_FILE"
IDENTITY_SHA256_ENV = "PORTABLE_RESUME_BUILD_IDENTITY_SHA256"
EMBEDDED_IDENTITY = Path("resources/build-identity.json")
_STABLE_BASE_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MAX_SDIST_FILE_BYTES = 64 * 1024 * 1024
MAX_SDIST_TOTAL_BYTES = 512 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@contextmanager
def reproducible_build_umask() -> Iterator[None]:
    """Give generated public build files stable POSIX permissions."""

    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def identity_sha256(identity: Mapping[str, Any]) -> str:
    return hashlib.sha256(identity_json_bytes(identity)).hexdigest()


def resolve_build_identity(
    *,
    repo_root: Path,
    package_root: Path,
    identity_file: str | Path | None = None,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    """Resolve explicit pin, embedded sdist identity, or checkout fallback."""
    if identity_file is not None or expected_sha256 is not None:
        selected_file = identity_file
        selected_digest = expected_sha256
    else:
        selected_file = os.environ.get(IDENTITY_FILE_ENV)
        selected_digest = os.environ.get(IDENTITY_SHA256_ENV)
    if (selected_file is None) != (selected_digest is None):
        raise ValueError("build identity file and digest must be provided together")

    package = package_root.resolve()
    if selected_file is not None and selected_digest is not None:
        identity = load_identity_file(
            selected_file,
            expected_sha256=selected_digest,
        )
    else:
        embedded = package / EMBEDDED_IDENTITY
        try:
            identity = load_identity_file(embedded)
        except FileNotFoundError:
            identity = git_build_identity(
                repo_root=repo_root,
                package_root=package,
            )
    validate_current_identity(identity)
    assert_identity_matches_package(identity, package_root=package)
    repository = Path(repo_root).resolve()
    if (repository / ".git").exists():
        current_identity = git_build_identity(
            repo_root=repository,
            package_root=package,
            base_version=str(identity["base_version"]),
        )
        if current_identity.get("commit_sha") is None:
            raise ValueError("Git checkout identity cannot be revalidated")
        if current_identity != identity:
            raise ValueError("build checkout changed after identity pinning")
    base_version = str(identity["base_version"])
    if (
        _STABLE_BASE_VERSION.fullmatch(base_version) is not None
        and identity.get("release_channel") != "release"
    ):
        # Release.yml never sets this: published bytes still require exact-tag
        # release identity. CI package jobs may set it so a pre-tag release
        # candidate (exact X.Y.Z on main before annotated vX.Y.Z exists) can
        # still smoke wheel/sdist/host archives under a development-channel pin.
        if os.environ.get("PORTABLE_RESUME_ALLOW_STABLE_DEVELOPMENT_IDENTITY") != "1":
            raise ValueError("stable artifacts require an exact release identity")
    return identity


def _source_date_epoch() -> int | None:
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdigit():
        raise ValueError("SOURCE_DATE_EPOCH must be a non-negative integer")
    value = int(raw)
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("SOURCE_DATE_EPOCH must fit an unsigned 32-bit timestamp")
    return value


def _stat_fingerprint(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _is_link_or_reparse(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _open_optional_real_directory(
    path: str | Path,
    *,
    dir_fd: int | None = None,
    subject: str,
) -> int | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(f"{subject} is not a real directory") from error
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode) or _is_link_or_reparse(opened):
        os.close(descriptor)
        raise ValueError(f"{subject} is not a real directory")
    return descriptor


def _refresh_generated_build_identity_by_descriptor(build_root: Path) -> bool:
    descriptors: list[int] = []
    try:
        for component, subject in (
            (build_root, "setuptools build root"),
            ("portable_resume", "setuptools package staging directory"),
            ("resources", "setuptools resource staging directory"),
        ):
            descriptor = _open_optional_real_directory(
                component,
                dir_fd=descriptors[-1] if descriptors else None,
                subject=subject,
            )
            if descriptor is None:
                return False
            descriptors.append(descriptor)
        try:
            existing = os.stat(
                "build-identity.json",
                dir_fd=descriptors[-1],
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(existing.st_mode) or _is_link_or_reparse(existing):
            raise ValueError("generated setuptools build identity is not a regular file")
        try:
            os.unlink("build-identity.json", dir_fd=descriptors[-1])
        except OSError as error:
            raise ValueError(
                "generated setuptools build identity could not be refreshed"
            ) from error
        return True
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _refresh_generated_build_identity_by_path(build_root: Path) -> bool:
    package = build_root / "portable_resume"
    resources = package / "resources"
    for directory, subject in (
        (build_root, "setuptools build root"),
        (package, "setuptools package staging directory"),
        (resources, "setuptools resource staging directory"),
    ):
        try:
            metadata = directory.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISDIR(metadata.st_mode) or _is_link_or_reparse(metadata):
            raise ValueError(f"{subject} is not a real directory")
    destination = resources / "build-identity.json"
    try:
        existing = destination.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(existing.st_mode) or _is_link_or_reparse(existing):
        raise ValueError("generated setuptools build identity is not a regular file")
    try:
        destination.unlink()
    except OSError as error:
        raise ValueError(
            "generated setuptools build identity could not be refreshed"
        ) from error
    return True


def refresh_generated_build_identity(build_root: Path) -> bool:
    """Remove only build_py's generated identity from its reusable staging tree.

    Finalized artifact trees still use :func:`write_staged_identity` and retain
    its exact-identity refusal.  This narrower operation is only for the
    disposable ``build_py --build-lib`` tree, before package sources are copied.
    """

    root = Path(build_root)
    descriptor_operations = (
        os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )
    if descriptor_operations:
        return _refresh_generated_build_identity_by_descriptor(root)
    return _refresh_generated_build_identity_by_path(root)


def _read_staged_regular_file(path: Path, before: os.stat_result) -> bytes:
    if before.st_size > MAX_SDIST_FILE_BYTES:
        raise ValueError("sdist release file exceeds the per-file bound")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("sdist release file is unreadable") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _stat_fingerprint(opened) != _stat_fingerprint(before)
        ):
            raise ValueError("sdist release file changed before open")
        chunks: list[bytes] = []
        remaining = MAX_SDIST_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(data) > MAX_SDIST_FILE_BYTES:
            raise ValueError("sdist release file exceeds the per-file bound")
        if _stat_fingerprint(after) != _stat_fingerprint(opened):
            raise ValueError("sdist release file changed during read")
    finally:
        os.close(descriptor)
    try:
        final = path.lstat()
    except OSError as error:
        raise ValueError("sdist release file changed after read") from error
    if _stat_fingerprint(final) != _stat_fingerprint(opened):
        raise ValueError("sdist release file changed after read")
    return data


def write_staged_identity(
    path: Path,
    identity: Mapping[str, Any],
) -> bytes:
    """Write canonical bytes inside an artifact staging tree without symlinks."""
    validate_current_identity(identity)
    data = identity_json_bytes(identity)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = destination.lstat()
    except FileNotFoundError:
        current = None
    if current is not None:
        if not stat.S_ISREG(current.st_mode):
            raise ValueError("staged identity destination is not a regular file")
        try:
            loaded = load_identity_file(
                destination,
                expected_sha256=hashlib.sha256(data).hexdigest(),
            )
        except ValueError as error:
            raise ValueError("staged identity differs from the pinned identity") from error
        if identity_json_bytes(loaded) != data:
            raise ValueError("staged identity differs from the pinned identity")
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".build-identity-",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    epoch = _source_date_epoch()
    if epoch is not None:
        os.utime(destination, (epoch, epoch), follow_symlinks=False)
    return data


def stage_package_identity(
    package_root: Path,
    identity: Mapping[str, Any],
) -> bytes:
    """Embed identity bytes, then prove the completed staged package matches."""
    package = Path(package_root)
    data = write_staged_identity(package / EMBEDDED_IDENTITY, identity)
    assert_identity_matches_package(identity, package_root=package)
    return data


def write_reproducible_sdist(
    archive_path: Path,
    tree_root: Path,
    *,
    archive_root_name: str,
) -> Path:
    """Write a deterministic tar.gz from one completed setuptools release tree."""
    archive_root = PurePosixPath(archive_root_name)
    if (
        not archive_root_name
        or archive_root.is_absolute()
        or "\\" in archive_root_name
        or len(archive_root.parts) != 1
        or archive_root.parts[0] in {".", ".."}
    ):
        raise ValueError("sdist archive root must be one safe path component")
    root = Path(tree_root)
    try:
        root_metadata = root.lstat()
    except OSError as error:
        raise ValueError("sdist release tree is unreadable") from error
    if root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("sdist release tree is not a real directory")

    entries = [root, *sorted(root.rglob("*"), key=lambda item: item.as_posix())]
    epoch = _source_date_epoch()
    normalized_epoch = 0 if epoch is None else epoch
    destination = Path(archive_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    total_bytes = 0
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=normalized_epoch,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as archive:
                    for entry in entries:
                        relative = entry.relative_to(root)
                        member_name = archive_root_name
                        if relative.parts:
                            member_name += f"/{relative.as_posix()}"
                        metadata = entry.lstat()
                        if entry.is_symlink():
                            raise ValueError("sdist release tree contains a symlink")
                        info = tarfile.TarInfo(member_name)
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = normalized_epoch
                        if stat.S_ISDIR(metadata.st_mode):
                            info.mode = 0o755
                            info.type = tarfile.DIRTYPE
                            info.size = 0
                            archive.addfile(info)
                        elif stat.S_ISREG(metadata.st_mode):
                            info.mode = (
                                0o755 if stat.S_IMODE(metadata.st_mode) & 0o111 else 0o644
                            )
                            data = _read_staged_regular_file(entry, metadata)
                            total_bytes += len(data)
                            if total_bytes > MAX_SDIST_TOTAL_BYTES:
                                raise ValueError("sdist release tree exceeds the total bound")
                            info.type = tarfile.REGTYPE
                            info.size = len(data)
                            archive.addfile(info, BytesIO(data))
                        else:
                            raise ValueError(
                                "sdist release tree contains a non-regular file"
                            )
            raw.flush()
            os.fsync(raw.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination


def write_external_identity(
    path: Path,
    identity: Mapping[str, Any],
) -> str:
    """Create/replace a private build pin and return its canonical digest."""
    validate_current_identity(identity)
    destination = Path(path)
    data = identity_json_bytes(identity)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = destination.lstat()
    except FileNotFoundError:
        current = None
    if current is not None and (
        destination.is_symlink() or not stat.S_ISREG(current.st_mode)
    ):
        raise ValueError("build identity output is not a regular file")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".build-identity-pin-",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return hashlib.sha256(data).hexdigest()
