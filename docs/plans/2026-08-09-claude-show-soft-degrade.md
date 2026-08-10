# Claude Show Soft-Degrade for Oversized Sessions (#258) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `resume-claude show` soft-degrade with `W_TRUNCATED`/`W_BROKEN_CHAIN` warnings instead of hard-failing with `E_LIMIT_EXCEEDED` when a discoverable Claude session exceeds `source_read_bytes` or `transcript_records`, while keeping hard failure for true unsafe/corrupt cases.

**Architecture:** Add a shared end-anchored `stable_scan_tail_lines` primitive in `snapshot.py` that verifies and admits only the final `source_read_bytes` window of a JSONL (no whole-file hashing). Claude discovery (`_metadata_windows`) relaxes `require_size_within_max` and emits `W_TRUNCATED` for oversized files. Claude `show` catches `E_LIMIT_EXCEEDED` from the full-graph path and falls back to a bounded suffix graph built from the tail scanner, mirrored into a private temp file so the existing lineage/turn assembly is reused unchanged.

**Tech Stack:** Python 3.11+ stdlib-only; unittest (no pytest); `PYTHONPATH=src` for module runs. Product runtime must stay stdlib-only (no new deps).

**Repo commands (verify at every step):**
```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_tail_lines -v
PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_tail_overflow -v
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
```

**Files touched:**
- `src/portable_resume/snapshot.py` — `_collect_scanned_lines` params, `_hash_descriptor_window`, `stable_scan_tail_lines`
- `src/portable_resume/adapters/claude.py` — `_metadata_windows`, `show` fallback, `_build_tail_graph`, `_assemble_from_index`
- `tests/unit/test_stable_scan_tail_lines.py` — NEW
- `tests/adapters/test_claude_tail_overflow.py` — NEW
- `tests/adapters/test_claude_codex_cursor.py` — update ONE test to new contract (Task 5)

---

### Task 1: Add `discard_first_line` + `enforce_record_budget` params to `_collect_scanned_lines`

**Files:**
- Modify: `src/portable_resume/snapshot.py:466-598` (`_collect_scanned_lines`)
- Test: `tests/unit/test_stable_scan_tail_lines.py` (NEW file, shared for Tasks 1-3)

**Step 1: Write the failing tests**

Create `tests/unit/test_stable_scan_tail_lines.py`:

```python
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.snapshot import _collect_scanned_lines, stable_scan_tail_lines


class CollectScannedTailParamsTests(unittest.TestCase):
    def _descriptor(self, payload: bytes) -> tuple[int, Path]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jsonl"
            path.write_bytes(payload)
            descriptor = os.open(str(path), os.O_RDONLY)
            self.addCleanup(os.close, descriptor)
            return descriptor, path

    def test_discard_first_line_skips_partial_window_head(self) -> None:
        descriptor, _path = self._descriptor(b'{"a":1}\n{"b":2}\n')
        os.lseek(descriptor, 3, os.SEEK_SET)  # mid-line inside {"a":1}
        lines, pending_bytes, pending_records, _ = _collect_scanned_lines(
            descriptor,
            max_line_bytes=1024,
            budget=None,
            charge_transcript=False,
            discard_first_line=True,
        )
        self.assertEqual([line.text for line in lines], ['{"b":2}'])
        self.assertEqual(pending_records, 1)
        self.assertGreater(pending_bytes, 0)

    def test_without_discard_first_line_keeps_complete_first_line(self) -> None:
        descriptor, _path = self._descriptor(b'{"a":1}\n{"b":2}\n')
        os.lseek(descriptor, 7, os.SEEK_SET)  # exactly at the boundary after \n
        lines, _b, pending_records, _ = _collect_scanned_lines(
            descriptor,
            max_line_bytes=1024,
            budget=None,
            charge_transcript=False,
            discard_first_line=False,
        )
        self.assertEqual([line.text for line in lines], ['{"b":2}'])
        self.assertEqual(pending_records, 1)

    def test_enforce_record_budget_false_counts_without_charging(self) -> None:
        descriptor, _path = self._descriptor(b'{"n":1}\n' * 5)
        budget = ReadBudget(Bounds(scanned_records=2, transcript_records=2))
        lines, _b, pending_records, _ = _collect_scanned_lines(
            descriptor,
            max_line_bytes=1024,
            budget=budget,
            charge_transcript=False,
            enforce_record_budget=False,
        )
        self.assertEqual(len(lines), 5)
        self.assertEqual(pending_records, 5)
        self.assertEqual(budget.records, 0)
        self.assertEqual(budget.transcript_records_read, 0)

    def test_enforce_record_budget_true_still_raises_limit(self) -> None:
        descriptor, _path = self._descriptor(b'{"n":1}\n' * 5)
        budget = ReadBudget(Bounds(scanned_records=2, transcript_records=2))
        with self.assertRaises(DiagnosticError) as caught:
            _collect_scanned_lines(
                descriptor,
                max_line_bytes=1024,
                budget=budget,
                charge_transcript=False,
                enforce_record_budget=True,
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_tail_lines.CollectScannedTailParamsTests -v`
Expected: FAIL with `TypeError: _collect_scanned_lines() got an unexpected keyword argument 'discard_first_line'`

**Step 3: Implement the params**

In `src/portable_resume/snapshot.py`, change the `_collect_scanned_lines` signature (line 466):

