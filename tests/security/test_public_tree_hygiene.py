from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


FORBIDDEN = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"aa22306546@hotmail\.com"),
    re.compile(r"-----BEGIN (RSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
]


class PublicTreeHygieneTests(unittest.TestCase):
    def test_tracked_files_have_no_local_pii_or_secrets(self) -> None:
        listed = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
        self.assertGreater(len(listed), 50)
        hits: list[str] = []
        for rel in listed:
            path = Path(rel)
            if not path.is_file():
                continue
            # allow binary fixtures without text scan
            if path.suffix in {".sqlite", ".vscdb", ".zst"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in FORBIDDEN:
                if pat.search(text):
                    hits.append(f"{rel}: {pat.pattern}")
        self.assertEqual(hits, [], msg="public tree leaks local paths/secrets:\n" + "\n".join(hits[:50]))

    def test_research_logs_are_not_tracked(self) -> None:
        listed = set(subprocess.check_output(["git", "ls-files"], text=True).splitlines())
        offenders = [p for p in listed if p.startswith(".omc/research/") and p.endswith((".log", ".md"))]
        # dual-review raw logs and opensource audit dumps must not ship
        bad = [p for p in offenders if "dual-review" in p or "opensource-" in p or "live-smoke" in p or "linux-gate" in p]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
