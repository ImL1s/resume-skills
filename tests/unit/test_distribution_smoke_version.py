from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _load_smoke_module():
    path = REPO / "scripts" / "smoke_distribution.py"
    spec = importlib.util.spec_from_file_location("smoke_distribution", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DistributionSmokeVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = _load_smoke_module()

    def test_portable_resume_accepts_runtime_identity_report(self) -> None:
        output = "\n".join(
            (
                "portable-resume 0.4.0.dev0",
                "runtime-root: /tmp/current",
                "recorded-root: unknown",
                "recorded-root-match: unknown",
                "package-identity: unknown",
            )
        )
        self.assertTrue(
            self.smoke._valid_version_output(
                "portable-resume", output, "0.4.0.dev0"
            )
        )

    def test_installer_version_remains_exactly_one_line(self) -> None:
        self.assertTrue(
            self.smoke._valid_version_output(
                "install-resume-skills",
                "install-resume-skills 0.4.0.dev0\n",
                "0.4.0.dev0",
            )
        )
        self.assertFalse(
            self.smoke._valid_version_output(
                "install-resume-skills",
                "install-resume-skills 0.4.0.dev0\nextra: value\n",
                "0.4.0.dev0",
            )
        )


if __name__ == "__main__":
    unittest.main()
