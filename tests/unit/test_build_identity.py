from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest import mock

from portable_resume.build_identity import (
    BUILD_IDENTITY_SCHEMA,
    BUILD_IDENTITY_SCHEMA_V1,
    build_identity,
    identity_json_bytes,
    load_embedded_identity,
    load_identity_bytes,
    load_identity_file,
    registry_sha256,
    runtime_identity,
    source_sha256,
    validate_identity,
)
from scripts.git_build_identity import build_inputs_sha256, git_build_identity


class BuildIdentityDigestTests(unittest.TestCase):
    def test_registry_digest_is_independent_of_mapping_order(self) -> None:
        first = {
            "sources": {"alpha": {"status": "supported"}},
            "destinations": {"beta": {"status": "supported"}},
            "packages": {},
        }
        reordered = {
            "packages": {},
            "destinations": {"beta": {"status": "supported"}},
            "sources": {"alpha": {"status": "supported"}},
        }

        self.assertEqual(
            registry_sha256(registry_payload=first),
            registry_sha256(registry_payload=reordered),
        )

    def test_registry_digest_changes_when_profile_representation_changes(self) -> None:
        baseline = {
            "sources": {"alpha": {"status": "supported"}},
            "destinations": {},
            "packages": {},
        }
        changed = {
            "sources": {"alpha": {"status": "research"}},
            "destinations": {},
            "packages": {},
        }

        self.assertNotEqual(
            registry_sha256(registry_payload=baseline),
            registry_sha256(registry_payload=changed),
        )

    def test_source_digest_ignores_generated_identity_and_python_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "portable_resume"
            (package_root / "resources").mkdir(parents=True)
            (package_root / "__pycache__").mkdir()
            (package_root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            generated = package_root / "resources" / "build-identity.json"
            generated.write_text('{"build": 1}\n', encoding="utf-8")
            cached = package_root / "__pycache__" / "module.cpython-311.pyc"
            cached.write_bytes(b"cache-one")
            baseline = source_sha256(package_root)

            generated.write_text('{"build": 2}\n', encoding="utf-8")
            cached.write_bytes(b"cache-two")

            self.assertEqual(source_sha256(package_root), baseline)

    def test_source_digest_changes_when_source_bytes_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "portable_resume"
            package_root.mkdir()
            source = package_root / "module.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            baseline = source_sha256(package_root)

            source.write_text("VALUE = 2\n", encoding="utf-8")

            self.assertNotEqual(source_sha256(package_root), baseline)

    def test_source_digest_enforces_per_file_and_aggregate_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "portable_resume"
            package_root.mkdir()
            (package_root / "first.py").write_bytes(b"abc")

            with mock.patch(
                "portable_resume.build_identity.MAX_SOURCE_FILE_BYTES",
                2,
            ):
                with self.assertRaisesRegex(ValueError, "bounded regular file"):
                    source_sha256(package_root)

            (package_root / "first.py").write_bytes(b"ab")
            (package_root / "second.py").write_bytes(b"cd")
            with (
                mock.patch(
                    "portable_resume.build_identity.MAX_SOURCE_FILE_BYTES",
                    2,
                ),
                mock.patch(
                    "portable_resume.build_identity.MAX_SOURCE_TOTAL_BYTES",
                    3,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "aggregate bound"):
                    source_sha256(package_root)

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_source_digest_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_root = root / "portable_resume"
            package_root.mkdir()
            target = root / "outside.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            (package_root / "module.py").symlink_to(target)

            with self.assertRaisesRegex(ValueError, "non-regular file"):
                source_sha256(package_root)

    def test_build_inputs_digest_enforces_per_file_and_aggregate_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_bytes(b"abc")

            with mock.patch(
                "scripts.git_build_identity.MAX_BUILD_INPUT_FILE_BYTES",
                2,
            ):
                with self.assertRaisesRegex(ValueError, "bounded stable regular"):
                    build_inputs_sha256(root)

            (root / "README.md").write_bytes(b"ab")
            (root / "LICENSE").write_bytes(b"cd")
            with (
                mock.patch(
                    "scripts.git_build_identity.MAX_BUILD_INPUT_FILE_BYTES",
                    2,
                ),
                mock.patch(
                    "scripts.git_build_identity.MAX_BUILD_INPUT_TOTAL_BYTES",
                    3,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "aggregate bound"):
                    build_inputs_sha256(root)

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_build_inputs_digest_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "outside.md"
            target.write_text("outside\n", encoding="utf-8")
            (root / "README.md").symlink_to(target)

            with self.assertRaisesRegex(ValueError, "bounded stable regular"):
                build_inputs_sha256(root)


@unittest.skipUnless(shutil.which("git"), "git is required for identity tests")
class BuildIdentityGitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary.name)
        self.package_root = self.repo_root / "src" / "portable_resume"
        self.package_root.mkdir(parents=True)
        (self.package_root / "__init__.py").write_text("", encoding="utf-8")
        self._git("init", "--quiet")
        self._git("config", "user.email", "identity-tests@example.invalid")
        self._git("config", "user.name", "Build Identity Tests")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(result.stderr)
        return result.stdout.strip()

    def test_clean_version_tag_reports_exact_release_identity(self) -> None:
        self._git("tag", "-a", "v1.2.3", "-m", "release v1.2.3")

        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.3",
        )

        self.assertEqual(identity["version"], "1.2.3")
        self.assertEqual(identity["release_channel"], "release")
        self.assertEqual(identity["commit_sha"], self._git("rev-parse", "HEAD"))
        self.assertIs(identity["dirty"], False)
        self.assertRegex(str(identity["build_inputs_sha256"]), r"^[0-9a-f]{64}$")

    def test_lightweight_version_tag_is_not_an_exact_release(self) -> None:
        self._git("tag", "v1.2.3")

        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.3",
        )

        self.assertEqual(identity["release_channel"], "development")
        self.assertRegex(identity["version"], r"^1\.2\.3\+g[0-9a-f]{12}$")

    def test_clean_development_commit_includes_git_local_version(self) -> None:
        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.4.dev0",
        )

        self.assertRegex(identity["version"], r"^1\.2\.4\.dev0\+g[0-9a-f]{7,40}$")
        self.assertEqual(identity["release_channel"], "development")
        self.assertIs(identity["dirty"], False)

    def test_dirty_development_commit_is_distinguishable(self) -> None:
        (self.package_root / "module.py").write_text("DIRTY = True\n", encoding="utf-8")

        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.4.dev0",
        )

        self.assertRegex(
            identity["version"],
            r"^1\.2\.4\.dev0\+g[0-9a-f]{7,40}\.dirty$",
        )
        self.assertIs(identity["dirty"], True)

    def test_identity_does_not_leak_repository_path(self) -> None:
        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.4.dev0",
        )

        self.assertNotIn(str(self.repo_root), identity_json_bytes(identity).decode("utf-8"))

    def test_ignored_package_source_prevents_release_identity(self) -> None:
        (self.repo_root / ".gitignore").write_text(
            "src/portable_resume/ignored.py\n",
            encoding="utf-8",
        )
        self._git("add", ".gitignore")
        self._git("commit", "--quiet", "-m", "ignore generated source")
        self._git("tag", "-a", "v1.2.3", "-m", "release v1.2.3")
        (self.package_root / "ignored.py").write_text("VALUE = 1\n", encoding="utf-8")

        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.3",
        )

        self.assertEqual(identity["release_channel"], "development")
        self.assertIs(identity["dirty"], True)

    def test_ignored_root_build_config_prevents_release_identity(self) -> None:
        (self.repo_root / ".gitignore").write_text("setup.py\n", encoding="utf-8")
        self._git("add", ".gitignore")
        self._git("commit", "--quiet", "-m", "ignore build config")
        self._git("tag", "-a", "v1.2.3", "-m", "release v1.2.3")
        (self.repo_root / "setup.py").write_text("raise SystemExit\n", encoding="utf-8")

        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.3",
        )

        self.assertEqual(identity["release_channel"], "development")
        self.assertIs(identity["dirty"], True)


