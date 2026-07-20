"""Release-archive style relocation without original checkout path."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class RelocatedBundleTests(unittest.TestCase):
    def test_relocated_copy_self_check_matrix_install_verify_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            relocated = Path(temporary) / "bundle"
            for name in ("src", "scripts", "schemas", "docs"):
                shutil.copytree(REPO / name, relocated / name)
            for name in ("LICENSE", "NOTICE", "README.md"):
                if (REPO / name).exists():
                    shutil.copy2(REPO / name, relocated / name)

            env = {**os.environ, "PYTHONPATH": str(relocated / "src")}
            # strip any checkout-specific pythonpath pollution
            completed = subprocess.run(
                [sys.executable, str(relocated / "scripts" / "portable-resume"), "self-check", "--json"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(relocated),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["ok"])
            self.assertEqual(report["sources"], sorted(report["sources"]))
            self.assertEqual(len(report["sources"]), 6)
            self.assertEqual(report["matrix"]["cell_count"], 36)

            project = Path(temporary) / "proj"
            project.mkdir()
            install = subprocess.run(
                [
                    sys.executable,
                    str(relocated / "scripts" / "install-resume-skills"),
                    "install",
                    "--host",
                    "claude",
                    "--scope",
                    "project",
                    "--project",
                    str(project),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(relocated),
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertTrue(json.loads(install.stdout)["ok"])
            skill = project / ".claude" / "skills" / "resume-claude" / "SKILL.md"
            self.assertTrue(skill.is_file())

            verify = subprocess.run(
                [
                    sys.executable,
                    str(relocated / "scripts" / "install-resume-skills"),
                    "verify",
                    "--host",
                    "claude",
                    "--scope",
                    "project",
                    "--project",
                    str(project),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(relocated),
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["ok"])

            uninstall = subprocess.run(
                [
                    sys.executable,
                    str(relocated / "scripts" / "install-resume-skills"),
                    "uninstall",
                    "--host",
                    "claude",
                    "--scope",
                    "project",
                    "--project",
                    str(project),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(relocated),
            )
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertFalse(skill.exists())


if __name__ == "__main__":
    unittest.main()
