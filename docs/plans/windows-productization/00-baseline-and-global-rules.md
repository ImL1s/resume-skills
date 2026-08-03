# 00 — Baseline and global rules

## Baseline snapshot (update when executing)

Record at start of each PR:

```text
git rev-parse HEAD
git log -1 --oneline
```

Expected post-#219 world (adjust if main advanced):

| Fact | Expected |
|------|----------|
| `WindowsFilesystemBackend.acquire_exclusive_lock` | Exists; CreateFileW + LockFileEx |
| Leaf metadata before lock | `GetFileInformationByHandle` fail-closed |
| `_handle_is_invalid` | Full pointer-width INVALID_HANDLE_VALUE |
| `relative_mutations` | `False` |
| `require_mutating_install_platform()` | Raises `E_INSTALL_UNSUPPORTED_PLATFORM` when `os.name == "nt"` |
| `RootLock.__enter__` | Calls `require_mutating_install_platform()` **before** creating support paths (POSIX uses `fcntl`) |
| Issues | **#125 OPEN**, **#209 OPEN** |

Key code:

- `src/portable_resume/platform_fs/windows.py` — backend, lock, fail-closed mutations  
- `src/portable_resume/platform_fs/api.py` — capabilities  
- `src/portable_resume/install/transaction.py` — `require_mutating_install_platform`, `RootLock`, install/uninstall/recover  
- Tests: `tests/unit/test_platform_fs.py`, `tests/unit/test_install_windows_platform_gate.py`, `tests/unit/test_issue_125_residual_contract.py`

## Residual backlog for #125 (productization)

These are the only #125 residuals this pack plans (Phase 1–2 already done):

1. **RootLock wire** → Phase 3  
2. **Reparse-safe relative mutations** → Phase 4  
3. **Parent-chain reparse defenses** → Phase 5  
4. **Adversarial product path evidence** → Phase 6  
5. **Policy B enablement** → Phase 7 only  

## Global must-not-do

See [INDEX.md](INDEX.md). Copy into every PR description:

```text
This PR must NOT lift Policy B / claim dual-OS mutating install / close #125
unless it is Phase 7 with checklist evidence.
```

## Anti-theater rules (all phases)

| Forbidden | Why |
|-----------|-----|
| `unittest.mock` making `os.name == "nt"` the only Windows proof | Not real `nt` |
| Green Ubuntu job labeled “Windows install works” | Wrong OS |
| Closing #125 after lock unit tests only | Primitive ≠ product |
| Setting `relative_mutations=True` without mutation tests on Windows | Honesty breach |
| Marking WSL2/musl/BSD `verified` without runners | #209 lie |

## Minimum Windows environment

```powershell
python -c "import os,sys; assert os.name=='nt', os.name; print(sys.version)"
python -m pytest tests/unit/test_platform_fs.py tests/unit/test_install_windows_platform_gate.py tests/unit/test_issue_125_residual_contract.py -q
```

CI: `.github/workflows` job on `windows-latest` / Python 3.12 (existing `test-windows` pattern).

## Status / docs honesty

When a phase lands, update `docs/STATUS.md` only with:

- what landed  
- what remains open  
- CI run URL on **windows-latest**  

Never write “#205–#209 closed” as a block; keep #125/#209 open until their own gates pass.
