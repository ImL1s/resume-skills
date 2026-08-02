"""Registry ↔ generated-docs matrix consistency gate (Lane C)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[2]


class RegistryDocsGateTests(unittest.TestCase):
    def test_matrix_dimensions_match_enabled_product(self) -> None:
        from portable_resume.registry import (
            enabled_destination_keys,
            enabled_source_keys,
            matrix_dimensions,
            rectangular_cells,
        )

        dims = matrix_dimensions()
        sources = len(enabled_source_keys())
        destinations = len(enabled_destination_keys())
        self.assertEqual(dims["sources"], sources)
        self.assertEqual(dims["destinations"], destinations)
        self.assertEqual(dims["cells"], sources * destinations)
        # Dynamic product (currently 17×18=306); do not hard-lock forever here
        # beyond the arithmetic invariant — see test_registry for the live snapshot.
        self.assertEqual(dims["cells"], dims["sources"] * dims["destinations"])

        rect = rectangular_cells(
            sources=enabled_source_keys(),
            destinations=enabled_destination_keys(),
        )
        self.assertEqual(len(rect), dims["cells"])
        self.assertEqual(len(set(rect)), dims["cells"])

    def test_render_docs_counts_match_registry(self) -> None:
        from scripts import render_docs
        from portable_resume.registry import matrix_dimensions

        self.assertEqual(render_docs.counts(), matrix_dimensions())
        summary = render_docs.rendered_regions()["matrix-summary"]
        dims = matrix_dimensions()
        self.assertIn(f"**{dims['sources']}**", summary)
        self.assertIn(f"**{dims['destinations']}**", summary)
        self.assertIn(
            f"**{dims['sources']}×{dims['destinations']}={dims['cells']}**",
            summary,
        )
        table = render_docs.rendered_regions()["matrix-counts-table"]
        self.assertIn(
            f"sources={dims['sources']} destinations={dims['destinations']} "
            f"cells={dims['cells']}",
            table,
        )
        self.assertIn(f"| cells | {dims['cells']} |", table)

    def test_assert_matrix_consistent_clean_tree(self) -> None:
        from scripts import render_docs

        failures = render_docs.assert_matrix_consistent(REPO)
        self.assertEqual(failures, [], msg="\n".join(failures))

    def test_assert_matrix_consistent_reports_generated_drift(self) -> None:
        from scripts import render_docs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "docs", root / "docs")
            path = root / "docs" / "matrix-current.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace("**17×18=306**", "**16×17=272**", 1)
            path.write_text(text, encoding="utf-8")

            failures = render_docs.assert_matrix_consistent(root)

        self.assertTrue(failures)
        joined = "\n".join(failures)
        self.assertIn("generated docs drift", joined)
        self.assertIn("docs/matrix-current.md", joined)

    def test_check_docs_includes_matrix_consistency_and_status_gate(self) -> None:
        from scripts import check_docs
        from portable_resume.registry import matrix_dimensions

        report = check_docs.check()
        self.assertTrue(report["ok"], msg="\n".join(report["failures"]))
        dims = matrix_dimensions()
        self.assertEqual(report["source_count"], dims["sources"])
        self.assertEqual(report["destination_count"], dims["destinations"])
        self.assertEqual(report["matrix_cells"], dims["cells"])

    def test_status_gate_rejects_wrong_current_product(self) -> None:
        from scripts import check_docs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(REPO / "README.md", root / "README.md")
            shutil.copy2(REPO / "CHANGELOG.md", root / "CHANGELOG.md")
            shutil.copytree(REPO / "docs", root / "docs")
            status_path = root / "docs" / "STATUS.md"
            status = status_path.read_text(encoding="utf-8")
            # Wrong *current* product while keeping historical 9×9=81 language.
            status = status.replace(
                "**306/306** on current main tip (**17×18**",
                "**272/272** on current main tip (**16×17**",
            )
            status_path.write_text(status, encoding="utf-8")

            with mock.patch.object(check_docs, "REPO", root):
                report = check_docs.check()

        failures = "\n".join(report["failures"])
        self.assertIn("Packaging matrix", failures)
        self.assertIn("Installed runner matrix", failures)
        self.assertIn("306/306", failures)


if __name__ == "__main__":
    unittest.main()