```python
def _collect_scanned_lines(
    descriptor: int,
    *,
    max_line_bytes: int,
    budget: ReadBudget | None,
    charge_transcript: bool,
    spool: BinaryIO | None = None,
    discard_first_line: bool = False,
    enforce_record_budget: bool = True,
) -> tuple[list[ScannedLine] | None, int, int, str]:
```

Change `check_record_budget` (lines 500-513) to no-op when enforcement is off:

```python
    def check_record_budget() -> None:
        if budget is None or not enforce_record_budget:
            return
        if charge_transcript:
            maximum = min(
                budget.limits.transcript_records,
                DEFAULT_BOUNDS.transcript_records,
            )
            current = budget.transcript_records_read
        else:
            maximum = min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records)
            current = budget.records
        if current + pending_records + 1 > maximum:
            raise DiagnosticError.limit_exceeded()
```

In `drain_complete_lines` (lines 531-561), skip decode/emit/count for the first line when `discard_first_line` (bytes still advance and count):

```python
    def drain_complete_lines() -> None:
        nonlocal absolute_offset, pending_records
        while True:
            newline_index = buffer.find(b"\n")
            if newline_index < 0:
                reject_oversize_unterminated_line()
                return
            line_bytes = bytes(buffer[: newline_index + 1])
            del buffer[: newline_index + 1]
            # Exclude LF and optional CR from the content-length budget so CRLF
            # and LF records with the same decoded text share the same ceiling.
            payload = line_bytes[:-1]
            if payload.endswith(b"\r"):
                payload = payload[:-1]
            if len(payload) > max_line_bytes:
                raise DiagnosticError.limit_exceeded()
            check_record_budget()
            if discard_first_line and line_ordinal == 0:
                absolute_offset += len(line_bytes)
                continue
            pending_records += 1
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise DiagnosticError("E_CORRUPT_RECORD") from error
            emit(
                ScannedLine(
                    ordinal=line_ordinal,
                    text=text,
                    byte_offset=absolute_offset,
                    terminated=True,
                )
            )
            absolute_offset += len(line_bytes)
```

In the final-buffer block (lines 578-597), skip when the only line is the discarded first line:

```python
    if buffer:
        check_record_budget()
        if not (discard_first_line and line_ordinal == 0):
            pending_records += 1
            utf8_valid = True
            try:
                text = bytes(buffer).decode("utf-8").removesuffix("\r")
            except UnicodeDecodeError as error:
                if error.reason != "unexpected end of data" or error.end != len(buffer):
                    raise DiagnosticError("E_CORRUPT_RECORD") from error
                text = bytes(buffer).decode("utf-8", errors="replace").removesuffix("\r")
                utf8_valid = False
            emit(
                ScannedLine(
                    ordinal=line_ordinal,
                    text=text,
                    byte_offset=absolute_offset,
                    terminated=False,
                    utf8_valid=utf8_valid,
                )
            )
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_tail_lines -v`
Expected: PASS (4 tests in `CollectScannedTailParamsTests`; `StableScanTailLinesTests` does not exist yet)

**Step 5: Commit**

```bash
git add src/portable_resume/snapshot.py tests/unit/test_stable_scan_tail_lines.py
git commit -m "test(snapshot): collect scanned tail lines with partial-head discard and uncapped record counting"
```

---

### Task 2: Add `_hash_descriptor_window` helper

**Files:**
- Modify: `src/portable_resume/snapshot.py` (next to `_hash_descriptor` at line 1038)
- Test: `tests/unit/test_stable_scan_tail_lines.py`

**Step 1: Write the failing test**

Append to `tests/unit/test_stable_scan_tail_lines.py`:

```python
from portable_resume.snapshot import _hash_descriptor_window


class HashDescriptorWindowTests(unittest.TestCase):
    def test_hashes_only_the_requested_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.jsonl"
            path.write_bytes(b"AAAA\nBBBB\nCCCC\n")
            descriptor = os.open(str(path), os.O_RDONLY)
            self.addCleanup(os.close, descriptor)
            digest, total = _hash_descriptor_window(descriptor, start=6, maximum=1024)
            self.assertEqual(total, 5)  # "BBBB\n"
            self.assertEqual(digest, __import__("hashlib").sha256(b"BBBB\n").hexdigest())

    def test_window_over_maximum_raises_limit_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.jsonl"
            path.write_bytes(b"ABCDEF")
            descriptor = os.open(str(path), os.O_RDONLY)
            self.addCleanup(os.close, descriptor)
            with self.assertRaises(DiagnosticError) as caught:
                _hash_descriptor_window(descriptor, start=0, maximum=3)
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_tail_lines.HashDescriptorWindowTests -v`
Expected: FAIL with `ImportError: cannot import name '_hash_descriptor_window'`

**Step 3: Implement**

Add after `_hash_descriptor` (line 1050):

```python
def _hash_descriptor_window(descriptor: int, *, start: int, maximum: int) -> tuple[str, int]:
    """SHA-256 of one bounded ``[start, EOF)`` window (no whole-file hash).

    Used by the end-anchored tail scanner (#258) so verification never reads
    bytes before ``start`` (a multi-GB file must not be hashed in full).
    """

    os.lseek(descriptor, start, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        block = os.read(descriptor, 64 * 1024)
        if not block:
            break
        total += len(block)
        if total > maximum:
            raise DiagnosticError.limit_exceeded()
        digest.update(block)
    return digest.hexdigest(), total
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_tail_lines -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add src/portable_resume/snapshot.py tests/unit/test_stable_scan_tail_lines.py
git commit -m "test(snapshot): hash only a bounded end-anchored descriptor window"
```

