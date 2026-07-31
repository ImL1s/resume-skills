#!/usr/bin/env python3
"""Render source-of-truth-derived documentation without generating evidence claims."""

from __future__ import annotations

import argparse
import ast
import difflib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_resume.install.catalog import host_catalog_snapshot  # noqa: E402
from portable_resume.diagnostics import (  # noqa: E402
    DiagnosticError,
    ERROR_EXIT_CODES,
    ExitCode,
    WARNING_CODES,
)
from portable_resume.registry import matrix_dimensions  # noqa: E402

REGION_FILES = {
    Path("docs/diagnostics.md"): (
        "exit-codes-table",
        "error-codes-table",
        "self-check-result-contract",
        "warning-codes-list",
    ),
    Path("docs/host-support.md"): ("matrix-summary", "host-support-table"),
    Path("docs/install-hosts.md"): ("matrix-summary", "install-hosts-table"),
}
MARKER_TEMPLATE = "<!-- generated:{name}:{edge} (run scripts/render_docs.py --write) -->"

EXIT_CODE_REFERENCE: dict[ExitCode, tuple[str, str]] = {
    ExitCode.OK: (
        "The command completed successfully.",
        "Parse the stdout result.",
    ),
    ExitCode.INVALID_INPUT: (
        "Arguments or request data are invalid.",
        "Correct the invocation; do not retry unchanged input.",
    ),
    ExitCode.NO_MATCH: (
        "No eligible persisted session matched.",
        "Treat this as an empty result or broaden the query.",
    ),
    ExitCode.AMBIGUOUS: (
        "More than one eligible session matched.",
        "Parse the stdout candidates envelope and choose an exact reference.",
    ),
    ExitCode.UNSUPPORTED: (
        "The store format or requested capability is unavailable.",
        "Select a supported source/capability or install the optional capability.",
    ),
    ExitCode.UNSAFE_OR_BUSY: (
        "A path, live store, install root, or recovery state is unsafe or busy.",
        "Retry later or inspect the reported store/install safety state.",
    ),
    ExitCode.CORRUPT_OR_LIMIT: (
        "Persisted data is corrupt, a bound was exceeded, or verification failed.",
        "Inspect the result, reduce scope if applicable, and repair or recreate invalid state.",
    ),
    ExitCode.INVARIANT: (
        "An internal contract invariant failed.",
        "Preserve the diagnostic and file a bug.",
    ),
}

DIAGNOSTIC_SURFACES: dict[str, str] = {
    "E_INVALID_INPUT": "Reader and installer",
    "E_NO_MATCH": "Reader",
    "E_AMBIGUOUS": "Reader",
    "E_UNSUPPORTED_FORMAT": "Reader",
    "E_CAPABILITY_UNAVAILABLE": "Reader",
    "E_UNSAFE_PATH": "Reader",
    "E_SOURCE_BUSY": "Reader",
    "E_SQLITE_HOT_JOURNAL": "Reader",
    "E_LIMIT_EXCEEDED": "Reader",
    "E_CORRUPT_RECORD": "Reader",
    "E_INVARIANT": "Reader and installer",
    "E_INSTALL_BUSY": "Installer",
    "E_INSTALL_CONFLICT": "Installer",
    "E_INSTALL_SHADOW": "Installer",
    "E_INSTALL_UNSUPPORTED_PLATFORM": "Installer",
    "E_RECOVERY_REQUIRED": "Installer",
    "E_VERIFY_MISMATCH": "Installer",
}

SELF_CHECK_RESULT_WARNINGS: dict[str, str] = {
    "W_REGISTRY_INVALID:<ExceptionType>": (
        "Registry validation raised the named exception type."
    ),
    "W_SCHEMA_MISSING": "The bundled request schema file is absent.",
}


def counts() -> dict[str, int]:
    """Return the current registry dimensions as plain integer counts."""

    return dict(matrix_dimensions())


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _hosts() -> list[dict[str, object]]:
    return list(host_catalog_snapshot()["hosts"])


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


