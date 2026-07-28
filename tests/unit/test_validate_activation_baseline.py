from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "validate_activation_baseline.py"


def load_validator_module():
    name = "validate_activation_baseline"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


class ValidateActivationBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_validator_module()

    def test_cli_succeeds_against_tracked_plans(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(REPO)],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issue_count"], 44)
        self.assertEqual(
            payload["jsonl_sha256"],
            self.mod.EXPECTED_JSONL_SHA256,
        )
        self.assertEqual(
            payload["manifest_sha256"],
            self.mod.EXPECTED_MANIFEST_SHA256,
        )
        self.assertEqual(payload["pair_count"], 212)
        self.assertEqual(payload["order_entry_count"], 44)

    def test_import_validate_activation_baseline_success(self) -> None:
        summary = self.mod.validate_activation_baseline(REPO)
        self.assertTrue(summary["ok"])
        self.assertEqual(len(summary["issue_numbers"]), 44)

    def _clone_tracked(self, root: Path) -> Path:
        dest = root / "plans" / "all-open-issues-sequential-prs"
        dest.mkdir(parents=True)
        src = REPO / "plans" / "all-open-issues-sequential-prs"
        for name in (
            "activation-baseline-20260728.jsonl",
            "activation-baseline-20260728.manifest.json",
            "activation-dependency-pairs-20260728.json",
            "activation-order-20260728.json",
            "activation-issue-ledger-20260728.md",
        ):
            shutil.copy2(src / name, dest / name)
        (root / "scripts").mkdir(exist_ok=True)
        return dest

    def test_rejects_jsonl_raw_hash_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dest = self._clone_tracked(root)
            jsonl = dest / "activation-baseline-20260728.jsonl"
            jsonl.write_bytes(jsonl.read_bytes() + b" ")
            with self.assertRaises(self.mod.ValidationError) as ctx:
                self.mod.validate_activation_baseline(root)
            self.assertEqual(ctx.exception.code, "E_JSONL_SHA256")

    def test_rejects_manifest_self_hash_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dest = self._clone_tracked(root)
            path = dest / "activation-baseline-20260728.manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            # Keep raw file form pretty-printed-ish but change a non-hash field
            # after recomputing would still fail expected raw hash first.
            # Mutate recorded manifest_sha256 only while keeping raw structure.
            text = path.read_text(encoding="utf-8")
            bad = text.replace(
                manifest["manifest_sha256"],
                "0" * 64,
                1,
            )
            path.write_text(bad, encoding="utf-8")
            with self.assertRaises(self.mod.ValidationError) as ctx:
                self.mod.validate_activation_baseline(root)
            # Raw SHA changes when we rewrite the file, so raw check fails first.
            self.assertIn(
                ctx.exception.code,
                {"E_MANIFEST_RAW_SHA256", "E_MANIFEST_HASH"},
            )

    def test_rejects_duplicate_issue_in_temp_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dest = self._clone_tracked(root)
            jsonl_path = dest / "activation-baseline-20260728.jsonl"
            lines = [
                line
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            # Duplicate first record as second line; also truncate to keep small.
            mutated = "\n".join([lines[0], lines[0]]) + "\n"
            jsonl_path.write_text(mutated, encoding="utf-8")
            # Raw hash fails before semantic checks — assert that path.
            with self.assertRaises(self.mod.ValidationError) as ctx:
                self.mod.validate_activation_baseline(root)
            self.assertEqual(ctx.exception.code, "E_JSONL_SHA256")

            # Direct record-path API: validate_jsonl rejects hash first; use
            # validate_record / duplicate detection via forced sha bypass by
            # calling internal pieces after temporarily monkey-patching expected.
            original = self.mod.EXPECTED_JSONL_SHA256
            try:
                self.mod.EXPECTED_JSONL_SHA256 = self.mod.sha256_bytes(
                    jsonl_path.read_bytes()
                )
                with self.assertRaises(self.mod.ValidationError) as ctx2:
                    self.mod.validate_jsonl(jsonl_path)
                self.assertEqual(ctx2.exception.code, "E_JSONL_DUP_ISSUE")
            finally:
                self.mod.EXPECTED_JSONL_SHA256 = original

    def test_rejects_pair_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dest = self._clone_tracked(root)
            pairs_path = dest / "activation-dependency-pairs-20260728.json"
            payload = json.loads(pairs_path.read_text(encoding="utf-8"))
            payload["pair_count"] = 999
            pairs_path.write_bytes(self.mod.canonical_bytes(payload) + b"\n")
            original = self.mod.EXPECTED_PAIRS_SHA256
            try:
                self.mod.EXPECTED_PAIRS_SHA256 = self.mod.sha256_bytes(
                    pairs_path.read_bytes()
                )
                # Still need other artifacts valid — only pairs mutated with matching sha pin.
                with self.assertRaises(self.mod.ValidationError) as ctx:
                    self.mod.validate_activation_baseline(root)
                self.assertEqual(ctx.exception.code, "E_PAIRS_COUNT")
            finally:
                self.mod.EXPECTED_PAIRS_SHA256 = original

    def test_strict_loads_rejects_duplicate_keys_and_nonfinite(self) -> None:
        with self.assertRaises(self.mod.ValidationError) as ctx:
            self.mod.strict_loads('{"a":1,"a":2}')
        self.assertEqual(ctx.exception.code, "E_JSON_DUPLICATE_KEY")
        with self.assertRaises(self.mod.ValidationError) as ctx2:
            self.mod.strict_loads("[NaN]")
        self.assertEqual(ctx2.exception.code, "E_JSON_NONFINITE")


if __name__ == "__main__":
    unittest.main()
