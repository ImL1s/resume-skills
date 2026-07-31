#!/usr/bin/env python3
"""Render registry-derived documentation regions without generating evidence claims."""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume.install.catalog import hosts_report  # noqa: E402
from portable_resume.registry import matrix_dimensions  # noqa: E402

REGION_FILES = {
    Path("docs/host-support.md"): ("matrix-summary", "host-support-table"),
    Path("docs/install-hosts.md"): ("matrix-summary", "install-hosts-table"),
}
MARKER_TEMPLATE = "<!-- generated:{name}:{edge} (run scripts/render_docs.py --write) -->"


def counts() -> dict[str, int]:
    """Return the current registry dimensions as plain integer counts."""

    return dict(matrix_dimensions())


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _hosts() -> list[dict[str, object]]:
    return sorted(hosts_report()["hosts"], key=lambda host: str(host["host"]))


def _matrix_summary() -> str:
    current = counts()
    return (
        f"This repository ships **{current['sources']}** enabled source Skills to "
        f"**{current['destinations']}** destination hosts (registry-derived; "
        f"currently **{current['sources']}×{current['destinations']}="
        f"{current['cells']}** cells)."
    )


def _host_support_table() -> str:
    lines = [
        "| Host | Profile | Project root | Global root |",
        "|---|---|---|---|",
    ]
    for host in _hosts():
        layouts = host["official_layouts"]
        lines.append(
            "| {display_name} | `{profile_id}` | `{project}` | `{global_root}` |".format(
                display_name=_markdown(host["display_name"]),
                profile_id=_markdown(host["profile_id"]),
                project=_markdown(layouts["project"]),
                global_root=_markdown(layouts["global"]),
            )
        )
    return "\n".join(lines)


def _install_hosts_table() -> str:
    lines = [
        "| Host | Project root | Global root | Project install | Global install | Activation |",
        "|---|---|---|---|---|---|",
    ]
    for host in _hosts():
        layouts = host["official_layouts"]
        commands = host["installer_commands"]
        lines.append(
            "| {display_name} (`{host}`) | `{project}` | `{global_root}` | `{project_command}` | "
            "`{global_command}` | {activation} |".format(
                display_name=_markdown(host["display_name"]),
                host=_markdown(host["host"]),
                project=_markdown(layouts["project"]),
                global_root=_markdown(layouts["global"]),
                project_command=_markdown(commands["project"]["installed"]),
                global_command=_markdown(commands["global"]["installed"]),
                activation=_markdown(host["activation_help"]),
            )
        )
    return "\n".join(lines)


def rendered_regions() -> dict[str, str]:
    """Render every generated region from registry/catalog structure only."""

    return {
        "matrix-summary": _matrix_summary(),
        "host-support-table": _host_support_table(),
        "install-hosts-table": _install_hosts_table(),
    }


def _replace_region(text: str, name: str, body: str, relative: Path) -> str:
    begin = MARKER_TEMPLATE.format(name=name, edge="begin")
    end = MARKER_TEMPLATE.format(name=name, edge="end")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    replacement = f"{begin}\n{body}\n{end}"
    updated, replacements = pattern.subn(lambda _: replacement, text)
    if replacements != 1:
        raise ValueError(
            f"{relative}: expected exactly one generated region {name!r}, "
            f"found {replacements}"
        )
    return updated


def _render_file(root: Path, relative: Path, names: tuple[str, ...]) -> str:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    regions = rendered_regions()
    for name in names:
        text = _replace_region(text, name, regions[name], relative)
    return text


def check(root: Path = REPO) -> list[str]:
    """Return unified diffs or marker errors for stale generated regions."""

    failures: list[str] = []
    for relative, names in REGION_FILES.items():
        path = root / relative
        current = path.read_text(encoding="utf-8")
        try:
            expected = _render_file(root, relative, names)
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
            continue
        if current == expected:
            continue
        failures.append(
            "".join(
                difflib.unified_diff(
                    current.splitlines(keepends=True),
                    expected.splitlines(keepends=True),
                    fromfile=str(relative),
                    tofile=f"{relative} (rendered)",
                )
            )
        )
    return failures


def write(root: Path = REPO) -> None:
    for relative, names in REGION_FILES.items():
        path = root / relative
        rendered = _render_file(root, relative, names)
        path.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    namespace = parser.parse_args(argv)

    if namespace.write:
        write()
        print(f"DOCS_RENDER WRITE targets={len(REGION_FILES)}")
        return 0

    failures = check()
    if failures:
        print("DOCS_RENDER FAIL", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr, end="" if failure.endswith("\n") else "\n")
        return 1
    print(
        "DOCS_RENDER PASS "
        f"targets={len(REGION_FILES)} regions={sum(map(len, REGION_FILES.values()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
