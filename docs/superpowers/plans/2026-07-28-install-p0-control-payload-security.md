# Installer P0 Control + Payload Security (#21 + #31) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close remaining P0 installer security gaps for control-plane pin/atomic writes (#21) and payload parent-swap resistance across lifecycle ops (#31).

**Architecture:** Extend existing dirfd helpers into shared support-control and payload-beneath-root primitives. Harden RootLock / journal / manifest through no-follow regular-file opens and unique-tmp atomic replace. Route rollback, orphan delete, uninstall, and verify mutations through pinned parents so ambient `realpath`+later-pathname races cannot escape.

**Tech Stack:** Python 3 stdlib (`os`, `fcntl`, `tempfile`, `unittest`); macOS/Linux dirfd + `O_NOFOLLOW`; Windows fail-closed or best-effort lstat (honest residual under #29).

**Spec sources:** GitHub issues #21, #31; goal plan; `docs/STATUS.md` partial notes after PR #49.

---

## File map

| Path | Responsibility |
|---|---|
| `src/portable_resume/install/transaction.py` | Control-store + payload lifecycle security |
| `tests/unit/test_install_control_store.py` | #21 symlink/atomic/lock regressions |
| `tests/unit/test_install_payload_lifecycle_containment.py` | #31 rollback/uninstall/verify/orphan parent-swap |
| `tests/unit/test_install_commit_containment.py` | Existing commit tests must stay green |
| `tests/unit/test_install_recover_containment.py` | Existing recover tests must stay green |
| `SECURITY.md`, `CHANGELOG.md`, `docs/STATUS.md` | Honest done / residual documentation |

---

### Task 1: Control-store primitives + RED tests (#21)

**Files:**
- Create: `tests/unit/test_install_control_store.py`
- Modify: `src/portable_resume/install/transaction.py` (`RootLock`, `_write_journal`, manifest load/write, support ensure)

- [ ] **Step 1: Write failing control-store tests**

Cover at minimum:
1. Symlinked `.portable-resume` rejected before lock/write; outside sentinel unchanged.
2. Symlinked `install.lock` / `journal.json` / `manifest.json` rejected.
3. FIFO (or non-regular) in place of lock/journal rejected when creatable.
4. Shorter PID lock write truncates trailing bytes (no stale suffix).
5. Planted `journal.json.tmp` symlink is not opened; journal write still atomic to regular final file (unique tmp).
6. Partial-style: previous valid manifest survives if writer is interrupted before replace (simulate by ensuring write goes via tmp+replace only).

- [ ] **Step 2: Implement `_ensure_support_directory`, `_atomic_write_support_file`, hardened `RootLock`, `_write_journal`, `load_manifest`, manifest writers**

POSIX path:
- Pin skill root via `_open_skill_root_descriptor`.
- `mkdir`/open `SUPPORT_DIR` with `O_NOFOLLOW|O_DIRECTORY`; reject symlink/non-dir.
- Open control basenames with `O_NOFOLLOW`; `fstat` must be regular file.
- Lock: after flock, `ftruncate(0)` + `lseek(0)` + write `pid=…\n` + optional fsync.
- Atomic docs: unique `.tmp-<hex>` under support, `O_EXCL|O_NOFOLLOW` write, fsync, `os.replace` (dir_fd when available), fsync support dir.
- Non-POSIX: reject support/control symlinks via `lstat`; keep install usable only where existing V1 gates allow; mutating payload still fail-closed without dirfd.

- [ ] **Step 3: Run control-store tests green; keep recover/commit suites green**

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_install_control_store tests.unit.test_install_commit_containment tests.unit.test_install_recover_containment -q
```

---

### Task 2: Payload lifecycle beneath-root primitives + RED tests (#31)

**Files:**
- Create: `tests/unit/test_install_payload_lifecycle_containment.py`
- Modify: `transaction.py` (`_rollback_paths`, orphan remove, `uninstall_claim`, `verify_root`, helpers)

- [ ] **Step 1: Write failing lifecycle tests with outside sentinels**

1. Parent swap before rollback restore → fail closed / recovery-required; outside sentinel unchanged.
2. Parent swap before uninstall delete → outside file not deleted.
3. Parent swap before orphan remove during upgrade → outside file not deleted.
4. Parent swap before verify hash → mismatch/conflict, not outside content accepted as match when crafted.
5. Happy path: reinstall + uninstall still works on normal trees.

- [ ] **Step 2: Implement helpers**

- `_open_regular_under_root(root_fd, rel) -> (parent_fd, fd, basename)` no-follow walk.
- `_sha256_regular_under_root(root_fd, rel) -> str`
- `_unlink_regular_under_root(root_fd, rel, *, expected_sha256=None) -> bool`
- `_replace_regular_under_root(root_fd, rel, src_parent_fd, src_basename)` for rollback from authorized support snapshots.
- Wire execute_install orphan delete, `_rollback_paths`, `uninstall_claim`, `verify_root` to these when dirfd supported; else fail closed on mutation (consistent with commit).

- [ ] **Step 3: Run new + old containment tests**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.unit.test_install_control_store \
  tests.unit.test_install_payload_lifecycle_containment \
  tests.unit.test_install_commit_containment \
  tests.unit.test_install_recover_containment -q
```

---

### Task 3: Docs + full gates + review + PR merge

**Files:** `SECURITY.md`, `CHANGELOG.md`, `docs/STATUS.md`

- [ ] **Step 1: Document hardened control plane + payload path-race policy; honest Windows residual (#29)**
- [ ] **Step 2: Full gates**

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Capture to `{SCRATCH}/gates.log`.

- [ ] **Step 3: Independent AI review (Codex dual-review / requesting-code-review); fix P1s**
- [ ] **Step 4: Open PR, wait CI green + review on HEAD, squash-merge, close/update #21 and #31**

---

## Self-review

1. **Spec coverage:** #21 done bullets map to Task 1; #31 lifecycle bullets map to Task 2; gates/PR map to Task 3.
2. **Placeholders:** none — concrete helpers and commands.
3. **Residual honesty:** Windows exclusive lock remains #29; previous-manifest crash journal enrichment may land as minimal “write manifest via atomic replace” without full previous-manifest snapshot schema if recover already uses path rollbacks — document if deferred.

## Execution note

Goal harness authorized full execution in-session (inline). Prefer frequent small commits on `fix/p0-install-control-payload-security-21-31`.