---

### Task 3: Implement `stable_scan_tail_lines`

**Files:**
- Modify: `src/portable_resume/snapshot.py` (insert after `stable_scan_lines`, i.e. after line 718)
- Test: `tests/unit/test_stable_scan_tail_lines.py`

**Step 1: Write the failing tests**

Append to `tests/unit/test_stable_scan_tail_lines.py`:

```python
class StableScanTailLinesTests(unittest.TestCase):
    def test_whole_file_when_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session.jsonl"
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(10)), encoding="utf-8")
            budget = ReadBudget(Bounds(transcript_records=100, scanned_records=100))
            lines = list(
                stable_scan_tail_lines(
                    str(path), root=str(root), budget=budget, charge_transcript=True
                )
            )
            self.assertEqual(len(lines), 10)
            self.assertEqual(lines[0].text, '{"n":0}')
            self.assertEqual(lines[-1].text, '{"n":9}')

    def test_admits_only_tail_window_when_file_exceeds_source_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "big.jsonl"
            # 9 bytes per line; 200 lines = 1800 bytes total.
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(200)), encoding="utf-8")
            tight = Bounds(
                source_read_bytes=512,
                transcript_records=5_000,
                scanned_records=5_000,
            )
            budget = ReadBudget(limits=tight)
            admitted = list(
                stable_scan_tail_lines(
                    str(path), root=str(root), budget=budget, charge_transcript=True
                )
            )
            self.assertGreater(len(admitted), 0)
            self.assertLess(len(admitted), 200)
            # tail_start = 1800-512 = 1288 is mid-line (line 143), which is
            # discarded; the first admitted line is the next complete one.
            self.assertEqual(admitted[0].text, '{"n":144}')
            self.assertEqual(admitted[-1].text, '{"n":199}')
            self.assertLessEqual(budget.bytes_read, 512)

    def test_trims_oldest_records_to_transcript_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "many.jsonl"
            path.write_text("".join(f'{{"n":{i}}}\n' for i in range(10)), encoding="utf-8")
            budget = ReadBudget(Bounds(transcript_records=3, scanned_records=100))
            lines = list(
                stable_scan_tail_lines(
                    str(path), root=str(root), budget=budget, charge_transcript=True
                )
            )
            self.assertEqual([line.text for line in lines], ['{"n":7}', '{"n":8}', '{"n":9}'])
            self.assertEqual(budget.transcript_records_read, 3)

    def test_interior_corruption_raises_corrupt_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "bad.jsonl"
            path.write_bytes(b'{"n":1}\n{"n":2}\xff\xfe\n{"n":3}\n')
            with self.assertRaises(DiagnosticError) as caught:
                list(stable_scan_tail_lines(str(path), root=str(root)))
            self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_oversize_line_raises_limit_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "huge.jsonl"
            path.write_bytes(b'{"n":1}\n' + b"x" * 32 + b"\n")
            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_tail_lines(
                        str(path), root=str(root), max_line_bytes=16
                    )
                )
            self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_mutation_during_attempt_retries_then_source_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "mut.jsonl"
            path.write_text('{"n":1}\n' * 10, encoding="utf-8")
            budget = ReadBudget(Bounds(transcript_records=100, scanned_records=100))

            def mutate(_stage: str, _attempt: int, _safe: str) -> None:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write('{"n":99}\n')

            with self.assertRaises(DiagnosticError) as caught:
                list(
                    stable_scan_tail_lines(
                        str(path),
                        root=str(root),
                        budget=budget,
                        charge_transcript=True,
                        hook=mutate,
                    )
                )
            self.assertEqual(caught.exception.code, "E_SOURCE_BUSY")

    def test_source_tree_byte_for_byte_unchanged(self) -> None:
        from tests.helpers.core import tree_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "stable.jsonl"
            path.write_text('{"n":1}\n' * 20, encoding="utf-8")
            before = tree_snapshot(str(root))
            list(stable_scan_tail_lines(str(path), root=str(root)))
            self.assertEqual(tree_snapshot(str(root)), before)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_tail_lines.StableScanTailLinesTests -v`
Expected: FAIL with `ImportError: cannot import name 'stable_scan_tail_lines'`

**Step 3: Implement**

Insert after `stable_scan_lines` (after line 718):

