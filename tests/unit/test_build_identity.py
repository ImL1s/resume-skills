from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from portable_resume.build_identity import (
    BUILD_IDENTITY_SCHEMA,
    build_identity,
    identity_json_bytes,
    registry_sha256,
    source_sha256,
    validate_identity,
)
from scripts.git_build_identity import git_build_identity


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
        self._git("tag", "v1.2.3")

        identity = git_build_identity(
            repo_root=self.repo_root,
            package_root=self.package_root,
            base_version="1.2.3",
        )

        self.assertEqual(identity["version"], "1.2.3")
        self.assertEqual(identity["release_channel"], "release")
        self.assertEqual(identity["commit_sha"], self._git("rev-parse", "HEAD"))
        self.assertIs(identity["dirty"], False)

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
        self._git("tag", "v1.2.3")
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
        self._git("tag", "v1.2.3")
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


class BuildIdentitySerializationTests(unittest.TestCase):
    def _valid_identity(self) -> dict[str, object]:
        return {
            "schema": BUILD_IDENTITY_SCHEMA,
            "version": "1.2.4.dev0+g0123456789ab",
            "base_version": "1.2.4.dev0",
            "release_channel": "development",
            "commit_sha": "0123456789abcdef0123456789abcdef01234567",
            "dirty": False,
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


if __name__ == "__main__":
    unittest.main()
