"""Plan 055: skill frontmatter descriptions are trigger-first, not mechanism-first."""

from __future__ import annotations

import re
import unittest

from portable_resume.install.catalog import SOURCE_TITLES, description_for
from portable_resume.install.render import frontmatter_keys, render_skill_markdown
from portable_resume.model import SOURCE_KEYS

_TRIGGER = re.compile(
    r"resume|continue|last session|previous session|handoff|pick up",
    re.IGNORECASE,
)


def _load_skill_frontmatter(skill_md: str) -> dict[str, str]:
    """Strict host-like frontmatter load (stdlib-only).

    Hosts use real YAML. We do not depend on PyYAML in CI, but we still reject
    the class of bugs that break YAML: bare mapping markers inside unquoted
    scalars, and require quoted description values from the template.
    """

    lines = skill_md.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening frontmatter fence")
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"frontmatter line missing colon: {line!r}")
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not key:
            raise ValueError(f"empty frontmatter key: {line!r}")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            value = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        else:
            # Unquoted scalar: colon+space is a YAML mapping marker and breaks
            # PyYAML/host parsers (the 48f9f90 plan-055 regression).
            if ": " in raw:
                raise ValueError(
                    f"unquoted frontmatter value embeds ': ' (YAML-unsafe): {raw!r}"
                )
            value = raw
        data[key] = value
    if "name" not in data or "description" not in data:
        raise ValueError(f"frontmatter missing name/description: {sorted(data)}")
    return data


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

    def test_rendered_frontmatter_is_yaml_safe_for_all_sources(self) -> None:
        """Every enabled source's rendered SKILL.md frontmatter must host-load."""

        for source in sorted(SOURCE_KEYS):
            with self.subTest(source=source):
                body = render_skill_markdown(host="claude", source=source)
                self.assertTrue(body.startswith("---\n"), body[:40])
                loaded = _load_skill_frontmatter(body)
                self.assertEqual(loaded.get("name"), f"resume-{source}")
                expected = description_for(source)
                self.assertEqual(loaded.get("description"), expected)
                self.assertRegex(expected, _TRIGGER)
                self.assertEqual(frontmatter_keys(body), ["name", "description"])
                # Template must quote the description scalar.
                front = body.split("---", 2)[1]
                self.assertIn(f'description: "{expected}"', front)

                # Prefer real PyYAML when present (local/dev) for dual proof.
                try:
                    import yaml  # type: ignore
                except ImportError:
                    yaml = None  # type: ignore
                if yaml is not None:
                    py = yaml.safe_load(front)
                    self.assertEqual(py.get("description"), expected)
                    self.assertEqual(py.get("name"), f"resume-{source}")

    def test_unquoted_colon_space_description_is_rejected_by_guard(self) -> None:
        """Regression: the broken 48f9f90 shape must not pass the YAML-safety guard."""

        broken = (
            "---\n"
            "name: resume-claude\n"
            "description: Resume or continue the last Claude Code session: pick up work\n"
            "---\n"
            "# body\n"
        )
        with self.assertRaises(ValueError) as ctx:
            _load_skill_frontmatter(broken)
        self.assertIn(": ", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
