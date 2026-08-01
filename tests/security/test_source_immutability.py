"""Source fixture trees must keep byte/mtime identity after every reader outcome."""

from __future__ import annotations

import hashlib
import io
import stat
import unittest
from pathlib import Path

from portable_resume.diagnostics import SOURCE_KEYS
from portable_resume.reader import run


def _fingerprint(root: Path) -> dict[str, tuple[int, int, str]]:
    """path -> (mode, mtime_ns, sha256)."""
    result: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
        result[rel] = (stat.S_IFMT(st.st_mode) | (st.st_mode & 0o777), mtime_ns, digest)
    return result


FIXTURES: dict[str, tuple[str, str | None]] = {
    "antigravity": ("tests/fixtures/antigravity/s-ant-01/root", "/workspace/project"),
    "claude": ("tests/fixtures/claude/s-cla-01-ordered-parent-chain/root", "/workspace/project"),
    "cline": ("tests/fixtures/cline/s-cl-01-user-basic", "/tmp/project"),
    "codex": ("tests/fixtures/codex/s-cod-01-state-generation-selection/root", "/workspace/project"),
    "crush": ("tests/fixtures/crush/s-cr-01-user-basic", None),
    "cursor": ("tests/fixtures/cursor/s-cur-01-cli-cwd-hash/root", "/workspace/project"),
    "gemini": ("tests/fixtures/gemini/s-gm-01-user-basic", "/tmp/project"),
    "github-copilot": ("tests/fixtures/github-copilot/s-gcp-01-user-basic", "/tmp/project"),
    "goose": ("tests/fixtures/goose/s-go-01-user-basic", "/tmp/project"),
    "grok": ("tests/fixtures/grok/s-gro-01/root", "/workspace/project"),
    "hermes": ("tests/fixtures/hermes/s-hm-01-user-basic", "/tmp/project"),
    "kimi": ("tests/fixtures/kimi/s-kim-01/root", "/workspace/project"),
    "openclaw": ("tests/fixtures/openclaw/s-oc-01-basic", "/tmp/project"),
    "opencode": ("tests/fixtures/opencode/s-ope-01/root", "/workspace/project"),
    "openhands": ("tests/fixtures/openhands/s-oh-01-user-basic", "/tmp/project"),
    "pi": ("tests/fixtures/pi/s-pi-01-basic-v3/agent", "/tmp/project"),
    "qwen": ("tests/fixtures/qwen/s-qwe-01/root", "/workspace/project"),
}


class SourceImmutabilityTests(unittest.TestCase):
    def test_every_source_has_an_immutability_case(self) -> None:
        self.assertEqual(sorted(FIXTURES), sorted(SOURCE_KEYS))

    def test_list_and_show_leave_source_tree_unchanged(self) -> None:
        for source, (root_s, cwd) in sorted(FIXTURES.items()):
            with self.subTest(source=source):
                root = Path(root_s)
                resolved_cwd = str(root.resolve()) if cwd is None else cwd
                self.assertTrue(root.is_dir(), root)
                before = _fingerprint(root)
                for action in (
                    ["list", "--within-min", "0", "--json"],
                    ["show", "latest", "--within-min", "0", "--format", "handoff"],
                    ["show", "no-such-session-zzzz", "--within-min", "0", "--json"],
                ):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    run(
                        [source, *action, "--cwd", resolved_cwd, "--source-root", str(root.resolve())],
                        stdout=stdout,
                        stderr=stderr,
                    )
                    after = _fingerprint(root)
                    self.assertEqual(before, after, f"{source} {action} mutated source")
                    # no new sidecars at root either
                    self.assertEqual(set(before), set(after))


if __name__ == "__main__":
    unittest.main()
