from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock
from pathlib import Path

from portable_resume import reader


REPO = Path(__file__).resolve().parents[2]
WARNING = "W_RUNTIME_IDENTITY_DRIFT"


class RuntimeIdentityDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.installed = self.base / "installed"
        self._install(self.installed)
        self.source_root, self.cwd = self._write_claude_session()

    def _install(self, root: Path) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / "install-resume-skills"),
                "quick-install",
                "claude",
                "--root",
                str(root),
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def _write_claude_session(self) -> tuple[Path, Path]:
        source_root = self.base / "claude-store"
        cwd = self.base / "project"
        cwd.mkdir()
        session_id = str(uuid.uuid4())
        transcript = source_root / "projects" / "synthetic" / f"{session_id}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(
            json.dumps(
                {
                    "type": "user",
                    "uuid": str(uuid.uuid4()),
                    "parentUuid": None,
                    "sessionId": session_id,
                    "cwd": str(cwd),
                    "timestamp": "2026-08-01T00:00:00.000Z",
                    "message": {"role": "user", "content": "synthetic"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return source_root, cwd

    def _runner(self, root: Path) -> Path:
        return root / "resume-claude" / "scripts" / "run_reader.py"

    def _list(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self._runner(root)),
                "list",
                "--cwd",
                str(self.cwd),
                "--source-root",
                str(self.source_root),
                "--json",
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )

    def _list_default(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self._runner(root)),
                "list",
                "--cwd",
                str(self.cwd),
                "--source-root",
                str(self.source_root),
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )

    def _relocate(self) -> Path:
        relocated = self.base / "relocated"
        shutil.copytree(self.installed / "resume-claude", relocated / "resume-claude")
        shutil.copytree(self.installed / ".portable-resume", relocated / ".portable-resume")
        return relocated

    def test_pristine_and_manifestless_installs_are_silent(self) -> None:
        pristine = self._list(self.installed)
        self.assertEqual(pristine.returncode, 0, pristine.stderr)
        self.assertNotIn(WARNING, json.loads(pristine.stdout)["warnings"])

        manifest = self.installed / ".portable-resume" / ".state" / "manifest.json"
        manifest.unlink()
        manifestless = self._list(self.installed)
        self.assertEqual(manifestless.returncode, 0, manifestless.stderr)
        pristine_payload = json.loads(pristine.stdout)
        manifestless_payload = json.loads(manifestless.stdout)
        self.assertNotIn(WARNING, manifestless_payload["warnings"])
        manifestless_payload["generated_at"] = pristine_payload["generated_at"]
        self.assertEqual(pristine_payload, manifestless_payload)

    def test_relocated_tree_warns_without_changing_exit_or_payload(self) -> None:
        pristine = self._list(self.installed)
        relocated = self._list(self._relocate())

        self.assertEqual(pristine.returncode, 0, pristine.stderr)
        self.assertEqual(relocated.returncode, 0, relocated.stderr)
        pristine_payload = json.loads(pristine.stdout)
        relocated_payload = json.loads(relocated.stdout)
        self.assertNotIn(WARNING, pristine_payload["warnings"])
        self.assertIn(WARNING, relocated_payload["warnings"])
        relocated_payload["warnings"].remove(WARNING)
        relocated_payload["generated_at"] = pristine_payload["generated_at"]
        self.assertEqual(relocated_payload, pristine_payload)

    def test_relocated_tree_default_list_visibly_warns_without_failing(self) -> None:
        completed = self._list_default(self._relocate())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("SOURCE\tSESSION_ID\t"))
        self.assertIn(f"# {WARNING}\n", completed.stdout)
        self.assertEqual(completed.stderr, "")

    def test_other_install_does_not_make_an_intact_tree_look_stale(self) -> None:
        self._install(self.base / "newer-elsewhere")
        intact = self._list(self.installed)
        self.assertEqual(intact.returncode, 0, intact.stderr)
        self.assertNotIn(WARNING, json.loads(intact.stdout)["warnings"])

    def test_unreadable_identity_warns_but_never_blocks(self) -> None:
        manifest = self.installed / ".portable-resume" / ".state" / "manifest.json"
        manifest.write_text("not-json\n", encoding="utf-8")
        completed = self._list(self.installed)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(WARNING, json.loads(completed.stdout)["warnings"])

    def test_runtime_identity_hot_path_reads_at_most_one_file(self) -> None:
        manifest = self.installed / ".portable-resume" / ".state" / "manifest.json"
        runtime_reader = (
            self.installed
            / ".portable-resume"
            / "runtime"
            / "portable_resume"
            / "reader.py"
        )
        real_open = reader.os.open
        opened: list[object] = []

        def tracking_open(path: object, flags: int) -> int:
            opened.append(path)
            return real_open(path, flags)

        with mock.patch.object(reader, "__file__", str(runtime_reader)), mock.patch.object(
            reader.os, "open", side_effect=tracking_open
        ):
            identity = reader.runtime_install_identity()

        self.assertTrue(identity["manifest_present"])
        self.assertEqual(opened, [manifest])

    def test_version_identifies_actual_and_recorded_roots(self) -> None:
        relocated = self._relocate()
        pristine = subprocess.run(
            [sys.executable, str(self._runner(self.installed)), "--version"],
            text=True,
            capture_output=True,
            check=False,
        )
        copied = subprocess.run(
            [sys.executable, str(self._runner(relocated)), "--version"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(pristine.returncode, 0, pristine.stderr)
        self.assertEqual(copied.returncode, 0, copied.stderr)
        self.assertNotEqual(pristine.stdout, copied.stdout)
        self.assertIn(f"runtime-root: {json.dumps(str(self.installed))}", pristine.stdout)
        self.assertIn(f"runtime-root: {json.dumps(str(relocated))}", copied.stdout)
        self.assertIn(f"recorded-root: {json.dumps(str(self.installed))}", pristine.stdout)
        self.assertIn("recorded-root-match: true", pristine.stdout)
        self.assertIn("recorded-root-match: false", copied.stdout)
        self.assertIn("package-identity: ", pristine.stdout)


if __name__ == "__main__":
    unittest.main()
