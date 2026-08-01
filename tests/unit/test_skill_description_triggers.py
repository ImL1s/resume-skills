"""Plan 055: skill frontmatter descriptions are trigger-first, not mechanism-first."""

from __future__ import annotations

import re
import unittest

import yaml

from portable_resume.install.catalog import SOURCE_TITLES, description_for
from portable_resume.install.render import frontmatter_keys, render_skill_markdown
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
                # Bare colon+space would break unquoted YAML scalars.
                self.assertNotIn(": ", text)

    def test_rendered_frontmatter_is_yaml_parseable_for_all_sources(self) -> None:
        """Hosts load frontmatter with real YAML — guard every enabled source."""

        for source in sorted(SOURCE_KEYS):
            with self.subTest(source=source):
                body = render_skill_markdown(host="claude", source=source)
                self.assertTrue(body.startswith("---\n"), body[:40])
                front = body.split("---", 2)[1]
                loaded = yaml.safe_load(front)
                self.assertIsInstance(loaded, dict)
                self.assertEqual(loaded.get("name"), f"resume-{source}")
                expected = description_for(source)
                self.assertEqual(loaded.get("description"), expected)
                self.assertRegex(expected, _TRIGGER)
                self.assertEqual(frontmatter_keys(body), ["name", "description"])
                # Quoted scalar form in the template.
                self.assertIn(f'description: "{expected}"', body.split("---", 2)[1])


if __name__ == "__main__":
    unittest.main()
