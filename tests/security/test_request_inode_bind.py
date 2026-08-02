"""TOCTOU / inode-binding regressions for portable-resume/request-v1 (#62)."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.bounds import DEFAULT_BOUNDS
from portable_resume.diagnostics import DiagnosticError
from portable_resume.request import load_request
import portable_resume.request as request_module


class RequestInodeBindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.path = self.root / "request.json"
        self.addCleanup(self._clear_hook)

    def _clear_hook(self) -> None:
        request_module._request_read_hook = None

    def valid_payload(self, *, ref: str = "latest", source: str = "claude") -> dict[str, str]:
        return {
            "schema_version": "portable-resume/request-v1",
            "source": source,
            "action": "show",
            "resume_ref": ref,
            "cwd": str(self.cwd),
        }

    def write_request(self, payload: object | None = None, *, path: Path | None = None, raw: bytes | None = None) -> Path:
        target = path or self.path
        if raw is not None:
            target.write_bytes(raw)
        else:
            target.write_text(json.dumps(payload if payload is not None else self.valid_payload()), encoding="utf-8")
        return target

    def load(self, path: Path | None = None) -> object:
        return load_request(str(path or self.path), expected_source="claude")

    def test_unchanged_regular_request_succeeds(self) -> None:
        self.write_request()
        request = self.load()
        self.assertEqual(request.resume_ref, "latest")
        self.assertEqual(request.cwd, str(self.cwd))
        self.assertEqual(request.source, "claude")

    def test_preopen_path_swap_opens_whatever_is_present_atomically(self) -> None:
        """Open is the atomic point: a completed pre-open swap is just path B."""

        self.write_request(self.valid_payload(ref="original"))
        replacement = self.root / "replacement.json"
        self.write_request(self.valid_payload(ref="swapped"), path=replacement)

        def hook(stage: str, path: str) -> None:
            if stage == "after-precheck":
                os.replace(replacement, path)

        request_module._request_read_hook = hook
        request = self.load()
        self.assertEqual(request.resume_ref, "swapped")

    def test_path_swap_after_open_rejected_via_final_lstat(self) -> None:
        self.write_request(self.valid_payload(ref="A"))
        other = self.root / "B.json"
        self.write_request(self.valid_payload(ref="B"), path=other)

        def hook(stage: str, path: str) -> None:
            if stage == "after-open":
                os.replace(other, path)

        request_module._request_read_hook = hook
        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_regular_replaced_by_symlink_before_open_rejected(self) -> None:
        self.write_request()
        target = self.root / "outside.json"
        self.write_request(self.valid_payload(ref="via-symlink"), path=target)

        def hook(stage: str, path: str) -> None:
            if stage == "after-precheck":
                Path(path).unlink()
                Path(path).symlink_to(target)

        request_module._request_read_hook = hook
        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_initial_symlink_rejected_even_if_later_becomes_regular(self) -> None:
        real = self.root / "real.json"
        self.write_request(path=real)
        self.path.symlink_to(real)

        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_deleted_and_recreated_after_open_rejected(self) -> None:
        self.write_request(self.valid_payload(ref="aaaaaa"))
        payload = json.dumps(self.valid_payload(ref="bbbbbb")).encode("utf-8")

        def hook(stage: str, path: str) -> None:
            if stage == "after-open":
                Path(path).unlink()
                Path(path).write_bytes(payload)

        request_module._request_read_hook = hook
        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_inplace_content_change_with_stable_inode_detected(self) -> None:
        self.write_request(self.valid_payload(ref="before"))
        mutated = json.dumps(self.valid_payload(ref="after-mutate")).encode("utf-8")

        def hook(stage: str, path: str) -> None:
            if stage == "after-read":
                # Grow/shrink so size/mtime change is visible on the same inode.
                Path(path).write_bytes(mutated + b"\n")

        request_module._request_read_hook = hook
        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_same_stat_content_mutation_detected_by_second_read(self) -> None:
        original = json.dumps(self.valid_payload(ref="aaaa")).encode("utf-8")
        spoofed = json.dumps(self.valid_payload(ref="bbbb")).encode("utf-8")
        self.assertEqual(len(original), len(spoofed))
        self.path.write_bytes(original)
        st = self.path.stat()

        def hook(stage: str, path: str) -> None:
            if stage == "after-read":
                Path(path).write_bytes(spoofed)
                os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))

        request_module._request_read_hook = hook
        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_final_pathname_replacement_after_read_detected(self) -> None:
        self.write_request(self.valid_payload(ref="primary"))
        other = self.root / "other.json"
        self.write_request(self.valid_payload(ref="other"), path=other)

        def hook(stage: str, path: str) -> None:
            if stage == "before-final":
                os.replace(other, path)

        request_module._request_read_hook = hook
        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")

    def test_oversize_replacement_rejected_before_json_parse(self) -> None:
        self.write_request()
        oversize = self.root / "big.json"
        oversize.write_bytes(b"{" + b" " * (DEFAULT_BOUNDS.request_bytes + 8) + b"}")

        parse_calls: list[object] = []
        real_loads = json.loads

        def tracked_loads(text: str, *args: object, **kwargs: object) -> object:
            parse_calls.append(text[:32])
            return real_loads(text, *args, **kwargs)

        def hook(stage: str, path: str) -> None:
            if stage == "after-precheck":
                os.replace(oversize, path)

        request_module._request_read_hook = hook
        with mock.patch("portable_resume.request.json.loads", side_effect=tracked_loads):
            with self.assertRaises(DiagnosticError) as caught:
                self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        self.assertEqual(parse_calls, [])

    def test_failed_attempt_bytes_never_reach_json_loads(self) -> None:
        self.write_request(self.valid_payload(ref="kept"))
        hostile = self.root / "hostile.json"
        self.write_request(self.valid_payload(ref="LEAK-ME-REF"), path=hostile)
        seen: list[str] = []

        def tracked_loads(text: str, *args: object, **kwargs: object) -> object:
            seen.append(text)
            return json.JSONDecoder().decode(text)

        def hook(stage: str, path: str) -> None:
            if stage == "after-open":
                os.replace(hostile, path)

        request_module._request_read_hook = hook
        with mock.patch("portable_resume.request.json.loads", side_effect=tracked_loads):
            with self.assertRaises(DiagnosticError):
                self.load()
        # Failed attempt must not parse hostile path contents.
        self.assertEqual(seen, [])
        self.assertNotIn("LEAK-ME-REF", "".join(seen))

    def test_diagnostics_do_not_leak_request_content_or_cwd(self) -> None:
        secret_cwd = self.root / "secret-project-path"
        secret_cwd.mkdir()
        payload = self.valid_payload(ref="SECRET-REF-VALUE")
        payload["cwd"] = str(secret_cwd)
        self.write_request(payload)
        other = self.root / "alt.json"
        alt = self.valid_payload(ref="OTHER-SECRET")
        alt["cwd"] = str(secret_cwd)
        self.write_request(alt, path=other)

        def hook(stage: str, path: str) -> None:
            if stage == "after-open":
                os.replace(other, path)

        request_module._request_read_hook = hook
        with self.assertRaises(DiagnosticError) as caught:
            load_request(str(self.path), expected_source="claude")
        text = str(caught.exception)
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        self.assertNotIn("SECRET-REF-VALUE", text)
        self.assertNotIn("OTHER-SECRET", text)
        self.assertNotIn(str(secret_cwd), text)
        self.assertNotIn("secret-project-path", text)

    def test_schema_mismatch_still_content_free(self) -> None:
        self.write_request({**self.valid_payload(), "schema_version": "portable-resume/request-v2"})
        with self.assertRaises(DiagnosticError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        self.assertNotIn("request-v2", str(caught.exception))

    def test_without_dirfd_uses_backend_stable_read(self) -> None:
        """When dir_fd/O_NOFOLLOW is unavailable, platform_fs backend path is used."""
        self.write_request()
        with mock.patch.object(request_module, "_symlink_safe_request_open_supported", return_value=False):
            request = self.load()
        self.assertEqual(request.resume_ref, "latest")
        self.assertEqual(request.source, "claude")

    def test_without_dirfd_and_without_backend_nofollow_fails_closed(self) -> None:
        """No dir_fd and no backend nofollow capability must still fail closed."""
        from portable_resume.platform_fs import get_filesystem_backend
        from portable_resume.platform_fs.select import _reset_backend_cache

        self.write_request()
        backend = get_filesystem_backend()
        caps = backend.capabilities
        frozen = type(caps)(
            descriptor_relative=caps.descriptor_relative,
            nofollow_reads=False,
            relative_mutations=caps.relative_mutations,
            sqlite_snapshots=caps.sqlite_snapshots,
            atomic_output=caps.atomic_output,
            exclusive_locking=caps.exclusive_locking,
            reparse_points=caps.reparse_points,
            handle_locking=caps.handle_locking,
        )
        with mock.patch.object(request_module, "_symlink_safe_request_open_supported", return_value=False):
            with mock.patch.object(type(backend), "capabilities", new_callable=lambda: property(lambda self: frozen)):
                _reset_backend_cache()
                # Force the same backend instance with patched capabilities.
                with mock.patch(
                    "portable_resume.platform_fs.get_filesystem_backend",
                    return_value=backend,
                ), mock.patch.object(
                    type(backend),
                    "capabilities",
                    property(lambda self: frozen),
                ):
                    with self.assertRaises(DiagnosticError) as caught:
                        self.load()
        self.assertEqual(caught.exception.code, "E_INVALID_INPUT")
        _reset_backend_cache()

    def test_fingerprint_identity_tuple_is_dev_ino_type(self) -> None:
        self.write_request()
        st = os.lstat(self.path)
        fp = request_module._fingerprint(st)
        self.assertEqual(fp.device, st.st_dev)
        self.assertEqual(fp.inode, st.st_ino)
        self.assertEqual(fp.mode, st.st_mode)
        self.assertTrue(stat.S_ISREG(fp.mode))


if __name__ == "__main__":
    unittest.main()
