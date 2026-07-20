"""Per-host install catalog and hosts CLI."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from portable_resume.install.catalog import (
    HOST_KEYS,
    HOST_PROFILES,
    host_install_record,
    hosts_report,
    resolve_skill_root,
)
from portable_resume.install.cli import run as install_cli_run


class HostsCatalogTests(unittest.TestCase):
    def test_six_hosts_complete_metadata(self) -> None:
        self.assertEqual(set(HOST_PROFILES), set(HOST_KEYS))
        self.assertEqual(len(HOST_KEYS), 6)
        for key, profile in HOST_PROFILES.items():
            self.assertEqual(profile.key, key)
            self.assertTrue(profile.project_rel)
            self.assertTrue(profile.global_rel)
            self.assertTrue(profile.activation_help)
            self.assertTrue(profile.install_methods)
            self.assertTrue(profile.project_layout)
            self.assertTrue(profile.global_layout)
            self.assertTrue(profile.display_name)

    def test_default_roots_match_public_table(self) -> None:
        expected = {
            "claude": (".claude/skills", ".claude/skills"),
            "codex": (".agents/skills", ".agents/skills"),
            "cursor": (".cursor/skills", ".cursor/skills"),
            "opencode": (".opencode/skills", ".config/opencode/skills"),
            "antigravity": (".agents/skills", ".gemini/config/skills"),
            "grok": (".grok/skills", ".grok/skills"),
        }
        for host, (project, global_rel) in expected.items():
            self.assertEqual(HOST_PROFILES[host].project_rel, project)
            self.assertEqual(HOST_PROFILES[host].global_rel, global_rel)

    def test_resolve_and_host_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "proj"
            home.mkdir()
            project.mkdir()
            rec = host_install_record(
                "claude",
                project_dir=str(project),
                home_dir=str(home),
            )
            self.assertEqual(rec["host"], "claude")
            self.assertTrue(rec["installer_defaults"]["project_root_resolved"].endswith(
                os.path.join("proj", ".claude", "skills")
            ))
            self.assertTrue(rec["installer_defaults"]["global_root_resolved"].endswith(
                os.path.join("home", ".claude", "skills")
            ))
            self.assertIn("resume-codex", rec["skills_installed"])
            self.assertEqual(rec["live_ui"], "not-run")
            self.assertIn("project", rec["installer_commands"])

    def test_hosts_report_all_and_shared_pair(self) -> None:
        report = hosts_report(project_dir="/tmp/proj", home_dir="/tmp/home")
        self.assertTrue(report["ok"])
        self.assertEqual(report["host_count"], 6)
        self.assertEqual(len(report["hosts"]), 6)
        self.assertEqual(report["docs"], "docs/install-hosts.md")
        pairs = report["shared_root_pairs"]
        self.assertEqual(pairs[0]["hosts"], ["codex", "antigravity"])
        names = {h["host"] for h in report["hosts"]}
        self.assertEqual(names, set(HOST_KEYS))

    def test_hosts_cli_json_and_human(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = install_cli_run(["hosts", "--json", "--project", "/tmp/p", "--home", "/tmp/h"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["host_count"], 6)

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            code2 = install_cli_run(["hosts", "--host", "grok"])
        self.assertEqual(code2, 0)
        text = buf2.getvalue()
        self.assertIn("## grok", text)
        self.assertIn(".grok/skills", text)
        self.assertIn("/resume-", text)

    def test_install_hosts_doc_exists(self) -> None:
        doc = Path("docs/install-hosts.md")
        self.assertTrue(doc.is_file())
        text = doc.read_text(encoding="utf-8")
        for host in sorted(HOST_KEYS):
            self.assertIn(f"`{host}`", text)
        self.assertIn("install-resume-skills hosts", text)
        self.assertIn("E_INSTALL_CONFLICT", text)

    def test_resolve_skill_root_requires_project(self) -> None:
        with self.assertRaises(ValueError):
            resolve_skill_root(
                host="claude", scope="project", project_dir=None, home_dir="/tmp"
            )


if __name__ == "__main__":
    unittest.main()