def _require_exact_keys(label: str, actual: object, expected: object) -> None:
    actual_keys = set(actual)
    expected_keys = set(expected)
    if actual_keys != expected_keys:
        missing = sorted(str(item) for item in expected_keys - actual_keys)
        unexpected = sorted(str(item) for item in actual_keys - expected_keys)
        raise ValueError(
            f"{label} keys must be exhaustive: missing={missing} unexpected={unexpected}"
        )


def _exit_codes_table() -> str:
    _require_exact_keys("exit-code reference", EXIT_CODE_REFERENCE, ExitCode)
    lines = [
        "| Number | Name | Meaning | Caller action |",
        "|---:|---|---|---|",
    ]
    for exit_code in ExitCode:
        meaning, action = EXIT_CODE_REFERENCE[exit_code]
        lines.append(
            f"| {int(exit_code)} | `{exit_code.name}` | {_markdown(meaning)} | "
            f"{_markdown(action)} |"
        )
    return "\n".join(lines)


def _error_codes_table() -> str:
    _require_exact_keys("diagnostic surfaces", DIAGNOSTIC_SURFACES, ERROR_EXIT_CODES)
    lines = [
        "| Code | Exit | Fixed message | Emitted by |",
        "|---|---:|---|---|",
    ]
    for code, exit_code in ERROR_EXIT_CODES.items():
        lines.append(
            f"| `{code}` | {int(exit_code)} | "
            f"{_markdown(DiagnosticError(code).message)} | {DIAGNOSTIC_SURFACES[code]} |"
        )
    return "\n".join(lines)


def _warning_codes_list() -> str:
    return "\n".join(f"- `{code}`" for code in sorted(WARNING_CODES))


def _self_check_source_contract() -> set[str]:
    """Read the self-check function contract without resolving runtime paths."""

    source = (SRC / "portable_resume" / "reader.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "self_check"
        ),
        None,
    )
    if function is None:
        raise ValueError("reader self-check function is missing")

    warnings: set[str] = set()
    has_corrupt_or_limit_exit = False
    for node in ast.walk(function):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A JoinedStr's literal prefix also appears as an ast.Constant;
            # only the completed f-string pattern is part of the contract.
            if node.value.startswith("W_") and not node.value.endswith(":"):
                warnings.add(node.value)
        elif isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append("<ExceptionType>")
            joined = "".join(parts)
            if joined.startswith("W_"):
                warnings.add(joined)
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == ExitCode.CORRUPT_OR_LIMIT.name
            and isinstance(node.value, ast.Name)
            and node.value.id == "ExitCode"
        ):
            has_corrupt_or_limit_exit = True

    _require_exact_keys(
        "self-check result warnings",
        SELF_CHECK_RESULT_WARNINGS,
        warnings,
    )
    if not has_corrupt_or_limit_exit:
        raise ValueError("reader self-check must return CORRUPT_OR_LIMIT on failure")
    return warnings


def _self_check_result_contract() -> str:
    _self_check_source_contract()
    lines = [
        "The reader's `self-check` command has a separate JSON result contract on stdout. "
        "These result warnings are not `diagnostic-v1` stderr diagnostics:",
        "",
        "| Result warning | Meaning |",
        "|---|---|",
    ]
    for warning, meaning in SELF_CHECK_RESULT_WARNINGS.items():
        lines.append(f"| `{warning}` | {_markdown(meaning)} |")
    lines.extend(
        (
            "",
            "Either warning makes the self-check result's `ok` field false. The command still "
            f"writes the result envelope to stdout and returns exit {int(ExitCode.CORRUPT_OR_LIMIT)} "
            f"(`{ExitCode.CORRUPT_OR_LIMIT.name}`), rather than emitting an error diagnostic.",
        )
    )
    return "\n".join(lines)


def rendered_regions() -> dict[str, str]:
    """Render every generated region from code-owned structure only."""

    return {
        "exit-codes-table": _exit_codes_table(),
        "error-codes-table": _error_codes_table(),
        "self-check-result-contract": _self_check_result_contract(),
        "warning-codes-list": _warning_codes_list(),
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
