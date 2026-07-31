#!/usr/bin/env python3
"""Installed skill runner smoke for every host × source cell.

For each destination host and each source skill:
  1. install package into a temp project skill root
  2. run the installed resume-<source>/scripts/run_reader.py list + show
     against a synthetic fixture (source_root)

The runner executes with Python isolated mode and without checkout PYTHONPATH,
then its JSON envelope is checked for the exact synthetic session and content.
This is packaging/runtime evidence, not host UI natural-language activation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from portable_resume.diagnostics import SOURCE_KEYS  # noqa: E402
from portable_resume.install.catalog import HOST_KEYS  # noqa: E402
from portable_resume.paths import same_cwd  # noqa: E402
from portable_resume.registry import matrix_dimensions  # noqa: E402

HOSTS = tuple(sorted(HOST_KEYS))
SOURCES = tuple(sorted(SOURCE_KEYS))

FIXTURES: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "claude": (
        "tests/fixtures/claude/s-cla-01-ordered-parent-chain/root",
        "/workspace/project",
        "7e0a1246-d538-5993-8d6f-3495aafcdd92",
        ("synthetic request", "synthetic response"),
    ),
    "codex": (
        "tests/fixtures/codex/s-cod-01-state-generation-selection/root",
        "/workspace/project",
        "0493207e-6039-5026-81d4-e75c0efff76a",
        ("synthetic request", "synthetic response"),
    ),
    "cursor": (
        "tests/fixtures/cursor/s-cur-01-cli-cwd-hash/root",
        "/workspace/project",
        "418306f5-3983-5ab7-b8e0-fa47843e83aa",
        ("synthetic request", "synthetic response"),
    ),
    "opencode": (
        "tests/fixtures/opencode/s-ope-01/root",
        "/workspace/project",
        "ses-sql",
        (
            "Please inspect the synthetic parser.",
            "I inspected only synthetic evidence.",
            "synthetic tool output",
        ),
    ),
    "antigravity": (
        "tests/fixtures/antigravity/s-ant-01/root",
        "/workspace/project",
        "conv-one",
        ("Antigravity prompt", "Antigravity answer"),
    ),
    "grok": (
        "tests/fixtures/grok/s-gro-01/root",
        "/workspace/project",
        "grok-one",
        ("Grok prompt", "Grok answer"),
    ),
    "qwen": (
        "tests/fixtures/qwen/s-qwe-01/root",
        "/workspace/project",
        "qwen-one",
        (
            "Inspect the synthetic Qwen store.",
            "Only public answer text.",
            "synthetic tool output",
        ),
    ),
    "kimi": (
        "tests/fixtures/kimi/s-kim-01/root",
        "/workspace/project",
        "11111111-1111-4111-8111-111111111111",
        ("Current Kimi prompt", "Current Kimi answer"),
    ),
    "pi": (
        "tests/fixtures/pi/s-pi-01-basic-v3/agent",
        "/tmp/project",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        (
            "synthetic user request for basic v3 branch",
            "synthetic assistant reply on the active branch",
        ),
    ),
    "openclaw": (
        "tests/fixtures/openclaw/s-oc-01-basic",
        "/tmp/project",
        "main:sess-basic-0001",
        (
            "Resume context from /tmp/project",
            "Synthetic assistant reply",
        ),
    ),
    "goose": (
        "tests/fixtures/goose/s-go-01-user-basic",
        "/tmp/project",
        "go000101-0101-4101-8101-010101010101",
        (
            "synthetic goose user prompt",
            "synthetic goose assistant reply",
        ),
    ),
    "crush": (
        "tests/fixtures/crush/s-cr-01-user-basic",
        "/tmp/project",
        "cr000101-0101-4101-8101-010101010101",
        (
            "synthetic crush user prompt",
            "synthetic crush assistant reply",
        ),
    ),
    "cline": (
        "tests/fixtures/cline/s-cl-01-user-basic",
        "/tmp/project",
        "cl000101-0101-4101-8101-010101010101",
        (
            "synthetic cline user prompt",
            "synthetic cline assistant reply",
        ),
    ),
    "openhands": (
        "tests/fixtures/openhands/s-oh-01-user-basic",
        "/tmp/project",
        "oh000101010141018101010101010101",
        (
            "synthetic openhands user prompt",
            "synthetic openhands assistant reply",
        ),
    ),
    "hermes": (
        "tests/fixtures/hermes/s-hm-01-user-basic",
        "/tmp/project",
        "hm000101-0101-4101-8101-010101010101",
        (
            "synthetic hermes user prompt",
            "synthetic hermes assistant reply",
        ),
    ),
    "gemini": (
        "tests/fixtures/gemini/s-gm-01-user-basic",
        "/tmp/project",
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        (
            "synthetic gemini user prompt",
            "synthetic gemini assistant reply",
        ),
    ),
    "github-copilot": (
        "tests/fixtures/github-copilot/s-gcp-01-user-basic",
        "/tmp/project",
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        (
            "synthetic copilot user prompt",
            "synthetic copilot assistant reply",
            "bash",
        ),
    ),
}


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _parse_envelope(
    output: str,
    *,
    operation: str,
    source: str,
    cwd: str,
    session_id: str,
    contents: tuple[str, ...],
) -> str | None:
    """Return a failure detail, or None when the exact fixture envelope matches."""
    try:
        value = json.loads(output)
    except (TypeError, json.JSONDecodeError) as error:
        return f"invalid JSON envelope: {error}"
    if not isinstance(value, dict):
        return "JSON envelope is not an object"
    if value.get("schema_version") != "portable-resume/v1":
        return f"unexpected schema_version: {value.get('schema_version')!r}"
    if value.get("operation") != operation:
        return f"unexpected operation: {value.get('operation')!r}"
    query = value.get("query")
    if not isinstance(query, dict) or query.get("source") != source or not same_cwd(query.get("cwd"), cwd):
        return f"unexpected query: {query!r}"
    if value.get("inert") is not True or value.get("untrusted_content") is not True:
        return "envelope is missing inert/untrusted boundary flags"
    sessions = value.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        return f"expected at least one session, received: {sessions!r}"
    if operation == "show" and len(sessions) != 1:
        return f"show returned multiple sessions: {sessions!r}"
    matches: list[dict[str, object]] = []
    for candidate in sessions:
        if not isinstance(candidate, dict):
            return "session is not an object"
        if candidate.get("source") != source:
            return f"unexpected session source: {candidate.get('source')!r}"
        if (
            candidate.get("inert") is not True
            or candidate.get("untrusted_content") is not True
        ):
            return "session is missing inert/untrusted boundary flags"
        candidate_turns = candidate.get("turns")
        if not isinstance(candidate_turns, list):
            return "session turns is not a list"
        if operation == "list" and candidate_turns:
            return "list session unexpectedly contains turns"
        if candidate.get("session_id") == session_id:
            matches.append(candidate)
    if len(matches) != 1:
        return f"expected one matching session {session_id!r}, received {len(matches)}"
    session = matches[0]
    turns = session.get("turns")
    assert isinstance(turns, list)
    actual_contents = tuple(
        turn.get("content")
        for turn in turns
        if isinstance(turn, dict)
    )
    expected_contents = () if operation == "list" else contents
    if actual_contents != expected_contents:
        return f"unexpected turn content: {actual_contents!r}"
    if any(
        not isinstance(turn, dict)
        or turn.get("inert") is not True
        or turn.get("untrusted_content") is not True
        for turn in turns
    ):
        return "turn is missing inert/untrusted boundary flags"
    return None


def _materialize_fixture(source: str, fixture: Path, destination: Path) -> Path:
    """Return an immutable fixture root, or a relocated synthetic copy.

    Current Kimi indexes persist an absolute ``sessionDir``. The tracked
    synthetic fixture intentionally cannot contain a developer's real home
    path, so smoke tests relocate it and rewrite only the temporary copy.
    """

    if source != "kimi":
        return fixture
    target = destination / source
    shutil.copytree(fixture, target)
    session_dirs = sorted((target / "sessions").glob("*/*"))
    if len(session_dirs) != 1:
        raise RuntimeError("synthetic Kimi fixture must contain exactly one session")
    index = target / "session_index.jsonl"
    records = [
        json.loads(line)
        for line in index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(records) != 1 or not isinstance(records[0], dict):
        raise RuntimeError("synthetic Kimi index must contain exactly one record")
    records[0]["sessionDir"] = str(session_dirs[0].resolve())
    index.write_text(
        json.dumps(records[0], ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    as_json = "--json" in (argv or sys.argv[1:])
    cells: list[dict[str, object]] = []
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    installed_env = os.environ.copy()
    installed_env.pop("PYTHONPATH", None)
    installed_env["PYTHONNOUSERSITE"] = "1"
    python = sys.executable
    install = str(ROOT / "scripts" / "install-resume-skills")

    with tempfile.TemporaryDirectory(prefix="portable-resume-smoke-") as tmp:
        project = Path(tmp) / "project"
        home = Path(tmp) / "home"
        fixture_copies = Path(tmp) / "fixtures"
        project.mkdir()
        home.mkdir()
        fixtures = {
            source: _materialize_fixture(
                source,
                ROOT / fixture[0],
                fixture_copies,
            )
            for source, fixture in FIXTURES.items()
        }
        for host in HOSTS:
            # Distinct roots: Codex/Antigravity share .agents/skills by default.
            skill_root = str(project / f"skills-{host}")
            Path(skill_root).mkdir(parents=True, exist_ok=True)
            planned = _run(
                [
                    python,
                    install,
                    "install",
                    "--host",
                    host,
                    "--scope",
                    "project",
                    "--project",
                    str(project),
                    "--home",
                    str(home),
                    "--root",
                    skill_root,
                ],
                env=env,
            )
            if planned.returncode != 0:
                for source in SOURCES:
                    cells.append(
                        {
                            "host": host,
                            "source": source,
                            "result": "fail",
                            "stage": "install",
                            "detail": (planned.stderr or planned.stdout)[-500:],
                        }
                    )
                continue
            for source in SOURCES:
                _fixture_rel, cwd, session_id, contents = FIXTURES[source]
                fixture = fixtures[source]
                # Crush binds cwd from project layout (<project>/.crush/crush.db);
                # align smoke query.cwd with the synthetic project root.
                if source == "crush":
                    cwd = str(fixture.resolve())
                runner = Path(skill_root) / f"resume-{source}" / "scripts" / "run_reader.py"
                if not runner.is_file():
                    cells.append(
                        {
                            "host": host,
                            "source": source,
                            "result": "fail",
                            "stage": "missing_runner",
                            "detail": str(runner),
                        }
                    )
                    continue
                # Synthetic fixtures use 2024–2026 timestamps; disable age filter.
                listed = _run(
                    [
                        python,
                        "-I",
                        str(runner),
                        "list",
                        "--cwd",
                        cwd,
                        "--source-root",
                        str(fixture),
                        "--within-min",
                        "0",
                        "--json",
                    ],
                    env=installed_env,
                )
                list_detail = _parse_envelope(
                    listed.stdout,
                    operation="list",
                    source=source,
                    cwd=cwd,
                    session_id=session_id,
                    contents=contents,
                )
                if listed.returncode != 0 or list_detail is not None:
                    if listed.returncode != 0:
                        detail = listed.stderr or listed.stdout
                    else:
                        detail = list_detail or listed.stdout
                    cells.append(
                        {
                            "host": host,
                            "source": source,
                            "result": "fail",
                            "stage": "list",
                            "detail": detail[-500:],
                        }
                    )
                    continue
                shown = _run(
                    [
                        python,
                        "-I",
                        str(runner),
                        "show",
                        "latest",
                        "--cwd",
                        cwd,
                        "--source-root",
                        str(fixture),
                        "--within-min",
                        "0",
                        "--format",
                        "json",
                    ],
                    env=installed_env,
                )
                show_detail = _parse_envelope(
                    shown.stdout,
                    operation="show",
                    source=source,
                    cwd=cwd,
                    session_id=session_id,
                    contents=contents,
                )
                ok = shown.returncode == 0 and show_detail is None
                if shown.returncode != 0:
                    detail = shown.stderr or shown.stdout
                else:
                    detail = show_detail or shown.stdout
                cells.append(
                    {
                        "host": host,
                        "source": source,
                        "result": "pass" if ok else "fail",
                        "stage": "show" if not ok else "ok",
                        "detail": "" if ok else detail[-500:],
                    }
                )

    passed = sum(1 for c in cells if c["result"] == "pass")
    failed = [c for c in cells if c["result"] != "pass"]
    expected = matrix_dimensions()["cells"]
    report = {
        "schema_version": "portable-resume/installed-runner-smoke-v1",
        "cell_count": len(cells),
        "expected": expected,
        "passed": passed,
        "failed": len(failed),
        "ok": passed == expected and len(cells) == expected,
        "note": "Installed skill runner smoke only — not host UI NL/picker activation",
        "failures": failed,
    }
    if as_json:
        report["cells"] = cells
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif failed:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"INSTALLED_RUNNER_SMOKE PASS cells={passed}/{expected}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
