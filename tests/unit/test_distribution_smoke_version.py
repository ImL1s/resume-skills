from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import ClassVar


REPO = Path(__file__).resolve().parents[2]


def _load_smoke_module():
    path = REPO / "scripts" / "smoke_distribution.py"
    spec = importlib.util.spec_from_file_location("smoke_distribution", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DistributionSmokeVersionTests(unittest.TestCase):
    smoke: ClassVar[ModuleType]

    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = _load_smoke_module()

    def test_portable_resume_accepts_runtime_identity_report(self) -> None:
        output = "\n".join(
            (
                "portable-resume 0.4.0.dev0",
                'runtime-root: "/tmp/current"',
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

    def test_manifestless_distribution_identity_is_exact_and_consistent(self) -> None:
        output = "\n".join(
            (
                "portable-resume 0.4.0.dev0",
                'runtime-root: "/tmp/venv/site-packages"',
                "recorded-root: unknown",
                "recorded-root-match: unknown",
                "package-identity: unknown",
            )
        )
        self.assertTrue(
            self.smoke._valid_version_output(
                "portable-resume",
                output,
                "0.4.0.dev0",
                expected_runtime_root=Path("/tmp/venv/site-packages"),
                require_manifestless=True,
            )
        )

    def test_portable_resume_rejects_invalid_identity_fields(self) -> None:
        valid = [
            "portable-resume 0.4.0.dev0",
            'runtime-root: "/tmp/current"',
            "recorded-root: unknown",
            "recorded-root-match: unknown",
            "package-identity: unknown",
        ]
        cases = {
            "relative path": (1, 'runtime-root: "relative"'),
            "control path": (1, 'runtime-root: "/tmp/bad\\u0000path"'),
            "bad enum": (3, "recorded-root-match: maybe"),
            "bad digest": (4, "package-identity: abc123"),
            "manifest claim": (2, 'recorded-root: "/tmp/recorded"'),
        }
        for name, (index, replacement) in cases.items():
            with self.subTest(name=name):
                lines = list(valid)
                lines[index] = replacement
                self.assertFalse(
                    self.smoke._valid_version_output(
                        "portable-resume",
                        "\n".join(lines),
                        "0.4.0.dev0",
                        expected_runtime_root=Path("/tmp/current"),
                        require_manifestless=True,
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
