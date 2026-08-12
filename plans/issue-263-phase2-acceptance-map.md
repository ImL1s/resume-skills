# Issue #263 Phase 2: coherent live-WAL snapshot acceptance map

Status: **production implementation blocked pending an independent security
review of this map**.

This document is the pre-production contract for the macOS/APFS phase of
issue #263. It does not enable live-WAL recovery by itself. Phase 1 retains the
closed `E_SQLITE_LIVE_WAL` behavior on every unsupported path.

Phase 1 PR #269 is an explicit prerequisite. This Phase 2 branch and draft PR
must remain stacked on the current reviewed Phase 1 HEAD until #269 merges,
then be rebased onto that merge before production work begins. Consequently,
all Phase 1 regression IDs named below must already exist on this mapping
commit's exact HEAD; future placeholder test names do not satisfy the gate.

## Scope and fixed safety boundary

- First consumer: OpenCode list/show through a private SQLite snapshot.
- Enabled backend: Darwin on a real APFS source and same-volume APFS scratch
  where a real `fclonefileat` call succeeds.
- Unsupported Darwin filesystems, Linux, Windows, missing symbols, and failed
  capability probes remain `E_SQLITE_LIVE_WAL` (`exit_code: 6`, `attempts: 0`).
- The reader never opens a SQLite connection to the source family, invokes the
  source CLI, copies source SHM, deletes a WAL, or uses `immutable=1`.
- All parsing, integrity checks, schema checks, and queries run against a
  private `0700` directory and a percent-encoded
  `mode=ro&cache=private` URI with `PRAGMA query_only=ON` read back as `1`.
- The stdlib-only runtime and existing lower-only `Bounds` contract remain.

Forbidden alternatives: SQLite online backup against the source, a normal
read-only source connection, `nolock=1`, source SHM copying, manual checkpoint
or WAL deletion, unbounded retry, and mocked capability as production proof.

## Protocol and acceptance point

One absolute monotonic deadline covers attempts, descriptor validation,
cloning, WAL parsing/copying/revalidation, private integrity/schema checks,
and the consumer query.

1. Validate all fixed ceilings before source I/O.
2. Open the approved source parent descriptor-relative beneath the configured
   root. Pin main and WAL using `O_RDONLY|O_CLOEXEC|O_NOFOLLOW`; compare each
   basename entry identity with `fstat`. Validate any SHM as regular/no-follow
   and bind its identity, but never copy or parse SHM. A present rollback
   journal remains `E_SQLITE_HOT_JOURNAL`; symlink/non-regular members remain
   `E_UNSAFE_PATH` and take priority over advisory diagnostics.
3. Read and validate the complete 32-byte WAL header from the pinned WAL before
   cloning main. Accept only SQLite WAL magic `0x377f0682`/`0x377f0683`, version
   `3007000`, a power-of-two page size from 512 through 65536 (including the
   encoded 65536 case), valid header checksum, checkpoint sequence, salts, and
   checksum words. The generation identity is the full raw header plus pinned
   WAL `(device,inode)`, not salts alone.
4. Allocate a random `0700` private scratch directory outside the source root.
   Prefer a pinned canonical temporary root when it is same-volume APFS; a
   random sibling under a pinned approved parent is the fallback. Creation,
   enumeration, cleanup, and final removal are descriptor-relative. Bind the
   scratch pathname entry to its opened directory descriptor.
5. Preflight free space with `f_bavail * f_frsize`, then require the source
   logical main size, prospective complete WAL prefix, and a fixed 64 MiB
   reserve to fit. Repeat after clone using the private main's authoritative
   logical size.
6. Call real Darwin `fclonefileat(srcfd, dst_dirfd, dst, flags)` from the pinned
   **source-file** descriptor into the pinned private directory, with a fixed
   slash-free destination name, `CLONE_NOFOLLOW|CLONE_NOOWNERCOPY`, and no ACL
   copy. This is deliberately `fclonefileat`, not the five-argument
   pathname-source `clonefileat`: Apple's XNU `clonefile(2)` declares the first
   argument as `int srcfd` and states that the source is identified by that file
   descriptor rather than a path
   (<https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/clonefile.2>).
   The `ctypes` wrapper must declare that exact four-argument ABI and a real
   descriptor-bound test must prove pathname replacement cannot redirect the
   clone. Open the result no-follow, require regular/same-device, bind its
   identity, and force mode `0600`.
7. Re-read the pinned source WAL header. Any raw-header/generation change,
   reset, shrink, or replacement rejects this attempt as `E_SOURCE_BUSY`.
