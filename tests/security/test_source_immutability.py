"""Source fixture trees must keep byte/mtime identity after every reader outcome."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import unittest
from pathlib import Path

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


class SourceImmutabilityTests(unittest.TestCase):
    CASES = (
        ("claude", "tests/fixtures/claude/s-cla-01-ordered-parent-chain/root", "/workspace/project"),
        ("grok", "tests/fixtures/grok/s-gro-01/root", "/workspace/project"),
        ("opencode", "tests/fixtures/opencode/s-ope-01/root", "/workspace/project"),
    )

    def test_list_and_show_leave_source_tree_unchanged(self) -> None:
        for source, root_s, cwd in self.CASES:
            with self.subTest(source=source):
                root = Path(root_s)
                self.assertTrue(root.is_dir(), root)
                before = _fingerprint(root)
                for action in (
                    ["list", "--json"],
                    ["show", "latest", "--format", "handoff"],
                    ["show", "no-such-session-zzzz", "--json"],
                ):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    run(
                        [source, *action, "--cwd", cwd, "--source-root", str(root.resolve())],
                        stdout=stdout,
                        stderr=stderr,
                    )
                    after = _fingerprint(root)
                    self.assertEqual(before, after, f"{source} {action} mutated source")
                    # no new sidecars at root either
                    self.assertEqual(set(before), set(after))


if __name__ == "__main__":
    unittest.main()
