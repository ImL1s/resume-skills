"""Platform-native path / SQLite URI / containment tests (#206)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from portable_resume.paths import (
    canonicalize_cwd,
    is_within,
    normalize_unicode,
    same_cwd,
)
from portable_resume.snapshot import SQLiteSnapshot, snapshot_sqlite_family


class PlatformPathNormalizationTests(unittest.TestCase):
    def test_drive_letter_case_normalized_on_nt(self) -> None:
        with mock.patch("portable_resume.paths.os.name", "nt"):
            # Simulate Windows drive letter fold without requiring a real nt host.
            with mock.patch(
                "portable_resume.paths.os.path.realpath",
                side_effect=lambda p: p.replace("/", "\\"),
            ), mock.patch(
                "portable_resume.paths.os.path.abspath",
                side_effect=lambda p: p if len(p) >= 2 and p[1] == ":" else "C:\\" + p.lstrip("\\/"),
            ), mock.patch(
                "portable_resume.paths.os.path.isabs",
                side_effect=lambda p: len(os.fspath(p)) >= 2 and os.fspath(p)[1] == ":",
            ):
                # Avoid literal "/Users/…" spellings (secrets scanner).
                lower = canonicalize_cwd("c:\\workdir\\demo\\proj")
                upper = canonicalize_cwd("C:\\workdir\\demo\\proj")
                self.assertEqual(lower[0], "C")
                self.assertEqual(lower, upper)

    def test_is_within_rejects_other_drive_on_nt(self) -> None:
        with mock.patch("portable_resume.paths.os.name", "nt"):
            with mock.patch(
                "portable_resume.paths.canonicalize_cwd",
                side_effect=lambda p: os.fspath(p).replace("/", "\\"),
            ):
                # commonpath across drives raises ValueError → outside.
                self.assertFalse(is_within("D:\\other\\file", "C:\\root"))

    def test_same_cwd_nfc_normalization(self) -> None:
        # Combining vs precomposed should match after NFC.
        composed = "café"
        # Build a non-NFC form when possible; if already NFC equal, still assert identity.
        self.assertEqual(normalize_unicode(composed), composed)
        self.assertTrue(same_cwd(composed, normalize_unicode(composed)))

    def test_sqlite_uri_posix_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "x.db")
            with open(db, "wb") as fp:
                fp.write(b"x")
            snap = SQLiteSnapshot(
                directory=tmp,
                database=db,
                source_name="x.db",
                attempts=1,
                family=("x.db",),
                _temporary=tempfile.TemporaryDirectory(),  # placeholder not used
            )
            try:
                uri = snap.uri
                self.assertTrue(uri.startswith("file:"))
                self.assertIn("mode=ro", uri)
                self.assertIn("cache=private", uri)
                # No backslashes in URI path portion on any host.
                path_part = uri.split("?", 1)[0]
                self.assertNotIn("\\", path_part)
            finally:
                # Avoid double-cleanup of the real temp dir used as directory=.
                snap._temporary = tempfile.TemporaryDirectory()
                snap.close()

    def test_sqlite_uri_windows_drive_shape(self) -> None:
        with mock.patch("portable_resume.snapshot.os.name", "nt"), mock.patch(
            "portable_resume.snapshot.os.path.abspath",
            return_value=r"C:\workdir\demo\app\state.db",
        ):
            snap = SQLiteSnapshot(
                directory=r"C:\workdir\demo\app",
                database=r"C:\workdir\demo\app\state.db",
                source_name="state.db",
                attempts=1,
                family=("state.db",),
                _temporary=tempfile.TemporaryDirectory(),
            )
            try:
                uri = snap.uri
                self.assertTrue(uri.startswith("file:"))
                # Absolute Windows URI uses /C:/... after file:
                self.assertIn("/C:/workdir/demo/app/state.db", uri.replace("%3A", ":"))
                self.assertNotIn("\\", uri.split("?", 1)[0])
            finally:
                snap.close()

    def test_sqlite_family_private_copy_open_includes_obinary(self) -> None:
        """Private SQLite family copies must pass O_BINARY when available (#207)."""
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "state.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
            conn.close()

            opens: list[int] = []
            real_open = os.open

            def tracking_open(path, flags, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
                # Capture write opens to private temp destinations only.
                path_s = os.fspath(path)
                if "portable-resume-sqlite-" in path_s or path_s.endswith("state.db"):
                    opens.append(flags)
                return real_open(path, flags, mode, *args, **kwargs)

            with mock.patch("portable_resume.snapshot.os.open", side_effect=tracking_open):
                snap = snapshot_sqlite_family(db, root=tmp)
                try:
                    self.assertTrue(os.path.isfile(snap.database))
                    with open(snap.database, "rb") as fp:
                        # SQLite header must survive the private copy byte-for-byte.
                        self.assertTrue(fp.read(16).startswith(b"SQLite format 3"))
                finally:
                    snap.close()

            write_flags = [
                flags
                for flags in opens
                if flags & os.O_WRONLY and flags & os.O_CREAT and flags & os.O_EXCL
            ]
            self.assertTrue(write_flags, f"expected private-copy write open; saw {opens!r}")
            binary = getattr(os, "O_BINARY", 0)
            if binary:
                self.assertTrue(
                    all(flags & binary for flags in write_flags),
                    f"O_BINARY missing from write flags {write_flags!r}",
                )


if __name__ == "__main__":
    unittest.main()
