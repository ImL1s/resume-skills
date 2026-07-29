"""#28: closed bounded schemas for installer control documents."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from portable_resume.diagnostics import DiagnosticError
from portable_resume.install.control_schema import (
    ControlSchemaError,
    parse_journal_document,
    parse_manifest_document,
    strict_json_loads,
)
from portable_resume.install.manifest import Manifest
from portable_resume.install.transaction import (
    execute_install,
    load_manifest,
    plan_install,
    recover_root,
)


class InstallControlSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = str(Path(self.temp.name) / "root")
        Path(self.root).mkdir()

    def _valid_manifest_text(self) -> str:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        manifest = load_manifest(self.root)
        assert manifest is not None
        return manifest.dumps()

    def test_duplicate_keys_rejected(self) -> None:
        with self.assertRaises(ControlSchemaError):
            strict_json_loads('{"a": 1, "a": 2}')

    def test_nan_infinity_rejected(self) -> None:
        with self.assertRaises(ControlSchemaError):
            strict_json_loads('{"x": NaN}')
        with self.assertRaises(ControlSchemaError):
            strict_json_loads('{"x": Infinity}')

    def test_valid_manifest_round_trip(self) -> None:
        text = self._valid_manifest_text()
        again = Manifest.loads(text).dumps()
        self.assertEqual(text, again)

    def test_unknown_manifest_property_rejected(self) -> None:
        data = json.loads(self._valid_manifest_text())
        data["extra"] = True
        with self.assertRaises(ValueError):
            Manifest.loads(json.dumps(data))

    def test_bad_digest_rejected(self) -> None:
        data = json.loads(self._valid_manifest_text())
        first = next(iter(data["files"]))
        data["files"][first]["sha256"] = "not-a-digest"
        with self.assertRaises(ValueError):
            Manifest.loads(json.dumps(data))

    def test_path_key_mismatch_rejected(self) -> None:
        data = json.loads(self._valid_manifest_text())
        first = next(iter(data["files"]))
        data["files"][first]["path"] = "other/path.txt"
        with self.assertRaises(ValueError):
            Manifest.loads(json.dumps(data))

    def test_unknown_host_rejected(self) -> None:
        data = json.loads(self._valid_manifest_text())
        claim_id = next(iter(data["claims"]))
        data["claims"][claim_id]["host"] = "not-a-host"
        with self.assertRaises(ValueError):
            Manifest.loads(json.dumps(data))

    def test_unsafe_file_path_rejected(self) -> None:
        data = json.loads(self._valid_manifest_text())
        entry = next(iter(data["files"].values()))
        data["files"] = {"../escape": {**entry, "path": "../escape"}}
        with self.assertRaises(ValueError):
            Manifest.loads(json.dumps(data))

    def test_corrupt_manifest_on_disk_is_verify_mismatch(self) -> None:
        execute_install(plan_install(host="claude", scope="project", root=self.root))
        path = Path(self.root) / ".portable-resume" / "manifest.json"
        path.write_text('{"schema_version":"x","a":1,"a":2}\n', encoding="utf-8")
        with self.assertRaises(DiagnosticError) as caught:
            load_manifest(self.root)
        self.assertEqual(caught.exception.code, "E_VERIFY_MISMATCH")

    def test_malformed_journal_is_recovery_required(self) -> None:
        support = Path(self.root) / ".portable-resume"
        support.mkdir(parents=True)
        (support / "journal.json").write_text('{"state":"staging","a":1,"a":2}\n', encoding="utf-8")
        with self.assertRaises(DiagnosticError) as caught:
            recover_root(self.root)
        self.assertEqual(caught.exception.code, "E_RECOVERY_REQUIRED")

    def test_journal_unknown_state_rejected(self) -> None:
        with self.assertRaises(ControlSchemaError):
            parse_journal_document(
                json.dumps(
                    {
                        "schema_version": "portable-resume/install-journal-v1",
                        "state": "exploded",
                        "generation": 1,
                        "claim": "c",
                        "stage_dir": "/tmp/stage",
                        "paths": {},
                    }
                )
            )


if __name__ == "__main__":
    unittest.main()
