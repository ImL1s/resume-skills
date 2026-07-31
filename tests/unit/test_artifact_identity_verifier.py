from __future__ import annotations

import io
import hashlib
import json
import os
import stat
import struct
import tarfile
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from portable_resume import __version__
from portable_resume.build_identity import (
    BUILD_IDENTITY_SCHEMA_V1,
    identity_json_bytes,
    runtime_identity,
)
from portable_resume.install.package_contracts import (
    PACKAGE_CONTRACTS_SCHEMA,
    RUNTIME_IDENTITY_RELATIVE,
    contract_for_package_type,
    contracts_report,
)
from portable_resume.registry import (
    PACKAGE_SURFACES,
    enabled_destination_keys,
    enabled_package_keys,
)
from scripts.verify_artifact_identities import (
    _read_report,
    main as verifier_main,
    verify_artifact_identities,
)


class ArtifactIdentityVerifierTests(unittest.TestCase):
    def _zip(
        self,
        path: Path,
        member: str,
        data: bytes,
        *,
        compression: int = zipfile.ZIP_STORED,
    ) -> None:
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            archive.writestr(member, data)

    def _corrupt_compressed_member(self, path: Path, member: str) -> None:
        corrupted = bytearray(path.read_bytes())
        with zipfile.ZipFile(io.BytesIO(corrupted)) as archive:
            info = archive.getinfo(member)
            self.assertNotEqual(info.compress_type, zipfile.ZIP_STORED)
            local_offset = info.header_offset
        name_size = struct.unpack_from("<H", corrupted, local_offset + 26)[0]
        extra_size = struct.unpack_from("<H", corrupted, local_offset + 28)[0]
        payload_offset = local_offset + 30 + name_size + extra_size
        corrupted[payload_offset] = 0xFF
        path.write_bytes(corrupted)

    def _set_unsupported_zip_metadata_version(self, path: Path) -> None:
        data = bytearray(path.read_bytes())
        central_offset = data.find(b"PK\x01\x02")
        self.assertGreaterEqual(central_offset, 0)
        struct.pack_into("<H", data, central_offset + 6, 100)
        path.write_bytes(data)

    def _corruptible_compressions(self) -> tuple[int, ...]:
        methods = [zipfile.ZIP_DEFLATED]
        zstandard = getattr(zipfile, "ZIP_ZSTANDARD", None)
        if getattr(zipfile, "zstd", None) is not None and isinstance(
            zstandard,
            int,
        ):
            methods.append(zstandard)
        return tuple(methods)

    def test_rejects_legacy_v1_identity_pin_before_artifact_reads(self) -> None:
        identity = runtime_identity()
        identity["schema"] = BUILD_IDENTITY_SCHEMA_V1
        del identity["build_inputs_sha256"]
        encoded = identity_json_bytes(identity)
        with tempfile.TemporaryDirectory() as temporary:
            pin = Path(temporary) / "identity.json"
            pin.write_bytes(encoded)

            with self.assertRaisesRegex(ValueError, "current identity schema"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=hashlib.sha256(encoded).hexdigest(),
                    artifacts=(),
                )

    def _sdist(self, path: Path, member: str, data: bytes) -> None:
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo(member)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))

    def _host_fixture(
        self,
        root: Path,
        encoded: bytes,
        identity: dict[str, object],
    ) -> tuple[list[Path], Path]:
        identity_digest = hashlib.sha256(encoded).hexdigest()
        artifact_version = str(identity["version"])
        hosts: list[Path] = []
        rows: list[dict[str, object]] = []
        direct_contract = contract_for_package_type("direct-skills")
        for host_key in sorted(enabled_destination_keys()):
            name = f"portable-resume-{artifact_version}-{host_key}-skills.zip"
            host = root / name
            self._zip(host, RUNTIME_IDENTITY_RELATIVE, encoded)
            hosts.append(host)
            rows.append(
                {
                    "host": host_key,
                    "type": "direct-skills",
                    "file": name,
                    "sha256": hashlib.sha256(host.read_bytes()).hexdigest(),
                    "members": 1,
                    "install": direct_contract.install_hint,
                    "contract_id": direct_contract.contract_id,
                    "package_contracts_schema": PACKAGE_CONTRACTS_SCHEMA,
                    "native_evidence_status": direct_contract.native_evidence_status,
                    "last_native_evidence_ref": direct_contract.last_native_evidence_ref,
                    "offline_validation": "pass",
                    "build_identity_sha256": identity_digest,
                }
            )
        for package_key in sorted(enabled_package_keys()):
            surface = PACKAGE_SURFACES[package_key]
            contract = contract_for_package_type(package_key)
            name = f"portable-resume-{artifact_version}-{package_key}.zip"
            host = root / name
            self._zip(
                host,
                f"{contract.skills_prefix}{RUNTIME_IDENTITY_RELATIVE}",
                encoded,
            )
            hosts.append(host)
            rows.append(
                {
                    "host": surface.destination,
                    "type": package_key,
                    "package_surface": package_key,
                    "file": name,
                    "sha256": hashlib.sha256(host.read_bytes()).hexdigest(),
                    "members": 1,
                    "install": contract.install_hint,
                    "contract_id": contract.contract_id,
                    "package_contracts_schema": PACKAGE_CONTRACTS_SCHEMA,
                    "native_evidence_status": contract.native_evidence_status,
                    "last_native_evidence_ref": contract.last_native_evidence_ref,
                    "offline_validation": "pass",
                    "build_identity_sha256": identity_digest,
                }
            )
        report_path = root / "host-packages.json"
        report_path.write_text(
            json.dumps(
                {
                    "schema_version": "portable-resume/host-packages-v2",
                    "version": __version__,
                    "artifact_version": artifact_version,
                    "build_identity": identity,
                    "build_identity_sha256": identity_digest,
                    "package_contracts_schema": PACKAGE_CONTRACTS_SCHEMA,
                    "host_count": len(enabled_destination_keys()),
                    "direct_package_count": len(enabled_destination_keys()),
                    "plugin_package_count": len(enabled_package_keys()),
                    "package_surfaces": sorted(enabled_package_keys()),
                    "artifacts": rows,
                    "live_host_installation": "not-run",
                    "native_package_activation": "not-run",
                    "contracts": contracts_report()["contracts"],
                }
            ),
            encoding="utf-8",
        )
        return hosts, report_path

    def test_verifies_wheel_sdist_host_zip_and_report_against_one_pin(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)
            host_count = len(hosts)

            report = verify_artifact_identities(
                identity_file=pin,
                expected_sha256=hashlib.sha256(encoded).hexdigest(),
                artifacts=(wheel, sdist, *hosts),
                host_report=report_path,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(len(report["artifacts"]), 2 + host_count)
            self.assertTrue(all(item["identity_match"] for item in report["artifacts"]))

            extra = root / "extra.zip"
            self._zip(
                extra,
                ".portable-resume/runtime/portable_resume/resources/build-identity.json",
                encoded,
            )
            with self.assertRaisesRegex(ValueError, "report inventory"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=hashlib.sha256(encoded).hexdigest(),
                    artifacts=(wheel, sdist, *hosts, extra),
                    host_report=report_path,
                )

    def test_rejects_missing_host_zip_from_report_inventory(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)

            with self.assertRaisesRegex(ValueError, "report inventory"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel, sdist, *hosts[:-1]),
                    host_report=report_path,
                )

    def test_host_report_requires_one_wheel_and_one_sdist(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)

            for artifacts in ((wheel, *hosts), (sdist, *hosts)):
                with self.subTest(first=artifacts[0].name):
                    with self.assertRaisesRegex(
                        ValueError,
                        "requires one wheel and one sdist",
                    ):
                        verify_artifact_identities(
                            identity_file=pin,
                            expected_sha256=digest,
                            artifacts=artifacts,
                            host_report=report_path,
                        )

    def test_rejects_duplicate_host_report_artifact_filename(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["artifacts"][1]["file"] = report["artifacts"][0]["file"]
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid or duplicate"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel, sdist, *hosts),
                    host_report=report_path,
                )

    def test_rejects_host_report_registry_semantic_mismatch(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["artifacts"][0]["host"] = "wrong-host"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "semantics are invalid"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel, sdist, *hosts),
                    host_report=report_path,
                )

    def test_rejects_host_report_member_count_mismatch(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["artifacts"][0]["members"] += 1
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "member count differs"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel, sdist, *hosts),
                    host_report=report_path,
                )

    def test_rejects_host_report_install_hint_mismatch(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["artifacts"][0]["install"] = "tampered arbitrary command"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "semantics are invalid"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel, sdist, *hosts),
                    host_report=report_path,
                )

    def test_rejects_plugin_zip_with_direct_identity_layout(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, report_path = self._host_fixture(root, encoded, identity)
            plugin = hosts[-1]
            self._zip(plugin, RUNTIME_IDENTITY_RELATIVE, encoded)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            row = next(item for item in report["artifacts"] if item["file"] == plugin.name)
            row["sha256"] = hashlib.sha256(plugin.read_bytes()).hexdigest()
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "identity path differs"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel, sdist, *hosts),
                    host_report=report_path,
                )

    def test_rejects_duplicate_identity(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            duplicate = root / "duplicate.zip"
            with zipfile.ZipFile(duplicate, "w") as archive:
                archive.writestr(
                    "one/portable_resume/resources/build-identity.json",
                    encoded,
                )
                archive.writestr(
                    "two/portable_resume/resources/build-identity.json",
                    encoded,
                )

            with self.assertRaises(ValueError):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=hashlib.sha256(encoded).hexdigest(),
                    artifacts=(duplicate,),
                )

    def test_rejects_zip_archive_over_member_count_bound(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "bounded.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "portable_resume/resources/build-identity.json",
                    encoded,
                )
                archive.writestr("irrelevant.txt", b"x")

            with (
                mock.patch(
                    "scripts.verify_artifact_identities.ARTIFACT_MAX_MEMBERS",
                    1,
                ),
                mock.patch(
                    "scripts.verify_artifact_identities.zipfile.ZipFile",
                    side_effect=AssertionError("ZIP parser must not run"),
                ),
                self.assertRaisesRegex(ValueError, "member-count bound"),
            ):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel,),
                )

    def test_rejects_zip_before_parsing_oversized_central_directory(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "bounded.whl"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )

            with (
                mock.patch(
                    "scripts.verify_artifact_identities."
                    "ARTIFACT_MAX_CENTRAL_DIRECTORY_BYTES",
                    1,
                ),
                mock.patch(
                    "scripts.verify_artifact_identities.zipfile.ZipFile",
                    side_effect=AssertionError("ZIP parser must not run"),
                ),
                self.assertRaisesRegex(ValueError, "central-directory size bound"),
            ):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel,),
                )

    def test_rejects_zip_artifact_over_compressed_size_bound(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "bounded.whl"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )

            with (
                mock.patch(
                    "scripts.verify_artifact_identities.ARTIFACT_MAX_BYTES",
                    wheel.stat().st_size - 1,
                ),
                self.assertRaisesRegex(ValueError, "bounded regular file"),
            ):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel,),
                )

    def test_rejects_zip_archive_over_uncompressed_size_bound(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "bounded.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "portable_resume/resources/build-identity.json",
                    encoded,
                )
                archive.writestr("irrelevant.txt", b"x")

            with (
                mock.patch(
                    "scripts.verify_artifact_identities.ARTIFACT_MAX_UNCOMPRESSED_BYTES",
                    len(encoded),
                ),
                self.assertRaisesRegex(ValueError, "uncompressed size bound"),
            ):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel,),
                )

    def test_rejects_sdist_over_member_count_bound(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            sdist = root / "bounded.tar.gz"
            with tarfile.open(sdist, "w:gz") as archive:
                for name, data in (
                    (
                        "portable_resume-0/src/portable_resume/resources/"
                        "build-identity.json",
                        encoded,
                    ),
                    ("portable_resume-0/irrelevant.txt", b"x"),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

            with (
                mock.patch(
                    "scripts.verify_artifact_identities.ARTIFACT_MAX_MEMBERS",
                    1,
                ),
                self.assertRaisesRegex(ValueError, "member-count bound"),
            ):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(sdist,),
                )

    def test_rejects_sdist_artifact_over_compressed_size_bound(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            sdist = root / "bounded.tar.gz"
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )

            with (
                mock.patch(
                    "scripts.verify_artifact_identities.ARTIFACT_MAX_BYTES",
                    sdist.stat().st_size - 1,
                ),
                self.assertRaisesRegex(ValueError, "bounded regular file"),
            ):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(sdist,),
                )

    def test_rejects_sdist_over_uncompressed_size_bound(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            sdist = root / "bounded.tar.gz"
            with tarfile.open(sdist, "w:gz") as archive:
                for name, data in (
                    (
                        "portable_resume-0/src/portable_resume/resources/"
                        "build-identity.json",
                        encoded,
                    ),
                    ("portable_resume-0/irrelevant.txt", b"x"),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

            with (
                mock.patch(
                    "scripts.verify_artifact_identities.ARTIFACT_MAX_UNCOMPRESSED_BYTES",
                    len(encoded),
                ),
                self.assertRaisesRegex(ValueError, "uncompressed size bound"),
            ):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(sdist,),
                )

    def test_rejects_mismatched_identity_at_exact_path(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        mismatch = dict(identity)
        mismatch["source_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "mismatch.whl"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                identity_json_bytes(mismatch),
            )

            with self.assertRaises(ValueError):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=hashlib.sha256(encoded).hexdigest(),
                    artifacts=(wheel,),
                )

    def test_rejects_identity_at_non_runtime_paths(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            cases = (
                (
                    root / "wrong.whl",
                    "decoy/portable_resume/resources/build-identity.json",
                    self._zip,
                ),
                (
                    root / "wrong.zip",
                    "decoy/portable_resume/resources/build-identity.json",
                    self._zip,
                ),
                (
                    root / "wrong.tar.gz",
                    "decoy/portable_resume/resources/build-identity.json",
                    self._sdist,
                ),
            )
            for artifact, member, writer in cases:
                with self.subTest(artifact=artifact.name):
                    writer(artifact, member, encoded)
                    with self.assertRaises(ValueError):
                        verify_artifact_identities(
                            identity_file=pin,
                            expected_sha256=digest,
                            artifacts=(artifact,),
                        )

    def test_rejects_symlink_identity_member(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "symlink.whl"
            info = zipfile.ZipInfo(
                "portable_resume/resources/build-identity.json"
            )
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(info, encoded)

            with self.assertRaisesRegex(ValueError, "bounded regular file"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(wheel,),
                )

    def test_cli_reports_corrupt_compressed_identity_without_traceback(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        member = "portable_resume/resources/build-identity.json"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            for compression in self._corruptible_compressions():
                with self.subTest(compression=compression):
                    self._zip(
                        wheel,
                        member,
                        encoded,
                        compression=compression,
                    )
                    baseline = verify_artifact_identities(
                        identity_file=pin,
                        expected_sha256=digest,
                        artifacts=(wheel,),
                    )
                    self.assertTrue(baseline["ok"])
                    self._corrupt_compressed_member(wheel, member)
                    stderr = io.StringIO()

                    with redirect_stderr(stderr):
                        result = verifier_main(
                            [
                                "--identity-file",
                                str(pin),
                                "--identity-sha256",
                                digest,
                                str(wheel),
                            ]
                        )

                    self.assertEqual(result, 1)
                    self.assertEqual(
                        stderr.getvalue(),
                        "ARTIFACT_IDENTITY_VERIFY FAIL ValueError\n",
                    )

    def test_cli_reports_unsupported_zip_metadata_without_traceback(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            baseline = verify_artifact_identities(
                identity_file=pin,
                expected_sha256=digest,
                artifacts=(wheel,),
            )
            self.assertTrue(baseline["ok"])
            self._set_unsupported_zip_metadata_version(wheel)
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = verifier_main(
                    [
                        "--identity-file",
                        str(pin),
                        "--identity-sha256",
                        digest,
                        str(wheel),
                    ]
                )

        self.assertEqual(result, 1)
        self.assertEqual(
            stderr.getvalue(), "ARTIFACT_IDENTITY_VERIFY FAIL ValueError\n"
        )

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_rejects_symlink_artifact_path(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        digest = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            target = root / "target.whl"
            self._zip(
                target,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            link = root / "artifact.whl"
            link.symlink_to(target)

            with self.assertRaisesRegex(ValueError, "bounded regular file"):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=digest,
                    artifacts=(link,),
                )

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_rejects_symlink_host_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            link = root / "host-packages.json"
            link.symlink_to(target)

            with self.assertRaisesRegex(ValueError, "bounded regular file"):
                _read_report(link)

    def test_rejects_host_report_identity_mismatch(self) -> None:
        identity = runtime_identity()
        encoded = identity_json_bytes(identity)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = root / "identity.json"
            pin.write_bytes(encoded)
            wheel = root / "portable_resume-0-py3-none-any.whl"
            sdist = root / "portable_resume-0.tar.gz"
            self._zip(
                wheel,
                "portable_resume/resources/build-identity.json",
                encoded,
            )
            self._sdist(
                sdist,
                "portable_resume-0/src/portable_resume/resources/build-identity.json",
                encoded,
            )
            hosts, host_report = self._host_fixture(root, encoded, identity)
            report = json.loads(host_report.read_text(encoding="utf-8"))
            report["build_identity"] = {"schema": "wrong"}
            host_report.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaises(ValueError):
                verify_artifact_identities(
                    identity_file=pin,
                    expected_sha256=hashlib.sha256(encoded).hexdigest(),
                    artifacts=(wheel, sdist, *hosts),
                    host_report=host_report,
                )


if __name__ == "__main__":
    unittest.main()