```python
def stable_scan_tail_lines(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    budget: ReadBudget | None = None,
    max_line_bytes: int | None = None,
    charge_transcript: bool = False,
    hook: AttemptHook | None = None,
) -> Iterator[ScannedLine]:
    """Yield UTF-8 lines from a stable end-anchored window (#258).

    Same no-follow / containment / attempt-verification rules as
    ``stable_scan_lines``, but when the file exceeds the remaining
    ``source_read_bytes`` budget the scanner admits only the final
    ``remaining`` bytes (``tail_start = st_size - remaining``) instead of
    hard-failing. The first line is discarded when the window begins
    mid-record. After verification the admitted line count is trimmed to the
    remaining ``transcript_records`` (or ``scanned_records`` when
    ``charge_transcript`` is false), charging only the admitted records and
    the unique window bytes. The whole file is never hashed or buffered.
    """

    effective_budget = budget if budget is not None else ReadBudget()
    budget_line_cap = min(
        effective_budget.limits.record_bytes,
        DEFAULT_BOUNDS.record_bytes,
    )
    if max_line_bytes is None:
        line_limit = budget_line_cap
    else:
        if max_line_bytes < 0:
            raise DiagnosticError.invalid()
        line_limit = min(max_line_bytes, budget_line_cap)
    max_file_bytes = min(
        DEFAULT_BOUNDS.source_read_bytes,
        effective_budget.limits.source_read_bytes,
    )
    safe, base = require_regular_no_symlinks(path, root)
    parent = os.path.dirname(safe)
    basename = os.path.basename(safe)
    attempts = min(
        effective_budget.limits.snapshot_attempts,
        DEFAULT_BOUNDS.snapshot_attempts,
    )
    if attempts < 1:
        raise DiagnosticError.invalid()
    for attempt in range(1, attempts + 1):
        before_entry = _target_entry_fingerprint(parent, basename, root=base)
        descriptor = _open_no_follow(safe, base)
        spool: tempfile.SpooledTemporaryFile | None = None
        verified_spool: tempfile.SpooledTemporaryFile | None = None
        pending_bytes = 0
        pending_records = 0
        tail_start = 0
        try:
            before_stat = os.fstat(descriptor)
            if not _entry_identity_matches(before_entry, before_stat):
                continue
            remaining = max(0, max_file_bytes - effective_budget.bytes_read)
            tail_start = max(0, before_stat.st_size - remaining)
            starts_mid_line = False
            if tail_start > 0:
                os.lseek(descriptor, tail_start - 1, os.SEEK_SET)
                probe = os.read(descriptor, 1)
                starts_mid_line = probe != b"\n"
            if hook:
                hook("before-read", attempt, safe)
            os.lseek(descriptor, tail_start, os.SEEK_SET)
            spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_RAM_CAP, mode="w+b")
            try:
                _list, pending_bytes, pending_records, content_hash = _collect_scanned_lines(
                    descriptor,
                    max_line_bytes=line_limit,
                    budget=effective_budget,
                    charge_transcript=False,
                    spool=spool,
                    discard_first_line=starts_mid_line,
                    enforce_record_budget=False,
                )
            except DiagnosticError as error:
                # File grew past the admitted window mid-read: unstable, retry.
                if (
                    error.code == "E_LIMIT_EXCEEDED"
                    and os.fstat(descriptor).st_size > before_stat.st_size
                ):
                    continue
                raise
            observed = _fingerprint(before_stat, content_hash)
            if hook:
                hook("after-read", attempt, safe)
            verified_hash, verified_size = _hash_descriptor_window(
                descriptor,
                start=tail_start,
                maximum=max_file_bytes,
            )
            verified = _fingerprint(os.fstat(descriptor), verified_hash)
            if hook:
                hook("after-verify-read", attempt, safe)
            middle_entry = _target_entry_fingerprint(parent, basename, root=base)
            final_hash, final_size = _hash_descriptor_window(
                descriptor,
                start=tail_start,
                maximum=max_file_bytes,
            )
            final_stat = os.fstat(descriptor)
            final = _fingerprint(final_stat, final_hash)
            after_entry = _target_entry_fingerprint(parent, basename, root=base)
            if not (
                observed == verified == final
                and before_entry == middle_entry == after_entry
                and _entry_identity_matches(before_entry, before_stat)
                and _entry_identity_matches(after_entry, final_stat)
                and pending_bytes == verified_size == final_size
                == before_stat.st_size - tail_start
            ):
                continue
            # Hand off spool for post-close replay so the source fd is never
            # held open while yielding to callers.
            verified_spool = spool
            spool = None
        finally:
            os.close(descriptor)
            if spool is not None:
                spool.close()
        if verified_spool is not None:
            effective_budget.consume_bytes(pending_bytes)
            if charge_transcript:
                record_max = min(
                    effective_budget.limits.transcript_records,
                    DEFAULT_BOUNDS.transcript_records,
                )
                remaining_records = record_max - effective_budget.transcript_records_read
            else:
                record_max = min(
                    effective_budget.limits.scanned_records,
                    DEFAULT_BOUNDS.scanned_records,
                )
                remaining_records = record_max - effective_budget.records
            skip = max(0, pending_records - remaining_records)
            admitted = pending_records - skip
            if charge_transcript:
                effective_budget.consume_transcript_records(admitted)
            else:
                effective_budget.consume_records(admitted)
            try:
                verified_spool.seek(0)
                for line in _spool_iter_lines(verified_spool):
                    if skip > 0:
                        skip -= 1
                        continue
                    yield line
            finally:
                verified_spool.close()
            return
    family = (os.path.basename(safe),)
    raise DiagnosticError.source_busy(attempts=attempts, family=family)
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_tail_lines -v`
Expected: PASS (13 tests: 4 params + 2 hash-window + 7 tail-scan)

Then run the existing scanner suite to confirm no regression:
`PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_lines -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/portable_resume/snapshot.py tests/unit/test_stable_scan_tail_lines.py
git commit -m "feat(snapshot): stable end-anchored tail line scanner for oversized sessions"
```