8. Capture the bounded current-generation prefix from the physically complete
   frames:

   ```text
   frame_size = 24 + page_size
   N = 32 + floor((wal_size - 32) / frame_size) * frame_size
   ```

   First bound `N` by the WAL byte/frame ceilings. Stream with bounded `pread`
   and validate every current-generation frame's nonzero page number,
   cumulative checksum, and database-size commit marker using SQLite's
   documented WAL byte order. SQLite may restart a fully checkpointed WAL in
   place without shrinking it: the first physically complete frame whose salts
   differ from the validated current header explicitly ends the logical prefix,
   and the remaining prior-generation bytes are not copied, but only after the
   current generation has established a checksum-valid commit boundary. A
   same-generation invalid page/checksum and a salt transition before any
   current commit are never shortened into success. Track the last valid commit
   frame and committed database-page count. A partial physical tail is deferred
   to a future run.
9. Write only `snapshot.sqlite-wal` in private scratch (`0600`, create-exclusive,
   no-follow). Re-read or digest-and-compare the exact accepted source prefix,
   require current source WAL length `>= N`, and require unchanged full header,
   source parent membership, main/WAL pathname identities, and descriptor-relative
   absence of a rollback journal immediately before acceptance. Append strictly
   beyond `N` is allowed. Interior mutation, shrink/regrow, generation reset,
   pathname replacement, or a rollback journal created after initial validation
   rejects the attempt (`E_SQLITE_HOT_JOURNAL`).
10. The private family is accepted only after steps 1-9 succeed. Legal source
    changes after that point belong to the next run. Do not compare source main
    content/mtime after the atomic clone: a legal checkpoint may update source
    main while the private clone remains paired with the same-generation WAL.
11. Open only the private URI, set and read back query-only, install a deadline
    progress handler, run `PRAGMA integrity_check(1)`, validate exact OpenCode
    schema, then run list/show. Any SQLite-created SHM must remain in scratch.
12. Close SQLite first. Enumerate and unlink known private artifacts through the
    pinned scratch descriptor, reject unknown nested entries, close descriptors,
    and remove scratch through its pinned parent. Cleanup is idempotent on
    success, retry, diagnostic, cancellation, consumer exception, and integrity
    failure. Cleanup failure is `E_INVARIANT`, never silent success.

The correctness claim is limited to this pairing: the atomic main-file image is
overlaid by a checksum-valid prefix from the same pinned WAL generation. All
checksum-valid commits at or before the accepted prefix are recoverable;
transactions committed after the accepted prefix may be absent until the next
run. Uncommitted tail frames are never claimed as committed output.

## Fixed bounds and errno policy

Proposed defaults, which callers may lower but never raise:

- `sqlite_cow_logical_bytes = 2_147_483_648` (covers the observed
  1,414,021,120-byte OpenCode main file)
- `sqlite_wal_bytes = 268_435_456`
- `sqlite_wal_frames = 524_288`
- `sqlite_snapshot_deadline_ms = 30_000`
- existing `snapshot_attempts = 3`
- private reserve `_SQLITE_COW_RESERVE_BYTES = 67_108_864`

`fclonefileat` capability failures (`ENOTSUP`, `EXDEV`, `EROFS`, `EINVAL`,
`EACCES`, `EPERM`) try the next eligible scratch and then return the closed
unsupported live-WAL diagnostic. `ENOSPC`, `EDQUOT`, and `EFBIG` are
`E_LIMIT_EXCEEDED`. `EEXIST` permits only a bounded new random private name.
Validated-entry `ELOOP`/`ENOTDIR`/`ENOENT` fails closed; `EINTR`/`EAGAIN`/`EBUSY`
may retry only within attempts/deadline; `EIO` discards the attempt; impossible
ABI results are `E_INVARIANT`. Unknown errno never enables capability.

### Deadline decision requiring security approval

The deadline is checked immediately before and after the atomic
`fclonefileat` syscall and an overrun is rejected immediately after return.
Darwin exposes no timeout or cancellation parameter for that individual kernel
call, so it cannot be preempted safely in-process. All user-space loops and
SQLite work are preemptible by the same deadline. This map proposes accepting
that narrow boundary rather than adding an out-of-scope helper process, FD
handoff, termination, and orphan-cleanup surface. If a hard preemptive wall-clock
cap around the syscall is mandatory, security review must block production
implementation and require a separately designed helper process.

## Mandatory 11-row evidence map

