#!/usr/bin/env python3
"""Verify one canonical build identity across distribution and host archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import struct
import sys
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable, Iterator

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume.build_identity import (  # noqa: E402
    MAX_BUILD_IDENTITY_BYTES,
    identity_json_bytes,
    load_identity_bytes,
    load_identity_file,
    validate_current_identity,
)
from portable_resume import __version__  # noqa: E402
from portable_resume.install.package_contracts import (  # noqa: E402
    MAX_ARCHIVE_MEMBERS,
    MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    PACKAGE_CONTRACTS_SCHEMA,
    RUNTIME_IDENTITY_RELATIVE,
    contract_for_package_type,
    contracts_report,
    read_bounded_zip_info,
)
from portable_resume.registry import (  # noqa: E402
    PACKAGE_SURFACES,
    enabled_destination_keys,
    enabled_package_keys,
)

REPORT_MAX_BYTES = 4 * 1024 * 1024
ARTIFACT_MAX_BYTES = 1024 * 1024 * 1024
ARTIFACT_MAX_MEMBERS = MAX_ARCHIVE_MEMBERS
ARTIFACT_MAX_UNCOMPRESSED_BYTES = MAX_ARCHIVE_UNCOMPRESSED_BYTES
ARTIFACT_MAX_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP_EOCD_SIZE = 22
_ZIP_MAX_COMMENT_BYTES = 0xFFFF
IDENTITY_PARTS = ("portable_resume", "resources", "build-identity.json")
WHEEL_IDENTITY_MEMBER = "portable_resume/resources/build-identity.json"
HOST_IDENTITY_MEMBERS = frozenset(
    {
        ".portable-resume/runtime/portable_resume/resources/build-identity.json",
        "skills/.portable-resume/runtime/portable_resume/resources/build-identity.json",
        (
            "plugins/portable-resume/skills/.portable-resume/runtime/"
            "portable_resume/resources/build-identity.json"
        ),
    }
)
SDIST_IDENTITY_TAIL = (
    "src",
    "portable_resume",
    "resources",
    "build-identity.json",
)


def _matches_identity_member(name: str) -> bool:
    return tuple(PurePosixPath(name).parts[-3:]) == IDENTITY_PARTS


def _valid_sdist_member(name: str) -> bool:
    pure = PurePosixPath(name)
    return (
        not pure.is_absolute()
        and "\\" not in name
        and ".." not in pure.parts
        and pure.as_posix() == name
        and len(pure.parts) == 5
        and tuple(pure.parts[1:]) == SDIST_IDENTITY_TAIL
    )


def _stat_fingerprint(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@contextmanager
def _open_stable_file(
    path: Path,
    *,
    max_bytes: int,
    subject: str,
) -> Iterator[tuple[BinaryIO, str]]:
    """Open and hash one bounded regular inode without following its final name."""
    try:
        before = path.lstat()
    except OSError as error:
        raise ValueError(f"{subject} is unreadable") from error
    if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
        raise ValueError(f"{subject} is not a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{subject} is unreadable") from error
    opened: os.stat_result | None = None
    try:
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size > max_bytes
                or _stat_fingerprint(opened) != _stat_fingerprint(before)
            ):
                raise ValueError(f"{subject} changed before open")
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"{subject} is oversized")
                digest.update(chunk)
            handle.seek(0)
            try:
                yield handle, digest.hexdigest()
            finally:
                after = os.fstat(handle.fileno())
                if _stat_fingerprint(after) != _stat_fingerprint(opened):
                    raise ValueError(f"{subject} changed during read")
    finally:
        if opened is None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        else:
            try:
                final_path = path.lstat()
            except OSError as error:
                raise ValueError(f"{subject} changed after read") from error
            if _stat_fingerprint(final_path) != _stat_fingerprint(opened):
                raise ValueError(f"{subject} changed after read")


def _read_exact_at(handle: BinaryIO, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0:
        raise ValueError("artifact is not a valid zip archive")
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("artifact is not a valid zip archive")
    return data


def _preflight_zip_archive(handle: BinaryIO) -> int:
    """Bound the ZIP entry table before ``zipfile`` materializes it."""
    handle.seek(0, os.SEEK_END)
    archive_size = handle.tell()
    tail_size = min(archive_size, _ZIP_EOCD_SIZE + _ZIP_MAX_COMMENT_BYTES)
    tail_offset = archive_size - tail_size
    tail = _read_exact_at(handle, tail_offset, tail_size)
    search_end = len(tail)
    while True:
        relative_eocd = tail.rfind(_ZIP_EOCD_SIGNATURE, 0, search_end)
        if relative_eocd < 0:
            raise ValueError("artifact is not a valid zip archive")
        if relative_eocd + _ZIP_EOCD_SIZE <= len(tail):
            candidate = tail[relative_eocd : relative_eocd + _ZIP_EOCD_SIZE]
            candidate_comment_size = struct.unpack_from("<H", candidate, 20)[0]
            if relative_eocd + _ZIP_EOCD_SIZE + candidate_comment_size == len(tail):
                eocd = candidate
                break
        search_end = relative_eocd
    (
        disk_number,
        central_disk,
        entries_on_disk,
        entries_total,
        central_size,
        central_offset,
        comment_size,
    ) = struct.unpack_from("<HHHHIIH", eocd, 4)
    if comment_size != candidate_comment_size:
        raise ValueError("artifact is not a valid zip archive")
    eocd_offset = tail_offset + relative_eocd
    if disk_number != 0 or central_disk != 0 or entries_on_disk != entries_total:
        raise ValueError("multi-disk ZIP artifacts are unsupported")

    needs_zip64 = (
        entries_total == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
    )
    if needs_zip64:
        locator = _read_exact_at(handle, eocd_offset - 20, 20)
        if locator[:4] != _ZIP64_LOCATOR_SIGNATURE:
            raise ValueError("artifact ZIP64 locator is invalid")
        locator_disk, zip64_offset, total_disks = struct.unpack_from(
            "<IQI", locator, 4
        )
        if locator_disk != 0 or total_disks != 1:
            raise ValueError("multi-disk ZIP64 artifacts are unsupported")
        zip64_eocd = _read_exact_at(handle, zip64_offset, 56)
        if zip64_eocd[:4] != _ZIP64_EOCD_SIGNATURE:
            raise ValueError("artifact ZIP64 record is invalid")
        record_size = struct.unpack_from("<Q", zip64_eocd, 4)[0]
        zip64_disk, zip64_central_disk = struct.unpack_from("<II", zip64_eocd, 16)
        entries_on_disk, entries_total = struct.unpack_from("<QQ", zip64_eocd, 24)
        central_size, central_offset = struct.unpack_from("<QQ", zip64_eocd, 40)
        if (
            record_size < 44
            or zip64_disk != 0
            or zip64_central_disk != 0
            or entries_on_disk != entries_total
        ):
            raise ValueError("artifact ZIP64 record is invalid")

    if entries_total > ARTIFACT_MAX_MEMBERS:
        raise ValueError("artifact exceeds the archive member-count bound")
    if central_size > ARTIFACT_MAX_CENTRAL_DIRECTORY_BYTES:
        raise ValueError("artifact exceeds the central-directory size bound")
    if central_offset > archive_size or central_size > archive_size - central_offset:
        raise ValueError("artifact central directory is out of bounds")
    handle.seek(0)
    return int(entries_total)


def _zip_identity(path: Path, *, wheel: bool) -> tuple[str, bytes, str, int]:
    allowed = {WHEEL_IDENTITY_MEMBER} if wheel else HOST_IDENTITY_MEMBERS
    try:
        with _open_stable_file(
            path,
            max_bytes=ARTIFACT_MAX_BYTES,
            subject="artifact",
        ) as (artifact, artifact_sha256):
            declared_entries = _preflight_zip_archive(artifact)
            with zipfile.ZipFile(artifact) as archive:
                infos = archive.infolist()
                if len(infos) != declared_entries:
                    raise ValueError("artifact ZIP member count is inconsistent")
                if len(infos) > ARTIFACT_MAX_MEMBERS:
                    raise ValueError("artifact exceeds the archive member-count bound")
                if (
                    sum(info.file_size for info in infos)
                    > ARTIFACT_MAX_UNCOMPRESSED_BYTES
                ):
                    raise ValueError(
                        "artifact exceeds the total uncompressed size bound"
                    )
                candidates = [
                    info
                    for info in infos
                    if _matches_identity_member(info.filename)
                ]
                matches = [info for info in candidates if info.filename in allowed]
                if len(candidates) != 1 or len(matches) != 1:
                    raise ValueError(
                        "archive must contain one build identity at its contracted path, "
                        f"found {len(matches)} exact and {len(candidates)} total"
                    )
                info = matches[0]
                try:
                    data = read_bounded_zip_info(
                        archive,
                        info,
                        max_bytes=MAX_BUILD_IDENTITY_BYTES,
                    )
                except ValueError as error:
                    raise ValueError(
                        f"archive build identity is unreadable: {error}"
                    ) from error
    except zipfile.BadZipFile as error:
        raise ValueError("artifact is not a valid zip archive") from error
    load_identity_bytes(data)
    return info.filename, data, artifact_sha256, len(infos)


def _sdist_identity(path: Path) -> tuple[str, bytes, str, int]:
    try:
        with _open_stable_file(
            path,
            max_bytes=ARTIFACT_MAX_BYTES,
            subject="artifact",
        ) as (artifact, artifact_sha256):
            with tarfile.open(fileobj=artifact, mode="r:gz") as archive:
                candidates: list[tarfile.TarInfo] = []
                member_count = 0
                expanded_bytes = 0
                for current in archive:
                    member_count += 1
                    if member_count > ARTIFACT_MAX_MEMBERS:
                        raise ValueError(
                            "artifact exceeds the archive member-count bound"
                        )
                    if current.size < 0:
                        raise ValueError("sdist contains a negative-size member")
                    expanded_bytes += current.size
                    if expanded_bytes > ARTIFACT_MAX_UNCOMPRESSED_BYTES:
                        raise ValueError(
                            "artifact exceeds the total uncompressed size bound"
                        )
                    if _matches_identity_member(current.name):
                        candidates.append(current)
                matches = [
                    member for member in candidates if _valid_sdist_member(member.name)
                ]
                if len(candidates) != 1 or len(matches) != 1:
                    raise ValueError(
                        "sdist must contain one build identity at its contracted path, "
                        f"found {len(matches)} exact and {len(candidates)} total"
                    )
                member = matches[0]
                if not member.isfile() or member.size > MAX_BUILD_IDENTITY_BYTES:
                    raise ValueError("sdist build identity is not a bounded regular file")
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError("sdist build identity is unreadable")
                data = handle.read(MAX_BUILD_IDENTITY_BYTES + 1)
    except (tarfile.TarError, OSError) as error:
        raise ValueError("artifact is not a valid sdist") from error
    if len(data) > MAX_BUILD_IDENTITY_BYTES:
        raise ValueError("sdist build identity is oversized")
    load_identity_bytes(data)
    return member.name, data, artifact_sha256, member_count


def _read_report(path: Path) -> dict[str, Any]:
    try:
        with _open_stable_file(
            path,
            max_bytes=REPORT_MAX_BYTES,
            subject="host package report",
        ) as (report, _):
            data = report.read(REPORT_MAX_BYTES + 1)
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("host package report is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("host package report has the wrong shape")
    return value


def _validate_host_report_inventory(
    report: dict[str, Any],
    *,
    host_rows: list[dict[str, Any]],
    expected_identity: dict[str, object],
    expected_identity_sha256: str,
) -> None:
    destinations = tuple(sorted(enabled_destination_keys()))
    package_keys = tuple(sorted(enabled_package_keys()))
    expected_direct = len(destinations)
    expected_plugins = len(package_keys)
    expected_total = expected_direct + expected_plugins
    expected_top_keys = {
        "schema_version",
        "version",
        "artifact_version",
        "build_identity",
        "build_identity_sha256",
        "package_contracts_schema",
        "host_count",
        "direct_package_count",
        "plugin_package_count",
        "package_surfaces",
        "artifacts",
        "live_host_installation",
        "native_package_activation",
        "contracts",
    }
    if set(report) != expected_top_keys:
        raise ValueError("host package report fields are invalid")
    if (
        report.get("schema_version") != "portable-resume/host-packages-v2"
        or report.get("version") != __version__
        or report.get("artifact_version") != expected_identity.get("version")
        or report.get("build_identity") != expected_identity
        or report.get("build_identity_sha256") != expected_identity_sha256
        or report.get("package_contracts_schema") != PACKAGE_CONTRACTS_SCHEMA
        or report.get("contracts") != contracts_report()["contracts"]
        or report.get("live_host_installation") != "not-run"
        or report.get("native_package_activation") != "not-run"
    ):
        raise ValueError("host package report metadata is invalid")
    if (
        report.get("host_count") != expected_direct
        or report.get("direct_package_count") != expected_direct
        or report.get("plugin_package_count") != expected_plugins
    ):
        raise ValueError("host package report registry-derived counts are invalid")
    if report.get("package_surfaces") != list(package_keys):
        raise ValueError("host package report surfaces are incomplete")

    artifact_version = str(expected_identity["version"])
    expected_rows: dict[str, dict[str, Any]] = {}
    direct_contract = contract_for_package_type("direct-skills")
    for host in destinations:
        name = f"portable-resume-{artifact_version}-{host}-skills.zip"
        expected_rows[name] = {
            "host": host,
            "type": "direct-skills",
            "file": name,
            "contract_id": direct_contract.contract_id,
            "package_contracts_schema": PACKAGE_CONTRACTS_SCHEMA,
            "native_evidence_status": direct_contract.native_evidence_status,
            "last_native_evidence_ref": direct_contract.last_native_evidence_ref,
            "offline_validation": "pass",
            "build_identity_sha256": expected_identity_sha256,
            "identity_member": RUNTIME_IDENTITY_RELATIVE,
            "install": direct_contract.install_hint,
        }
    for package_key in package_keys:
        surface = PACKAGE_SURFACES[package_key]
        contract = contract_for_package_type(package_key)
        name = f"portable-resume-{artifact_version}-{package_key}.zip"
        expected_rows[name] = {
            "host": surface.destination,
            "type": package_key,
            "package_surface": package_key,
            "file": name,
            "contract_id": contract.contract_id,
            "package_contracts_schema": PACKAGE_CONTRACTS_SCHEMA,
            "native_evidence_status": contract.native_evidence_status,
            "last_native_evidence_ref": contract.last_native_evidence_ref,
            "offline_validation": "pass",
            "build_identity_sha256": expected_identity_sha256,
            "identity_member": f"{contract.skills_prefix}{RUNTIME_IDENTITY_RELATIVE}",
            "install": contract.install_hint,
        }

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != expected_total:
        raise ValueError("host package report artifact inventory is incomplete")
    reported: dict[str, str] = {}
    reported_members: dict[str, int] = {}
    reported_order: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("host package report artifact row has the wrong shape")
        raw_name = item.get("file")
        digest = item.get("sha256")
        expected_row = (
            expected_rows.get(raw_name) if isinstance(raw_name, str) else None
        )
        expected_fields = (
            set(expected_row) - {"identity_member"}
            if expected_row is not None
            else set()
        )
        expected_fields.update({"sha256", "members", "install"})
        if (
            not isinstance(raw_name, str)
            or not raw_name.endswith(".zip")
            or PurePosixPath(raw_name).name != raw_name
            or "\\" in raw_name
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or raw_name in reported
            or expected_row is None
            or set(item) != expected_fields
            or type(item.get("members")) is not int
            or item["members"] <= 0
            or not isinstance(item.get("install"), str)
            or not item["install"]
        ):
            raise ValueError("host package report artifact row is invalid or duplicate")
        name = raw_name
        for key, expected_value in expected_row.items():
            if key == "identity_member":
                continue
            if item.get(key) != expected_value:
                raise ValueError(
                    f"host package report artifact semantics are invalid: {name}"
                )
        reported[name] = digest
        reported_members[name] = item["members"]
        reported_order.append(name)
    if reported_order != list(expected_rows):
        raise ValueError("host package report artifact order is invalid")

    supplied: dict[str, dict[str, object]] = {}
    for row in host_rows:
        name = Path(str(row["path"])).name
        if name in supplied:
            raise ValueError("host ZIP inputs contain duplicate basenames")
        supplied[name] = {
            "sha256": str(row["sha256"]),
            "identity_member": str(row["identity_member"]),
            "members": row["members"],
        }
    if supplied.keys() != reported.keys():
        raise ValueError("host ZIP inputs differ from the report inventory")
    for name, artifact in supplied.items():
        if reported[name] != artifact["sha256"]:
            raise ValueError(f"host ZIP digest differs from report: {name}")
        if artifact["identity_member"] != expected_rows[name]["identity_member"]:
            raise ValueError(f"host ZIP identity path differs from its family: {name}")
        if artifact["members"] != reported_members[name]:
            raise ValueError(f"host ZIP member count differs from report: {name}")


def verify_artifact_identities(
    *,
    identity_file: Path,
    expected_sha256: str,
    artifacts: Iterable[Path],
    host_report: Path | None = None,
) -> dict[str, Any]:
    expected = load_identity_file(
        identity_file,
        expected_sha256=expected_sha256,
    )
    validate_current_identity(expected)
    expected_bytes = identity_json_bytes(expected)
    paths = tuple(Path(path) for path in artifacts)
    if not paths:
        raise ValueError("at least one artifact is required")
    rows: list[dict[str, Any]] = []
    for path in paths:
        if path.name.endswith(".tar.gz"):
            member, embedded, artifact_sha256, member_count = _sdist_identity(path)
            artifact_type = "sdist"
        elif path.suffix in {".whl", ".zip"}:
            member, embedded, artifact_sha256, member_count = _zip_identity(
                path,
                wheel=path.suffix == ".whl",
            )
            artifact_type = "wheel" if path.suffix == ".whl" else "host-zip"
        else:
            raise ValueError(f"unsupported artifact type: {path.name}")
        if embedded != expected_bytes:
            raise ValueError(f"artifact build identity mismatch: {path.name}")
        rows.append(
            {
                "path": path.as_posix(),
                "type": artifact_type,
                "sha256": artifact_sha256,
                "identity_member": member,
                "identity_sha256": hashlib.sha256(embedded).hexdigest(),
                "identity_match": True,
                "members": member_count,
            }
        )

    host_report_status = "not-provided"
    if host_report is not None:
        if sum(row["type"] == "wheel" for row in rows) != 1 or sum(
            row["type"] == "sdist" for row in rows
        ) != 1:
            raise ValueError("host artifact verification requires one wheel and one sdist")
        report = _read_report(Path(host_report))
        if report.get("build_identity") != expected:
            raise ValueError("host package report build identity mismatch")
        if report.get("build_identity_sha256") != expected_sha256:
            raise ValueError("host package report build identity digest mismatch")
        _validate_host_report_inventory(
            report,
            host_rows=[row for row in rows if row["type"] == "host-zip"],
            expected_identity=expected,
            expected_identity_sha256=expected_sha256,
        )
        host_report_status = "pass"

    return {
        "schema_version": "portable-resume/artifact-identities-v1",
        "build_identity": expected,
        "build_identity_sha256": expected_sha256,
        "artifact_count": len(rows),
        "artifacts": rows,
        "host_report": host_report_status,
        "ok": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--identity-sha256", required=True)
    parser.add_argument("--host-report")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("artifacts", nargs="+")
    namespace = parser.parse_args(argv)
    try:
        report = verify_artifact_identities(
            identity_file=Path(namespace.identity_file),
            expected_sha256=namespace.identity_sha256,
            artifacts=tuple(Path(value) for value in namespace.artifacts),
            host_report=(Path(namespace.host_report) if namespace.host_report else None),
        )
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if namespace.output:
            Path(namespace.output).write_text(encoded, encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"ARTIFACT_IDENTITY_VERIFY FAIL {type(error).__name__}", file=sys.stderr)
        return 1
    if namespace.json:
        print(encoded, end="")
    else:
        print(
            "ARTIFACT_IDENTITY_VERIFY PASS "
            f"artifacts={report['artifact_count']} "
            f"sha256={report['build_identity_sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
