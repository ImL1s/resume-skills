from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers.fixture_manifest import FixtureManifestError, validate_fixture_manifest, validate_fixture_tree


class FoundationBaselineTests(unittest.TestCase):
    def valid_manifest(self) -> dict:
        return {
            "synthetic": True,
            "source": "claude",
            "format_id": "foundation-synthetic-v1",
            "case": "manifest-validator",
            "expected_operation": "error",
            "expected_code": 5,
            "expected_warnings": [],
            "provenance_ref": "docs/source-formats.md#foundation-only",
        }

    def write(self, root: Path, payload: object, *, raw: str | None = None, name: str = "fixture.json") -> Path:
        path = root / name
        path.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")
        return path

    def test_apache_notice_and_clean_room_baselines_exist_without_adapter_claims(self) -> None:
        license_text = Path("LICENSE").read_text()
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)
        notice = Path("NOTICE").read_text()
        self.assertIn("independently authored", notice)
        provenance = Path("docs/provenance.md").read_text()
        self.assertIn("~/.grok/bundled/skills/**", provenance)
        self.assertIn("does **not** claim", provenance)
        source_formats = Path("docs/source-formats.md").read_text()
        # G001 used "| planned |" rows; G002 promotes adapters to fixture/parser support.
        planned = source_formats.count("| planned |")
        supported = source_formats.count("| supported (fixture/parser) |")
        self.assertEqual(planned + supported, 6)
        self.assertGreaterEqual(supported, 1)
        attestation = Path("docs/clean-room-attestation.md").read_text()
        self.assertIn("No excluded source was opened", attestation)

    def test_fixture_manifest_accepts_strict_synthetic_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = validate_fixture_manifest(self.write(root, self.valid_manifest()))
            self.assertTrue(manifest.synthetic)
            self.assertEqual(manifest.source, "claude")
            self.assertEqual(validate_fixture_tree(root), (manifest,))

    def test_fixture_manifest_rejects_non_synthetic_extra_private_duplicate_and_unknown(self) -> None:
        cases = []
        non_synthetic = {**self.valid_manifest(), "synthetic": False}
        cases.append(("non-synthetic", non_synthetic, None))
        extra = {**self.valid_manifest(), "extra": True}
        cases.append(("extra", extra, None))
        private = {**self.valid_manifest(), "case": "/Users/alice/private"}
        cases.append(("private", private, None))
        unknown_source = {**self.valid_manifest(), "source": "other"}
        cases.append(("source", unknown_source, None))
        unknown_warning = {**self.valid_manifest(), "expected_warnings": ["W_MADE_UP"]}
        cases.append(("warning", unknown_warning, None))
        duplicate = '{"synthetic":true,"synthetic":true,"source":"claude","format_id":"x-v1","case":"case","expected_operation":"error","expected_code":5,"expected_warnings":[],"provenance_ref":"docs/source-formats.md#foundation-only"}'
        cases.append(("duplicate", None, duplicate))
        for index, (name, payload, raw) in enumerate(cases):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = self.write(Path(temporary), payload, raw=raw)
                with self.assertRaises(FixtureManifestError):
                    validate_fixture_manifest(path)


if __name__ == "__main__":
    unittest.main()
