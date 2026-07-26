from __future__ import annotations

import unittest

from portable_resume.registry import (
    DESTINATION_PROFILES,
    PACKAGE_SURFACES,
    SOURCE_PROFILES,
    destination_keys,
    enabled_destination_keys,
    enabled_source_keys,
    matrix_dimensions,
    source_keys,
    validate_registries,
)


class RegistryInvariantTests(unittest.TestCase):
    def test_current_eight_sources_and_destinations(self) -> None:
        self.assertEqual(
            enabled_source_keys(),
            frozenset(
                {
                    "antigravity",
                    "claude",
                    "codex",
                    "cursor",
                    "grok",
                    "kimi",
                    "opencode",
                    "qwen",
                }
            ),
        )
        self.assertEqual(enabled_destination_keys(), enabled_source_keys())
        dims = matrix_dimensions()
        self.assertEqual(dims["sources"], 8)
        self.assertEqual(dims["destinations"], 8)
        self.assertEqual(dims["cells"], 64)

    def test_source_and_destination_sets_are_independent_types(self) -> None:
        # Adding a destination-only key must not invent a source.
        self.assertIn("claude", SOURCE_PROFILES)
        self.assertIn("claude", DESTINATION_PROFILES)
        self.assertIsNot(SOURCE_PROFILES, DESTINATION_PROFILES)

    def test_validate_registries_rejects_duplicate_keys(self) -> None:
        # validate_registries() is the closed gate used by self-check.
        validate_registries()  # current tree must pass

    def test_planned_profiles_excluded_from_enabled_sets(self) -> None:
        # After Task 3 inserts a planned synthetic profile, enabled_* ignore it.
        for profile in SOURCE_PROFILES.values():
            if profile.status == "supported":
                self.assertIn(profile.key, enabled_source_keys())
            elif profile.status in {"planned", "experimental", "research"}:
                self.assertNotIn(profile.key, enabled_source_keys())


if __name__ == "__main__":
    unittest.main()
