# Next-Wave Agent Support Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decouple source adapters, destination hosts, and native package surfaces so Portable Resume can add asymmetric next-wave tools (Pi, OpenClaw, goose, …) without hard-coding `8 × 8 = 64`, then land first-wave support behind the standard PR A–E sequence and honesty gates.

**Architecture:** Introduce independent typed registries (`SourceProfile`, `DestinationProfile`, `PackageSurface`) that replace paired frozensets. Matrix cell counts become `enabled_sources × enabled_destinations` derived at runtime. New tools follow research → fixtures → source and/or destination axes independently. Shared JSONL scanner + Bounds raise-rejection harden the read path before multi-adapter streaming work. Installer P0s (#20/#31) gate any new mutating destination installs.

**Tech Stack:** Python 3.11+ stdlib only, unittest, existing `portable_resume` package, synthetic fixtures under `tests/fixtures/`, scripts under `scripts/`.

**Issue map (research complete 2026-07-26; no runtime code yet):**

| Issue | Role |
|---|---|
| [#36](https://github.com/ImL1s/resume-skills/issues/36) | Capability registries + dynamic matrix |
| [#48](https://github.com/ImL1s/resume-skills/issues/48) | Umbrella roadmap, PR A–E, acceptance contracts, milestones N1–N6 |
| [#37](https://github.com/ImL1s/resume-skills/issues/37)–[#43](https://github.com/ImL1s/resume-skills/issues/43) | Tier-1 source+destination |
| [#44](https://github.com/ImL1s/resume-skills/issues/44)–[#46](https://github.com/ImL1s/resume-skills/issues/46) | Destination-first / compatibility |
| [#47](https://github.com/ImL1s/resume-skills/issues/47) | Second-wave qualification scorecard |
| [#10](https://github.com/ImL1s/resume-skills/issues/10)/[#17](https://github.com/ImL1s/resume-skills/issues/17) | Shared scanner + Bounds invariants |
| [#20](https://github.com/ImL1s/resume-skills/issues/20)/[#31](https://github.com/ImL1s/resume-skills/issues/31) | Installer P0 security (before new hosts) |

**Product boundary (every task):** local/offline source reads; immutable stores; inert handoff; stdlib-only runtime; no source CLI/gateway; no auth migration; no live-process resume claims.

**Canonical verify (every PR):**

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Also run `python3 scripts/check_docs.py` when docs/tables change.

---

## File map (foundation)

| File | Responsibility |
|---|---|
| `src/portable_resume/registry.py` | **Create** — `SourceProfile`, `DestinationProfile`, `PackageSurface`, registries, enabled-key helpers |
| `src/portable_resume/model.py` | Migrate `SOURCE_KEYS` to derive from registry (compat re-export) |
| `src/portable_resume/install/catalog.py` | Migrate `HOST_KEYS`/`HOST_PROFILES`/`matrix_cells` to destination registry |
| `src/portable_resume/reader.py` | Load adapters via `SourceProfile.adapter_module`; self-check uses enabled sources |
| `src/portable_resume/bounds.py` | #17 — reject raised ceilings on all consume paths |
| `src/portable_resume/snapshot.py` | #10 — `stable_scan_lines` streaming scanner |
| `src/portable_resume/install/transaction.py` | #20/#31 recover + descriptor-relative commit; dynamic `matrix_report` |
| `scripts/smoke_installed_matrix.py` | Derive expected cell count from registries |
| `tests/unit/test_registry.py` | **Create** — registry invariants |
| `tests/unit/test_bounds_raise_reject.py` | **Create** — #17 |
| `tests/unit/test_stable_scan_lines.py` | **Create** — #10 |
| `docs/STATUS.md`, `docs/host-support.md`, `README.md`, `AGENTS.md` | Dynamic counts; no new-tool claims until axes land |

---

## Phase 0 — Architecture and safety (Milestone N1)

### Task 1: Registry module — failing invariant tests

**Files:**
- Create: `tests/unit/test_registry.py`
- Create: `src/portable_resume/registry.py` (minimal stub after first fail)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_registry.py
from __future__ import annotations

import unittest

from portable_resume.registry import (
    DESTINATION_PROFILES,
    PACKAGE_SURFACES,
    SOURCE_PROFILES,
    destination_keys,
    enabled_destination_keys,
    enabled_source_keys,
    matrix_dimensions,
    source_keys,
    validate_registries,
)


class RegistryInvariantTests(unittest.TestCase):
    def test_current_eight_sources_and_destinations(self) -> None:
        self.assertEqual(
            enabled_source_keys(),
            frozenset(
                {
                    "antigravity",
                    "claude",
                    "codex",
                    "cursor",
                    "grok",
                    "kimi",
                    "opencode",
                    "qwen",
                }
            ),
        )
        self.assertEqual(enabled_destination_keys(), enabled_source_keys())
        dims = matrix_dimensions()
        self.assertEqual(dims["sources"], 8)
        self.assertEqual(dims["destinations"], 8)
        self.assertEqual(dims["cells"], 64)

    def test_source_and_destination_sets_are_independent_types(self) -> None:
        # Adding a destination-only key must not invent a source.
        self.assertIn("claude", SOURCE_PROFILES)
        self.assertIn("claude", DESTINATION_PROFILES)
        self.assertIsNot(SOURCE_PROFILES, DESTINATION_PROFILES)

    def test_validate_registries_rejects_duplicate_keys(self) -> None:
        # validate_registries() is the closed gate used by self-check.
        validate_registries()  # current tree must pass

    def test_planned_profiles_excluded_from_enabled_sets(self) -> None:
        # After Task 3 inserts a planned synthetic profile, enabled_* ignore it.
        for profile in SOURCE_PROFILES.values():
            if profile.status == "supported":
                self.assertIn(profile.key, enabled_source_keys())
            elif profile.status in {"planned", "experimental", "research"}:
                self.assertNotIn(profile.key, enabled_source_keys())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_registry -v
```

Expected: FAIL with `ModuleNotFoundError: portable_resume.registry` (or missing symbols).

- [ ] **Step 3: Write minimal registry implementation**

```python
# src/portable_resume/registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProfileStatus = Literal["supported", "partial", "experimental", "planned", "research"]


@dataclass(frozen=True, slots=True)
class SourceProfile:
    key: str
    adapter_module: str
    format_ids: tuple[str, ...]
    status: ProfileStatus = "supported"
    local_only: bool = True
    supports_list: bool = True
    supports_show: bool = True
    exact_ref_kinds: tuple[str, ...] = ("id", "path", "text", "latest")
    fixture_profile: str | None = None


@dataclass(frozen=True, slots=True)
class DestinationProfile:
    key: str
    payload_profile: str
    status: ProfileStatus = "supported"
    direct_skill: bool = True
    project_rel: str = ""
    global_rel: str = ""
    native_package_profile: str | None = None
    activation_profile: str | None = None
    # Keep HostProfile fields during migration by storing catalog HostProfile separately
    # or embed the existing HostProfile under DESTINATION_HOST_DETAILS.


@dataclass(frozen=True, slots=True)
class PackageSurface:
    key: str
    destination: str
    profile: str
    buildable: bool = True
    last_verified_host_version: str | None = None
    status: ProfileStatus = "supported"


# Populate SOURCE_PROFILES / DESTINATION_PROFILES / PACKAGE_SURFACES with the
# current eight keys only (status="supported"). Mirror adapter_module =
# f"portable_resume.adapters.{key}" and format_ids from docs/source-formats.md.

SOURCE_PROFILES: dict[str, SourceProfile] = {}  # filled in same file
DESTINATION_PROFILES: dict[str, DestinationProfile] = {}
PACKAGE_SURFACES: dict[str, PackageSurface] = {}


def source_keys() -> frozenset[str]:
    return frozenset(SOURCE_PROFILES)


def destination_keys() -> frozenset[str]:
    return frozenset(DESTINATION_PROFILES)


def enabled_source_keys() -> frozenset[str]:
    return frozenset(k for k, p in SOURCE_PROFILES.items() if p.status == "supported")


def enabled_destination_keys() -> frozenset[str]:
    return frozenset(
        k
        for k, p in DESTINATION_PROFILES.items()
        if p.status == "supported" and p.direct_skill
    )


def matrix_dimensions() -> dict[str, int]:
    sources = len(enabled_source_keys())
    destinations = len(enabled_destination_keys())
    return {
        "sources": sources,
        "destinations": destinations,
        "cells": sources * destinations,
    }


def validate_registries() -> None:
    if len(SOURCE_PROFILES) != len({p.key for p in SOURCE_PROFILES.values()}):
        raise ValueError("duplicate source keys")
    if len(DESTINATION_PROFILES) != len({p.key for p in DESTINATION_PROFILES.values()}):
        raise ValueError("duplicate destination keys")
    for surface in PACKAGE_SURFACES.values():
        if surface.destination not in DESTINATION_PROFILES:
            raise ValueError(f"package surface owner missing: {surface.key}")
    for key, profile in SOURCE_PROFILES.items():
        if key != profile.key:
            raise ValueError(f"source map key mismatch: {key}")
        if profile.status == "supported" and not profile.adapter_module.startswith(
            "portable_resume.adapters."
        ):
            raise ValueError(f"bad adapter_module: {key}")
```

Fill the three dicts with the existing eight keys before claiming green.

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_registry -v
```

Expected: PASS for Task-1 assertions that do not yet require planned-profile insertion.

- [ ] **Step 5: Commit**

```bash
git add src/portable_resume/registry.py tests/unit/test_registry.py
git commit -m "$(cat <<'EOF'
feat: add independent source/destination/package registries

Unblock asymmetric next-wave profiles without hard-coding 8×8.
EOF
)"
```

---

### Task 2: Wire registries into model, catalog, matrix, self-check

**Files:**
- Modify: `src/portable_resume/model.py:9-20`
- Modify: `src/portable_resume/install/catalog.py:11-22`, `479-487`
- Modify: `src/portable_resume/install/transaction.py` (`matrix_report`)
- Modify: `src/portable_resume/reader.py:49-64`, `139-183`
- Modify: `scripts/smoke_installed_matrix.py`
- Modify: `tests/integration/test_matrix_and_installer.py` (remove literal `64`; assert `matrix_dimensions()["cells"]`)
- Modify: `tests/unit/test_hosts_catalog.py`
- Modify: `tests/e2e/test_platform_release_gate.py`, `test_installed_runner_and_relocation.py`, `test_relocated_bundle.py`

- [ ] **Step 1: Write failing tests for asymmetric matrix**

```python
# tests/unit/test_registry.py — add:
class DynamicMatrixTests(unittest.TestCase):
    def test_matrix_cells_match_dimensions(self) -> None:
        from portable_resume.install.catalog import matrix_cells
        from portable_resume.registry import matrix_dimensions

        cells = matrix_cells()
        dims = matrix_dimensions()
        self.assertEqual(len(cells), dims["cells"])
        self.assertEqual(len(cells), 64)  # still true for current eight

    def test_destination_only_expands_rectangle(self) -> None:
        # Unit-level: call a helper that builds cells from explicit key sets.
        from portable_resume.registry import rectangular_cells

        cells = rectangular_cells(
            sources=frozenset({"claude"}),
            destinations=frozenset({"claude", "pi"}),
        )
        self.assertEqual(cells, [("claude", "claude"), ("pi", "claude")])
        # Note ordering: sorted destination then sorted source, matching catalog.
```

Add `rectangular_cells(sources, destinations) -> list[tuple[str, str]]` returning `(destination, source)` pairs in deterministic sort order — same shape as today's `matrix_cells()`.

- [ ] **Step 2: Run — expect FAIL** until `matrix_cells` / `rectangular_cells` use registries.

- [ ] **Step 3: Minimal wiring**

1. `model.py`:

```python
from .registry import enabled_source_keys

SOURCE_KEYS = enabled_source_keys()  # keep name for import compatibility
```

Or keep a module-level frozenset that `registry` populates and re-export — but **one SSOT only**. Prefer:

```python
# model.py
from .registry import enabled_source_keys as _enabled_source_keys

def _source_keys() -> frozenset[str]:
    return _enabled_source_keys()

# For frozen import-time sets used widely today, set:
SOURCE_KEYS = frozenset(...)  # populated from registry at import after SOURCE_PROFILES fill
```

Simplest migration: define profiles in `registry.py`, then in `model.py`:

```python
from .registry import enabled_source_keys

SOURCE_KEYS = enabled_source_keys()
```

2. `catalog.py` `matrix_cells`:

```python
from ..registry import enabled_destination_keys, enabled_source_keys, rectangular_cells

def matrix_cells(hosts: Iterable[str] | None = None) -> list[tuple[str, str]]:
    destinations = frozenset(hosts) if hosts is not None else enabled_destination_keys()
    unknown = destinations - enabled_destination_keys()
    if unknown:
        raise KeyError(sorted(unknown)[0])
    return rectangular_cells(sources=enabled_source_keys(), destinations=destinations)
```

3. `reader._load_adapter`: resolve module from `SOURCE_PROFILES[source].adapter_module` instead of f-string only; still require `adapter.key == source`.

4. `self_check`: report `matrix_dimensions()`, `enabled_source_keys()`, `enabled_destination_keys()`, and call `validate_registries()`.

5. Replace every literal `assertEqual(..., 64)` / `len(HOST_KEYS) == 8` with `matrix_dimensions()` / `len(enabled_*)`.

6. `smoke_installed_matrix.py`: `expected = matrix_dimensions()["cells"]`.

- [ ] **Step 4: Run focused + full suite**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_registry tests.unit.test_hosts_catalog tests.integration.test_matrix_and_installer -q
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Expected: still **64** cells; all pass; no behavior change for the original eight.

- [ ] **Step 5: Commit**

```bash
git add src/portable_resume/model.py src/portable_resume/registry.py \
  src/portable_resume/install/catalog.py src/portable_resume/install/transaction.py \
  src/portable_resume/reader.py scripts/smoke_installed_matrix.py tests/
git commit -m "$(cat <<'EOF'
refactor: derive matrix dimensions from capability registries

Keep the original eight profiles green while removing hard-coded 64/8 gates.
EOF
)"
```

---

### Task 3: Docs/report honesty — dynamic tables, no new-tool claims

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/host-support.md`
- Modify: `README.md` (8×8 wording)
- Modify: `AGENTS.md` (still says six×six / 36 — fix to registry-derived language)
- Optional: small generator script later; for N1, hand-edit with “derived from registries” note

- [ ] **Step 1: Write a docs/self-check assertion** (if `check_docs.py` already greps for `64/64`, update it to accept `N×M` from a machine report, or assert STATUS does not claim OpenClaw/Pi supported).

```python
# tests/unit/test_status_honesty.py (new or extend existing docs gate)
def test_status_does_not_claim_next_wave_supported(self) -> None:
    text = Path("docs/STATUS.md").read_text(encoding="utf-8")
    for name in ("OpenClaw", "Pi source", "goose source"):
        # Allow backlog mentions; forbid "supported" adjacent claims — keep simple:
        self.assertNotIn("OpenClaw: supported", text)
        self.assertNotIn("pi destination: supported", text.lower())
```

- [ ] **Step 2: Run — FAIL if STATUS already has premature claims** (should pass today).

- [ ] **Step 3: Update STATUS open-work table** with links to #36/#48; replace “always 64” language with “currently 8×8=64 derived from registries”. Fix `AGENTS.md` six×six stale claim.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: describe registry-derived matrix; link next-wave roadmap

Do not claim Pi/OpenClaw/goose support until axes land.
EOF
)"
```

---

### Task 4: #17 — reject caller-raised global Bounds ceilings

**Files:**
- Create: `tests/unit/test_bounds_raise_reject.py`
- Modify: `src/portable_resume/bounds.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_bounds_raise_reject.py
from __future__ import annotations

import unittest

from portable_resume.bounds import DEFAULT_BOUNDS, Bounds, ReadBudget
from portable_resume.diagnostics import DiagnosticError


class BoundsRaiseRejectTests(unittest.TestCase):
    def test_consume_records_clamps_to_default_ceiling(self) -> None:
        raised = Bounds(
            scanned_records=DEFAULT_BOUNDS.scanned_records * 2,
            transcript_records=DEFAULT_BOUNDS.transcript_records,
            source_read_bytes=DEFAULT_BOUNDS.source_read_bytes,
            normalized_turns=DEFAULT_BOUNDS.normalized_turns,
        )
        budget = ReadBudget(limits=raised)
        # Filling exactly DEFAULT scanned_records must succeed; +1 must fail.
        budget.consume_records(DEFAULT_BOUNDS.scanned_records)
        with self.assertRaises(DiagnosticError):
            budget.consume_records(1)

    def test_consume_bytes_and_turns_also_reject_raise(self) -> None:
        raised = Bounds(
            source_read_bytes=DEFAULT_BOUNDS.source_read_bytes * 2,
            normalized_turns=DEFAULT_BOUNDS.normalized_turns * 2,
        )
        budget = ReadBudget(limits=raised)
        budget.consume_bytes(DEFAULT_BOUNDS.source_read_bytes)
        with self.assertRaises(DiagnosticError):
            budget.consume_bytes(1)
        budget2 = ReadBudget(limits=raised)
        budget2.consume_turns(DEFAULT_BOUNDS.normalized_turns)
        with self.assertRaises(DiagnosticError):
            budget2.consume_turns(1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect FAIL** (`consume_records` / `consume_bytes` / `consume_turns` currently trust caller limits; only `consume_transcript_records` clamps).

- [ ] **Step 3: Minimal fix in `bounds.py`**

```python
def consume_records(self, amount: int = 1) -> None:
    self._consume(
        "records",
        amount,
        min(self.limits.scanned_records, DEFAULT_BOUNDS.scanned_records),
    )

def consume_bytes(self, amount: int) -> None:
    self._consume(
        "bytes_read",
        amount,
        min(self.limits.source_read_bytes, DEFAULT_BOUNDS.source_read_bytes),
    )

def consume_turns(self, amount: int = 1) -> None:
    self._consume(
        "turns",
        amount,
        min(self.limits.normalized_turns, DEFAULT_BOUNDS.normalized_turns),
    )
```

Keep `consume_transcript_records` as-is (already clamps). Document: callers may lower Bounds, never raise effective ceilings.

- [ ] **Step 4: Run PASS + commit**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_bounds_raise_reject -v
git add src/portable_resume/bounds.py tests/unit/test_bounds_raise_reject.py
git commit -m "$(cat <<'EOF'
fix: clamp ReadBudget consume paths to DEFAULT_BOUNDS ceilings

Callers may lower limits but must not raise global resource ceilings (#17).
EOF
)"
```

---

### Task 5: #10 — shared stable JSONL line scanner

**Files:**
- Create: `tests/unit/test_stable_scan_lines.py`
- Modify: `src/portable_resume/snapshot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stable_scan_lines.py
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from portable_resume.bounds import ReadBudget
from portable_resume.snapshot import stable_scan_lines


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
        from portable_resume.bounds import Bounds, DEFAULT_BOUNDS
        from portable_resume.diagnostics import DiagnosticError

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — FAIL** (`stable_scan_lines` missing).

- [ ] **Step 3: Minimal implementation sketch**

```python
# snapshot.py — add near stable_read_bytes
@dataclass(frozen=True, slots=True)
class ScannedLine:
    ordinal: int
    text: str
    byte_offset: int


def stable_scan_lines(
    path: str,
    *,
    root: str,
    budget: ReadBudget | None = None,
    max_line_bytes: int | None = None,
    charge_transcript: bool = False,
    hook: Any = None,
) -> Iterator[ScannedLine]:
    """Yield UTF-8 lines under no-follow / containment / budget rules.

    Uses the same root containment and symlink rejection as stable_read_bytes.
    Prefer streaming reads; do not require the whole file in memory.
    Terminal partial line may be skipped with a warning path left to callers.
    """
    ...
```

Reuse existing open/no-follow helpers. Do **not** migrate all adapters in this task — land API + tests only. Adapter migrations happen in per-tool PR B (Pi first).

- [ ] **Step 4: Run PASS + commit**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_stable_scan_lines -v
git add src/portable_resume/snapshot.py tests/unit/test_stable_scan_lines.py
git commit -m "$(cat <<'EOF'
feat: add stable_scan_lines shared JSONL scanner

Provide #10 streaming primitive before next-wave file adapters.
EOF
)"
```

---

### Task 6: Installer P0 — #20 recover containment

**Files:**
- Create or extend: `tests/unit/test_install_recover_containment.py`
- Modify: `src/portable_resume/install/transaction.py:718-729`

- [ ] **Step 1: Write the failing test**

```python
def test_recover_complete_journal_does_not_delete_escaped_stage_dir(self) -> None:
    # Arrange a complete journal whose stage_dir points outside support/.
    # Expect: recover_root leaves the external dir intact and fails closed
    # or clears journal only after containment check (match incomplete branch).
    ...
```

Mirror the incomplete-branch check already at `transaction.py:735-738` (`_path_within_support`).

- [ ] **Step 2: Run — FAIL** (complete branch currently `rmtree` without containment at 724-727).

- [ ] **Step 3: Fix**

```python
if journal.get("state") == "complete":
    stage_dir = journal.get("stage_dir")
    if stage_dir and _path_within_support(root, stage_dir):
        shutil.rmtree(stage_dir, ignore_errors=True)
    elif stage_dir:
        raise DiagnosticError("E_RECOVERY_REQUIRED")  # or warn + refuse journal only — pick fail-closed
    os.remove(path)
    return {"ok": True, "recovered": True, "action": "cleared_complete_journal"}
```

Prefer fail-closed: never delete uncontained paths.

- [ ] **Step 4: PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
fix: contain recover_root complete-journal stage deletion

Untrusted complete journals must not delete paths outside support (#20).
EOF
)"
```

---

### Task 7: Installer P0 — #31 descriptor-relative payload commit

**Files:**
- Extend installer unit tests for parent-directory symlink swap during commit
- Modify: `src/portable_resume/install/transaction.py` (`_dest_under_root` and commit path)

- [ ] **Step 1: Write failing TOCTOU test** — between path check and `os.replace`, swap parent to symlink escaping skill root; commit must fail with `E_INSTALL_CONTAINMENT` / `E_INSTALL_CONFLICT`, and no bytes outside root.

- [ ] **Step 2: Implement descriptor-relative / reopen-and-revalidate policy** per #31 (open parent dirfd, `openat`, re-check containment immediately before replace). Keep stdlib-only; on platforms without full support, fail closed rather than optimistic `realpath`.

- [ ] **Step 3: PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
fix: make installer payload commits descriptor-relative

Resist parent-directory symlink swap escapes during install (#31).
EOF
)"
```

**Gate:** Do not merge new destination profiles (Phase 2) until Tasks 6–7 are on main (or an explicit exception for source-only PRs that never call the mutating installer).

---

## Phase 1 — First sources (Milestone N2)

Follow **PR A → PR B** for Pi first (#38), then OpenClaw (#37) and goose (#39) fixture PRs in parallel after Pi source is green.

### Task 8: Pi PR A — format decision record + synthetic fixtures

**Files:**
- Create: `docs/source-formats.md` section `pi-session-jsonl-v3` (and v1/v2 compatibility notes)
- Create: `tests/fixtures/pi/` family:
  - `s-pi-01-basic-v3/`
  - `s-pi-02-branch-compaction/`
  - `s-pi-03-tool-and-custom/`
  - `s-pi-04-corrupt-interior/`
  - `s-pi-05-v2-compat/` (optional)
- Create: `tests/fixtures/pi/MANIFEST.md` listing format ids + `synthetic: true`
- **No** `SOURCE_PROFILES["pi"]` with `status="supported"` yet — use `planned` only if needed for docs, else keep fixtures-only

- [ ] **Step 1: Write fixture schema test**

```python
def test_pi_fixtures_are_synthetic_and_path_clean(self) -> None:
    root = Path("tests/fixtures/pi")
    for path in root.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("/Users/", text)
            self.assertNotIn("/home/", text)
```

- [ ] **Step 2: Author minimal v3 JSONL** (header first line with version=3, then tree nodes with `id`/`parentId`). Mark fixture.json with `synthetic: true`.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
test: add Pi session JSONL synthetic fixtures and format notes

Pin upstream contract for #38 before any runtime adapter key.
EOF
)"
```

---

### Task 9: Pi PR B — source adapter (first new source)

**Files:**
- Create: `src/portable_resume/adapters/pi.py`
- Modify: `src/portable_resume/registry.py` — add `SourceProfile(key="pi", status="supported", ...)`
- Create: `tests/unit/test_pi_adapter.py`
- Modify: smoke fixture map in `scripts/smoke_installed_matrix.py` **only after** destination exists; for source-only milestone, extend unit/adapter tests and reader CLI against `--source-root`

- [ ] **Step 1: Failing adapter tests**

```python
class PiAdapterTests(unittest.TestCase):
    def test_list_metadata_only_from_fixture(self) -> None:
        from portable_resume.adapters.pi import ADAPTER
        from portable_resume.model import Query

        root = str(Path("tests/fixtures/pi/s-pi-01-basic-v3").resolve())
        summaries = ADAPTER.list(Query(source="pi", source_root=root, cwd=root))
        self.assertGreaterEqual(len(summaries), 1)
        self.assertEqual(summaries[0].source, "pi")

    def test_show_active_branch_skips_compacted_interior(self) -> None:
        ...

    def test_exact_path_does_not_scan_sibling_buckets(self) -> None:
        ...

    def test_unsupported_future_version_is_e_unsupported_format(self) -> None:
        ...
```

- [ ] **Step 2: Run — FAIL** (module missing / key not in registry).

- [ ] **Step 3: Implement `adapters/pi.py`**
  - `approved_roots` → `~/.pi/agent` default + `--source-root`
  - discovery only under `sessions/--cwd--/*.jsonl`
  - header version gate; v3 required for `supported`; v1/v2 explicit compat or `E_UNSUPPORTED_FORMAT`
  - use `stable_scan_lines` for show; metadata-only list (header + light scan)
  - active leaf / compaction / branch_summary per #38
  - never import Pi runtime; never mutate files
  - large synthetic (generate in test, 17–30 MiB / 50_001 records) must hit budget diagnostics cleanly

- [ ] **Step 4: Register source only**

```python
SOURCE_PROFILES["pi"] = SourceProfile(
    key="pi",
    adapter_module="portable_resume.adapters.pi",
    format_ids=("pi-session-jsonl-v3",),
    status="supported",
    fixture_profile="pi-session-jsonl-v3",
)
# Do NOT add DESTINATION_PROFILES["pi"] in this task.
```

Confirm `matrix_dimensions()` becomes `9 sources × 8 destinations = 72` once destination still excludes `pi`. Update tests that assumed equal sets.

- [ ] **Step 5: Verify + commit**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_pi_adapter tests.unit.test_registry -q
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py  # expect 72 if smoke uses enabled registries
git commit -m "$(cat <<'EOF'
feat: add Pi source adapter for versioned tree JSONL sessions

Ship source-only pi support; destination remains a later PR (#38).
EOF
)"
```

Update `docs/STATUS.md`: Pi **source** supported; destination not-run.

---

### Task 10: OpenClaw PR A — schema/fixtures

**Files:**
- Create: `tests/fixtures/openclaw/` synthetic SQLite DBs (build via stdlib `sqlite3` in a fixture builder script under `tests/fixtures/openclaw/build_fixtures.py`, checked-in DB blobs or rebuild-in-test)
- Document format `openclaw-agent-sqlite-v1` in `docs/source-formats.md`
- Cover: multi-agent paths, branch/compaction/reset windows, internal-session filter, privacy fields redacted in fixtures

- [ ] Steps: failing fixture integrity test → builder → commit (no adapter yet).

```bash
git commit -m "$(cat <<'EOF'
test: add OpenClaw per-agent SQLite synthetic fixtures

Pin openclaw-agent-sqlite-v1 before adapter work (#37).
EOF
)"
```

---

### Task 11: goose PR A — schema 15 fixtures

**Files:**
- Create: `tests/fixtures/goose/` for `goose-sessions-sqlite-v15`
- Session types: user vs scheduled/subagent/hidden/gateway/ACP (filter expectations documented)
- Legacy JSONL explicitly **out of scope** for this PR

```bash
git commit -m "$(cat <<'EOF'
test: add goose sessions.db schema-15 synthetic fixtures

Lock current SQLite authority before source adapter (#39).
EOF
)"
```

---

## Phase 2 — First destinations (Milestone N3–N4)

**Prerequisite:** Phase 0 Tasks 6–7 on main.

### Task 12: Finish #36 destination registry migration (if any HostProfile fields remain outside registry)

Ensure adding `DestinationProfile(key="pi", ...)` does not require a source. Package surfaces stay separate (`PackageSurface` optional).

### Task 13: Pi PR C — destination profile

**Files:**
- Modify: `registry.py` / `catalog.py` — `DESTINATION_PROFILES["pi"]` + `HostProfile` details:
  - `project_rel=".pi/skills"`
  - `global_rel=".pi/agent/skills"` (under home)
  - alternates: `.agents/skills`
- Extend installed-runner smoke fixtures for all **enabled** sources × `pi`
- Docs: host-support row; STATUS destination claim only after smoke green

```bash
git commit -m "$(cat <<'EOF'
feat: add Pi destination Skill roots and matrix cells

Direct .pi/skills install only; native activation evidence is separate (#38).
EOF
)"
```

### Task 14: OpenClaw + goose PR B/C (source then destination)

Reuse Tasks 9/13 pattern. Shared SQLite helpers only (snapshot/private connection); no cross-adapter format assumptions.

### Task 15: Copilot destination-only (#44 Track A)

**Files:**
- `DestinationProfile(key="github-copilot", status="supported", ...)`
- Roots: project `.github/skills`; global `$COPILOT_HOME/skills` / `~/.copilot/skills`
- Alternates recorded, not multi-installed
- `SourceProfile` for copilot remains `planned`/`research` until events.jsonl schema qualification
- Matrix becomes rectangular (e.g. 11×12) — reports must print dimensions

```bash
git commit -m "$(cat <<'EOF'
feat: add GitHub Copilot CLI destination profile

Keep source planned until session-event schema is pinned (#44).
EOF
)"
```

### Task 16: PR D — exact-version host activation evidence (per host)

Manual/scheduled; write rows into `docs/host-ui-smoke.md` / evidence docs. Never infer from `smoke_installed_matrix.py`.

---

## Phase 3 — Remaining Tier-1 (Milestone N5)

For each of Crush (#40), Cline (#41), OpenHands (#42), Hermes (#43), execute the standard sequence as separate bite-sized PR chains:

| Step | PR | Deliverable |
|---|---|---|
| A | fixtures + `docs/source-formats.md` | no supported key |
| B | `adapters/<key>.py` + source profile | source tests + immutability |
| C | destination profile + matrix | installer smoke cells |
| D | host evidence | docs only |
| E | marketplace/native | optional, separate |

**Per-tool non-negotiables (copy into each PR description):**

- Closed format id + synthetic fixtures (`synthetic: true`, no real home paths)
- Exact ID/path + cwd isolation
- Child/subagent filtered before list LIMIT
- 17–30 MiB / 50_001-record budget tests
- Race/busy → retry diagnostic, not mixed transcript
- Destination roots + provenance
- STATUS names exact axes only

---

## Phase 4 — Compatibility / forks (Milestone N6 partial)

### Task 17: Gemini CLI (#45)

1. Destination `.gemini/skills` + lifecycle docs first
2. Source only after Gemini-owned session JSON qualification
3. **Never** alias Antigravity store/profile/IDs
4. Document consumer Login-with-Google shutdown (2026-06-18) as migration context only — not a reason to merge adapters

### Task 18: Kilo Code CLI (#46)

1. Separate profile keys from `opencode`
2. Divergence fixtures (Kilo-only vs OpenCode-only)
3. Shared code limited to generic SQLite/sanitize helpers
4. Source stays research until DB/migration/schema qualification

---

## Phase 5 — Second-wave qualification (#47)

### Task 19: Machine-readable scorecard store

**Files:**
- Create: `docs/qualification/scorecard-schema.md` + `docs/qualification/candidates/*.md` (or JSON under `docs/qualification/`)
- Fields per #47: maintenance, CLI/IDE/cloud boundary, local authority, schema evidence, branch/rewind/compaction/subagent, cwd/exact ID, Skills roots, privacy, source/destination go-no-go

- [ ] No `SOURCE_PROFILES`/`DESTINATION_PROFILES` entries with `status="supported"` from this task
- [ ] Candidates that pass get **new GitHub issues** modeled on #37–#46 — not silent registry inserts

```bash
git commit -m "$(cat <<'EOF'
docs: add second-wave agent qualification scorecards

Research-only; no runtime registry keys (#47).
EOF
)"
```

---

## Reusable micro-checklist (every adapter PR B)

- [ ] Failing unittest with synthetic fixture
- [ ] Adapter module + `ADAPTER` export
- [ ] Registry source profile `supported`
- [ ] probe/list/show paths covered
- [ ] Immutable source proof (hash/mtime before/after)
- [ ] Budget / corruption / symlink escape tests
- [ ] Canonical verify commands green
- [ ] STATUS/CHANGELOG axis-accurate
- [ ] Commit

## Reusable micro-checklist (every destination PR C)

- [ ] Installer P0s present on baseline
- [ ] Destination profile + HostProfile roots/provenance
- [ ] `matrix_dimensions` updated; smoke expected dynamic
- [ ] install/verify/uninstall transaction tests for new host
- [ ] No native-activation claim from runner matrix
- [ ] Commit

---

## Out of scope (entire plan)

- Live process / session restore
- Invoking source agent CLIs from readers
- Auth, quota, MCP, extensions migration
- Copying `~/.grok/bundled/skills/**`
- Treating `gh skill` host list as source-schema authority
- Collapsing native package / marketplace / picker evidence into installed-runner pass counts

---

## Milestone exit criteria

| Milestone | Exit |
|---|---|
| N1 | Registries live; 8×8 still green; #17/#10 landed; #20/#31 fixed; docs honest |
| N2 | Pi source probe/list/show supported; matrix rectangular if dest missing |
| N3 | Pi destination + dynamic smoke cells; optional PR D evidence row |
| N4 | OpenClaw + goose source+dest on current SQLite formats |
| N5 | Crush/Cline/OpenHands/Hermes approved axes; Copilot dest explicit |
| N6 | Gemini/Kilo phased; #47 promotions only via new issues |

---

## Execution note

Work **source-only** adapters freely before installer P0s. Block **destination** merges on Tasks 6–7. Prefer one tool axis per PR. Keep commits frequent (each task above).