Every name below must exist on the final implementation HEAD. A skipped test,
mocked clone, retry-after-flake, or result from an older SHA is not proof.

### 1. Actual oversized live-WAL branch

- `tests/adapters/test_opencode_antigravity_grok.py::OpenCodeAdapterTests.test_issue263_cow_list_show_cross_lowered_snapshot_ceiling`
- Real harness scenario `oversized_live_wal_list_show`.
- Lower the ordinary byte-copy snapshot ceiling below the live main size and
  prove both list and resolved show use the COW branch and return the expected
  session without a source SQLite connection.

### 2. Unsupported backend

- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_unsupported_linux_other_non_apfs_and_missing_symbol_fail_live_wal_contract`
- Re-run Phase 1's full sidecar-validation/no-connect regression.
- Assert exact `E_SQLITE_LIVE_WAL`, exit 6, attempts 0, provider, bounded family,
  static hint, no scratch residue, and no source SQLite connection.

### 3. Normal live WAL

- `tests/unit/test_sqlite_wal_prefix.py::WalPrefixTests.test_complete_checksum_valid_prefix_tracks_last_commit`
- `tests/unit/test_sqlite_wal_prefix.py::WalPrefixTests.test_restarted_wal_excludes_previous_generation_physical_tail`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_append_beyond_accepted_prefix_is_deferred_without_losing_committed_prefix`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_restarted_wal_stale_tail_survives_repeated_checkpoints`
- Real scenarios `continuous_append`, `checkpoint_before_clone`, and
  `checkpoint_after_clone`.
- Every success has `integrity_check=ok`, sees the anchor commit, and does not
  require a transaction committed beyond the accepted prefix.

### 4. Generation changes

- `tests/unit/test_sqlite_wal_prefix.py::WalPrefixTests.test_reset_shrink_header_salt_and_interior_rewrite_rejected`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_generation_reset_truncate_replace_and_prefix_mutation_are_busy_and_cleanup`
- Real scenarios `restart_reset`, `truncate_reset`, `wal_replace`,
  `header_salt_change`, and `prefix_mutation`.
- Each forced event must produce a bounded closed rejection and zero residue;
  shrink-then-regrow cannot pass on length alone.

### 5. Path safety

- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_source_main_wal_shm_symlink_and_nonregular_are_unsafe_without_side_effect`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_source_parent_main_wal_and_scratch_path_swaps_fail_closed`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_transient_main_path_swap_restore_cannot_change_fd_clone_source`
- Cover symlink/non-regular main, WAL, and SHM; parent replacement; main/WAL
  rename replacement; transient source-main swap-and-restore during the clone;
  scratch replacement; basename membership revalidation; no-follow opens;
  cleanup without following attacker-controlled paths. The transient-swap test
  must assert the private clone bytes/inode provenance come from the pinned
  source fd, never the temporary pathname replacement.

### 6. Static source immutability

- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_quiescent_source_main_wal_shm_digest_inode_mode_mtime_xattr_and_entries_unchanged`
- Real scenario `quiescent_immutability` with an xattr-aware test-only capture.
- Compare bytes/digests, device/inode, mode, mtime, xattrs where supported, and
  source-root entries. Metadata such as atime that the platform updates merely
  on read is not presented as a cross-platform invariant.

### 7. Concurrent writer ownership

- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_reader_mutation_and_connect_audit_never_targets_source_root`
- Real scenario `writer_ownership_audit`.
- Separately record writer-owned commits/checkpoints and instrument every
  reader write-open, create, mkdir, unlink, rename/replace, clone destination,
  and SQLite URI. Reader-owned mutation beneath source root must remain zero.

### 8. Private-only SQLite effects

- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_private_query_only_connection_rebuilds_only_private_shm_and_passes_integrity`
- `tests/adapters/test_opencode_antigravity_grok.py::OpenCodeAdapterTests.test_issue263_cow_connection_validates_opencode_schema_and_private_uri`
- Assert private percent-encoded URI, private cache, read-back query-only,
  private-only SHM, integrity result, exact schema, and close-before-cleanup.

### 9. Fallback contract