class BuildIdentityFallbackTests(unittest.TestCase):
    def test_source_archive_without_git_has_deterministic_development_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "portable_resume"
            package_root.mkdir()
            (package_root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            first = build_identity(
                package_root=package_root,
                base_version="1.2.4.dev0",
            )
            second = build_identity(
                package_root=package_root,
                base_version="1.2.4.dev0",
            )

            self.assertEqual(second, first)
            self.assertEqual(first["version"], "1.2.4.dev0")
            self.assertEqual(first["release_channel"], "development")
            self.assertIsNone(first["commit_sha"])
            self.assertIsNone(first["dirty"])
            self.assertIsNone(first["build_inputs_sha256"])


class BuildIdentitySerializationTests(unittest.TestCase):
    def _valid_identity(self) -> dict[str, object]:
        return {
            "schema": BUILD_IDENTITY_SCHEMA,
            "version": "1.2.4.dev0+g0123456789ab",
            "base_version": "1.2.4.dev0",
            "release_channel": "development",
            "commit_sha": "0123456789abcdef0123456789abcdef01234567",
            "dirty": False,
            "build_inputs_sha256": "c" * 64,
            "registry_sha256": "a" * 64,
            "source_sha256": "b" * 64,
        }

    def test_json_serialization_is_canonical_and_newline_terminated(self) -> None:
        identity = self._valid_identity()

        encoded = identity_json_bytes(dict(reversed(tuple(identity.items()))))

        self.assertEqual(encoded, identity_json_bytes(identity))
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertEqual(json.loads(encoded), identity)
        self.assertNotRegex(encoded.decode("utf-8"), re.compile(r":\s|,\s"))

    def test_schema_validation_accepts_complete_identity(self) -> None:
        self.assertIsNone(validate_identity(self._valid_identity()))

    def test_builder_emits_v2_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "portable_resume"
            package_root.mkdir()
            (package_root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            identity = build_identity(package_root=package_root)

        self.assertEqual(identity["schema"], BUILD_IDENTITY_SCHEMA)
        self.assertIn("build_inputs_sha256", identity)

    def test_legacy_v1_identity_loads_validates_and_round_trips(self) -> None:
        identity = self._valid_identity()
        identity["schema"] = BUILD_IDENTITY_SCHEMA_V1
        del identity["build_inputs_sha256"]
        encoded = (
            json.dumps(identity, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")

        self.assertIsNone(validate_identity(identity))
        self.assertEqual(load_identity_bytes(encoded), identity)
        self.assertEqual(identity_json_bytes(identity), encoded)

    def test_legacy_v1_source_archive_identity_remains_valid(self) -> None:
        identity = self._valid_identity()
        identity.update(
            {
                "schema": BUILD_IDENTITY_SCHEMA_V1,
                "version": "1.2.4.dev0",
                "commit_sha": None,
                "dirty": None,
                "provenance": "source-archive",
            }
        )
        del identity["build_inputs_sha256"]

        self.assertIsNone(validate_identity(identity))
        self.assertEqual(load_identity_bytes(identity_json_bytes(identity)), identity)

    def test_v1_rejects_v2_field_and_v2_requires_it(self) -> None:
        v1_with_v2_field = self._valid_identity()
        v1_with_v2_field["schema"] = BUILD_IDENTITY_SCHEMA_V1
        with self.assertRaisesRegex(ValueError, "incomplete or unknown"):
            validate_identity(v1_with_v2_field)

        v2_without_required_field = self._valid_identity()
        del v2_without_required_field["build_inputs_sha256"]
        with self.assertRaisesRegex(ValueError, "incomplete or unknown"):
            validate_identity(v2_without_required_field)

    def test_schema_validation_rejects_missing_required_field(self) -> None:
        identity = self._valid_identity()
        del identity["registry_sha256"]

        with self.assertRaises(ValueError):
            validate_identity(identity)

    def test_schema_validation_rejects_malformed_digest(self) -> None:
        identity = self._valid_identity()
        identity["source_sha256"] = "not-a-sha256"

        with self.assertRaises(ValueError):
            validate_identity(identity)

    def test_schema_validation_rejects_integer_dirty_state(self) -> None:
        identity = self._valid_identity()
        identity["dirty"] = 1

        with self.assertRaises(ValueError):
            validate_identity(identity)

    def test_schema_validation_rejects_unrelated_development_version(self) -> None:
        identity = self._valid_identity()
        identity["version"] = "9.9.9.dev0+g0123456789ab"

        with self.assertRaises(ValueError):
            validate_identity(identity)

    def test_builder_rejects_non_boolean_tag_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "portable_resume"
            package_root.mkdir()
            (package_root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                build_identity(
                    package_root=package_root,
                    base_version="1.2.4.dev0",
                    exact_tag=1,  # type: ignore[arg-type]
                )


class EmbeddedBuildIdentityTests(unittest.TestCase):
    def _package(self, root: Path) -> tuple[Path, dict[str, object], bytes]:
        package = root / "portable_resume"
        resources = package / "resources"
        resources.mkdir(parents=True)
        (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        identity = build_identity(package_root=package)
        encoded = identity_json_bytes(identity)
        return package, identity, encoded

    def test_load_identity_file_requires_canonical_bytes_and_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, identity, encoded = self._package(Path(temporary))
            path = package / "resources" / "build-identity.json"
            path.write_bytes(encoded)

            loaded = load_identity_file(
                path,
                expected_sha256=sha256(encoded).hexdigest(),
            )

            self.assertEqual(loaded, identity)

    def test_load_identity_file_rejects_hash_mismatch_noncanonical_and_oversized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, identity, encoded = self._package(Path(temporary))
            path = package / "resources" / "build-identity.json"
            path.write_bytes(encoded)
            with self.assertRaises(ValueError):
                load_identity_file(path, expected_sha256="0" * 64)

            path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_identity_file(path)

            path.write_bytes(b"{" + b" " * 20_000 + b"}")
            with self.assertRaises(ValueError):
                load_identity_file(path)

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_load_identity_file_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, _, encoded = self._package(Path(temporary))
            target = package / "resources" / "identity-target.json"
            target.write_bytes(encoded)
            link = package / "resources" / "build-identity.json"
            link.symlink_to(target)

            with self.assertRaises(ValueError):
                load_identity_file(link)

    def test_runtime_identity_uses_fixed_embedded_resource_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, identity, encoded = self._package(Path(temporary))
            embedded = package / "resources" / "build-identity.json"
            embedded.write_bytes(encoded)

            self.assertEqual(load_embedded_identity(package), identity)
            self.assertEqual(runtime_identity(package), identity)

    def test_present_invalid_embedded_identity_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, _, _ = self._package(Path(temporary))
            embedded = package / "resources" / "build-identity.json"
            embedded.write_text("not json\n", encoding="utf-8")

            with mock.patch(
                "portable_resume.build_identity.build_identity",
                side_effect=AssertionError("fallback must not run"),
            ):
                with self.assertRaises(ValueError):
                    runtime_identity(package)

    def test_runtime_identity_ignores_environment_selected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, _, _ = self._package(root / "source")
            other_package, _, other_encoded = self._package(root / "other")
            external = other_package / "resources" / "external.json"
            external.write_bytes(other_encoded)

            with mock.patch.dict(
                os.environ,
                {"PORTABLE_RESUME_BUILD_IDENTITY_FILE": str(external)},
                clear=False,
            ):
                loaded = runtime_identity(package)

            self.assertEqual(loaded, build_identity(package_root=package))


if __name__ == "__main__":
    unittest.main()
