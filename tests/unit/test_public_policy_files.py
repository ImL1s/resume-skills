from __future__ import annotations

import unittest
from pathlib import Path


class PublicPolicyFilesTests(unittest.TestCase):
    def test_security_and_contributing_exist(self) -> None:
        for name in ("SECURITY.md", "CONTRIBUTING.md"):
            text = Path(name).read_text(encoding="utf-8")
            self.assertGreater(len(text), 400)
        sec = Path("SECURITY.md").read_text(encoding="utf-8")
        self.assertRegex(sec, r"(?i)threat|session|report|vulnerab")
        con = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("synthetic", con)
        self.assertIn("~/.grok/bundled/skills", con)

    def test_contributing_documents_fast_but_non_authoritative_local_loops(self) -> None:
        con = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
        required_gate = """Run all four before opening a pull request:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```"""
        self.assertIn(required_gate, con)
        self.assertIn("### Fast iteration during development", con)
        self.assertIn("python3 scripts/self_verify.py --only unit", con)
        self.assertIn(
            "python3 scripts/self_verify.py --only docs"
            "          # localized quick-start docs gate",
            con,
        )
        self.assertIn(
            "For other\ndocumentation, run the focused unittest",
            con,
        )
        self.assertIn("python3 scripts/self_verify.py --profile ci-compat", con)
        self.assertIn("### Editable install (drops the `PYTHONPATH` prefix)", con)
        self.assertIn("pip install -e .", con)
        self.assertIn("### pytest (optional local convenience)", con)
        self.assertIn("The authoritative runner is unittest", con)
        self.assertIn("Do not add pytest-only constructs", con)
