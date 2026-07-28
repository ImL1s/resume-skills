"""Regression tests for exact-path no-symlink validation (#68).

Lexical supplied paths must be rejected before realpath can erase symlink
evidence. Only configured-root OS aliases (lexical root vs pinned canonical
root) are accepted as alternate walk spellings.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.paths import canonicalize_cwd, require_regular_no_symlinks


class RequireRegularNoSymlinksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.approved = self.root / "approved"
        self.outside = self.root / "outside"
        self.approved.mkdir()
        self.outside.mkdir()
        self.target = self.approved / "session.jsonl"
        self.target.write_text("{}\n", encoding="utf-8")

    def test_regular_lexical_path_under_root_succeeds(self) -> None:
        canonical, base = require_regular_no_symlinks(str(self.target), str(self.approved))
        self.assertEqual(canonical, canonicalize_cwd(self.target))
        self.assertEqual(base, canonicalize_cwd(self.approved))

    def test_final_component_symlink_under_root_rejected(self) -> None:
        link = self.approved / "link.jsonl"
        link.symlink_to(self.target)
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(link), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_parent_component_symlink_under_root_rejected(self) -> None:
        nested = self.approved / "nested"
        nested.mkdir()
        real = nested / "session.jsonl"
        real.write_text("{}\n", encoding="utf-8")
        alias_dir = self.approved / "alias_dir"
        alias_dir.symlink_to(nested)
        linked = alias_dir / "session.jsonl"
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(linked), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_outside_symlink_to_inside_regular_file_rejected(self) -> None:
        link = self.outside / "session-link"
        link.symlink_to(self.target)
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(link), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_outside_relative_symlink_to_inside_rejected(self) -> None:
        link = self.outside / "session-link-rel"
        link.symlink_to(os.path.relpath(self.target, self.outside))
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(link), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_outside_symlinked_directory_into_root_rejected(self) -> None:
        link_dir = self.outside / "into-approved"
        link_dir.symlink_to(self.approved)
        linked = link_dir / "session.jsonl"
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(linked), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_inside_symlink_pointing_outside_rejected(self) -> None:
        secret = self.outside / "secret.jsonl"
        secret.write_text("TOP SECRET\n", encoding="utf-8")
        link = self.approved / "escape.jsonl"
        link.symlink_to(secret)
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(link), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_chained_symlinks_rejected(self) -> None:
        mid = self.outside / "mid-link"
        mid.symlink_to(self.target)
        outer = self.outside / "outer-link"
        outer.symlink_to(mid)
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(outer), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_dotdot_cannot_reenter_via_canonicalization(self) -> None:
        sneaky = self.approved / "nested" / ".." / ".." / "outside" / "session.jsonl"
        # abspath collapses .. before validation; outside path must fail.
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(sneaky), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_user_created_root_alias_not_treated_as_platform_alias(self) -> None:
        alias = self.root / "user-root-alias"
        alias.symlink_to(self.approved)
        # Configured root remains self.approved; path under the unrelated alias
        # must not gain acceptance merely because realpath lands inside.
        with self.assertRaises(DiagnosticError) as caught:
            require_regular_no_symlinks(str(alias / "session.jsonl"), str(self.approved))
        self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_configured_root_spelling_and_canonical_alias_both_work(self) -> None:
        """OS root aliases: lexical abspath spelling and pinned realpath spelling.

        On macOS, tempfile paths often live under /var which realpaths to
        /private/var. Both spellings of the *configured* root must accept a
        path written with the other spelling. On platforms without such an
        alias the two spellings are identical and the check still holds.
        """

        raw = os.path.abspath(str(self.approved))
        base = canonicalize_cwd(self.approved)
        target_raw = os.path.join(raw, "session.jsonl")
        target_base = os.path.join(base, "session.jsonl")

        # Configured with lexical spelling; path may use either spelling.
        for path in (target_raw, target_base):
            with self.subTest(configured=raw, path=path):
                canonical, pinned = require_regular_no_symlinks(path, raw)
                self.assertEqual(canonical, canonicalize_cwd(self.target))
                self.assertEqual(pinned, base)

        # Configured with canonical spelling; path may use either spelling.
        for path in (target_raw, target_base):
            with self.subTest(configured=base, path=path):
                canonical, pinned = require_regular_no_symlinks(path, base)
                self.assertEqual(canonical, canonicalize_cwd(self.target))
                self.assertEqual(pinned, base)


if __name__ == "__main__":
    unittest.main()
