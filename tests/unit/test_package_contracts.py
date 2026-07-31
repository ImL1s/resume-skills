"""#27: versioned package contracts and offline validation."""

from __future__ import annotations

import io
import json
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume import __version__
from portable_resume.build_identity import (
    BUILD_IDENTITY_SCHEMA_V1,
    identity_json_bytes,
    runtime_identity,
)
from portable_resume.install.render import materialize_plan
from portable_resume.install.package_contracts import (
    PACKAGE_CONTRACTS,
    PACKAGE_CONTRACTS_SCHEMA,
    MAX_MANIFEST_MEMBER_BYTES,
    contract_for_package_type,
    contracts_report,
    validate_archive_bytes,
    validate_archive_path,
    validate_member_paths,
    validate_skills_layout,
)


class PackageContractRegistryTests(unittest.TestCase):
    def test_contracts_cover_all_builder_surfaces(self) -> None:
        expected = {
            "direct-skills",
            "antigravity-plugin",
            "claude-marketplace",
            "codex-marketplace",
            "cursor-marketplace",
            "grok-plugin",
            "qwen-extension",
            "kimi-plugin",
        }
        self.assertEqual(set(PACKAGE_CONTRACTS), expected)
        report = contracts_report()
        self.assertEqual(report["schema_version"], PACKAGE_CONTRACTS_SCHEMA)
        self.assertEqual(report["bundle_version"], __version__)

    def test_each_contract_has_stable_id(self) -> None:
        for key, contract in PACKAGE_CONTRACTS.items():
            self.assertTrue(contract.contract_id.endswith("-v1"))
            self.assertEqual(contract.package_type, key)
            self.assertIn(contract.native_evidence_status, {"not-run", "pass", "historical"})

    def test_optional_zip_codecs_are_not_import_requirements(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("plugin.json", b"{}")
            local_offset = archive.getinfo("plugin.json").header_offset
        data = bytearray(buffer.getvalue())
        central_offset = data.find(b"PK\x01\x02")
        struct.pack_into("<H", data, local_offset + 8, zipfile.ZIP_DEFLATED)
        struct.pack_into("<H", data, central_offset + 10, zipfile.ZIP_DEFLATED)
        source_root = Path(__file__).resolve().parents[2] / "src"
        script = """
import builtins
import sys

real_import = builtins.__import__

def blocked_import(name, *args, **kwargs):
    if name in {"lzma", "zlib"}:
        raise ImportError(f"blocked optional codec: {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = blocked_import
sys.path.insert(0, sys.argv[1])
from portable_resume.install.package_contracts import validate_archive_bytes

report = validate_archive_bytes(bytes.fromhex(sys.argv[2]), package_type="antigravity-plugin")
assert not report["ok"]
assert any("primary manifest unreadable" in item for item in report["failures"])
print("OPTIONAL_CODEC_IMPORT PASS")
"""

        completed = subprocess.run(
            [sys.executable, "-c", script, str(source_root), bytes(data).hex()],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "OPTIONAL_CODEC_IMPORT PASS\n")


class OfflineValidationTests(unittest.TestCase):
    def _zip(
        self,
        files: dict[str, bytes],
        *,
        compression: int = zipfile.ZIP_STORED,
    ) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=compression) as archive:
            for name, data in sorted(files.items()):
                archive.writestr(name, data)
        return buf.getvalue()

    def _corrupt_compressed_member(self, data: bytes, member: str) -> bytes:
        corrupted = bytearray(data)
        with zipfile.ZipFile(io.BytesIO(corrupted)) as archive:
            info = archive.getinfo(member)
            self.assertNotEqual(info.compress_type, zipfile.ZIP_STORED)
            local_offset = info.header_offset
        name_size = struct.unpack_from("<H", corrupted, local_offset + 26)[0]
        extra_size = struct.unpack_from("<H", corrupted, local_offset + 28)[0]
        payload_offset = local_offset + 30 + name_size + extra_size
        corrupted[payload_offset] = 0xFF
        return bytes(corrupted)

    def _corruptible_compressions(self) -> tuple[int, ...]:
        methods = [zipfile.ZIP_DEFLATED]
        zstandard = getattr(zipfile, "ZIP_ZSTANDARD", None)
        if getattr(zipfile, "zstd", None) is not None and isinstance(
            zstandard,
            int,
        ):
            methods.append(zstandard)
        return tuple(methods)

    def _member_header_offsets(
        self,
        data: bytearray,
        member: str,
    ) -> tuple[int, int]:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            local_offset = archive.getinfo(member).header_offset
        central_offset = data.find(b"PK\x01\x02")
        while central_offset >= 0:
            name_size = struct.unpack_from("<H", data, central_offset + 28)[0]
            extra_size = struct.unpack_from("<H", data, central_offset + 30)[0]
            comment_size = struct.unpack_from("<H", data, central_offset + 32)[0]
            name = bytes(data[central_offset + 46 : central_offset + 46 + name_size])
            if name.decode("utf-8") == member:
                return local_offset, central_offset
            central_offset = data.find(
                b"PK\x01\x02",
                central_offset + 46 + name_size + extra_size + comment_size,
            )
        self.fail(f"missing central-directory entry for {member}")

    def test_rejects_parent_escape_and_install_runtime(self) -> None:
        failures = validate_member_paths(
            [
                "ok/SKILL.md",
                "../escape",
                "x/portable_resume/install/cli.py",
                "portable_resume/install/evil.py",
                ".portable-resume/.state/manifest.json",
            ]
        )
        self.assertTrue(any("unsafe" in f for f in failures))
        self.assertTrue(any("forbidden" in f for f in failures))
        self.assertTrue(
            any("portable_resume/install/evil.py" in f for f in failures)
        )
        self.assertTrue(any(".state/" in f for f in failures))

    def test_skills_layout_requires_all_sources(self) -> None:
        failures = validate_skills_layout(
            ["skills/resume-claude/SKILL.md"],
            skills_prefix="skills/",
        )
        self.assertTrue(any("missing skill" in f for f in failures))

    def test_validate_bad_zip(self) -> None:
        with mock.patch(
            "portable_resume.install.package_contracts.zipfile.ZipFile"
        ) as zip_parser:
            report = validate_archive_bytes(
                b"not-a-zip",
                package_type="direct-skills",
            )
        self.assertFalse(report["ok"])
        self.assertEqual(report["native_evidence_status"], "not-run")
        self.assertTrue(report["failures"])
        zip_parser.assert_not_called()

    def test_minimal_direct_skills_contract_shape(self) -> None:
        # Empty archive fails skills layout — proves contract is enforced.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("readme.txt", b"x")
        report = validate_archive_bytes(buf.getvalue(), package_type="direct-skills")
        self.assertFalse(report["ok"])
        self.assertEqual(report["contract_id"], "direct-skills-v1")

    def test_rejects_manifest_decompression_bomb(self) -> None:
        payload = b" " * (MAX_MANIFEST_MEMBER_BYTES + 1)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("plugin.json", payload)
            info = archive.getinfo("plugin.json")
            self.assertGreater(info.file_size, MAX_MANIFEST_MEMBER_BYTES)
            self.assertLess(info.compress_size, info.file_size // 100)

        report = validate_archive_bytes(
            buf.getvalue(),
            package_type="antigravity-plugin",
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("bounded regular file" in failure for failure in report["failures"])
        )

    def test_reports_unsupported_primary_manifest_compression(self) -> None:
        data = bytearray(self._zip({"plugin.json": b"{}"}))
        local_offset, central_offset = self._member_header_offsets(
            data,
            "plugin.json",
        )
        struct.pack_into("<H", data, local_offset + 8, 99)
        struct.pack_into("<H", data, central_offset + 10, 99)

        report = validate_archive_bytes(
            bytes(data),
            package_type="antigravity-plugin",
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                "primary manifest unreadable" in failure
                for failure in report["failures"]
            ),
            report["failures"],
        )

    def test_reports_corrupt_compressed_primary_manifest(self) -> None:
        identity = runtime_identity()
        files = {
            f"skills/{name}": value
            for name, value in materialize_plan(
                "antigravity",
                identity=identity,
            ).items()
        }
        files["plugin.json"] = b'{"name":"portable-resume"}\n'
        for compression in self._corruptible_compressions():
            with self.subTest(compression=compression):
                data = self._zip(files, compression=compression)
                baseline = validate_archive_bytes(
                    data,
                    package_type="antigravity-plugin",
                    expected_identity=identity,
                )
                self.assertTrue(baseline["ok"], baseline["failures"])

                report = validate_archive_bytes(
                    self._corrupt_compressed_member(data, "plugin.json"),
                    package_type="antigravity-plugin",
                    expected_identity=identity,
                )

                self.assertFalse(report["ok"])
                self.assertTrue(
                    any(
                        "primary manifest unreadable" in failure
                        for failure in report["failures"]
                    ),
                    report["failures"],
                )

    def test_reports_unsupported_zip_metadata_version(self) -> None:
        identity = runtime_identity()
        files = {
            f"skills/{name}": value
            for name, value in materialize_plan(
                "antigravity",
                identity=identity,
            ).items()
        }
        files["plugin.json"] = b'{"name":"portable-resume"}\n'
        data = bytearray(self._zip(files))
        baseline = validate_archive_bytes(
            bytes(data),
            package_type="antigravity-plugin",
            expected_identity=identity,
        )
        self.assertTrue(baseline["ok"], baseline["failures"])
        _, central_offset = self._member_header_offsets(data, "plugin.json")
        struct.pack_into("<H", data, central_offset + 6, 100)

        report = validate_archive_bytes(
            bytes(data),
            package_type="antigravity-plugin",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                "unreadable zip metadata" in failure
                for failure in report["failures"]
            ),
            report["failures"],
        )

    def test_rejects_archive_member_count_over_bound(self) -> None:
        data = self._zip({"one": b"1", "two": b"2"})

        with (
            mock.patch(
                "portable_resume.install.package_contracts.MAX_ARCHIVE_MEMBERS",
                1,
            ),
            mock.patch(
                "portable_resume.install.package_contracts.zipfile.ZipFile"
            ) as zip_parser,
        ):
            report = validate_archive_bytes(data, package_type="direct-skills")

        self.assertFalse(report["ok"])
        self.assertIn("archive exceeds the member-count bound", report["failures"])
        zip_parser.assert_not_called()

    def test_rejects_central_directory_bytes_over_bound_before_parser(self) -> None:
        data = self._zip({"one": b"1"})

        with (
            mock.patch(
                "portable_resume.install.package_contracts."
                "MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES",
                1,
            ),
            mock.patch(
                "portable_resume.install.package_contracts.zipfile.ZipFile"
            ) as zip_parser,
        ):
            report = validate_archive_bytes(data, package_type="direct-skills")

        self.assertFalse(report["ok"])
        self.assertIn(
            "archive exceeds the central-directory size bound",
            report["failures"],
        )
        zip_parser.assert_not_called()

    def test_rejects_malformed_zip64_before_parser(self) -> None:
        data = bytearray(self._zip({"one": b"1"}))
        eocd_offset = data.rfind(b"PK\x05\x06")
        self.assertGreaterEqual(eocd_offset, 0)
        struct.pack_into("<HH", data, eocd_offset + 8, 0xFFFF, 0xFFFF)

        with mock.patch(
            "portable_resume.install.package_contracts.zipfile.ZipFile"
        ) as zip_parser:
            report = validate_archive_bytes(
                bytes(data),
                package_type="direct-skills",
            )

        self.assertFalse(report["ok"])
        self.assertIn("archive ZIP64 locator is invalid", report["failures"])
        zip_parser.assert_not_called()

    def test_rejects_total_decompressed_size_over_bound(self) -> None:
        data = self._zip({"payload": b"1234"})

        with mock.patch(
            "portable_resume.install.package_contracts.MAX_ARCHIVE_UNCOMPRESSED_BYTES",
            3,
        ):
            report = validate_archive_bytes(data, package_type="direct-skills")

        self.assertFalse(report["ok"])
        self.assertIn(
            "archive exceeds the total decompressed size bound",
            report["failures"],
        )

    def test_validate_archive_path_rejects_oversized_input(self) -> None:
        data = self._zip({"payload": b"x"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "package.zip")
            path.write_bytes(data)
            with mock.patch(
                "portable_resume.install.package_contracts.MAX_ARCHIVE_BYTES",
                len(data) - 1,
            ):
                report = validate_archive_path(
                    str(path),
                    package_type="direct-skills",
                )

        self.assertFalse(report["ok"])
        self.assertEqual(
            report["failures"],
            ["archive is not a bounded stable regular file"],
        )

    def test_contract_for_unknown_raises(self) -> None:
        with self.assertRaises(KeyError):
            contract_for_package_type("nope")

    def test_direct_contract_requires_exact_embedded_identity(self) -> None:
        identity = runtime_identity()
        data = self._zip(materialize_plan("claude", identity=identity))

        report = validate_archive_bytes(
            data,
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertTrue(report["ok"], report["failures"])
        self.assertIsNotNone(report["build_identity_sha256"])

    def test_direct_contract_rejects_legacy_embedded_identity_without_pin(
        self,
    ) -> None:
        identity = runtime_identity()
        legacy = dict(identity)
        legacy["schema"] = BUILD_IDENTITY_SCHEMA_V1
        del legacy["build_inputs_sha256"]
        files = materialize_plan("claude", identity=identity)
        member = (
            ".portable-resume/runtime/portable_resume/resources/"
            "build-identity.json"
        )
        files[member] = identity_json_bytes(legacy)

        report = validate_archive_bytes(
            self._zip(files),
            package_type="direct-skills",
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                "current identity schema" in failure
                for failure in report["failures"]
            ),
            report["failures"],
        )

    def test_direct_contract_rejects_mismatched_embedded_identity(self) -> None:
        identity = runtime_identity()
        files = materialize_plan("claude", identity=identity)
        member = ".portable-resume/runtime/portable_resume/resources/build-identity.json"
        files[member] = files[member].replace(b'"dirty":null', b'"dirty":false')

        report = validate_archive_bytes(
            self._zip(files),
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("build identity" in failure for failure in report["failures"])
        )

    def test_direct_contract_rejects_identity_at_decoy_path(self) -> None:
        identity = runtime_identity()
        files = materialize_plan("claude", identity=identity)
        member = ".portable-resume/runtime/portable_resume/resources/build-identity.json"
        files["decoy/portable_resume/resources/build-identity.json"] = files.pop(member)

        report = validate_archive_bytes(
            self._zip(files),
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("embedded build identity" in failure for failure in report["failures"])
        )

    def test_direct_contract_rejects_symlink_identity_member(self) -> None:
        identity = runtime_identity()
        files = materialize_plan("claude", identity=identity)
        member = ".portable-resume/runtime/portable_resume/resources/build-identity.json"
        encoded = files.pop(member)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in sorted(files.items()):
                archive.writestr(name, data)
            info = zipfile.ZipInfo(member)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, encoded)

        report = validate_archive_bytes(
            buffer.getvalue(),
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("bounded regular file" in failure for failure in report["failures"])
        )

    def test_direct_contract_reports_unsupported_identity_compression(self) -> None:
        identity = runtime_identity()
        member = ".portable-resume/runtime/portable_resume/resources/build-identity.json"
        data = bytearray(self._zip(materialize_plan("claude", identity=identity)))
        local_offset, central_offset = self._member_header_offsets(data, member)
        struct.pack_into("<H", data, local_offset + 8, 99)
        struct.pack_into("<H", data, central_offset + 10, 99)

        report = validate_archive_bytes(
            bytes(data),
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                "embedded build identity is unreadable" in failure
                for failure in report["failures"]
            ),
            report["failures"],
        )

    def test_direct_contract_reports_encrypted_identity_member(self) -> None:
        identity = runtime_identity()
        member = ".portable-resume/runtime/portable_resume/resources/build-identity.json"
        data = bytearray(self._zip(materialize_plan("claude", identity=identity)))
        local_offset, central_offset = self._member_header_offsets(data, member)
        local_flags = struct.unpack_from("<H", data, local_offset + 6)[0]
        central_flags = struct.unpack_from("<H", data, central_offset + 8)[0]
        struct.pack_into("<H", data, local_offset + 6, local_flags | 1)
        struct.pack_into("<H", data, central_offset + 8, central_flags | 1)

        report = validate_archive_bytes(
            bytes(data),
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                "embedded build identity is unreadable" in failure
                for failure in report["failures"]
            ),
            report["failures"],
        )

    def test_direct_contract_reports_corrupt_compressed_identity(self) -> None:
        identity = runtime_identity()
        member = (
            ".portable-resume/runtime/portable_resume/resources/build-identity.json"
        )
        files = materialize_plan("claude", identity=identity)
        for compression in self._corruptible_compressions():
            with self.subTest(compression=compression):
                data = self._zip(files, compression=compression)
                baseline = validate_archive_bytes(
                    data,
                    package_type="direct-skills",
                    expected_identity=identity,
                )
                self.assertTrue(baseline["ok"], baseline["failures"])

                report = validate_archive_bytes(
                    self._corrupt_compressed_member(data, member),
                    package_type="direct-skills",
                    expected_identity=identity,
                )

                self.assertFalse(report["ok"])
                self.assertTrue(
                    any(
                        "embedded build identity is unreadable" in failure
                        for failure in report["failures"]
                    ),
                    report["failures"],
                )

    def test_direct_contract_rejects_non_identity_symlink_member(self) -> None:
        identity = runtime_identity()
        files = materialize_plan("claude", identity=identity)
        member = ".portable-resume/runtime/portable_resume/__init__.py"
        encoded = files.pop(member)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in sorted(files.items()):
                archive.writestr(name, data)
            info = zipfile.ZipInfo(member)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, encoded)

        report = validate_archive_bytes(
            buffer.getvalue(),
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("non-regular members" in failure for failure in report["failures"])
        )

    def test_direct_contract_rejects_schema_at_decoy_path(self) -> None:
        identity = runtime_identity()
        files = materialize_plan("claude", identity=identity)
        member = (
            ".portable-resume/runtime/portable_resume/resources/"
            "portable-resume-v1.schema.json"
        )
        files[
            "decoy/portable_resume/resources/portable-resume-v1.schema.json"
        ] = files.pop(member)

        report = validate_archive_bytes(
            self._zip(files),
            package_type="direct-skills",
            expected_identity=identity,
        )

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("exactly one runtime schema" in failure for failure in report["failures"])
        )

    def test_marketplace_rejects_stale_version_and_wrong_source_root(self) -> None:
        import zipfile
        from io import BytesIO

        # Minimal fake claude marketplace archive with wrong version + skills subtree source.
        files = {
            ".claude-plugin/marketplace.json": json.dumps(
                {
                    "name": "portable-resume",
                    "plugins": [
                        {
                            "name": "portable-resume",
                            "version": "0.0.0",
                            "source": "./plugins/portable-resume/skills",
                        }
                    ],
                },
                sort_keys=True,
            ).encode()
            + b"\n",
            "plugins/portable-resume/.claude-plugin/plugin.json": json.dumps(
                {
                    "name": "portable-resume",
                    "version": __version__,
                    "description": "x",
                    "author": {"name": "x"},
                    "license": "Apache-2.0",
                    "homepage": "https://example.com",
                    "repository": "https://example.com",
                },
                sort_keys=True,
            ).encode()
            + b"\n",
            "plugins/portable-resume/skills/resume-claude/SKILL.md": b"x",
        }
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        report = validate_archive_bytes(buf.getvalue(), package_type="claude-marketplace")
        self.assertFalse(report["ok"])
        blob = " ".join(report["failures"])
        self.assertIn("version", blob)
        self.assertIn("plugin root", blob)

    def test_reports_corrupt_compressed_marketplace_manifest(self) -> None:
        identity = runtime_identity()
        files = {
            f"plugins/portable-resume/skills/{name}": value
            for name, value in materialize_plan(
                "claude",
                identity=identity,
            ).items()
        }
        files["plugins/portable-resume/.claude-plugin/plugin.json"] = (
            json.dumps(
                {
                    "name": "portable-resume",
                    "version": __version__,
                    "description": "x",
                    "author": {"name": "x"},
                    "license": "Apache-2.0",
                    "homepage": "https://example.com",
                    "repository": "https://example.com",
                },
                sort_keys=True,
            ).encode()
            + b"\n"
        )
        marketplace_member = ".claude-plugin/marketplace.json"
        files[marketplace_member] = (
            json.dumps(
                {
                    "name": "portable-resume",
                    "plugins": [
                        {
                            "name": "portable-resume",
                            "version": __version__,
                            "source": "./plugins/portable-resume",
                        }
                    ],
                },
                sort_keys=True,
            ).encode()
            + b"\n"
        )
        for compression in self._corruptible_compressions():
            with self.subTest(compression=compression):
                data = self._zip(files, compression=compression)
                baseline = validate_archive_bytes(
                    data,
                    package_type="claude-marketplace",
                    expected_identity=identity,
                )
                self.assertTrue(baseline["ok"], baseline["failures"])

                report = validate_archive_bytes(
                    self._corrupt_compressed_member(data, marketplace_member),
                    package_type="claude-marketplace",
                    expected_identity=identity,
                )

                self.assertFalse(report["ok"])
                self.assertTrue(
                    any(
                        "unreadable marketplace" in failure
                        for failure in report["failures"]
                    ),
                    report["failures"],
                )


if __name__ == "__main__":
    unittest.main()
