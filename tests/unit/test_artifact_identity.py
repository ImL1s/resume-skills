from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.build_identity import (
    BUILD_IDENTITY_SCHEMA_V1,
    build_identity,
    identity_json_bytes,
)
from scripts.git_build_identity import git_build_identity
from scripts.build_artifact_identity import (
    IDENTITY_FILE_ENV,
    IDENTITY_SHA256_ENV,
    reproducible_build_umask,
    resolve_build_identity,
    stage_package_identity,
    write_external_identity,
    write_reproducible_sdist,
    write_staged_identity,
)


class ArtifactIdentityTests(unittest.TestCase):
    def _package(self, root: Path) -> tuple[Path, dict[str, object]]:
        package = root / "src" / "portable_resume"
        (package / "resources").mkdir(parents=True)
        (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        # Stable package versions require an exact-tag release identity before
        # artifact resolve; development bases may use the source-archive fallback.
        from portable_resume import __version__ as package_version
        import re

        if re.fullmatch(r"\d+\.\d+\.\d+", package_version):
            identity = build_identity(
                package_root=package,
                commit_sha="a" * 40,
                dirty=False,
                exact_tag=True,
                build_inputs_sha256="b" * 64,
            )
        else:
            identity = build_identity(package_root=package)
        return package, identity

    def test_explicit_pin_requires_hash_and_resolves_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            pin = root / "pin" / "identity.json"
            digest = write_external_identity(pin, identity)

            loaded = resolve_build_identity(
                repo_root=root,
                package_root=package,
                identity_file=pin,
                expected_sha256=digest,
            )

            self.assertEqual(loaded, identity)
            self.assertEqual(pin.stat().st_mode & 0o777, 0o600)

    def test_artifact_build_rejects_legacy_v1_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            identity["schema"] = BUILD_IDENTITY_SCHEMA_V1
            del identity["build_inputs_sha256"]
            pin = root / "pin" / "identity.json"
            encoded = identity_json_bytes(identity)
            pin.parent.mkdir(parents=True)
            pin.write_bytes(encoded)
            digest = hashlib.sha256(encoded).hexdigest()

            with self.assertRaisesRegex(ValueError, "current identity schema"):
                resolve_build_identity(
                    repo_root=root,
                    package_root=package,
                    identity_file=pin,
                    expected_sha256=digest,
                )

            for destination, writer in (
                (root / "external.json", write_external_identity),
                (root / "staged.json", write_staged_identity),
            ):
                with self.subTest(writer=writer.__name__):
                    with self.assertRaisesRegex(ValueError, "current identity schema"):
                        writer(destination, identity)

    def test_environment_pin_is_all_or_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            pin = root / "identity.json"
            write_external_identity(pin, identity)

            with mock.patch.dict(
                os.environ,
                {IDENTITY_FILE_ENV: str(pin)},
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    resolve_build_identity(repo_root=root, package_root=package)

    def test_explicit_pin_does_not_mix_with_environment_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            pin = root / "identity.json"
            digest = write_external_identity(pin, identity)

            with mock.patch.dict(
                os.environ,
                {IDENTITY_SHA256_ENV: digest},
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    resolve_build_identity(
                        repo_root=root,
                        package_root=package,
                        identity_file=pin,
                    )

    def test_embedded_sdist_identity_precedes_gitless_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            embedded = package / "resources" / "build-identity.json"
            embedded.write_bytes(identity_json_bytes(identity))

            loaded = resolve_build_identity(repo_root=root, package_root=package)

            self.assertEqual(loaded, identity)

    def test_gitless_stable_fallback_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "src" / "portable_resume"
            (package / "resources").mkdir(parents=True)
            (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            with (
                mock.patch("portable_resume.__version__", "9.9.9"),
                mock.patch("portable_resume.build_identity.__version__", "9.9.9"),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "stable artifacts require an exact release identity",
                ):
                    resolve_build_identity(repo_root=root, package_root=package)

    def test_stable_nonrelease_pins_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "src" / "portable_resume"
            (package / "resources").mkdir(parents=True)
            (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            with mock.patch("portable_resume.build_identity.__version__", "9.9.9"):
                for dirty in (False, True):
                    with self.subTest(dirty=dirty):
                        identity = build_identity(
                            package_root=package,
                            base_version="9.9.9",
                            commit_sha="a" * 40,
                            dirty=dirty,
                            build_inputs_sha256="c" * 64,
                        )
                        pin = root / f"identity-{dirty}.json"
                        digest = write_external_identity(pin, identity)
                        with self.assertRaisesRegex(
                            ValueError,
                            "stable artifacts require an exact release identity",
                        ):
                            resolve_build_identity(
                                repo_root=root,
                                package_root=package,
                                identity_file=pin,
                                expected_sha256=digest,
                            )

    def test_exact_stable_release_pin_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "src" / "portable_resume"
            (package / "resources").mkdir(parents=True)
            (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            with mock.patch("portable_resume.build_identity.__version__", "9.9.9"):
                identity = build_identity(
                    package_root=package,
                    base_version="9.9.9",
                    commit_sha="a" * 40,
                    dirty=False,
                    exact_tag=True,
                    build_inputs_sha256="c" * 64,
                )
                pin = root / "identity.json"
                digest = write_external_identity(pin, identity)

                loaded = resolve_build_identity(
                    repo_root=root,
                    package_root=package,
                    identity_file=pin,
                    expected_sha256=digest,
                )

            self.assertEqual(loaded, identity)

    def test_post_pin_source_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            pin = root / "identity.json"
            digest = write_external_identity(pin, identity)
            (package / "module.py").write_text("VALUE = 2\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                resolve_build_identity(
                    repo_root=root,
                    package_root=package,
                    identity_file=pin,
                    expected_sha256=digest,
                )

    @unittest.skipUnless(shutil.which("git"), "git is required for checkout drift test")
    def test_post_pin_root_build_input_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            package = repository / "src" / "portable_resume"
            (package / "resources").mkdir(parents=True)
            (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            readme = repository / "README.md"
            readme.write_text("before\n", encoding="utf-8")
            for arguments in (
                ("init", "--quiet"),
                ("config", "user.email", "identity-tests@example.invalid"),
                ("config", "user.name", "Build Identity Tests"),
                ("add", "."),
                ("commit", "--quiet", "-m", "fixture"),
            ):
                subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                )
            identity = git_build_identity(
                repo_root=repository,
                package_root=package,
            )
            pin = root / "identity.json"
            digest = write_external_identity(pin, identity)
            readme.write_text("after\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "checkout changed"):
                resolve_build_identity(
                    repo_root=repository,
                    package_root=package,
                    identity_file=pin,
                    expected_sha256=digest,
                )

    @unittest.skipUnless(shutil.which("git"), "git is required for checkout drift test")
    def test_post_pin_root_build_input_drift_fails_when_already_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            package = repository / "src" / "portable_resume"
            (package / "resources").mkdir(parents=True)
            (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            readme = repository / "README.md"
            readme.write_text("committed\n", encoding="utf-8")
            for arguments in (
                ("init", "--quiet"),
                ("config", "user.email", "identity-tests@example.invalid"),
                ("config", "user.name", "Build Identity Tests"),
                ("add", "."),
                ("commit", "--quiet", "-m", "fixture"),
            ):
                subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                )
            readme.write_text("first dirty state\n", encoding="utf-8")
            identity = git_build_identity(
                repo_root=repository,
                package_root=package,
            )
            self.assertIs(identity["dirty"], True)
            pin = root / "identity.json"
            digest = write_external_identity(pin, identity)
            readme.write_text("second dirty state\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "checkout changed"):
                resolve_build_identity(
                    repo_root=repository,
                    package_root=package,
                    identity_file=pin,
                    expected_sha256=digest,
                )

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics required")
    @unittest.skipUnless(shutil.which("git"), "git is required for checkout drift test")
    def test_post_pin_root_build_input_mode_drift_fails_when_already_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            package = repository / "src" / "portable_resume"
            (package / "resources").mkdir(parents=True)
            (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            readme = repository / "README.md"
            readme.write_text("committed\n", encoding="utf-8")
            for arguments in (
                ("init", "--quiet"),
                ("config", "user.email", "identity-tests@example.invalid"),
                ("config", "user.name", "Build Identity Tests"),
                ("add", "."),
                ("commit", "--quiet", "-m", "fixture"),
            ):
                subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                )
            readme.write_text("dirty before pin\n", encoding="utf-8")
            identity = git_build_identity(
                repo_root=repository,
                package_root=package,
            )
            pin = root / "identity.json"
            digest = write_external_identity(pin, identity)
            readme.chmod(0o755)

            with self.assertRaisesRegex(ValueError, "checkout changed"):
                resolve_build_identity(
                    repo_root=repository,
                    package_root=package,
                    identity_file=pin,
                    expected_sha256=digest,
                )

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics required")
    @unittest.skipUnless(shutil.which("git"), "git is required for checkout drift test")
    def test_post_pin_package_source_mode_drift_fails_when_already_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            package = repository / "src" / "portable_resume"
            (package / "resources").mkdir(parents=True)
            module = package / "module.py"
            module.write_text("VALUE = 1\n", encoding="utf-8")
            readme = repository / "README.md"
            readme.write_text("committed\n", encoding="utf-8")
            for arguments in (
                ("init", "--quiet"),
                ("config", "user.email", "identity-tests@example.invalid"),
                ("config", "user.name", "Build Identity Tests"),
                ("add", "."),
                ("commit", "--quiet", "-m", "fixture"),
            ):
                subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                )
            readme.write_text("dirty before pin\n", encoding="utf-8")
            identity = git_build_identity(
                repo_root=repository,
                package_root=package,
            )
            pin = root / "identity.json"
            digest = write_external_identity(pin, identity)
            module.chmod(0o755)

            with self.assertRaisesRegex(ValueError, "checkout changed"):
                resolve_build_identity(
                    repo_root=repository,
                    package_root=package,
                    identity_file=pin,
                    expected_sha256=digest,
                )

    def test_staging_refuses_to_replace_different_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            destination = root / "stage" / "build-identity.json"
            write_staged_identity(destination, identity)
            destination.write_text("{}\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                write_staged_identity(destination, identity)

    def test_staged_identity_honors_source_date_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, identity = self._package(root)
            destination = root / "stage" / "build-identity.json"
            with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1234567890"}):
                write_staged_identity(destination, identity)

            self.assertEqual(int(destination.stat().st_mtime), 1234567890)

    def test_completed_staged_package_rejects_stale_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, identity = self._package(root)
            stage_package_identity(package, identity)
            (package / "stale.py").write_text("STALE = True\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                stage_package_identity(package, identity)

    def test_reproducible_sdist_normalizes_metadata_and_gzip_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_tree = root / "first"
            second_tree = root / "second"
            for tree, timestamp, directory_mode, file_mode, executable_mode in (
                (first_tree, 100, 0o755, 0o644, 0o755),
                (second_tree, 200, 0o700, 0o600, 0o700),
            ):
                (tree / "pkg").mkdir(parents=True)
                source = tree / "pkg" / "module.py"
                source.write_text("VALUE = 1\n", encoding="utf-8")
                executable = tree / "pkg" / "tool"
                executable.write_text("#!/bin/sh\n", encoding="utf-8")
                tree.chmod(directory_mode)
                (tree / "pkg").chmod(directory_mode)
                source.chmod(file_mode)
                executable.chmod(executable_mode)
                os.utime(source, (timestamp, timestamp))
                os.utime(executable, (timestamp, timestamp))
                os.utime(tree / "pkg", (timestamp, timestamp))
                os.utime(tree, (timestamp, timestamp))
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"

            with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1234567890"}):
                write_reproducible_sdist(
                    first,
                    first_tree,
                    archive_root_name="portable_resume-1.0.0",
                )
                write_reproducible_sdist(
                    second,
                    second_tree,
                    archive_root_name="portable_resume-1.0.0",
                )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first, "r:gz") as archive:
                members = archive.getmembers()
            self.assertEqual(
                [member.name for member in members],
                [
                    "portable_resume-1.0.0",
                    "portable_resume-1.0.0/pkg",
                    "portable_resume-1.0.0/pkg/module.py",
                    "portable_resume-1.0.0/pkg/tool",
                ],
            )
            self.assertTrue(all(member.mtime == 1234567890 for member in members))
            self.assertTrue(all(member.uid == 0 and member.gid == 0 for member in members))
            self.assertEqual(
                {member.name: member.mode for member in members},
                {
                    "portable_resume-1.0.0": 0o755,
                    "portable_resume-1.0.0/pkg": 0o755,
                    "portable_resume-1.0.0/pkg/module.py": 0o644,
                    "portable_resume-1.0.0/pkg/tool": 0o755,
                },
            )

    @unittest.skipIf(os.name == "nt", "POSIX umask semantics required")
    def test_reproducible_build_umask_normalizes_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = os.umask(0o077)
            try:
                with reproducible_build_umask():
                    normalized_dir = root / "normalized"
                    normalized_dir.mkdir()
                    normalized_file = normalized_dir / "file"
                    normalized_file.write_text("normalized\n", encoding="utf-8")
                restored_file = root / "restored"
                restored_file.write_text("restored\n", encoding="utf-8")
            finally:
                os.umask(original)

            self.assertEqual(normalized_dir.stat().st_mode & 0o777, 0o755)
            self.assertEqual(normalized_file.stat().st_mode & 0o777, 0o644)
            self.assertEqual(restored_file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
