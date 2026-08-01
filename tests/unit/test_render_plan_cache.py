from __future__ import annotations

import unittest
from unittest import mock

import portable_resume.install.render as render_module
from portable_resume.build_identity import runtime_identity
from portable_resume.install.render import (
    _reset_plan_cache,
    materialize_plan,
    package_identity,
)


class RenderPlanCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_plan_cache()

    def tearDown(self) -> None:
        _reset_plan_cache()

    def test_repeated_calls_reuse_render_work_but_return_defensive_copies(self) -> None:
        with (
            mock.patch.object(
                render_module,
                "_iter_runtime_files",
                wraps=render_module._iter_runtime_files,
            ) as iter_runtime_files,
            mock.patch.object(
                render_module,
                "assert_identity_matches_package",
                wraps=render_module.assert_identity_matches_package,
            ) as assert_identity,
        ):
            first = materialize_plan("claude")
            second = materialize_plan("claude")

        self.assertEqual(iter_runtime_files.call_count, 1)
        self.assertEqual(assert_identity.call_count, 2)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)

        removed = next(iter(first))
        del first[removed]
        self.assertIn(removed, materialize_plan("claude"))

    def test_warm_cache_remains_host_invariant_and_validates_each_host(self) -> None:
        claude = materialize_plan("claude")
        qwen = materialize_plan("qwen")

        self.assertEqual(package_identity(claude), package_identity(qwen))
        with self.assertRaises(KeyError):
            materialize_plan("not-a-host")

    def test_distinct_resolved_identities_use_distinct_cache_entries(self) -> None:
        source_identity = runtime_identity()
        embedded_identity = dict(source_identity)
        embedded_identity["provenance"] = "embedded"

        with mock.patch.object(
            render_module,
            "_iter_runtime_files",
            wraps=render_module._iter_runtime_files,
        ) as iter_runtime_files:
            source_files = materialize_plan("claude", identity=source_identity)
            embedded_files = materialize_plan("claude", identity=embedded_identity)
            source_files_again = materialize_plan("qwen", identity=source_identity)

        self.assertEqual(iter_runtime_files.call_count, 2)
        self.assertEqual(source_files, source_files_again)
        self.assertNotEqual(package_identity(source_files), package_identity(embedded_files))


if __name__ == "__main__":
    unittest.main()
