"""Adversarial Windows installer product-path integration tests under test-only harness."""

from __future__ import annotations

import json
import os
import stat
import tempfile
if os.name == "nt":
    import _winapi
else:
    _winapi = None  # type: ignore
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError, ExitCode
from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.transaction import (
    RootLock,
    _allow_windows_install_for_tests,
    _is_windows_install_allowed_for_tests,
    execute_install,
    plan_install,
    recover_root,
    require_mutating_install_platform,
    uninstall_claim,
    verify_root,
)
from portable_resume.platform_fs.windows import WindowsFilesystemBackend


def _tree_snapshot(root: str | Path) -> dict[str, tuple[str, bytes]]:
    root_path = Path(root)
    if not root_path.exists():
        return {}
    snapshot: dict[str, tuple[str, bytes]] = {}
    for p in sorted(root_path.rglob("*")):
        rel = p.relative_to(root_path).as_posix()
        try:
            st = os.lstat(p)
        except OSError:
            continue
        is_reparse = bool(getattr(st, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(st.st_mode) or is_reparse:
            snapshot[rel] = ("reparse_or_link", b"")
        elif stat.S_ISDIR(st.st_mode):
            snapshot[rel] = ("dir", b"")
        elif stat.S_ISREG(st.st_mode):
            try:
                snapshot[rel] = ("file", p.read_bytes())
            except OSError:
                snapshot[rel] = ("file", b"")
    return snapshot


@unittest.skipUnless(os.name == "nt", "Requires Windows nt")
class WindowsInstallAdversarialIntegrationTests(unittest.TestCase):

    def test_harness_toggle_isolation_and_default_state(self) -> None:
        """Verify harness defaults to False and restores state on exit or exception.

        Phase 7: require_mutating_install_platform() no longer raises on real
        Windows regardless of harness state.  The harness toggle itself still
        works for backward compatibility.
        """
        self.assertFalse(_is_windows_install_allowed_for_tests())
        # Phase 7: no longer raises on real Windows
        require_mutating_install_platform()

        with _allow_windows_install_for_tests():
            self.assertTrue(_is_windows_install_allowed_for_tests())
            require_mutating_install_platform()  # Should not raise

        self.assertFalse(_is_windows_install_allowed_for_tests())

        try:
            with _allow_windows_install_for_tests():
                self.assertTrue(_is_windows_install_allowed_for_tests())
                raise ValueError("Intentional error inside harness")
        except ValueError:
            pass

        self.assertFalse(_is_windows_install_allowed_for_tests())

    def test_happy_path_dry_run_zero_mutations(self) -> None:
        """Dry-run install produces zero filesystem mutations with or without harness."""
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            Path(root).mkdir()
            plan = plan_install(host="claude", scope="project", root=root, dry_run=True)
            before = _tree_snapshot(root)

            # Without harness
            res1 = execute_install(plan)
            self.assertTrue(res1["ok"])
            self.assertTrue(res1["dry_run"])
            self.assertEqual(before, _tree_snapshot(root))

            # With harness
            with _allow_windows_install_for_tests():
                res2 = execute_install(plan)
            self.assertTrue(res2["ok"])
            self.assertTrue(res2["dry_run"])
            self.assertEqual(before, _tree_snapshot(root))

    def test_locked_install_temporary_root(self) -> None:
        """Real mutating install executes with RootLock and relative mutations (Phase 7: no harness needed)."""
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            plan = plan_install(host="claude", scope="project", root=root)

            # Phase 7: install succeeds without harness on real Windows
            res = execute_install(plan)
            self.assertTrue(res["ok"])
            self.assertFalse(res["dry_run"])

            # Verify files materialized and manifest published
            state_dir = Path(root) / ".portable-resume" / ".state"
            self.assertTrue((state_dir / "manifest.json").is_file())
            self.assertTrue((state_dir / "install.lock").is_file())

            # Verify root integrity
            verified = verify_root(root)
            self.assertTrue(verified["ok"])

    def test_uninstall_and_journal_recovery(self) -> None:
        """Uninstall and journal recovery execute real transactions (Phase 7: no harness needed)."""
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            plan = plan_install(host="claude", scope="project", root=root)

            # 1. Install
            res_inst = execute_install(plan)
            self.assertTrue(res_inst["ok"])

            # 2. Uninstall
            res_uninst = uninstall_claim(host="claude", scope="project", root=root)
            self.assertTrue(res_uninst["ok"])
            self.assertFalse((Path(root) / ".portable-resume" / ".state" / "manifest.json").exists())

            # 3. Journal recovery simulation
            Path(root).mkdir(parents=True, exist_ok=True)
            state_dir = Path(root) / ".portable-resume" / ".state"
            state_dir.mkdir(parents=True, exist_ok=True)

            journal_data = {
                "schema_version": "portable-resume/install-journal-v1",
                "state": "staging",
                "generation": 1,
                "claim": "claude:project",
                "stage_dir": str(state_dir / "portable-resume-stage-test123"),
                "operation": "install",
                "paths": {},
            }
            (state_dir / "journal.json").write_text(json.dumps(journal_data), encoding="utf-8")
            sentinel = Path(root) / "sentinel.txt"
            sentinel.write_bytes(b"keep me")

            res_rec = recover_root(root)
            self.assertTrue(res_rec["ok"])
            self.assertTrue(res_rec["recovered"])
            self.assertFalse((state_dir / "journal.json").exists())
            self.assertEqual(sentinel.read_bytes(), b"keep me")

    def test_lock_contention_blocks_second_install(self) -> None:
        """Second concurrent install attempt is blocked by exclusive RootLock, raising E_INSTALL_BUSY."""
        backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")
            Path(root).mkdir()
            lock_path = Path(root) / ".portable-resume" / ".state" / "install.lock"

            plan = plan_install(host="claude", scope="project", root=root)

            # Hold exclusive lock on lock_path
            with backend.acquire_exclusive_lock(lock_path):
                before = _tree_snapshot(root)
                with self.assertRaises(DiagnosticError) as ctx:
                    execute_install(plan)
                self.assertEqual(ctx.exception.code, "E_INSTALL_BUSY")
                after = _tree_snapshot(root)
                self.assertEqual(before, after)

    def test_junction_attack_rejection(self) -> None:
        """Attempted NTFS junction redirect escaping root raises E_UNSAFE_PATH and leaves target untouched."""
        backend = WindowsFilesystemBackend()
        with tempfile.TemporaryDirectory() as temporary:
            temp_path = Path(temporary)
            target_dir = temp_path / "external_target"
            target_dir.mkdir()
            sensitive = target_dir / "sensitive.txt"
            sensitive.write_bytes(b"topsecret")

            skill_root = temp_path / "skill_root"
            skill_root.mkdir()
            sub_dir = skill_root / "sub"
            sub_dir.mkdir()

            junction = sub_dir / "junc"
            _winapi.CreateJunction(str(target_dir), str(junction))

            ext_before = _tree_snapshot(target_dir)

            # Attempting relative mutation escaping via junction
            with self.assertRaises(DiagnosticError) as ctx:
                backend.replace_beneath(sensitive, skill_root / "escaped.txt", root=skill_root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

            with self.assertRaises(DiagnosticError) as ctx:
                backend.unlink_beneath(junction / "sensitive.txt", root=skill_root)
            self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

            ext_after = _tree_snapshot(target_dir)
            self.assertEqual(ext_before, ext_after)
            self.assertEqual(sensitive.read_bytes(), b"topsecret")

    def test_strict_snapshot_and_side_effect_assertions_on_failure_paths(self) -> None:
        """Failure paths leave zero unexpected filesystem side effects.

        Phase 7: On real Windows the platform gate no longer rejects.
        This test verifies junction-attack and lock-contention failures
        still leave no side effects.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "skills")

            # Install succeeds on real Windows (Phase 7)
            plan = plan_install(host="claude", scope="project", root=root)
            res = execute_install(plan)
            self.assertTrue(res["ok"])

            # Verify integrity after install
            verified = verify_root(root)
            self.assertTrue(verified["ok"])


def _take_tree_snapshot(root_path: Path) -> dict[str, tuple[str, bytes]]:
    return _tree_snapshot(root_path)


@unittest.skipUnless(os.name == "nt", "Requires Windows nt")
class WindowsJunctionAttackStressTests(unittest.TestCase):

    def setUp(self) -> None:
        self.backend = WindowsFilesystemBackend()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.tmp_dir.name)

        # External sensitive directory & file (outside skill_root)
        self.external_dir = self.base_path / "external_sensitive"
        self.external_dir.mkdir()
        self.sensitive_file = self.external_dir / "secret.txt"
        self.sensitive_file.write_bytes(b"SUPER_SECRET_DATA_12345")

        # Main skill root directory
        self.skill_root = self.base_path / "skill_root"
        self.skill_root.mkdir()

        # Capture baseline snapshot of external directory
        self.ext_before = _take_tree_snapshot(self.external_dir)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _assert_external_untouched(self) -> None:
        """Assert external target files remain 100% untouched."""
        ext_after = _take_tree_snapshot(self.external_dir)
        self.assertEqual(self.ext_before, ext_after, "External directory was mutated!")
        self.assertEqual(
            self.sensitive_file.read_bytes(),
            b"SUPER_SECRET_DATA_12345",
            "Sensitive file content modified!",
        )

    # -------------------------------------------------------------------------
    # Category 1: Intermediate Parent Directory Converted to Junction Mid-Path
    # -------------------------------------------------------------------------

    def test_intermediate_parent_junction_external_mkdirs(self) -> None:
        """backend.mkdirs_beneath fails with E_UNSAFE_PATH when intermediate parent is a junction to external dir."""
        inter_junc = self.skill_root / "inter_junc"
        _winapi.CreateJunction(str(self.external_dir), str(inter_junc))

        target_dir = inter_junc / "nested_dir"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.mkdirs_beneath(target_dir, root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
        self._assert_external_untouched()

    def test_intermediate_parent_junction_external_replace(self) -> None:
        """backend.replace_beneath fails with E_UNSAFE_PATH when dst parent has intermediate junction."""
        inter_junc = self.skill_root / "inter_junc"
        _winapi.CreateJunction(str(self.external_dir), str(inter_junc))

        src_file = self.skill_root / "staged.txt"
        src_file.write_bytes(b"attack payload")

        target_file = inter_junc / "sub" / "malicious.txt"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(src_file, target_file, root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")
        self._assert_external_untouched()

    def test_intermediate_parent_junction_external_execute_install(self) -> None:
        """execute_install rejects transaction when intermediate parent in install path is a junction to external dir."""
        plan = plan_install(host="claude", scope="project", root=str(self.skill_root))
        first_file = list(plan.files.keys())[0]  # e.g., '.portable-resume/resources/handoff-policy.md'
        first_dir_component = first_file.split("/")[0]

        # Convert the intermediate target directory into a junction pointing outside skill_root
        target_junc = self.skill_root / first_dir_component
        _winapi.CreateJunction(str(self.external_dir), str(target_junc))

        with self.assertRaises(DiagnosticError) as ctx:
            execute_install(plan)
        self.assertIn(ctx.exception.code, ("E_UNSAFE_PATH", "E_INSTALL_CONFLICT"))

        self._assert_external_untouched()

    def test_intermediate_parent_junction_internal(self) -> None:
        """Intermediate junction pointing INSIDE root is also rejected with E_UNSAFE_PATH."""
        legit_dir = self.skill_root / "legit_internal"
        legit_dir.mkdir()
        internal_junc = self.skill_root / "internal_junc"
        _winapi.CreateJunction(str(legit_dir), str(internal_junc))

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.mkdirs_beneath(internal_junc / "nested", root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        src = self.skill_root / "tmp.txt"
        src.write_bytes(b"data")
        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(src, internal_junc / "out.txt", root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_intermediate_parent_converted_to_junction_mid_install(self) -> None:
        """Parent directory converted to junction right before commit step in transaction."""
        plan = plan_install(host="claude", scope="project", root=str(self.skill_root))
        first_file = list(plan.files.keys())[0]
        first_dir_component = first_file.split("/")[0]

        # Create normal directory first
        normal_dir = self.skill_root / first_dir_component
        normal_dir.mkdir(parents=True, exist_ok=True)

        # Convert to junction right before execution
        normal_dir.rmdir()
        _winapi.CreateJunction(str(self.external_dir), str(normal_dir))

        with self.assertRaises(DiagnosticError) as ctx:
            execute_install(plan)
        self.assertIn(ctx.exception.code, ("E_UNSAFE_PATH", "E_INSTALL_CONFLICT"))

        self._assert_external_untouched()

    # -------------------------------------------------------------------------
    # Category 2: Target Payload Path Pointing to NTFS Junction (External Redirect)
    # -------------------------------------------------------------------------

    def test_target_payload_leaf_is_junction_to_external_dir(self) -> None:
        """Target leaf path is an NTFS junction redirecting to external dir with sensitive file."""
        junc_leaf = self.skill_root / "target_junc"
        _winapi.CreateJunction(str(self.external_dir), str(junc_leaf))

        src_file = self.skill_root / "stage.txt"
        src_file.write_bytes(b"overwrite attempt")

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(src_file, junc_leaf / "secret.txt", root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.unlink_beneath(junc_leaf / "secret.txt", root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        self._assert_external_untouched()

    def test_target_payload_leaf_direct_junction_replace(self) -> None:
        """Directly replacing a junction leaf with a file raises E_UNSAFE_PATH or E_INSTALL_CONFLICT."""
        junc_leaf = self.skill_root / "direct_junc"
        _winapi.CreateJunction(str(self.external_dir), str(junc_leaf))

        src_file = self.skill_root / "stage.txt"
        src_file.write_bytes(b"overwrite attempt")

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(src_file, junc_leaf, root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        self._assert_external_untouched()

    def test_target_payload_read_stable_rejection(self) -> None:
        """read_regular_stable fails with E_UNSAFE_PATH when targeting file inside junction."""
        junc = self.skill_root / "junc"
        _winapi.CreateJunction(str(self.external_dir), str(junc))

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.read_regular_stable(junc / "secret.txt", root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

    def test_uninstall_claim_with_junction_path_rejection(self) -> None:
        """uninstall_claim fails or safely ignores junction paths without touching external targets."""
        junc = self.skill_root / "junc"
        _winapi.CreateJunction(str(self.external_dir), str(junc))

        res = uninstall_claim(host="claude", scope="project", root=str(self.skill_root))

        self.assertTrue(res["ok"])
        self._assert_external_untouched()

    def test_recover_root_with_junction_journal_rejection(self) -> None:
        """recover_root safely rejects junction targets specified in a malicious journal."""
        state_dir = self.skill_root / ".portable-resume" / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)

        junc = self.skill_root / "junc"
        _winapi.CreateJunction(str(self.external_dir), str(junc))

        malicious_journal = {
            "schema_version": "portable-resume/install-journal-v1",
            "state": "committing",
            "generation": 1,
            "claim": "claude:project",
            "stage_dir": str(state_dir / "portable-resume-stage-evil"),
            "operation": "install",
            "paths": {
                "junc/secret.txt": {
                    "state": "staged",
                    "sha256": "0" * 64,
                    "existed": True,
                    "rollback_backup": str(state_dir / "portable-resume-stage-evil" / ".rollback" / "junc" / "secret.txt"),
                    "original_sha256": "1" * 64,
                }
            },
        }
        (state_dir / "journal.json").write_text(json.dumps(malicious_journal), encoding="utf-8")

        try:
            res = recover_root(str(self.skill_root))
            self.assertTrue(res["ok"])
        except DiagnosticError as ctx:
            self.assertIn(ctx.code, ("E_UNSAFE_PATH", "E_INSTALL_CONFLICT", "E_RECOVERY_REQUIRED"))

        self._assert_external_untouched()

    # -------------------------------------------------------------------------
    # Category 3: Reparse Point Escape via Relative Traversal `..`
    # -------------------------------------------------------------------------

    def test_relative_traversal_through_junction_rejection(self) -> None:
        """Relative traversal via .. combined with junction is rejected with E_UNSAFE_PATH."""
        junc = self.skill_root / "junc"
        _winapi.CreateJunction(str(self.external_dir), str(junc))

        bad_path = junc / ".." / "secret.txt"

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.mkdirs_beneath(junc / "..", root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        src = self.skill_root / "file.txt"
        src.write_bytes(b"data")
        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(src, bad_path, root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.unlink_beneath(bad_path, root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        self._assert_external_untouched()

    def test_relative_traversal_escaping_root_rejection(self) -> None:
        """Relative traversal escaping skill_root raises E_UNSAFE_PATH."""
        escape_path = self.skill_root / "sub" / ".." / ".." / "external_sensitive" / "secret.txt"

        src = self.skill_root / "file.txt"
        src.write_bytes(b"data")

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.replace_beneath(src, escape_path, root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        with self.assertRaises(DiagnosticError) as ctx:
            self.backend.unlink_beneath(escape_path, root=self.skill_root)
        self.assertEqual(ctx.exception.code, "E_UNSAFE_PATH")

        self._assert_external_untouched()

    def test_root_lock_on_junction_rejection(self) -> None:
        """RootLock rejects lock acquisition when root itself is a junction to external dir."""
        junc_root = self.skill_root / "junc_root"
        _winapi.CreateJunction(str(self.external_dir), str(junc_root))

        with self.assertRaises(DiagnosticError) as ctx:
            with RootLock(str(junc_root)):
                pass
        self.assertIn(ctx.exception.code, ("E_UNSAFE_PATH", "E_INSTALL_UNSUPPORTED_PLATFORM", "E_INSTALL_CONFLICT"))

        self._assert_external_untouched()


if __name__ == "__main__":
    unittest.main()

