from __future__ import annotations

import unittest

from portable_resume.build_identity import BUILD_IDENTITY_SCHEMA
from portable_resume.version_state import baseline_tag_errors, evaluate_version_state


def identity(
    version: str,
    *,
    channel: str = "development",
    commit: str | None = "1" * 40,
    dirty: bool | None = False,
    registry: str = "a" * 64,
    source: str = "b" * 64,
) -> dict[str, object]:
    return {
        "schema": BUILD_IDENTITY_SCHEMA,
        "version": version,
        "base_version": version.split("+", 1)[0],
        "release_channel": channel,
        "commit_sha": commit,
        "dirty": dirty,
        "registry_sha256": registry,
        "source_sha256": source,
    }


LATEST = {
    "version": "0.3.4",
    "tag": "v0.3.4",
    "commit_sha": "0" * 40,
    "registry_sha256": "c" * 64,
    "source_sha256": "d" * 64,
}


class VersionStateTests(unittest.TestCase):
    def test_post_release_development_version_passes(self) -> None:
        report = evaluate_version_state(
            identity("0.4.0.dev0+g111111111111"),
            LATEST,
            head_sha="1" * 40,
        )
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["state"], "development")

    def test_same_published_version_with_divergent_identity_fails(self) -> None:
        report = evaluate_version_state(
            identity("0.3.4+g111111111111"),
            LATEST,
            head_sha="1" * 40,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("published version has divergent" in error for error in report["errors"])
        )

    def test_exact_published_identity_passes(self) -> None:
        release = identity(
            "0.3.4",
            channel="release",
            commit="0" * 40,
            registry="c" * 64,
            source="d" * 64,
        )
        report = evaluate_version_state(
            release,
            LATEST,
            tag_commits={"v0.3.4": "0" * 40},
            head_sha="0" * 40,
        )
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["state"], "published-release")

    def test_untagged_next_stable_version_is_release_candidate(self) -> None:
        report = evaluate_version_state(
            identity("0.4.0+g111111111111"),
            LATEST,
            head_sha="1" * 40,
        )
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["state"], "release-candidate")

    def test_published_tag_at_another_commit_blocks_stable_reuse(self) -> None:
        report = evaluate_version_state(
            identity("0.4.0+g111111111111"),
            LATEST,
            tag_commits={"v0.4.0": "2" * 40},
            head_sha="1" * 40,
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["state"], "post-release-divergent")

    def test_development_version_must_advance_latest_release(self) -> None:
        report = evaluate_version_state(
            identity("0.3.4.dev1+g111111111111"),
            LATEST,
            head_sha="1" * 40,
        )
        self.assertFalse(report["ok"])
        self.assertIn(
            "development version must advance beyond the latest release",
            report["errors"],
        )

    def test_baseline_must_match_latest_tag_during_development(self) -> None:
        current = identity("0.5.0.dev0+g111111111111")
        errors = baseline_tag_errors(
            current,
            LATEST,
            tag_commits={"v0.3.4": "0" * 40, "v0.4.0": "2" * 40},
            head_sha="1" * 40,
        )
        self.assertIn("latest release baseline is stale", errors)

    def test_new_release_tag_may_build_before_post_release_baseline_update(self) -> None:
        release = identity(
            "0.4.0",
            channel="release",
            commit="2" * 40,
        )
        errors = baseline_tag_errors(
            release,
            LATEST,
            tag_commits={"v0.3.4": "0" * 40, "v0.4.0": "2" * 40},
            head_sha="2" * 40,
        )
        self.assertEqual(errors, [])

    def test_baseline_commit_must_match_recorded_tag(self) -> None:
        errors = baseline_tag_errors(
            identity("0.4.0.dev0+g111111111111"),
            LATEST,
            tag_commits={"v0.3.4": "9" * 40},
            head_sha="1" * 40,
        )
        self.assertIn("latest release baseline does not match its Git tag", errors)

    def test_missing_baseline_tag_fails_closed(self) -> None:
        errors = baseline_tag_errors(
            identity("0.4.0.dev0+g111111111111"),
            LATEST,
            tag_commits={},
            head_sha="1" * 40,
        )
        self.assertIn("latest release baseline does not match its Git tag", errors)
        self.assertIn("no stable release tags are available", errors)


if __name__ == "__main__":
    unittest.main()
