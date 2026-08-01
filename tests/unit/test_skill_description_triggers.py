"""Plan 055: skill frontmatter descriptions are trigger-first, not mechanism-first."""

from __future__ import annotations

import re
import unittest

from portable_resume.install.catalog import SOURCE_TITLES, description_for
from portable_resume.install.render import render_skill_markdown
from portable_resume.model import SOURCE_KEYS

_TRIGGER = re.compile(
    r"resume|continue|last session|previous session|handoff|pick up",
    re.IGNORECASE,
)


class SkillDescriptionTriggerTests(unittest.TestCase):
    def test_description_for_every_enabled_source_is_trigger_first(self) -> None:
        self.assertEqual(frozenset(SOURCE_TITLES), frozenset(SOURCE_KEYS))
        for source in sorted(SOURCE_KEYS):
            with self.subTest(source=source):
                text = description_for(source)
                self.assertRegex(text, _TRIGGER)
                self.assertNotRegex(
                    text,
                    r"(?i)^import inert local .+ using a validated request document",
                )
                # Forbid live-restore capability claims while allowing "never live …".
                self.assertIn("never live process restore", text.lower())
                self.assertNotRegex(
                    text,
                    r"(?i)(?<!never )live (process |session )?restore",
                )
                self.assertNotIn("validated request document", text.lower())

    def test_rendered_frontmatter_embeds_description_for(self) -> None:
        for source in ("claude", "codex", "grok"):
            with self.subTest(source=source):
                body = render_skill_markdown(host="claude", source=source)
                front = body.split("---", 2)[1]
                expected = description_for(source)
                self.assertIn(f"description: {expected}", front)
                self.assertRegex(front, _TRIGGER)


if __name__ == "__main__":
    unittest.main()
