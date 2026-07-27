from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import _collect_scanned_lines, stable_scan_lines


class StableScanLinesTests(unittest.TestCase):
    def test_streams_lines_without_loading_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text('{"id":1}\n{"id":2}\n{"id":3}\n', encoding="utf-8")
            budget = ReadBudget()
            lines = list(stable_scan_lines(str(path), root=str(root), budget=budget))
            self.assertEqual(len(lines), 3)
            self.assertTrue(all(isinstance(item.text, str) for item in lines))
            self.assertGreater(budget.bytes_read, 0)

    def test_stops_at_transcript_record_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "big.jsonl"
            path.write_text('{"n":1}\n' * 5, encoding="utf-8")
            tight = Bounds(transcript_records=3, scanned_records=3)
            budget = ReadBudget(limits=tight)
            with self.assertRaises(DiagnosticError):
                list(
                    stable_scan_lines(
                        str(path),
                        root=str(root),
                        budget=budget,
                        charge_transcript=True,
                    )
                )

    def test_oversize_line_without_newline_raises_limit_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "huge.jsonl"
            path.write_bytes(b"x" * 32)
            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_lines(
                        str(path),
                        root=str(root),
                        max_line_bytes=16,
                    )
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_invalid_utf8_raises_corrupt_record(self) -> None:
        for payload in (b"\xff\n", b'{"content":"\xff'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "bad.jsonl"
                path.write_bytes(payload)
                with self.assertRaises(DiagnosticError) as caught:
                    list(stable_scan_lines(str(path), root=str(root)))
                self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_unterminated_incomplete_utf8_is_marked_as_a_partial_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "partial.jsonl"
            path.write_bytes(b'{"content":"\xe4\xb8')
            lines = list(stable_scan_lines(str(path), root=str(root)))
            self.assertEqual(len(lines), 1)
            self.assertFalse(lines[0].terminated)
            self.assertFalse(lines[0].utf8_valid)

    def test_same_size_mtime_spoof_is_detected_by_second_content_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "record.jsonl"
            path.write_bytes(b"aaaa\n")
            original = path.stat().st_mtime_ns

            def hook(stage: str, attempt: int, _: str) -> None:
                if stage == "after-read":
                    path.write_bytes(b"bbbb\n" if attempt % 2 else b"aaaa\n")
                    os.utime(path, ns=(original, original))

            with self.assertRaises(DiagnosticError) as caught:
                list(stable_scan_lines(str(path), root=str(root), hook=hook))
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
            self.assertEqual(caught.exception.attempts, 3)

    def test_symlink_escape_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "store"
            store.mkdir()
            outside = root / "outside.jsonl"
            outside.write_text("secret\n", encoding="utf-8")
            link = store / "link.jsonl"
            link.symlink_to(outside)
            with self.assertRaises(DiagnosticError) as caught:
                list(stable_scan_lines(str(link), root=str(store)))
            self.assertEqual(caught.exception.code, "E_UNSAFE_PATH")

    def test_final_line_without_trailing_newline_is_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text('{"id":1}\n{"id":2}', encoding="utf-8")
            lines = list(stable_scan_lines(str(path), root=str(root)))
            self.assertEqual([item.text for item in lines], ['{"id":1}', '{"id":2}'])

    def test_crlf_lines_strip_carriage_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_bytes(b'{"id":1}\r\n{"id":2}\r\n')
            lines = list(stable_scan_lines(str(path), root=str(root)))
            self.assertEqual([item.text for item in lines], ['{"id":1}', '{"id":2}'])

    def test_pending_cr_at_max_line_bytes_waits_for_newline(self) -> None:
        max_line = 8
        payload = b"x" * max_line + b"\r"
        chunks = [payload, b"\n"]

        chunk_iter = iter(chunks)

        def mock_read(_fd: int, _size: int) -> bytes:
            try:
                return next(chunk_iter)
            except StopIteration:
                return b""
        with mock.patch("os.read", side_effect=mock_read):
            collected, _, _, _ = _collect_scanned_lines(
                0,
                max_line_bytes=max_line,
                budget=None,
                charge_transcript=False,
            )
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0].text, "x" * max_line)
        self.assertTrue(collected[0].terminated)

    def test_crlf_exact_max_line_bytes_matches_lf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "edge.jsonl"
            payload = b"x" * 8
            path.write_bytes(payload + b"\r\n")
            lines = list(stable_scan_lines(str(path), root=str(root), max_line_bytes=8))
            self.assertEqual([item.text for item in lines], ["x" * 8])

    def test_default_budget_bounds_record_count_when_budget_omitted(self) -> None:
        from portable_resume.bounds import DEFAULT_BOUNDS

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "many.jsonl"
            # Exceed scanned_records with tiny lines while staying under byte cap.
            count = DEFAULT_BOUNDS.scanned_records + 5
            path.write_text("\n".join('{"n":%d}' % i for i in range(count)) + "\n", encoding="utf-8")
            with self.assertRaises(DiagnosticError) as caught:
                list(stable_scan_lines(str(path), root=str(root)))
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_termination_metadata_distinguishes_eof_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text('{"id":1}\n{"id":2}', encoding="utf-8")
            lines = list(stable_scan_lines(str(path), root=str(root)))
            self.assertTrue(lines[0].terminated)
            self.assertFalse(lines[1].terminated)

    def test_scan_honors_lower_record_bytes_without_explicit_max(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text("abcdef\n", encoding="utf-8")
            budget = ReadBudget(limits=Bounds(record_bytes=4))
            with self.assertRaises(DiagnosticError) as caught:
                list(stable_scan_lines(str(path), root=str(root), budget=budget))
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_explicit_max_cannot_exceed_budget_record_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text("abcdef\n", encoding="utf-8")
            budget = ReadBudget(limits=Bounds(record_bytes=4))
            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_lines(
                        str(path),
                        root=str(root),
                        budget=budget,
                        max_line_bytes=64,
                    )
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_scan_honors_lower_snapshot_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "record.jsonl"
            path.write_bytes(b"aaaa\n")
            original = path.stat().st_mtime_ns
            budget = ReadBudget(limits=Bounds(snapshot_attempts=1))

            def hook(stage: str, attempt: int, _: str) -> None:
                if stage == "after-read":
                    path.write_bytes(b"bbbb\n")
                    os.utime(path, ns=(original, original))

            with self.assertRaises(DiagnosticError) as caught:
                list(stable_scan_lines(str(path), root=str(root), budget=budget, hook=hook))
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")
            self.assertEqual(caught.exception.attempts, 1)


if __name__ == "__main__":
    unittest.main()
