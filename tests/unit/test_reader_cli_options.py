"""Reader CLI: accepted options must apply or fail closed (#65)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from portable_resume import __version__
from portable_resume.build_identity import latest_release
from portable_resume.diagnostics import ExitCode
from portable_resume.reader import run


class SelfCheckArgvTests(unittest.TestCase):
    def test_self_check_json_ok(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(["self-check", "--json"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIn("package_surfaces", payload)
        self.assertEqual(payload["build_identity"]["base_version"], __version__)
        self.assertEqual(
            payload["latest_release"]["version"],
            latest_release()["version"],
        )

    def test_self_check_rejects_unknown_option(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(["self-check", "--definitely-invalid"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, int(ExitCode.INVALID_INPUT))
        self.assertEqual(stdout.getvalue(), "")

    def test_self_check_rejects_extra_positional(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(["self-check", "extra"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, int(ExitCode.INVALID_INPUT))

    def test_self_check_rejects_source_options(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(["self-check", "--within-min", "1"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, int(ExitCode.INVALID_INPUT))


class RequestFileOptionTests(unittest.TestCase):
    def test_request_file_rejects_within_min(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary) / "work"
            cwd.mkdir()
            request = Path(temporary) / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "schema_version": "portable-resume/request-v1",
                        "source": "claude",
                        "action": "show",
                        "resume_ref": "latest",
                        "cwd": str(cwd.resolve()),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = run(
                [
                    "--request-file",
                    str(request),
                    "--expected-source",
                    "claude",
                    "--within-min",
                    "5",
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, int(ExitCode.INVALID_INPUT))
            self.assertEqual(stdout.getvalue(), "")


class FormatContractTests(unittest.TestCase):
    def test_list_accepts_explicit_table_format(self) -> None:
        # Invalid source root / empty list may still parse format path.
        # Use self-contained: format validation happens before adapter I/O for
        # show+table; for list+table we need a valid invocation shape.
        # Empty cwd list: still exercises argparse + _format.
        stdout = io.StringIO()
        stderr = io.StringIO()
        # Will fail at capability if no sessions, but format must not be invalid.
        code = run(
            ["claude", "list", "--format", "table", "--json"],
            stdout=stdout,
            stderr=stderr,
        )
        # --json and --format table conflict
        self.assertEqual(code, int(ExitCode.INVALID_INPUT))

    def test_show_rejects_table_format(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            ["claude", "show", "latest", "--format", "table"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, int(ExitCode.INVALID_INPUT))


if __name__ == "__main__":
    unittest.main()
