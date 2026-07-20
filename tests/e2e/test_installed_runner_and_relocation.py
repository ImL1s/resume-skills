"""Installed runner and offline relocation smoke tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from portable_resume.install.catalog import resolve_skill_root
from portable_resume.install.transaction import execute_install, plan_install, verify_root


REPO = Path(__file__).resolve().parents[2]


class InstalledRunnerTests(unittest.TestCase):
    def test_installed_run_reader_request_boundary_and_fixture_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            project = Path(temporary) / "project"
            home.mkdir()
            project.mkdir()
            root = resolve_skill_root(
                host="claude",
                scope="project",
                project_dir=str(project),
                home_dir=str(home),
            )
            execute_install(plan_install(host="claude", scope="project", root=root))
            verify_root(root)

            fixture_root = REPO / "tests" / "fixtures" / "claude" / "s-cla-01-ordered-parent-chain" / "root"
            self.assertTrue(fixture_root.is_dir(), "missing claude fixture root")

            request_path = Path(temporary) / "request.json"
            # Align request cwd with synthetic fixture sessions (/workspace/project).
            request_path.write_text(
                json.dumps(
                    {
                        "schema_version": "portable-resume/request-v1",
                        "source": "claude",
                        "action": "show",
                        "resume_ref": "latest",
                        "cwd": "/workspace/project",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            runner = Path(root) / "resume-claude" / "scripts" / "run_reader.py"
            env = os.environ.copy()
            # Intentionally do not put checkout src on PYTHONPATH; runtime must resolve.
            env.pop("PYTHONPATH", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--request-file",
                    str(request_path),
                    "--format",
                    "handoff",
                    "--source-root",
                    str(fixture_root),
                    # host-supplied override must be ignored by hard-bound skill source
                    "--expected-source",
                    "codex",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(project),
            )
            self.assertNotIn("ModuleNotFoundError", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("untrusted", completed.stdout.lower())
            self.assertIn("synthetic request", completed.stdout.lower())


class RelocationTests(unittest.TestCase):
    def test_copy_tree_installs_from_relocated_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            relocated = Path(temporary) / "relocated-bundle"
            # copy only needed package surfaces
            shutil.copytree(REPO / "src", relocated / "src")
            shutil.copytree(REPO / "scripts", relocated / "scripts")
            shutil.copytree(REPO / "schemas", relocated / "schemas")
            for name in ("LICENSE", "NOTICE"):
                shutil.copy2(REPO / name, relocated / name)

            env = {**os.environ, "PYTHONPATH": str(relocated / "src")}
            completed = subprocess.run(
                [sys.executable, "-m", "portable_resume.install.cli", "matrix", "--json"],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(relocated),
            )
            report = json.loads(completed.stdout)
            self.assertTrue(report["ok"])
            self.assertEqual(report["cell_count"], 36)

            project = Path(temporary) / "proj"
            project.mkdir()
            root = str(project / ".claude" / "skills")
            install = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "portable_resume.install.cli",
                    "install",
                    "--host",
                    "claude",
                    "--scope",
                    "project",
                    "--project",
                    str(project),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(relocated),
            )
            payload = json.loads(install.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue((Path(root) / "resume-claude" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