- Re-run these exact Phase 1 regressions from
  `tests/adapters/test_opencode_antigravity_grok.py::OpenCodeAdapterTests`:
  - `test_issue263_live_wal_degrades_to_file_store_with_warning`
  - `test_issue263_live_wal_without_fallback_rethrows_diagnostic`
  - `test_issue263_empty_or_ineligible_fallback_does_not_hide_live_wal`
  - `test_issue263_alternate_sqlite_without_eligible_rows_does_not_hide_live_wal`
  - `test_issue263_exact_fallback_ref_stays_bound_when_sqlite_recovers`
  - `test_issue263_exact_sqlite_ref_rejects_different_source_path`
  - `test_issue263_exact_export_ref_rejects_unapproved_root_json`
  - `test_issue263_file_store_show_requires_query_admitted_session_path`
  - `test_issue263_unsafe_live_sidecar_does_not_degrade_to_fallback`
  - `test_issue263_fallback_duplicate_remains_ambiguous`
  - `test_issue263_only_live_or_busy_sqlite_errors_degrade`
- When COW succeeds it is authoritative SQLite output. When the backend is
  unsupported, the established provider-local Phase 1 fallback policy remains.

### 10. Resource contract

- `tests/unit/test_sqlite_cow_bounds.py::SQLiteCowBoundsTests.test_defaults_are_finite_cover_observed_store_and_callers_cannot_raise`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_same_volume_free_space_headroom_deadline_cancellation_and_cleanup`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_clone_errno_capability_mapping`
- Cover logical main, WAL bytes/frames, attempts, one deadline, free-space
  reserve, same-volume/APFS checks, cancellation, integrity/schema failure,
  all errno classes, zero leaked descriptors, and zero leaked scratch.

### 11. Regression and packaging

- Re-run these exact snapshot regressions:
  - `tests/security/test_snapshot.py::StableSnapshotTests.test_sqlite_rollback_journal_fails_closed`
  - `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_rollback_journal_created_between_validation_and_acceptance_fails_closed`
  - `tests/security/test_snapshot.py::StableSnapshotTests.test_sqlite_family_race_retries_then_busy_and_cleans_private_dirs`
  - `tests/security/test_verifier_regressions.py::VerifierRegressionTests.test_sqlite_post_verification_same_stat_mutation_fails_closed`
- Update and run these exact runtime/installed-package regressions for the new
  Darwin helper, without adding a dependency:
  - `tests/unit/test_runtime_package_allowlist.py::RuntimePackageAllowlistTests.test_runtime_allowlist_is_explicit_complete_and_excludes_installer`
  - `tests/unit/test_runtime_package_allowlist.py::RuntimePackageAllowlistTests.test_materialized_runtime_matches_allowlist_exactly`
  - `tests/e2e/test_installed_runner_and_relocation.py::InstalledRunnerTests.test_installed_run_reader_request_boundary_and_fixture_handoff`
  - `tests/e2e/test_installed_runner_and_relocation.py::RelocationTests.test_copy_tree_installs_from_relocated_checkout`
  - `tests/e2e/test_relocated_bundle.py::RelocatedBundleTests.test_relocated_copy_self_check_matrix_install_verify_uninstall`
- Run all four repository gates on the final exact HEAD, including the exact
  registry-derived installed matrix command
  `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py`.

## Real APFS proof harness

Final command shape:

```bash
PYTHONPATH=src python3 scripts/prove_issue263_macos_apfs.py \
  --iterations 200 \
  --output <sanitized-proof.json>
```

The harness must fail, not skip, unless Darwin, APFS, same-volume scratch, and a
real successful `fclonefileat` are present. Minimum non-vacuous evidence:

- at least 100 coherent continuous-append successes;
- at least 25 successes each for checkpoint-before-clone and
  checkpoint-after-clone;
- at least 20 forced bounded rejections each for reset, truncate, WAL
  replacement, header/salt change, accepted-prefix mutation, and source
  pathname replacement;
- `integrity_check=ok` for every success, anchor commit visible, and no future
  or uncommitted row required;
- zero reader-owned source mutation, zero private scratch leaks, and zero FD
  leaks;
- content-free counters only: exact SHA, OS/build/arch, Python/SQLite versions,
  backend/flags, APFS/same-volume booleans, bounded sizes, outcomes, cleanup
  count, and raw-output SHA-256. No source paths or recovered row text.

The exact-head macOS proof job must archive the sanitized artifact and its
Actions URL/SHA. Ordinary mocked tests or a skipped CI lane cannot enable the
backend or close #263.

## Security-review decision record

Production files may be edited only after an independent reviewer records:

1. PASS/BLOCK for every row 1-11;
2. ACCEPT/BLOCK for the non-preemptible atomic clone deadline boundary;
3. any required minimal mapping corrections; and
4. an overall APPROVE/REQUEST_CHANGES verdict on the exact mapping commit.
