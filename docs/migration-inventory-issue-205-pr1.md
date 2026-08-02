# Primary Issue #205 (PR 1): Filesystem & POSIX Operation Migration Inventory

**Document Version:** 1.0.0  
**Target Issue:** Primary Issue #205 (`[P0 architecture] Add a cross-platform safe-filesystem backend for reader, request, output, and installer paths`)  
**Phase:** PR 1 — API, capability contract, and migration inventory  
**Date:** 2026-08-02  
**Target Package:** `src/portable_resume`  

---

## 1. Executive Summary

As part of Primary Issue #205 Phase PR 1, an exhaustive static AST-based survey of all Python modules in `src/portable_resume/` was conducted to catalog direct POSIX, filesystem, SQLite, and file-locking operations.

### Key Metrics
- **Total Modules Analyzed:** 52 Python files
- **Total Direct Filesystem Operation Calls:** 1,299 call sites
- **Non-Goal Modules (PR 1):** 12 files (660 direct calls, 50.8% of total)
- **Candidate Modules (PR 1):** 40 files (639 direct calls, 49.2% of total)
  - Active Candidate Modules (>0 calls): 27 files (639 calls)
  - Zero-Call Candidate Modules: 13 files (0 calls)

This inventory establishes the structural baseline for introducing the cross-platform abstraction package `src/portable_resume/platform_fs/` while maintaining strict compliance with Requirement R4 non-goal boundaries.

---

## 2. Boundaries & Non-Goal Requirements (Requirement R4)

Requirement R4 defines explicit non-goal boundaries for PR 1:

1. **Excluded Call Sites in PR 1:**
   - **`src/portable_resume/snapshot.py`** (102 calls): High-level snapshotting and live database query logic remain unchanged in PR 1.
   - **`src/portable_resume/request.py`** (11 calls): Inert handoff request processing and descriptor validation remain unchanged in PR 1.
   - **`src/portable_resume/output_write.py`** (24 calls): Safe atomic document output writing remains unchanged in PR 1.
   - **`src/portable_resume/install/*`** (9 modules, 523 calls): Installer runtime, transaction engine (`transaction.py`), catalog discovery, and manifest management remain unchanged in PR 1.
2. **Platform & Installer Constraints:**
   - Windows mutating installer features are **NOT** enabled in PR 1; `E_INSTALL_UNSUPPORTED_PLATFORM` is strictly preserved on unsupported platforms.
3. **Behavioral Integrity:**
   - No source adapter session parsing logic, session selection logic, or output rendering format is modified.
4. **Runtime Dependencies:**
   - Stdlib-only runtime with zero third-party external package dependencies.

---

## 3. Complete Migration Inventory Table

The table below lists all 52 modules in `src/portable_resume/`, their assigned categorization, static call count of direct filesystem operations, key primitives used, and PR 1 migration status.

