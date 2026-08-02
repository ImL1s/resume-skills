#!/usr/bin/env python3
"""Validate multilingual quick-start coverage and canonical install commands."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume import __version__  # noqa: E402
from portable_resume.diagnostics import ERROR_EXIT_CODES, WARNING_CODES  # noqa: E402
from portable_resume.install.catalog import host_catalog_snapshot  # noqa: E402
from portable_resume.registry import (  # noqa: E402
    enabled_destination_keys,
    enabled_source_keys,
)
try:  # Direct script execution puts scripts/ rather than the repo root on sys.path.
    from scripts import render_docs  # type: ignore[no-redef]  # noqa: E402
except ModuleNotFoundError:
    import render_docs  # type: ignore[no-redef]  # noqa: E402

LOCALES = {
    "ar": "العربية",
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "hi": "हिन्दी",
    "ja": "日本語",
    "ko": "한국어",
    "pt-BR": "Português (Brasil)",
    "ru": "Русский",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
}
REQUIRED_COMMANDS = (
    "pipx install portable-resume",
    "install-resume-skills quick-install qwen",
    "install-resume-skills quick-install all",
    "claude plugin marketplace add ImL1s/portable-resume-marketplace",
    "python3 scripts/self_verify.py",
)
REQUIRED_LINKS = (
    "../install-hosts.md",
    "../STATUS.md",
    "https://github.com/ImL1s/portable-resume-marketplace",
)
# Plan 042 generates registry structure/counts only. These evidence claims remain
# human-recorded truth and must never be inferred by scripts/render_docs.py.
REQUIRED_EVIDENCE_MARKERS = (
    "8/8",
    "7/7",
    "6/6",
)
EVIDENCE_SCOPE_MARKER = (
    "<!-- portable-resume-evidence-scope: "
    "v0.3.2-hosts v0.3.4-host-reinstall-not-run -->"
)
ROOT_INSTALLED_COMMANDS = (
    "portable-resume --version",
    "install-resume-skills --version",
    "portable-resume self-check --json",
    "install-resume-skills matrix",
    "install-resume-skills hosts --json",
    "install-resume-skills install \\",
    "install-resume-skills verify \\",
)
_COUNT_TOKEN = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|hundred|thousand|\d+)\b",
    re.IGNORECASE,
)
_COUNTS_MARKER = re.compile(
    r"<!-- portable-resume-counts: sources=(\d+) destinations=(\d+) -->"
)
_CURRENT_REGISTRY_BEGIN = "<!-- portable-resume-current-registry:begin -->"
_CURRENT_REGISTRY_END = "<!-- portable-resume-current-registry:end -->"
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _host_names() -> tuple[str, ...]:
    return tuple(host["display_name"] for host in host_catalog_snapshot()["hosts"])


def _current_registry_facts(text: str) -> str | None:
    if (
        text.count(_CURRENT_REGISTRY_BEGIN) != 1
        or text.count(_CURRENT_REGISTRY_END) != 1
    ):
        return None
    pattern = re.compile(
        re.escape(_CURRENT_REGISTRY_BEGIN)
        + r"(.*?)"
        + re.escape(_CURRENT_REGISTRY_END),
        re.DOTALL,
    )
    matches = pattern.findall(text)
    if len(matches) != 1:
        return None
    return _HTML_COMMENT.sub("", matches[0])


def _check_root_docs(failures: list[str], root_readme: str) -> None:
    source_count = len(enabled_source_keys())
    destination_count = len(enabled_destination_keys())
    current_counts = f"{source_count} sources × {destination_count} hosts"
    if f"{current_counts} (derived from registries)" not in root_readme:
        failures.append(
            f"README.md: current registry counts must be {current_counts}"
        )

    hero_match = re.search(
        r'<img\s+src="docs/assets/portable-resume-skills-hero-v2\.jpg"\s+'
        r'alt="([^"]*)"',
        root_readme,
    )
    if hero_match is None or _COUNT_TOKEN.search(hero_match.group(1)):
        failures.append("README.md: hero alt text must be count-free")

    installed_heading = "Installed (pipx/pip):"
    checkout_heading = "From a source checkout (no install):"
    installed_start = root_readme.find(installed_heading)
    checkout_start = root_readme.find(checkout_heading)
    if installed_start < 0 or checkout_start <= installed_start:
        failures.append("README.md: missing installed (pipx/pip) command section")
    else:
        installed_section = root_readme[installed_start:checkout_start]
        for command in ROOT_INSTALLED_COMMANDS:
            if command not in installed_section:
                failures.append(
                    f"README.md: installed command section missing {command!r}"
                )

    install_hosts = (REPO / "docs" / "install-hosts.md").read_text(encoding="utf-8")
    quick_install_line = next(
        (
            line
            for line in install_hosts.splitlines()
            if "install-resume-skills quick-install all" in line
        ),
        "",
    )
    comment = quick_install_line.partition("#")[2]
    if not comment or "registry" not in comment.lower() or _COUNT_TOKEN.search(comment):
        failures.append(
            "docs/install-hosts.md: quick-install all comment must be registry-derived"
        )

    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [line for line in changelog.splitlines() if line.startswith("#")]
    if (
        not headings
        or headings[0] != "# Changelog"
        or headings.count("# Changelog") != 1
        or headings.count("## Unreleased") != 1
        or headings.index("# Changelog") > headings.index("## Unreleased")
    ):
        failures.append(
            "CHANGELOG.md: expected one H1 followed by one Unreleased section"
        )


def _check_diagnostics_reference(failures: list[str]) -> None:
    path = REPO / "docs" / "diagnostics.md"
    if not path.is_file():
        failures.append("docs/diagnostics.md: missing")
        return
    text = path.read_text(encoding="utf-8")
    missing = [
        code
        for code in (*ERROR_EXIT_CODES, *sorted(WARNING_CODES))
        if code not in text
    ]
    if missing:
        failures.append(f"docs/diagnostics.md: missing codes: {missing}")


def _check_status_current_matrix(failures: list[str]) -> None:
    """Require STATUS packaging/installed-runner rows match live registry counts.

    Historical products (e.g. published ``0.3.4`` **9×9=81**) may remain in the
    same row when labeled historical; only the *current main tip* product is gated.
    """

    path = REPO / "docs" / "STATUS.md"
    if not path.is_file():
        failures.append("docs/STATUS.md: missing")
        return
    text = path.read_text(encoding="utf-8")
    source_count = len(enabled_source_keys())
    destination_count = len(enabled_destination_keys())
    cells = source_count * destination_count
    expected_ratio = f"{cells}/{cells}"
    expected_product = f"{source_count}×{destination_count}"
    for label in ("Packaging matrix", "Installed runner matrix"):
        row = next(
            (
                line
                for line in text.splitlines()
                if line.startswith(f"| {label} |")
            ),
            None,
        )
        if row is None:
            failures.append(f"docs/STATUS.md: missing gate row for {label}")
            continue
        if expected_ratio not in row:
            failures.append(
                f"docs/STATUS.md: {label} row must claim current "
                f"{expected_ratio} (live registry cells)"
            )
        if expected_product not in row:
            failures.append(
                f"docs/STATUS.md: {label} row must include current product "
                f"{expected_product}"
            )
        lowered = row.lower()
        if "derived from registries" not in lowered and "registry-derived" not in lowered:
            failures.append(
                f"docs/STATUS.md: {label} row must note registry-derived counts"
            )
        if "current main" not in lowered and "on main" not in lowered:
            failures.append(
                f"docs/STATUS.md: {label} row must scope the live product to current main"
            )


def check() -> dict[str, object]:
    failures: list[str] = []
    root_readme = (REPO / "README.md").read_text(encoding="utf-8")
    _check_root_docs(failures, root_readme)
    _check_diagnostics_reference(failures)
    _check_status_current_matrix(failures)
    if "docs/i18n/README.md" not in root_readme:
        failures.append("README.md: missing multilingual documentation link")

    index_path = REPO / "docs" / "i18n" / "README.md"
    if not index_path.is_file():
        failures.append("docs/i18n/README.md: missing")
        index = ""
    else:
        index = index_path.read_text(encoding="utf-8")

    source_count = len(enabled_source_keys())
    destination_count = len(enabled_destination_keys())
    host_names = _host_names()
    checked: list[str] = []
    for locale, label in LOCALES.items():
        relative = f"./{locale}.md"
        if relative not in index or label not in index:
            failures.append(f"docs/i18n/README.md: missing {locale} index entry")
        path = REPO / "docs" / "i18n" / f"{locale}.md"
        if not path.is_file():
            failures.append(f"docs/i18n/{locale}.md: missing")
            continue
        text = path.read_text(encoding="utf-8")
        checked.append(locale)
        marker = f"<!-- portable-resume-i18n: {locale} v{__version__} -->"
        if marker not in text:
            failures.append(f"{path.relative_to(REPO)}: missing current version marker")
        count_markers = _COUNTS_MARKER.findall(text)
        expected_counts = (str(source_count), str(destination_count))
        if count_markers != [expected_counts]:
            failures.append(
                f"{path.relative_to(REPO)}: counts marker must be "
                f"sources={source_count} destinations={destination_count}"
            )
        current_facts = _current_registry_facts(text)
        if current_facts is None:
            failures.append(
                f"{path.relative_to(REPO)}: expected exactly one current registry facts region"
            )
        else:
            if re.search(
                rf"(?<!\d){destination_count}(?!\d)", current_facts
            ) is None:
                failures.append(
                    f"{path.relative_to(REPO)}: current registry facts must mention "
                    f"destination count {destination_count}"
                )
            for host in host_names:
                if host not in current_facts:
                    failures.append(
                        f"{path.relative_to(REPO)}: current registry facts missing host {host}"
                    )
        for command in REQUIRED_COMMANDS:
            if command not in text:
                failures.append(f"{path.relative_to(REPO)}: missing command {command!r}")
        for link in REQUIRED_LINKS:
            if link not in text:
                failures.append(f"{path.relative_to(REPO)}: missing link {link!r}")
        for marker in REQUIRED_EVIDENCE_MARKERS:
            if marker not in text:
                failures.append(
                    f"{path.relative_to(REPO)}: missing evidence marker {marker!r}"
                )
        if EVIDENCE_SCOPE_MARKER not in text:
            failures.append(
                f"{path.relative_to(REPO)}: missing version-scoped host evidence marker"
            )

    for failure in render_docs.assert_matrix_consistent(REPO):
        # assert_matrix_consistent already prefixes generated-region failures.
        if failure.startswith("generated docs drift"):
            failures.append(failure)
        else:
            failures.append(f"matrix consistency: {failure}")

    return {
        "ok": not failures,
        "version": __version__,
        "required_locale_count": len(LOCALES),
        "source_count": len(enabled_source_keys()),
        "destination_count": len(enabled_destination_keys()),
        "matrix_cells": len(enabled_source_keys()) * len(enabled_destination_keys()),
        "checked_locales": checked,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    namespace = parser.parse_args(argv)
    report = check()
    if namespace.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif report["ok"]:
        print(
            "DOCS_CHECK PASS "
            f"locales={report['required_locale_count']} version={report['version']}"
        )
    else:
        print("DOCS_CHECK FAIL", file=sys.stderr)
        for failure in report["failures"]:
            print(f" - {failure}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
