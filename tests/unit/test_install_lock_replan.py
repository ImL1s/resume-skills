"""#35: execute_install rebuilds and authorizes under RootLock."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.install.transaction import (
    execute_install,
    load_manifest,
    manifest_content_digest,
    manifest_path,
    plan_install,
)


class InstallLockReplanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = str(Path(self.temp.name) / "skill-root")
        Path(self.root).mkdir()

    def test_manifest_deleted_between_plan_and_execute_does_not_resurrect_claims(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        first = load_manifest(self.root)
        self.assertIsNotNone(first)
        assert first is not None
        self.assertGreaterEqual(first.generation, 1)
        claim = next(iter(first.claims))

        plan = plan_install(host="claude", scope="project", root=self.root)
        self.assertEqual(plan.base_generation, first.generation)
        # Delete ownership manifest after preflight (simulate concurrent wipe).
        os.unlink(manifest_path(self.root))
        self.assertIsNone(load_manifest(self.root))

        result = execute_install(plan)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("changed_since_preflight"))
        published = load_manifest(self.root)
        self.assertIsNotNone(published)
        assert published is not None
        # Fresh install under absence → generation 1, not preflight gen+1 resurrection.
        self.assertEqual(published.generation, 1)
        self.assertIn(claim, published.claims)
        self.assertEqual(result["previous_manifest_digest"], "absent")

    def test_same_generation_content_swap_uses_locked_manifest(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        plan = plan_install(host="claude", scope="project", root=self.root)
        # Tamper on-disk manifest: keep generation, change package_identity/claims text.
        path = Path(manifest_path(self.root))
        data = json.loads(path.read_text(encoding="utf-8"))
        original_gen = data["generation"]
        data["package_identity"] = "swapped-identity-" + ("a" * 40)
        # Keep schema valid enough for loads.
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        swapped = load_manifest(self.root)
        self.assertIsNotNone(swapped)
        assert swapped is not None
        self.assertEqual(swapped.generation, original_gen)
        self.assertNotEqual(manifest_content_digest(swapped), plan.base_manifest_digest)

        result = execute_install(plan)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("changed_since_preflight"))
        published = load_manifest(self.root)
        assert published is not None
        # Locked replan builds package identity from trusted materialize, not swap.
        self.assertNotEqual(published.package_identity, "swapped-identity-" + ("a" * 40))
        self.assertEqual(published.generation, original_gen + 1)

    def test_tampered_actionplan_files_cannot_be_committed(self) -> None:
        plan = plan_install(host="claude", scope="project", root=self.root)
        # Inject attacker payload into the preflight plan object.
        victim_rel = sorted(plan.files)[0]
        plan.files[victim_rel] = b"ATTACKER_BYTES_NOT_FROM_PACKAGE\n"
        result = execute_install(plan)
        self.assertTrue(result["ok"])
        on_disk = Path(self.root) / victim_rel
        self.assertTrue(on_disk.is_file())
        self.assertNotEqual(on_disk.read_bytes(), b"ATTACKER_BYTES_NOT_FROM_PACKAGE\n")
        # Trusted package content (skill markdown or runner) should remain package-shaped.
        self.assertNotIn(b"ATTACKER_BYTES_NOT_FROM_PACKAGE", on_disk.read_bytes())

    def test_preflight_digest_recorded_and_stable_when_unchanged(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        plan = plan_install(host="claude", scope="project", root=self.root)
        existing = load_manifest(self.root)
        self.assertEqual(plan.base_manifest_digest, manifest_content_digest(existing))
        result = execute_install(plan)
        self.assertFalse(result.get("changed_since_preflight"))
        self.assertEqual(result["previous_manifest_digest"], plan.base_manifest_digest)


if __name__ == "__main__":
    unittest.main()
