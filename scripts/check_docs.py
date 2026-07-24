#!/usr/bin/env python3
"""Validate multilingual quick-start coverage and canonical install commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume import __version__  # noqa: E402

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
)
REQUIRED_COMMANDS = (
    "pipx install portable-resume",
    "install-resume-skills quick-install qwen",
    "install-resume-skills quick-install all",
    "python3 scripts/self_verify.py",
)
REQUIRED_LINKS = (
    "../install-hosts.md",
    "../STATUS.md",
)


def check() -> dict[str, object]:
    failures: list[str] = []
    root_readme = (REPO / "README.md").read_text(encoding="utf-8")
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
        for host in HOST_NAMES:
            if host not in text:
                failures.append(f"{path.relative_to(REPO)}: missing host {host}")

    return {
        "ok": not failures,
        "version": __version__,
        "required_locale_count": len(LOCALES),
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