| Module / File Path | Category | Direct FS Calls | Key FS Primitives Used | Migration Status in PR 1 |
|---|---|---|---|---|
| `src/portable_resume/__init__.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/adapters/__init__.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/adapters/antigravity.py` | CANDIDATE | 37 | `os.lstat`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open`, `os.environ.get` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/base.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/adapters/claude.py` | CANDIDATE | 37 | `open`, `os.environ.get`, `os.lstat`, `os.path.abspath`, `os.path.commonpath`, `os.path.dirname`, `os.path.expanduser`, `os.path.exists`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `os.path.realpath` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/cline.py` | CANDIDATE | 46 | `os.environ.get`, `os.listdir`, `os.lstat`, `os.path.abspath`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.exists`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open`, `sqlite3.connect` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/codex.py` | CANDIDATE | 29 | `os.access`, `os.environ.get`, `os.lstat`, `os.path.basename`, `os.path.expanduser`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open`, `os.path.getsize` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/codex_sqlite.py` | CANDIDATE | 8 | `os.lstat`, `os.path.getsize`, `os.path.isabs`, `os.path.isdir`, `os.path.join` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/common.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/adapters/crush.py` | CANDIDATE | 18 | `os.lstat`, `os.path.abspath`, `os.path.basename`, `os.path.dirname`, `os.path.getsize`, `os.path.isabs`, `os.path.isdir`, `os.path.join` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/cursor.py` | CANDIDATE | 50 | `os.environ.get`, `os.listdir`, `os.lstat`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.exists`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open`, `sqlite3.connect` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/cursor_live.py` | CANDIDATE | 26 | `os.lstat`, `os.path.dirname`, `os.path.expanduser`, `os.path.getsize`, `os.path.isfile`, `os.path.join`, `open`, `sqlite3.connect`, `os.environ.get` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/gemini.py` | CANDIDATE | 37 | `os.environ.get`, `os.listdir`, `os.lstat`, `os.path.abspath`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.exists`, `os.path.isdir`, `os.path.isfile`, `os.path.join` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/github_copilot.py` | CANDIDATE | 33 | `os.environ.get`, `os.listdir`, `os.lstat`, `os.path.abspath`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.exists`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/goose.py` | CANDIDATE | 13 | `os.environ.get`, `os.lstat`, `os.path.expanduser`, `os.path.getsize`, `os.path.isdir`, `os.path.isfile`, `os.path.join` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/grok.py` | CANDIDATE | 38 | `os.environ.get`, `os.lstat`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.exists`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/hermes.py` | CANDIDATE | 14 | `os.environ.get`, `os.lstat`, `os.path.abspath`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/kimi.py` | CANDIDATE | 63 | `os.environ.get`, `os.lstat`, `os.path.basename`, `os.path.dirname`, `os.path.exists`, `os.path.expanduser`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open`, `sqlite3.connect` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/openclaw.py` | CANDIDATE | 12 | `os.lstat`, `os.path.expanduser`, `os.path.getsize`, `os.path.isdir`, `os.path.join`, `os.path.abspath`, `os.environ.get` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/opencode.py` | CANDIDATE | 35 | `os.environ.get`, `os.path.basename`, `os.path.expanduser`, `os.path.getsize`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open`, `os.lstat`, `sqlite3.connect` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/openhands.py` | CANDIDATE | 40 | `os.environ.get`, `os.listdir`, `os.lstat`, `os.path.abspath`, `os.path.basename`, `os.path.dirname`, `os.path.expanduser`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/pi.py` | CANDIDATE | 12 | `os.lstat`, `os.path.abspath`, `os.path.expanduser`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/adapters/qwen.py` | CANDIDATE | 31 | `os.environ.get`, `os.lstat`, `os.path.abspath`, `os.path.basename`, `os.path.exists`, `os.path.expanduser`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/bounds.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/build_identity.py` | CANDIDATE | 5 | `os.close`, `os.fstat`, `os.open`, `os.read` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/config_layer.py` | CANDIDATE | 1 | `os.path.expanduser` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/contracts.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/diagnostics.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/discover_doctor.py` | CANDIDATE | 5 | `os.getcwd`, `os.path.dirname`, `os.path.isfile`, `os.path.join` | CANDIDATE (Diagnostics integrated in PR 1 R2) |
| `src/portable_resume/handoff.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/install/__init__.py` | NON-GOAL | 0 | `None` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/catalog.py` | NON-GOAL | 13 | `os.getcwd`, `os.path.expanduser`, `os.path.isabs`, `os.path.join`, `os.path.realpath` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/cli.py` | NON-GOAL | 11 | `os.getcwd`, `os.path.expanduser`, `os.path.realpath` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/control_schema.py` | NON-GOAL | 1 | `os.path.isabs` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/discovery.py` | NON-GOAL | 31 | `os.close`, `os.fstat`, `os.lstat`, `os.open`, `os.path.basename`, `os.path.commonpath`, `os.path.dirname`, `os.path.exists`, `os.path.isabs`, `os.path.join` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/manifest.py` | NON-GOAL | 8 | `os.close`, `os.fstat`, `os.open`, `os.path.islink`, `os.path.realpath`, `os.read` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/package_contracts.py` | NON-GOAL | 1 | `stable_read_bytes` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/render.py` | NON-GOAL | 0 | `None` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/install/transaction.py` | NON-GOAL | 458 | `fcntl.flock`, `os.close`, `os.fchmod`, `os.fstat`, `os.fsync`, `os.lstat`, `os.mkdir`, `os.open`, `os.path.*`, `os.replace`, `os.unlink`, `os.write`, `open` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/model.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/output_write.py` | NON-GOAL | 24 | `os.close`, `os.fchmod`, `os.fsync`, `os.lstat`, `os.open`, `os.path.*`, `os.replace`, `os.write`, `open` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/paths.py` | CANDIDATE | 21 | `os.fspath`, `os.getcwd`, `os.lstat`, `os.path.abspath`, `os.path.commonpath`, `os.path.dirname`, `os.path.expanduser`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/reader.py` | CANDIDATE | 15 | `os.close`, `os.fstat`, `os.getcwd`, `os.open`, `os.path.dirname`, `os.path.exists`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `open` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/registry.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/request.py` | NON-GOAL | 11 | `os.close`, `os.fstat`, `os.lseek`, `os.lstat`, `os.open`, `os.path.*`, `os.read`, `open` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/sanitize.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/search_sessions.py` | CANDIDATE | 1 | `os.getcwd` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/select.py` | CANDIDATE | 1 | `os.path.isabs` | CANDIDATE (Target for future backend migration) |
| `src/portable_resume/snapshot.py` | NON-GOAL | 102 | `open`, `os.chmod`, `os.close`, `os.fstat`, `os.fsync`, `os.lseek`, `os.lstat`, `os.mkdir`, `os.open`, `os.path.*`, `sqlite3.connect` | EXCLUDED (Explicit Non-Goal per R4) |
| `src/portable_resume/time_range.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/version_state.py` | CANDIDATE | 0 | `None` | N/A (No FS Calls) |
| `src/portable_resume/workspace.py` | CANDIDATE | 11 | `open`, `os.getcwd`, `os.path.commonpath`, `os.path.dirname`, `os.path.isabs`, `os.path.isdir`, `os.path.isfile`, `os.path.join`, `os.lstat` | CANDIDATE (Target for future backend migration) |

