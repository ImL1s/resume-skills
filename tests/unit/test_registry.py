from __future__ import annotations

import unittest

from portable_resume.registry import (
    DESTINATION_PROFILES,
    SOURCE_PROFILES,
    DestinationProfile,
    PackageSurface,
    SourceProfile,
    _validate_maps,
    destination_keys,
    enabled_destination_keys,
    enabled_source_keys,
    matrix_dimensions,
    validate_registries,
)


class RegistryInvariantTests(unittest.TestCase):
    def test_current_nine_sources_and_nine_destinations(self) -> None:
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
                    "pi",
                    "qwen",
                }
            ),
        )
        self.assertEqual(
            enabled_destination_keys(),
            frozenset(
                {
                    "antigravity",
                    "claude",
                    "codex",
                    "cursor",
                    "grok",
                    "kimi",
                    "opencode",
                    "pi",
                    "qwen",
                }
            ),
        )
        dims = matrix_dimensions()
        self.assertEqual(dims["sources"], 9)
        self.assertEqual(dims["destinations"], 9)
        self.assertEqual(dims["cells"], 81)

    def test_source_and_destination_sets_are_independent_types(self) -> None:
        # Adding a destination-only key must not invent a source.
        self.assertIn("claude", SOURCE_PROFILES)
        self.assertIn("claude", DESTINATION_PROFILES)
        self.assertIsNot(SOURCE_PROFILES, DESTINATION_PROFILES)

    def test_validate_registries_passes_for_current_tree(self) -> None:
        validate_registries()

    def test_validate_maps_rejects_duplicate_source_keys(self) -> None:
        base = next(iter(SOURCE_PROFILES.values()))
        dup = SourceProfile(
            key=base.key,
            adapter_module=f"portable_resume.adapters.{base.key}-dup",
            format_ids=("dup-v1",),
        )
        with self.assertRaisesRegex(ValueError, "duplicate source keys"):
            _validate_maps(
                {"first": base, "second": dup},
                DESTINATION_PROFILES,
                {},
            )

    def test_validate_maps_rejects_source_key_mismatch(self) -> None:
        profile = SourceProfile(
            key="mismatch",
            adapter_module="portable_resume.adapters.mismatch",
            format_ids=("mismatch-v1",),
        )
        with self.assertRaisesRegex(ValueError, "source map key mismatch"):
            _validate_maps(
                {"wrong": profile},
                DESTINATION_PROFILES,
                {},
            )

    def test_validate_maps_rejects_supported_source_without_format_ids(self) -> None:
        profile = SourceProfile(
            key="empty",
            adapter_module="portable_resume.adapters.empty",
            format_ids=(),
        )
        with self.assertRaisesRegex(ValueError, "supported source missing format_ids"):
            _validate_maps(
                {"empty": profile},
                DESTINATION_PROFILES,
                {},
            )

    def test_validate_maps_rejects_duplicate_destination_keys(self) -> None:
        base = next(iter(DESTINATION_PROFILES.values()))
        dup = DestinationProfile(
            key=base.key,
            payload_profile=f"{base.key}-dup-v1",
        )
        with self.assertRaisesRegex(ValueError, "duplicate destination keys"):
            _validate_maps(
                SOURCE_PROFILES,
                {"first": base, "second": dup},
                {},
            )

    def test_validate_maps_rejects_destination_key_mismatch(self) -> None:
        profile = DestinationProfile(
            key="mismatch",
            payload_profile="mismatch-v1",
        )
        with self.assertRaisesRegex(ValueError, "destination map key mismatch"):
            _validate_maps(
                SOURCE_PROFILES,
                {"wrong": profile},
                {},
            )

    def test_validate_maps_rejects_package_surface_with_missing_owner(self) -> None:
        surface = PackageSurface(
            key="orphan-pkg",
            destination="missing-destination",
            profile="orphan-v1",
        )
        with self.assertRaisesRegex(
            ValueError, "package surface owner missing: missing-destination"
        ):
            _validate_maps(
                SOURCE_PROFILES,
                DESTINATION_PROFILES,
                {"orphan-pkg": surface},
            )

    def test_planned_profiles_excluded_from_enabled_sets(self) -> None:
        for profile in SOURCE_PROFILES.values():
            if profile.status == "supported":
                self.assertIn(profile.key, enabled_source_keys())
            elif profile.status in {"planned", "experimental", "research"}:
                self.assertNotIn(profile.key, enabled_source_keys())
        for profile in DESTINATION_PROFILES.values():
            if profile.status == "supported" and profile.direct_skill:
                self.assertIn(profile.key, enabled_destination_keys())
            elif profile.status in {"planned", "experimental", "research"}:
                self.assertNotIn(profile.key, enabled_destination_keys())

    def test_planned_destination_excluded_from_enabled_sets(self) -> None:
        planned = DestinationProfile(
            key="planned-host",
            payload_profile="planned-host-v1",
            status="planned",
            direct_skill=True,
        )
        enabled = frozenset(
            k
            for k, p in {**DESTINATION_PROFILES, "planned-host": planned}.items()
            if p.status == "supported" and p.direct_skill
        )
        self.assertNotIn("planned-host", enabled)
        self.assertEqual(enabled, enabled_destination_keys())

    def test_destination_profiles_match_host_catalog_roots(self) -> None:
        """Registry DestinationProfile roots must stay aligned with HOST_PROFILES."""
        from portable_resume.install.catalog import HOST_PROFILES

        self.assertEqual(set(HOST_PROFILES), set(enabled_destination_keys()))
        for key, dest in DESTINATION_PROFILES.items():
            if dest.status != "supported" or not dest.direct_skill:
                continue
            host = HOST_PROFILES[key]
            self.assertEqual(dest.project_rel, host.project_rel, msg=key)
            self.assertEqual(dest.global_rel, host.global_rel, msg=key)
            self.assertEqual(dest.payload_profile, host.profile_id, msg=key)


class DynamicMatrixTests(unittest.TestCase):
    def test_matrix_cells_match_dimensions(self) -> None:
        from portable_resume.install.catalog import matrix_cells

        cells = matrix_cells()
        dims = matrix_dimensions()
        self.assertEqual(len(cells), dims["cells"])
        self.assertEqual(len(cells), 81)

    def test_destination_only_expands_rectangle(self) -> None:
        from portable_resume.registry import rectangular_cells

        cells = rectangular_cells(
            sources=frozenset({"claude"}),
            destinations=frozenset({"claude", "pi"}),
        )
        self.assertEqual(cells, [("claude", "claude"), ("pi", "claude")])


if __name__ == "__main__":
    unittest.main()
