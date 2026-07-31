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
from portable_resume.registry import (  # noqa: E402
    enabled_destination_keys,
    enabled_source_keys,
)

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
HOST_NAMES = (
    "Claude",
    "Codex",
    "Cursor",
    "OpenCode",
    "Antigravity",
    "Grok",
    "Qwen",
    "Kimi",
    "Pi",
)
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


def _check_root_docs(failures: list[str], root_readme: str) -> None:
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


def check() -> dict[str, object]:
    failures: list[str] = []
    root_readme = (REPO / "README.md").read_text(encoding="utf-8")
    _check_root_docs(failures, root_readme)
    if "docs/i18n/README.md" not in root_readme:
        failures.append("README.md: missing multilingual documentation link")

    index_path = REPO / "docs" / "i18n" / "README.md"
    if not index_path.is_file():
        failures.append("docs/i18n/README.md: missing")
        index = ""
    else:
        index = index_path.read_text(encoding="utf-8")

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
        for host in HOST_NAMES:
            if host not in text:
                failures.append(f"{path.relative_to(REPO)}: missing host {host}")

    return {
        "ok": not failures,
        "version": __version__,
        "required_locale_count": len(LOCALES),
        "source_count": len(enabled_source_keys()),
        "destination_count": len(enabled_destination_keys()),
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