---


---

### Task 4: Claude discovery soft-degrades oversized files (`_metadata_windows`)

**Files:**
- Modify: `src/portable_resume/adapters/claude.py:33,662-712`
- Test: `tests/adapters/test_claude_tail_overflow.py` (NEW)

**Step 1: Write the failing test**

Create `tests/adapters/test_claude_tail_overflow.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from portable_resume.adapters import claude
from portable_resume.adapters.base import ResolvedRef
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError
from portable_resume.model import Query


def stamp(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class ClaudeTailOverflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()

    def query(self, ref: str | None = None, cwd: Path | None = None) -> Query:
        return Query("claude", ref=ref, cwd=str(cwd or self.cwd), source_root=str(self.root))

    def session(self, records: list[dict], *, identifier: str | None = None, project: str = "project") -> tuple[str, Path]:
        identifier = identifier or str(uuid.uuid4())
        path = self.root / "projects" / project / f"{identifier}.jsonl"
        payload = b"".join(json.dumps(record, separators=(",", ":")).encode() + b"\n" for record in records)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return identifier, path

    def turn(self, kind: str, identifier: str, parent: str | None, content: object, at: int, **extra: object) -> dict:
        return {
            "type": kind,
            "uuid": identifier,
            "parentUuid": parent,
            "sessionId": extra.pop("sessionId", None),
            "cwd": str(self.cwd),
            "timestamp": stamp(at),
            "message": {"role": kind, "content": content},
            **extra,
        }

    def oversized_session(self, session_id: str, *, project: str = "project") -> tuple[Path, str, str]:
        """File with records at BOTH head and tail; ~150 KiB of meta in between.

        Head holds a cwd-bearing user record (discovery), tail holds the
        recoverable request/answer pair (show fallback). Total size exceeds a
        128 KiB source_read_bytes budget.
        """
        tail_user_id = str(uuid.uuid4())
        tail_assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", str(uuid.uuid4()), None, "head request", -5, sessionId=session_id),
            *({"type": "meta"} for _ in range(10_000)),  # ~150 KiB
            self.turn("user", tail_user_id, None, "latest request", -2, sessionId=session_id),
            self.turn("assistant", tail_assistant_id, tail_user_id, "answer", -1, sessionId=session_id),
        ]
        _identifier, path = self.session(records, identifier=session_id, project=project)
        self.assertGreater(path.stat().st_size, 128 * 1024)
        return path, tail_user_id, tail_assistant_id

    def test_list_stays_discoverable_for_oversized_file_with_warning(self) -> None:
        session_id = str(uuid.uuid4())
        path, _user_id, _assistant_id = self.oversized_session(session_id)
        budget = ReadBudget(
            Bounds(source_read_bytes=128 * 1024, transcript_records=5_000, scanned_records=5_000)
        )
        summaries = claude.ADAPTER.list(self.query(), budget)
        self.assertEqual([item.session_id for item in summaries], [session_id])
        self.assertIn("W_TRUNCATED", summaries[0].warnings)
        self.assertGreater(path.stat().st_size, 128 * 1024)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_tail_overflow.ClaudeTailOverflowTests.test_list_stays_discoverable_for_oversized_file_with_warning -v`
Expected: FAIL — `DiagnosticError` with `E_LIMIT_EXCEEDED` raised from `_metadata_windows` (`stable_read_windows` defaults to `require_size_within_max=True`, and the 4 MiB head window itself exceeds the 128 KiB budget).

**Step 3: Implement**

In `claude.py` line 33, extend the snapshot import:

```python
from ..snapshot import (
    FileFingerprint,
    FileSnapshot,
    StableWindows,
    snapshot_regular_file,
    stable_read_windows,
    stable_scan_tail_lines,
)
```

Rewrite `_metadata_windows` lines 669-681 (the `_validate_claude_bounds` + `stable_read_windows` call + metadata init) to size the head/tail windows to the REMAINING budget and admit oversized files:

```python
    _validate_claude_bounds(budget)
    remaining = max(
        0,
        min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes)
        - budget.bytes_read,
    )
    head_bytes = min(_METADATA_HEAD_BYTES, remaining)
    tail_bytes = min(_METADATA_TAIL_BYTES, max(0, remaining - head_bytes))
    observation = stable_read_windows(
        path,
        root=root,
        head_bytes=head_bytes,
        tail_bytes=tail_bytes,
        max_bytes=min(budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
        attempts=min(budget.limits.snapshot_attempts, DEFAULT_BOUNDS.snapshot_attempts),
        membership_limit=min(budget.limits.scanned_records, DEFAULT_BOUNDS.scanned_records),
        budget=budget,
        require_size_within_max=False,
    )
    metadata = _TranscriptMetadata()
    warnings: list[str] = []
    if observation.fingerprint.size > min(
        budget.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes
    ):
        warnings.append("W_TRUNCATED")
```

