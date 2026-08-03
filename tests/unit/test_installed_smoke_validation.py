from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


def load_smoke_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_installed_matrix.py"
    spec = importlib.util.spec_from_file_location("smoke_installed_matrix", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load installed smoke module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstalledSmokeValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = load_smoke_module()

    def envelope(self) -> str:
        return json.dumps(
            {
                "schema_version": "portable-resume/v1",
                "operation": "show",
                "inert": True,
                "untrusted_content": True,
                "query": {"source": "qwen", "cwd": "/workspace/project"},
                "sessions": [
                    {
                        "source": "qwen",
                        "session_id": "qwen-one",
                        "inert": True,
                        "untrusted_content": True,
                        "turns": [
                            {
                                "content": "exact synthetic content",
                                "inert": True,
                                "untrusted_content": True,
                            }
                        ],
                    }
                ],
            }
        )

    def validate(self, output: str) -> str | None:
        return self.smoke._parse_envelope(
            output,
            operation="show",
            source="qwen",
            cwd="/workspace/project",
            session_id="qwen-one",
            contents=("exact synthetic content",),
        )

    def test_accepts_exact_structured_fixture_envelope(self) -> None:
        self.assertIsNone(self.validate(self.envelope()))

    def test_rejects_generic_banner_and_wrong_fixture_identity_or_content(self) -> None:
        self.assertIsNotNone(self.validate("Portable Resume SECURITY BOUNDARY"))

        wrong_identity = json.loads(self.envelope())
        wrong_identity["sessions"][0]["session_id"] = "different"
        self.assertIsNotNone(self.validate(json.dumps(wrong_identity)))

        wrong_content = json.loads(self.envelope())
        wrong_content["sessions"][0]["turns"][0]["content"] = "different"
        self.assertIsNotNone(self.validate(json.dumps(wrong_content)))

    def test_list_accepts_extra_safe_sessions_but_requires_exact_fixture(self) -> None:
        value = json.loads(self.envelope())
        value["operation"] = "list"
        value["sessions"][0]["turns"] = []
        value["sessions"].append(
            {
                "source": "qwen",
                "session_id": "archived-one",
                "inert": True,
                "untrusted_content": True,
                "turns": [],
            }
        )
        detail = self.smoke._parse_envelope(
            json.dumps(value),
            operation="list",
            source="qwen",
            cwd="/workspace/project",
            session_id="qwen-one",
            contents=("ignored for list",),
        )
        self.assertIsNone(detail)

        value["sessions"][1]["source"] = "different"
        self.assertIsNotNone(
            self.smoke._parse_envelope(
                json.dumps(value),
                operation="list",
                source="qwen",
                cwd="/workspace/project",
                session_id="qwen-one",
                contents=(),
            )
        )

    def test_kimi_smoke_fixture_rewrites_only_a_temporary_copy(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "kimi"
            / "s-kim-01"
            / "root"
        )
        original = (fixture / "session_index.jsonl").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            relocated = self.smoke._materialize_fixture(
                "kimi",
                fixture,
                Path(temporary),
            )
            record = json.loads(
                (relocated / "session_index.jsonl").read_text(encoding="utf-8")
            )
            self.assertTrue(
                Path(record["sessionDir"]).resolve().is_relative_to(relocated.resolve())
            )
        self.assertEqual((fixture / "session_index.jsonl").read_bytes(), original)

    def test_normalize_smoke_cwd_is_absolute_and_stable(self) -> None:
        """Easy Windows matrix class: POSIX fixture cwd becomes host absolute.

        Drives shipped ``_normalize_smoke_cwd`` (not a reimplementation) and
        proves envelope validation accepts the normalized host form via
        ``same_cwd`` against the original fixture spelling.
        """
        import os

        from portable_resume.paths import same_cwd

        # Existing directory: realpath should be absolute.
        with tempfile.TemporaryDirectory() as tmp:
            normalized = self.smoke._normalize_smoke_cwd(tmp)
            self.assertTrue(os.path.isabs(normalized))
            self.assertEqual(os.path.realpath(tmp), normalized)

        # POSIX-style synthetic project path used by FIXTURES.
        fixture_cwd = "/workspace/project"
        path = self.smoke._normalize_smoke_cwd(fixture_cwd)
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(same_cwd(path, path))
        # Fixture spelling and normalized host form must still compare equal.
        self.assertTrue(same_cwd(fixture_cwd, path))

        # Envelope check path used by smoke_installed_matrix after normalize.
        payload = json.loads(self.envelope())
        payload["query"]["cwd"] = path
        detail = self.smoke._parse_envelope(
            json.dumps(payload),
            operation="show",
            source="qwen",
            cwd=path,
            session_id="qwen-one",
            contents=("exact synthetic content",),
        )
        self.assertIsNone(detail)

        # All FIXTURES project cwds (except crush override) normalize to abs paths.
        for source, (_rel, cwd, _sid, _contents) in self.smoke.FIXTURES.items():
            if source == "crush":
                continue
            host_cwd = self.smoke._normalize_smoke_cwd(cwd)
            self.assertTrue(os.path.isabs(host_cwd), msg=source)
            self.assertTrue(same_cwd(cwd, host_cwd), msg=source)


if __name__ == "__main__":
    unittest.main()
