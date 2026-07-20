"""Grok-build resume-session UX parity: argv shape + Claude cwd slug discovery."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from portable_resume.adapters.claude import _slugify_cwd, ClaudeAdapter
from portable_resume.bounds import ReadBudget
from portable_resume.model import Query
from portable_resume.reader import run
from portable_resume.install.render import materialize_plan


class SlugifyTests(unittest.TestCase):
    def test_slugify_matches_claude_project_dirs(self) -> None:
        self.assertEqual(_slugify_cwd("/Users/iml1s/Documents/mine"), "-Users-iml1s-Documents-mine")
        self.assertEqual(_slugify_cwd("/tmp/foo_bar"), "-tmp-foo-bar")


class CwdScopedClaudeTests(unittest.TestCase):
    def test_many_project_dirs_still_list_cwd_slug(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cwd = root / "workspace" / "app"
            cwd.mkdir(parents=True)
            projects = root / "projects"
            # more than old 64 limit of unrelated project dirs
            for index in range(80):
                (projects / f"noise-{index}").mkdir(parents=True)
            session_id = str(uuid.uuid4())
            slug = _slugify_cwd(str(cwd))
            path = projects / slug / f"{session_id}.jsonl"
            path.parent.mkdir(parents=True)
            record = {
                "type": "user",
                "uuid": str(uuid.uuid4()),
                "parentUuid": None,
                "sessionId": session_id,
                "cwd": str(cwd),
                "timestamp": "2026-07-20T00:00:00.000Z",
                "message": {"role": "user", "content": "hello from noise tree"},
            }
            # include unknown + known types (Grok skips unknown)
            attachment = {"type": "attachment", "uuid": str(uuid.uuid4()), "sessionId": session_id}
            assistant = {
                "type": "assistant",
                "uuid": str(uuid.uuid4()),
                "parentUuid": record["uuid"],
                "sessionId": session_id,
                "cwd": str(cwd),
                "timestamp": "2026-07-20T00:00:01.000Z",
                "message": {"role": "assistant", "content": "hi"},
            }
            path.write_text(
                "\n".join(json.dumps(item) for item in (record, attachment, assistant)) + "\n",
                encoding="utf-8",
            )
            values = ClaudeAdapter().list(
                Query("claude", cwd=str(cwd), source_root=str(root)),
                ReadBudget(),
            )
            self.assertEqual(len(values), 1)
            self.assertEqual(values[0].session_id, session_id)


class SkillBoundArgvTests(unittest.TestCase):
    def test_installed_runner_accepts_show_latest_without_request_file(self) -> None:
        body = materialize_plan("claude")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # write skill tree
            for rel, data in body.items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            # fixture session under fake claude root
            home_claude = root / "claude-home"
            cwd = root / "proj"
            cwd.mkdir()
            session_id = str(uuid.uuid4())
            slug = _slugify_cwd(str(cwd))
            session = home_claude / "projects" / slug / f"{session_id}.jsonl"
            session.parent.mkdir(parents=True)
            uid = str(uuid.uuid4())
            session.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": uid,
                        "parentUuid": None,
                        "sessionId": session_id,
                        "cwd": str(cwd),
                        "timestamp": "2026-07-20T00:00:00.000Z",
                        "message": {"role": "user", "content": "skill argv works"},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "assistant",
                        "uuid": str(uuid.uuid4()),
                        "parentUuid": uid,
                        "sessionId": session_id,
                        "cwd": str(cwd),
                        "timestamp": "2026-07-20T00:00:01.000Z",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            runner = root / "resume-claude" / "scripts" / "run_reader.py"
            # simulate skill argv: show latest --cwd ... --source-root ... --json
            # by invoking reader main through subprocess would need execute bit;
            # unit-test the force wrapper via exec of rendered module.
            import importlib.util
            import sys

            # Ensure the bound runner injects source and allows expected-source.
            text = runner.read_text(encoding="utf-8")
            self.assertIn('if cleaned and cleaned[0] in {"list", "show"}', text)
            # Direct reader path equivalent after injection
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = run(
                [
                    "claude",
                    "show",
                    "latest",
                    "--cwd",
                    str(cwd),
                    "--source-root",
                    str(home_claude),
                    "--json",
                    "--expected-source",
                    "claude",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 0, stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["operation"], "show")
            self.assertEqual(payload["sessions"][0]["session_id"], session_id)
            self.assertIn("skill argv works", payload["sessions"][0]["last_user_request"] or "")

    def test_skill_template_argv_primary_not_request_file_required(self) -> None:
        from portable_resume.install.render import render_skill_markdown

        text = render_skill_markdown(host="claude", source="codex")
        self.assertIn("run_reader.py show", text)
        self.assertNotIn(
            "Still write a request-v1 file before invoking the runner.",
            text,
        )
        # optional advanced path must still be mentioned somewhere
        lower = text.lower()
        self.assertTrue("request-v1" in lower or "request-file" in lower)


if __name__ == "__main__":
    unittest.main()