(With default bounds this is a no-op: `remaining` = 256 MiB, so `head_bytes` stays 4 MiB and `tail_bytes` stays 64 KiB — identical windows to today. With lowered bounds the windows shrink to fit, so discovery no longer hard-fails; the file being larger than the budget is reported via `W_TRUNCATED`.)

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_tail_overflow.ClaudeTailOverflowTests.test_list_stays_discoverable_for_oversized_file_with_warning -v`
Expected: PASS

Run the existing large-listing test (must stay green — default bounds, 17 MiB file < 256 MiB, windows unchanged):
`PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor.ClaudeAdapterTests.test_large_listing_uses_metadata_windows_not_a_full_snapshot -v`
Expected: PASS

Run the charged-once prefilter test (budget exactly equals file size — window shrinks to fit):
`PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor.ClaudeAdapterTests.test_issue167_matching_prefilter_payload_is_charged_once -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/portable_resume/adapters/claude.py tests/adapters/test_claude_tail_overflow.py
git commit -m "fix(claude): keep oversized sessions discoverable with W_TRUNCATED"
```

---

### Task 5: Claude `show` soft-degrades to a bounded suffix graph

**Files:**
- Modify: `src/portable_resume/adapters/claude.py` (`show` at 1453-1581; add `_build_tail_graph`, `_assemble_from_index`)
- Test: `tests/adapters/test_claude_tail_overflow.py`
- Modify: `tests/adapters/test_claude_codex_cursor.py:693-745` (ONE existing test moves to the new contract)

**Step 1: Write the failing tests**

Append to `tests/adapters/test_claude_tail_overflow.py`:

```python
    def test_show_soft_degrades_when_transcript_budget_exceeded(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", user_id, None, "request", -2, sessionId=session_id),
            *({"type": "meta"} for _ in range(10)),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        budget = ReadBudget(
            Bounds(transcript_records=len(records) - 1, scanned_records=1)
        )
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)), self.query(), budget
        )
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_TRUNCATED", session.warnings)

    def test_show_soft_degrades_when_source_bytes_exceeded(self) -> None:
        session_id = str(uuid.uuid4())
        path, _user_id, _assistant_id = self.oversized_session(session_id)
        budget = ReadBudget(
            Bounds(
                source_read_bytes=128 * 1024,
                transcript_records=5_000,
                scanned_records=5_000,
            )
        )
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)), self.query(), budget
        )
        self.assertEqual(session.last_user_request, "latest request")
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_TRUNCATED", session.warnings)

    def test_parent_outside_admitted_window_warns_broken_chain(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        records = [
            self.turn("user", user_id, None, "request", -3, sessionId=session_id),
            *({"type": "meta"} for _ in range(6)),
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        # transcript_records=7 admits the last 7 of 8 records, dropping the
        # parent user record; the leaf's chain then crosses the cut.
        budget = ReadBudget(Bounds(transcript_records=7, scanned_records=100))
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)), self.query(), budget
        )
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_BROKEN_CHAIN", session.warnings)

    def test_replay_conflict_inside_window_stays_corrupt(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        base = self.turn("user", user_id, None, "request", -2, sessionId=session_id)
        replay = dict(base)
        replay["message"] = {"role": "user", "content": "changed"}
        records = [
            base,
            replay,
            self.turn("assistant", assistant_id, user_id, "answer", -1, sessionId=session_id),
        ]
        _, path = self.session(records, identifier=session_id)
        budget = ReadBudget(Bounds(transcript_records=3, scanned_records=100))
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)), self.query(), budget
            )
        self.assertEqual(caught.exception.code, "E_CORRUPT_RECORD")

    def test_single_record_over_record_bytes_stays_limit_exceeded(self) -> None:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        big = self.turn("user", user_id, None, "x" * 1024, -1, sessionId=session_id)
        encoded = json.dumps(big, separators=(",", ":")).encode() + b"\n"
        _, path = self.session([big], identifier=session_id)
        budget = ReadBudget(
            Bounds(
                record_bytes=len(encoded) - 1,
                transcript_records=10,
                scanned_records=10,
            )
        )
        with self.assertRaises(DiagnosticError) as caught:
            claude.ADAPTER.show(
                ResolvedRef(session_id, str(path)), self.query(), budget
            )
        self.assertEqual(caught.exception.code, "E_LIMIT_EXCEEDED")

    def test_show_source_tree_byte_for_byte_unchanged(self) -> None:
        from tests.helpers.core import tree_snapshot

        session_id = str(uuid.uuid4())
        path, _user_id, _assistant_id = self.oversized_session(session_id)
        before = tree_snapshot(str(self.root))
        budget = ReadBudget(
            Bounds(source_read_bytes=128 * 1024, transcript_records=5_000, scanned_records=5_000)
        )
        claude.ADAPTER.show(ResolvedRef(session_id, str(path)), self.query(), budget)
        self.assertEqual(tree_snapshot(str(self.root)), before)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_tail_overflow -v`
Expected: FAIL — the first four new tests raise `E_LIMIT_EXCEEDED` from `snapshot_regular_file` / `_index_snapshot` instead of returning a session. (`test_single_record_over_record_bytes_stays_limit_exceeded` and `test_show_source_tree_byte_for_byte_unchanged` may already pass — that is fine, they lock the contract.)

**Step 3: Implement**

**3a. Refactor `show` (lines 1508-1581).** Replace the body after `_validate_claude_bounds(budget)` with:

```python
        _validate_claude_bounds(budget)
        try:
            with snapshot_regular_file(
                path,
                root=root,
                bounds=budget.limits,
                attempts=budget.limits.snapshot_attempts,
                membership_limit=budget.limits.scanned_records,
                budget=budget,
                provider=FORMAT_ID,
            ) as observation:
                index = _index_snapshot(observation, budget)
                return _assemble_from_index(
                    observation, index, path, ref, query, budget
                )
        except DiagnosticError as error:
            if error.code != "E_LIMIT_EXCEEDED":
                raise
            observation, index = _build_tail_graph(path, root, budget)
            with observation:
                return _assemble_from_index(
                    observation, index, path, ref, query, budget
                )