---

## 4. Analysis by Category & Scope

### 4.1 Non-Goal Modules Analysis (12 Files, 660 Direct Calls)

The Non-Goal set contains all core mutating primitives, atomic transaction write loops, snapshot logic, and installation engine code.

1. **`src/portable_resume/install/transaction.py` (458 calls):**
   - Implements descriptor-relative file mutations, directory creation, lock acquisition via `fcntl.flock`, chmod/sync, and rollback tracking.
   - Excluded in PR 1 to prevent regression of critical installer safety mechanisms while building the `platform_fs` backend foundation.
2. **`src/portable_resume/snapshot.py` (102 calls):**
   - Handles strict no-follow directory traversal (`_open_directory_beneath`), safe file opening, and SQLite live database read connections (`query_only_live_sqlite`, `private_sqlite_connection`).
   - Excluded in PR 1 per R4.
3. **`src/portable_resume/output_write.py` (24 calls):**
   - Implements atomic document emission (`write_output_atomic_safe`) using temporary file descriptor creation, fchmod, fsync, and atomic replacing (`os.replace`).
   - Excluded in PR 1 per R4.
4. **`src/portable_resume/install/discovery.py` & `catalog.py` & `cli.py` & `manifest.py` & `control_schema.py` & `package_contracts.py` (65 total calls):**
   - Manage host environment inspection, install path normalization, manifest generation, and contract validation. Excluded in PR 1 per R4.

### 4.2 Candidate Modules Analysis (40 Files, 639 Direct Calls)

The Candidate set includes all source adapters (19 implementations) and core configuration/reader infrastructure.

1. **Source Adapters (19 Modules, 586 Calls):**
   - Adapters perform read-only discovery of local LLM host session logs (e.g., Kimi `63` calls, Cursor `50` calls, Cline `46` calls, OpenHands `40` calls, Grok `38` calls, Antigravity `37` calls, Claude `37` calls, Gemini `37` calls).
   - Primitives used include `os.lstat` for symbolic link detection, `sqlite3.connect` for DB-backed hosts (Kimi, Cursor, Cline, OpenCode), and `open()` for JSON/JSONL reading.
   - In PR 1, all 19 adapter call sites remain unmutated; they serve as candidates for future backend routing in subsequent PR phases.
2. **Core Infrastructure Candidate Modules (8 Active Modules, 53 Calls):**
   - `paths.py` (21 calls): Path validation, relative normalization under safe roots, and symlink resolution checks (`os.lstat`, `os.path.commonpath`).
   - `reader.py` (15 calls): Session data reading and validation (`os.open`, `os.fstat`, `os.close`).
   - `workspace.py` (11 calls): Safe workspace path boundary checks.
   - `discover_doctor.py` (5 calls): Doctor/health diagnostic reporting (updated in PR 1 R2 to report `FilesystemCapabilities`).
   - `build_identity.py` (5 calls): Build metadata extraction.
   - `config_layer.py` (1 call), `select.py` (1 call), `search_sessions.py` (1 call): Configuration directory expansion and path isolation checks.
3. **Zero-Call Candidate Modules (13 Modules, 0 Calls):**
   - Data models, contracts, bounds, diagnostic definitions, and adapter base interfaces (`contracts.py`, `diagnostics.py`, `model.py`, `registry.py`, `sanitize.py`, `time_range.py`, `version_state.py`, `bounds.py`, `handoff.py`, `__init__.py`, `adapters/__init__.py`, `adapters/base.py`, `adapters/common.py`).

---

## 5. Cross-Platform Primitive Mapping (`platform_fs` Architecture)

The high-level method contract designed for `FilesystemBackend` in `src/portable_resume/platform_fs/api.py` directly addresses the low-level primitives identified across Candidate and Non-Goal modules:

