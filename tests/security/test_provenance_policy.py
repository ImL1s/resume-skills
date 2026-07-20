"""Clean-room / provenance policy structural gates on shipped tree."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


# Implementation must not instruct loading the prohibited installed bundle as a library path.
FORBIDDEN_IN_SRC = (
    "Path.home() / \".grok\" / \"bundled\"",
    "expanduser(\"~/.grok/bundled",
)


class ProvenancePolicyTests(unittest.TestCase):
    def test_docs_forbid_installed_bundle_derivation(self) -> None:
        for path in (
            Path("docs/provenance.md"),
            Path("docs/clean-room-attestation.md"),
            Path("README.md"),
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn("~/.grok/bundled/skills", text.replace("**", ""))
        notice = Path("NOTICE").read_text(encoding="utf-8")
        self.assertIn("independently authored", notice)
        self.assertTrue(
            "installed Grok bundle" in notice or "bundled" in notice.lower() or "Grok Build" in notice
        )

    def test_fixtures_are_synthetic_manifests(self) -> None:
        manifests = list(Path("tests/fixtures").rglob("fixture.json"))
        self.assertGreaterEqual(len(manifests), 30)
        for path in manifests:
            text = path.read_text(encoding="utf-8")
            compact = re.sub(r"\s+", "", text)
            self.assertIn('"synthetic":true', compact, msg=str(path))
            self.assertNotRegex(text, r"/Users/[A-Za-z0-9_]+/")
            self.assertNotIn("sk-live-", text)

    def test_source_tree_does_not_load_installed_grok_bundle(self) -> None:
        for path in Path("src/portable_resume").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in FORBIDDEN_IN_SRC:
                self.assertNotIn(needle, text, msg=str(path))
            # reading the forbidden path as a default root is banned
            self.assertNotIn('"/bundled/skills"', text)
            self.assertNotIn("'/bundled/skills'", text)

    def test_source_formats_and_host_support_are_honest(self) -> None:
        host = Path("docs/host-support.md").read_text(encoding="utf-8")
        self.assertIn("`not-run`", host)
        self.assertIn("`verified-filesystem`", host)
        # no profile data row claims verified-live success
        for line in host.splitlines():
            if re.match(r"^\| `(claude|codex|cursor|opencode|antigravity|grok)-v1`", line):
                self.assertIn("`not-run`", line)
                self.assertNotIn("`verified-live`", line)
        formats = Path("docs/source-formats.md").read_text(encoding="utf-8")
        self.assertIn("supported (fixture/parser)", formats)
        self.assertRegex(formats, r"(?i)must not copy|must not inspect|do not copy")


if __name__ == "__main__":
    unittest.main()