```

**3b. Add `_assemble_from_index`** (extracted verbatim from the old `show` body lines 1519-1581, no behavior change):

```python
def _assemble_from_index(
    observation: FileSnapshot,
    index: _TranscriptIndex,
    path: str,
    ref: ResolvedRef,
    query: Query,
    budget: ReadBudget,
) -> Session:
    if _metadata_session_id(path, index.metadata) != ref.session_id:
        raise DiagnosticError("E_CORRUPT_RECORD", source="claude", provider=FORMAT_ID)
    cwd = index.metadata.selected_cwd(query.cwd)
    if query.cwd is not None and cwd is None:
        raise DiagnosticError("E_NO_MATCH", source="claude", provider=FORMAT_ID)
    lineage, lineage_warnings = _indexed_lineage(index)
    records = _load_lineage_records(
        observation,
        lineage,
        maximum_record=budget.limits.record_bytes,
    )
    turns: list[Turn] = []
    all_warnings = list((*index.warnings, *lineage_warnings))
    turn_bounds = replace(DEFAULT_BOUNDS, tool_output_chars=query.max_tool_chars)
    tool_calls = _ToolCallContext(
        maximum_pending=min(
            budget.limits.scanned_records,
            DEFAULT_BOUNDS.scanned_records,
        ),
        maximum_chars=query.max_tool_chars,
    )

    def append_turn(raw: Mapping[str, Any]) -> None:
        turn, turn_warnings = sanitize_turn_record(
            raw,
            ordinal=len(turns),
            bounds=turn_bounds,
        )
        all_warnings.extend(turn_warnings)
        if turn is not None:
            if raw.get("_pretruncated") is True and not turn.truncated:
                turn = replace(turn, truncated=True)
            budget.consume_turns()
            turns.append(turn)

    for record in records:
        for raw in _turn_records(record, tool_calls):
            append_turn(raw)
    for raw in tool_calls.missing_results():
        append_turn(raw)
    all_warnings.extend(tool_calls.warnings)
    last_user = next(
        (turn.content for turn in reversed(turns) if turn.role == "user"),
        None,
    )
    last_assistant = next(
        (turn.content for turn in reversed(turns) if turn.role == "assistant"),
        None,
    )
    return Session(
        source="claude",
        session_id=ref.session_id,
        source_path=path,
        title=index.metadata.title,
        cwd=cwd,
        branch=index.metadata.branch,
        created_at=index.metadata.created_at,
        updated_at=_mtime(observation),
        last_user_request=last_user,
        last_assistant_action=last_assistant,
        turns=tuple(turns),
        warnings=tuple(dict.fromkeys(all_warnings)),
    )
```

**3c. Add `_build_tail_graph`** (new function; place before `class ClaudeAdapter` at line 1303):

```python
def _build_tail_graph(
    path: str,
    root: str,
    budget: ReadBudget,
) -> tuple[FileSnapshot, _TranscriptIndex]:
    """Soft-degraded suffix graph for oversized sessions (#258).

    Called only after the full snapshot/index path raised E_LIMIT_EXCEEDED.
    Admits the stable tail window under remaining ``source_read_bytes`` /
    ``transcript_records``, mirrors the admitted lines into a private temp
    file (bounded), indexes them, and returns a synthetic FileSnapshot so the
    shared lineage/turn assembly can reuse ``_load_lineage_records``.
    """

    _validate_claude_bounds(budget)
    maximum_record = min(budget.limits.record_bytes, DEFAULT_BOUNDS.record_bytes)
    try:
        before = os.lstat(path)
    except OSError as error:
        raise DiagnosticError.source_busy(source="claude", provider=FORMAT_ID) from error
    temporary = tempfile.TemporaryDirectory(prefix="portable-resume-claude-tail-")
    try:
        target = Path(temporary.name) / "tail.jsonl"
        metadata = _TranscriptMetadata()
        nodes: dict[str, _TranscriptNode] = {}
        bridge: dict[str, str | None] = {}
        digests: dict[str, str] = {}
        warnings: list[str] = ["W_TRUNCATED"]
        index = 0
        lines = stable_scan_tail_lines(
            path,
            root=root,
            budget=budget,
            charge_transcript=True,
            max_line_bytes=maximum_record,
        )
        with open(target, "wb") as handle:
            for line in lines:
                offset = handle.tell()
                raw = line.text.encode("utf-8")
                if line.terminated:
                    raw += b"\n"
                handle.write(raw)
                if len(raw) > maximum_record:
                    raise DiagnosticError.limit_exceeded()
                record, warning = _decode_record(
                    raw, terminal_partial=not line.terminated
                )
                if warning is not None:
                    warnings.append(warning)
                if record is None:
                    if warning == "W_PARTIAL_TAIL":
                        break
                    index += 1
                    continue
                metadata.observe(record)
                observed = _observe_replay_record(record, digests=digests, bridge=bridge)
                if observed is not None and record.get("type") in _UUID_RECORD_TYPES:
                    identifier, digest = observed
                    if record.get("isSidechain") is not True:
                        nodes[identifier] = _TranscriptNode(
                            identifier=identifier,
                            index=index,
                            offset=offset,
                            digest=digest,
                            record=_graph_record(record),
                        )
                index += 1
        try:
            after = os.lstat(path)
        except OSError as error:
            raise DiagnosticError.source_busy(source="claude", provider=FORMAT_ID) from error
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_size != after.st_size
        ):
            raise DiagnosticError.source_busy(source="claude", provider=FORMAT_ID)
        if metadata.records_seen == 0 or not nodes:
            raise DiagnosticError("E_UNSUPPORTED_FORMAT", source="claude", provider=FORMAT_ID)
        fingerprint = FileFingerprint(
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
        )
        observation = FileSnapshot(
            directory=temporary.name,
            path=str(target),
            source_name=os.path.basename(path),
            fingerprint=fingerprint,
            attempts=1,
            _temporary=temporary,
        )
        return observation, _TranscriptIndex(
            metadata=metadata,
            nodes=nodes,
            bridge=bridge,
            warnings=tuple(dict.fromkeys(warnings)),
        )
    except BaseException:
        temporary.cleanup()
        raise