| High-Level `FilesystemBackend` Method | Low-Level FS Primitives Abstracted | Target Use Cases in Future PRs |
|---|---|---|
| `read_regular_stable(path, max_bytes)` | `os.open` (`O_NOFOLLOW`/`O_CLOEXEC`), `os.fstat`, `os.read`, `os.close` | Safe read-only file access in `reader.py`, `build_identity.py`, and source adapters |
| `mkdirs_beneath(root_fd_or_path, rel_path)` | `os.mkdir`, `os.open`, `os.fstat` descriptor relative traversal | Safe directory creation in `install/transaction.py` and output writing |
| `unlink_beneath(root_fd_or_path, rel_path)` | `os.unlink`, `os.open` | Safe file deletion beneath approved roots |
| `replace_beneath(root_fd, src_rel, dst_rel)` | `os.replace`, `os.open`, `os.fsync` | Atomic file swapping in transaction engine |
| `sqlite_family_snapshot(db_path)` | `sqlite3.connect`, WAL/SHM file copying, `os.lstat` | Safe SQLite reading in `snapshot.py`, `cursor.py`, `kimi.py`, `cline.py` |
| `atomic_replace_output(target_path, data)` | Temporary file descriptor creation, `fchmod`, `fsync`, `os.replace` | Atomic document writing in `output_write.py` |
| `acquire_exclusive_lock(lock_path)` | `fcntl.flock`, `os.open` | Lock acquisition in installer transaction engine |

---

## 6. Verification & Quality Assurance Protocol

To verify the accuracy of this inventory and maintain repository quality standards:

### 6.1 Static Inventory Verification Commands
```bash
python D:\OtherProject\mine\resume-skills\.agents\explorer_survey_1\survey_fs.py
python D:\OtherProject\mine\resume-skills\.agents\explorer_survey_1\summarize_inventory.py
```
*Verification Check:* Confirms 52 total modules analyzed, 12 Non-Goal modules (660 calls), and 40 Candidate modules (639 calls).

### 6.2 Mandatory Project Verification Suite
All PR 1 implementations must pass the four canonical quality gates prior to merge:
```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

---

## 7. Conclusion

This Migration Inventory document establishes the baseline for Issue #205 PR 1. By clearly separating Non-Goal modules (12 files, 660 calls) from Candidate modules (40 files, 639 calls), PR 1 satisfies Requirement R3 and enforces Requirement R4 non-goal boundaries.

---

## 8. Codex Review & Capability Flags Disposition (PR 1 Honesty Alignment)

### 8.1 Capability Flag Honesty Corrections
To ensure `doctor` diagnostics and system capabilities reflect current PR 1 implementation reality without overclaiming:

- **`WindowsFilesystemBackend`**:
  - `nofollow_reads = False` (In PR 1, `read_regular_stable` uses `lstat()` followed by standard `open()`, which does not guarantee handle-level/descriptor-level reparse point isolation; handle-based nofollow read is deferred to PR 3).
  - `handle_locking = False` (In PR 1, `acquire_exclusive_lock` raises `E_INSTALL_UNSUPPORTED_PLATFORM`; locking is deferred to future PRs).
- **`PosixFilesystemBackend`**:
  - `relative_mutations = False` (In PR 1, `mkdirs_beneath` uses string-path `os.makedirs`; descriptor-relative `mkdirat` mutations are deferred to PR 2).

### 8.2 Codex Inline Review Disposition Table

| Finding ID | Priority | Description / Location | PR 1 Disposition | Target PR |
|---|---|---|---|---|
| P1-1 | P1 | Windows `read_regular_stable` TOCTOU / nofollow (`windows.py`) | Flag set to `nofollow_reads=False` (Honest). Full handle-based read implementation deferred. | PR 3 (Windows Reader Backend) |
| P1-2 | P1 | Windows SQLite snapshot non-atomic sidecar copy (`windows.py`) | Scaffold implementation retained for PR 1 identity. Atomic VFS/shadow copy deferred. | PR 3 (Windows Reader Backend) |
| P1-3 | P1 | POSIX `mkdirs_beneath` string paths (`posix.py`) | Flag set to `relative_mutations=False` (Honest). Full `mkdirat`/`openat` deferred. | PR 2 (POSIX Mutating Operations) |
| P1-4 | P1 | POSIX `unlink_beneath` leaf resolution (`posix.py`) | Leaf resolution safety deferred to PR 2 mutating operations refactor. | PR 2 (POSIX Mutating Operations) |
| P1-5 | P1 | Runtime allowlist missing `platform_fs` (`render.py`) | **RESOLVED** in commit `aba7d86` (`render.py` + `test_runtime_package_allowlist.py`). | Fixed in PR 1 |
| P2-1 | P2 | Read budget bytes not charged on Windows read (`windows.py`) | **RESOLVED** in commit `aba7d86` (`budget.consume_bytes(len(data))`). | Fixed in PR 1 |
| P2-2 | P2 | SQLite family snapshot `max_bytes` boundary checking (`posix.py`, `windows.py`) | **RESOLVED** in commit `aba7d86` (`DEFAULT_BOUNDS.with_overrides(sqlite_snapshot_bytes=max_bytes)`). | Fixed in PR 1 |


