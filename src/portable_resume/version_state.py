"""Offline version-lifecycle checks for immutable published identities."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .build_identity import validate_identity

VERSION_STATE_SCHEMA = "portable-resume/version-state-v1"
_BASE_VERSION = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.dev(0|[1-9]\d*))?$"
)
_RELEASE_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _parts(version: str) -> tuple[tuple[int, int, int], bool]:
    match = _BASE_VERSION.fullmatch(version)
    if match is None:
        raise ValueError("unsupported base version")
    return (int(match[1]), int(match[2]), int(match[3])), match[4] is not None


def evaluate_version_state(
    identity: Mapping[str, Any],
    latest_release: Mapping[str, Any],
    *,
    tag_commits: Mapping[str, str] | None = None,
    head_sha: str | None = None,
) -> dict[str, object]:
    """Evaluate one build identity against immutable release/tag facts."""
    validate_identity(identity)
    errors: list[str] = []
    base = str(identity["base_version"])
    current_core, current_is_dev = _parts(base)
    latest_version = latest_release.get("version")
    if not isinstance(latest_version, str):
        raise ValueError("latest release version is missing")
    latest_core, latest_is_dev = _parts(latest_version)
    if latest_is_dev:
        raise ValueError("latest release baseline cannot be a development version")
    latest_tag = latest_release.get("tag")
    if latest_tag != f"v{latest_version}":
        raise ValueError("latest release tag/version mismatch")

    tags = dict(tag_commits or {})
    matching_tag = f"v{base}"
    state = "development"

    if base == latest_version:
        state = "published-release"
        for key in ("commit_sha", "registry_sha256", "source_sha256"):
            if identity.get(key) != latest_release.get(key):
                errors.append(f"published version has divergent {key}")
        if identity.get("release_channel") != "release" or identity.get("dirty") is not False:
            errors.append("published version must be a clean release identity")
    elif current_core < latest_core or (current_core == latest_core and current_is_dev):
        errors.append("development version must advance beyond the latest release")
    elif current_is_dev:
        if identity.get("release_channel") != "development":
            errors.append("development base version must use the development channel")
    else:
        tagged_commit = tags.get(matching_tag)
        if tagged_commit is None:
            state = "release-candidate"
            if identity.get("release_channel") != "development":
                errors.append("untagged stable version cannot claim the release channel")
        else:
            state = "release" if tagged_commit == head_sha else "post-release-divergent"
            if tagged_commit != head_sha:
                errors.append("stable version tag resolves to a different commit")
            if identity.get("release_channel") != "release" or identity.get("dirty") is not False:
                errors.append("tagged stable version must be a clean release identity")

    return {
        "schema": VERSION_STATE_SCHEMA,
        "ok": not errors,
        "state": state,
        "base_version": base,
        "latest_release": latest_version,
        "head_sha": head_sha,
        "matching_tag": matching_tag if not current_is_dev else None,
        "errors": errors,
    }


def baseline_tag_errors(
    identity: Mapping[str, Any],
    latest_release: Mapping[str, Any],
    *,
    tag_commits: Mapping[str, str],
    head_sha: str | None,
) -> list[str]:
    """Validate baseline freshness, allowing the release tag currently building."""
    baseline_tag = latest_release.get("tag")
    baseline_commit = latest_release.get("commit_sha")
    if not isinstance(baseline_tag, str) or not isinstance(baseline_commit, str):
        raise ValueError("latest release baseline tag/commit is missing")
    errors: list[str] = []
    if tag_commits.get(baseline_tag) != baseline_commit:
        errors.append("latest release baseline does not match its Git tag")

    stable_tags: list[tuple[tuple[int, int, int], str]] = []
    for tag in tag_commits:
        match = _RELEASE_TAG.fullmatch(tag)
        if match is not None:
            stable_tags.append(((int(match[1]), int(match[2]), int(match[3])), tag))
    if not stable_tags:
        errors.append("no stable release tags are available")
        return errors
    _, newest_tag = max(stable_tags)
    if newest_tag != baseline_tag:
        building_newest_release = (
            identity.get("release_channel") == "release"
            and f"v{identity.get('base_version')}" == newest_tag
            and tag_commits[newest_tag] == head_sha
        )
        if not building_newest_release:
            errors.append("latest release baseline is stale")
    return errors