```

Also add `import tempfile` to the `claude.py` imports (near line 10-21, alphabetical after `stat`):

```python
import stat
import tempfile
import time
```

**3d. Update the ONE existing test to the new contract.**

In `tests/adapters/test_claude_codex_cursor.py:693-745` (`test_streaming_show_has_independent_line_and_record_byte_bounds`), the transcript-budget half currently asserts `E_LIMIT_EXCEEDED`. Replace that assertion block (lines 709-715) with the soft-degrade contract:

```python
        session = claude.ADAPTER.show(
            ResolvedRef(session_id, str(path)),
            self.query(),
            ReadBudget(Bounds(transcript_records=len(records) - 1, scanned_records=1)),
        )
        self.assertEqual(session.last_assistant_action, "answer")
        self.assertIn("W_TRUNCATED", session.warnings)
```

The `record_bytes` half (lines 733-745) stays as-is: `E_LIMIT_EXCEEDED` is preserved because the fallback re-encounters the oversized line.

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_tail_overflow -v`
Expected: PASS (7 tests)

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor.ClaudeAdapterTests.test_streaming_show_has_independent_line_and_record_byte_bounds -v`
Expected: PASS

Run the whole Claude adapter lane:
`PYTHONPATH=src python3 -m unittest tests.adapters.test_claude_codex_cursor -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/portable_resume/adapters/claude.py tests/adapters/test_claude_tail_overflow.py tests/adapters/test_claude_codex_cursor.py
git commit -m "fix(claude): soft-degrade show to a bounded suffix graph for oversized sessions"
```

---

### Task 6: Full verification

**Files:** none (verification only)

**Step 1: Run the full local gates**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
```

Expected: all PASS / ok, no new failures.

**Step 2: Sanity-check the CLI surface**

```bash
PYTHONPATH=src python3 scripts/portable-resume claude show latest \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --format handoff
```

Expected: exit 0, handoff document rendered.

**Step 3: Run the issue's synthetic repro** (five records, `transcript_records=4`):

```bash
PYTHONPATH=src python3 -c '
from pathlib import Path
import tempfile, uuid, json
from portable_resume.adapters import claude
from portable_resume.bounds import Bounds, ReadBudget
from portable_resume.model import Query
from portable_resume.adapters.base import ResolvedRef

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp).resolve(); cwd = root / "repo"; cwd.mkdir()
    sid = str(uuid.uuid4())
    path = root / "projects" / "p" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True)
    recs = []
    prev = None
    for i in range(5):
        rid = str(uuid.uuid4())
        recs.append({"type": "user" if i % 2 == 0 else "assistant", "uuid": rid,
                     "parentUuid": prev, "sessionId": sid, "cwd": str(cwd),
                     "timestamp": f"2026-08-09T00:00:0{i}Z",
                     "message": {"role": "user" if i % 2 == 0 else "assistant",
                                 "content": f"turn-{i}"}})
        prev = rid
    path.write_bytes(b"".join(json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in recs))
    query = Query("claude", cwd=str(cwd), source_root=str(root))
    listed = claude.ADAPTER.list(query, ReadBudget())
    assert len(listed) == 1, listed
    session = claude.ADAPTER.show(
        ResolvedRef.from_summary(listed[0]), query,
        ReadBudget(Bounds(transcript_records=4)),
    )
    print("turns:", [t.content for t in session.turns])
    print("warnings:", session.warnings)
    assert "W_TRUNCATED" in session.warnings
    print("OK")
'
```

Expected: prints `OK` with `W_TRUNCATED` in warnings — the issue's deterministic repro now soft-degrades instead of raising `E_LIMIT_EXCEEDED`.

**Step 4: Commit any final fixes if the gates found non-blocking issues** (nothing to commit if all green).

---

## Out of scope (do NOT do in this plan)

- #257 (Codex show): the shared `stable_scan_tail_lines` primitive is built here and Codex can adopt it in a follow-up.
- Raising any `Bounds` ceilings or loading oversized files into memory.
- Invoking Claude Code or mutating the source store.
- Doc/CHANGELOG bumps (release-time concern).
