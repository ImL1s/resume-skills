from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


PI_FIXTURES = Path("tests/fixtures/pi")
_V3_CASES = frozenset(
    {
        "s-pi-01-basic-v3",
        "s-pi-02-branch-compaction",
        "s-pi-03-tool-and-custom",
        "s-pi-04-corrupt-interior",
    }
)
_V2_CASES = frozenset({"s-pi-05-v2-compat"})
_SESSION_JSONL = re.compile(r"agent/sessions/--[^/]+--/.+\.jsonl$")


class PiFixtureTests(unittest.TestCase):
    def test_paths_are_clean_and_manifests_are_synthetic(self) -> None:
        manifests = sorted(PI_FIXTURES.glob("s-pi-*/fixture.json"))
        self.assertEqual(len(manifests), 5)
        for manifest_path in manifests:
            for path in manifest_path.parent.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("/Users/", text, msg=str(path))
                self.assertNotIn("/home/", text, msg=str(path))
            manifest_text = manifest_path.read_text(encoding="utf-8")
            compact = re.sub(r"\s+", "", manifest_text)
            self.assertIn('"synthetic":true', compact, msg=str(manifest_path))
            payload = json.loads(manifest_text)
            self.assertTrue(payload["synthetic"], msg=str(manifest_path))
            self.assertEqual(payload["source"], "pi")

    def test_session_headers_match_expected_versions(self) -> None:
        for manifest_path in sorted(PI_FIXTURES.glob("s-pi-*/fixture.json")):
            case = json.loads(manifest_path.read_text(encoding="utf-8"))["case"]
            session_files = [
                path
                for path in manifest_path.parent.rglob("*.jsonl")
                if _SESSION_JSONL.search(path.as_posix())
            ]
            self.assertEqual(len(session_files), 1, msg=case)
            first_line = session_files[0].read_text(encoding="utf-8").splitlines()[0]
            header = json.loads(first_line)
            self.assertEqual(header.get("type"), "session", msg=case)
            if case in _V3_CASES:
                self.assertEqual(header.get("version"), 3, msg=case)
            elif case in _V2_CASES:
                self.assertEqual(header.get("version"), 2, msg=case)
            else:
                self.fail(f"unexpected pi fixture case: {case}")


if __name__ == "__main__":
    unittest.main()
