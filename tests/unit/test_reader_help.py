from __future__ import annotations

import contextlib
import io
import unittest
from typing import cast

from portable_resume.reader import build_parser


class ReaderHelpTests(unittest.TestCase):
    def render_help(self) -> str:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), self.assertRaises(SystemExit) as ctx:
            build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        return stream.getvalue()

    def test_help_teaches_reader_option_semantics(self) -> None:
        help_text = " ".join(self.render_help().split())

        self.assertIn("default: current directory", help_text)
        self.assertIn("0..5256000", help_text)
        self.assertIn("0 disables the age filter", help_text)
        self.assertIn("handoff for show, table for list", help_text)
        self.assertIn("conflicts with an explicit non-json", help_text)
        self.assertIn("per-tool-output character cap", help_text)
        self.assertIn("approved source store root", help_text)
        self.assertIn("portable-resume/request-v1", help_text)
        self.assertIn("required with --request-file", help_text)

        for action in build_parser()._actions:
            with self.subTest(option=action.dest):
                action_help = action.help
                self.assertIsInstance(action_help, str)
                self.assertTrue(cast(str, action_help).strip())

    def test_help_surfaces_self_check_and_worked_examples(self) -> None:
        help_text = self.render_help()

        self.assertEqual(help_text.count("self-check"), 2)
        self.assertIn("examples:\n", help_text)
        self.assertIn('portable-resume claude list --cwd "$PWD"', help_text)
        self.assertIn(
            'portable-resume claude show latest --cwd "$PWD" --format handoff',
            help_text,
        )
        self.assertIn("packaging/runtime health (always JSON)", help_text)


if __name__ == "__main__":
    unittest.main()
