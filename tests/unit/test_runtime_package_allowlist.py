from __future__ import annotations

import json
import unittest

from portable_resume.build_identity import runtime_identity
from portable_resume.install.render import _RUNTIME_MODULES, materialize_plan


class RuntimePackageAllowlistTests(unittest.TestCase):
    def test_runtime_allowlist_is_explicit_complete_and_excludes_installer(self) -> None:
        expected = {
            "__init__.py",
            "bounds.py",
            "build_identity.py",
            "config_layer.py",
            "contracts.py",
            "diagnostics.py",
            "discover_doctor.py",
            "handoff.py",
            "model.py",
            "output_write.py",
            "paths.py",
            "reader.py",
            "registry.py",
            "request.py",
            "resources/portable-resume-v1.schema.json",
            "resources/latest-release.json",
            "sanitize.py",
            "search_sessions.py",
            "select.py",
            "snapshot.py",
            "time_range.py",
            "workspace.py",
            "adapters/__init__.py",
            "adapters/antigravity.py",
            "adapters/base.py",
            "adapters/claude.py",
            "adapters/codex.py",
            "adapters/codex_sqlite.py",
            "adapters/common.py",
            "adapters/cursor.py",
            "adapters/cursor_live.py",
            "adapters/grok.py",
            "adapters/kimi.py",
            "adapters/goose.py",
            "adapters/crush.py",
            "adapters/cline.py",
            "adapters/openhands.py",
            "adapters/hermes.py",
            "adapters/gemini.py",
            "adapters/github_copilot.py",
            "adapters/opencode.py",
            "adapters/openclaw.py",
            "adapters/pi.py",
            "adapters/qwen.py",
        }
        self.assertEqual(set(_RUNTIME_MODULES), expected)
        self.assertEqual(len(_RUNTIME_MODULES), len(expected))
        self.assertFalse(any(path.startswith("install/") for path in _RUNTIME_MODULES))
        self.assertNotIn("resources/build-identity.json", _RUNTIME_MODULES)

    def test_materialized_runtime_matches_allowlist_exactly(self) -> None:
        files = materialize_plan("claude")
        prefix = ".portable-resume/runtime/portable_resume/"
        packaged = {
            relative.removeprefix(prefix)
            for relative in files
            if relative.startswith(prefix)
        }
        self.assertEqual(
            packaged,
            {*_RUNTIME_MODULES, "resources/build-identity.json"},
        )
        embedded = json.loads(
            files[f"{prefix}resources/build-identity.json"].decode("utf-8")
        )
        self.assertEqual(embedded, runtime_identity())


if __name__ == "__main__":
    unittest.main()
