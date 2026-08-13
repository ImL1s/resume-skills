# Issue #263 Phase 2: coherent live-WAL snapshot acceptance map

Status: **mapping approved; implementation hardened after exact-head security
review; revised production implementation and proof are under review in PR
#268**.

This document is the reviewed contract for the macOS/APFS phase of issue #263.
The map itself does not enable live-WAL recovery. Production changes remain
subject to the exact-head gates below, and every unsupported path retains the
closed `E_SQLITE_LIVE_WAL` behavior.

Phase 1 PR #269 merged as `fa897ca`; Phase 2 is rebased on that merge. The
independent review approved all rows 1-11 and accepted the documented deadline
boundary before production implementation began. Phase 1 regression IDs named
below must exist on the final Phase 2 HEAD; placeholder names do not satisfy the
gate.

## Scope and fixed safety boundary

- First consumer: OpenCode list/show through a private SQLite snapshot.
- Enabled backend: Darwin on a real APFS source and same-volume APFS scratch
  where a real `fclonefileat` call succeeds.
- Unsupported Darwin filesystems, Linux, Windows, missing symbols, and failed
  capability probes remain `E_SQLITE_LIVE_WAL` (`exit_code: 6`, `attempts: 0`).
- The reader never opens a SQLite connection to the source family, invokes the
  source CLI, copies source SHM, deletes a source WAL, or uses `immutable=1` on
  a live source. After the accepted private WAL prefix is materialized into the
  private clone, only that exact private vnode is opened with `immutable=1`.
- All parsing, integrity checks, schema checks, and queries run against a
  private `0700` directory and a percent-encoded descriptor-bound
  `file:/dev/fd/<retained-fd>?mode=ro&immutable=1&cache=private` URI with
  `PRAGMA query_only=ON` read back as `1`. The private main has already been
  unlinked and the `/dev/fd` reopen is verified against its retained
  `(device,inode,type)` before SQLite sees the URI.
- The stdlib-only runtime and existing lower-only `Bounds` contract remain.

Forbidden alternatives: SQLite online backup against the source, a normal or
`immutable=1` source connection, pathname-based private SQLite open,
`nolock=1`, source SHM copying, manual checkpoint or WAL deletion, unbounded
retry, and mocked capability as production proof.

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
   clone. Before the syscall, read `ATTR_CMNEXT_CLONEID` from the pinned source
   descriptor through `fgetattrlist`. Open the result no-follow and require a
   regular, single-link, same-device, distinct-inode, exact-size file whose
   descriptor-bound clone ID equals the captured source data-stream ID. This
   rejects a valid same-size database substituted after `fclonefileat` but
   before the result open. Force mode `0600`, then unlink exactly that private
   main vnode with `AT_UNIQUE`; require link count zero and unchanged
   identity, size, and clone ID before continuing. No private-main pathname
   remains during WAL materialization.
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
11. Revalidate the copied private WAL descriptor against the accepted prefix,
    then overlay frames through the last valid commit marker into the retained
    `O_RDWR` private-main descriptor. Later uncommitted frames are ignored;
    frames above the final committed page count are skipped; the private main is
    truncated to that count and `fsync`ed. This is private COW materialization,
    not a source checkpoint. It is bounded by the logical-size/frame/byte limits
    and the same deadline.
12. Capture the private main's new data-stream ID after committed-WAL
    materialization. Verify the retained descriptor is regular, unlinked, and
    still has that exact ID before and after the private-connect hook, after
    SQLite open, after integrity checking, and after the consumer returns.
    Verify that `/dev/fd/<retained-fd>` reopens the same
    `(device,inode,type)`, then open only that descriptor URI with
    `mode=ro&immutable=1&cache=private`, set and read back query-only, install a
    deadline progress handler, run `PRAGMA integrity_check(1)`, validate exact
    OpenCode schema, then run list/show. SQLite does not discover a live WAL or
    create SHM because the accepted commit is already materialized. A transient
    scratch-path replacement or retained attacker pathname cannot redirect this
    open.
13. Close SQLite first, verify the retained unlinked private-main data identity
    once more, and close that descriptor. Unlink the retained private WAL vnode
    and then the retained scratch-directory vnode through their verified
    `/.vol` identities with Darwin
    `unlinkat(AT_UNIQUE|AT_REMOVEDIR-as-needed)`. `AT_UNIQUE` rejects multiple
    path aliases instead of deleting through an ambiguous name. Reject any
    unknown entry on the first incremental directory result and any
    scratch-path replacement; never enumerate or materialize attacker-added
    names and never unlink the replacement. Cleanup is idempotent on success,
    retry, diagnostic, cancellation, consumer exception, and integrity failure.
    Cleanup failure is `E_INVARIANT`, never silent success.

The identity/cleanup primitive is Darwin-specific and capability-gated. Apple's
XNU tests construct `/.vol/<device>/<inode>` paths and verify they resolve the
same inode ([`volfs_chroot.c`](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/tests/vfs/volfs_chroot.c#L49-L85));
XNU lookup marks these as volume-file-system paths and rejects a `UNIQUE`
lookup when the vnode has multiple paths
([`vfs_lookup.c`](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/vfs/vfs_lookup.c#L420-L447),
[`vfs_lookup.c`](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/vfs/vfs_lookup.c#L600-L611)).
The shipped macOS SDK declares `AT_UNIQUE=0x8000` and
`AT_REMOVEDIR=0x0080`; real tests on the supported host must prove both exact
rename-bound removal and multi-link rejection. Failure of any primitive keeps
the backend closed.

Apple's `getattrlist(2)` contract defines `fgetattrlist` as descriptor-bound and
defines `ATTR_CMNEXT_CLONEID` as the unique data-stream identifier shared by
pure clones. It requires `FSOPT_ATTR_CMN_EXTENDED` and the `forkattr` bitmap
field for this attribute
(<https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/getattrlist.2>).
The backend uses this value only as an identity gate around the atomic clone
and private descriptor; it does not treat it as a content digest.

The correctness claim is limited to this pairing: the atomic main-file image is
materialized through the last commit in a checksum-valid prefix from the same
pinned WAL generation, then opened through the exact retained private descriptor. All
checksum-valid commits at or before the accepted commit boundary are
recoverable; transactions committed after it may be absent until the next run.
Uncommitted tail frames are never applied or claimed as committed output.

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
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_private_clone_destination_swap_is_rejected_before_wal_materialization`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_private_clone_retained_attacker_fd_mutation_is_rejected`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_private_main_path_injection_cannot_change_descriptor_bound_query`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_private_scratch_swap_during_connect_cannot_redirect_query`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_cleanup_rmdir_swap_removes_owned_inode_not_replacement`
- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_scratch_nonempty_check_stops_after_first_unknown_entry`
- Cover symlink/non-regular main, WAL, and SHM; parent replacement; main/WAL
  rename replacement; transient source-main swap-and-restore during the clone;
  private-main swap-and-restore at SQLite open; scratch replacement; basename
  membership revalidation; no-follow opens; identity-bound cleanup without
  deleting attacker-controlled replacements. The transient source-swap test
  must assert the private clone bytes/inode provenance come from the pinned
  source fd. The private-swap test must prove SQLite remains bound to the
  original private vnode, and cleanup must remove the relocated owned directory
  while preserving the replacement and returning `E_INVARIANT`. The clone
  destination substitution test must use a valid same-size SQLite replacement
  and prove rejection occurs before WAL materialization; the retained-FD test
  must prove a post-unlink private mutation is detected by the data-stream ID
  gate.

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

- `tests/security/test_sqlite_cow_snapshot.py::SQLiteCowSnapshotTests.test_private_query_only_connection_uses_unlinked_descriptor_and_passes_integrity`
- `tests/adapters/test_opencode_antigravity_grok.py::OpenCodeAdapterTests.test_issue263_cow_connection_validates_opencode_schema_and_private_uri`
- `tests/unit/test_sqlite_wal_prefix.py::WalPrefixTests.test_materialize_applies_only_committed_private_wal_state`
- Assert the percent-encoded `/dev/fd/<retained-fd>` URI reopens the retained,
  already-unlinked private-main inode, uses private cache plus private-only
  `immutable=1`, reads query-only
  back as enabled, does not create SHM, ignores uncommitted tail frames, passes
  integrity/exact schema, and closes SQLite before exact-vnode cleanup.

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
- at least 20 successes where the replaceable private-main pathname is swapped
  before SQLite open and restored after open while the anchor remains visible;
- at least 20 forced bounded rejections each for reset, truncate, WAL
  replacement, header/salt change, accepted-prefix mutation, and source
  pathname replacement, plus clone-destination substitution between
  `fclonefileat` return and result open;
- `integrity_check=ok` for every success, anchor commit visible, and no future
  or uncommitted row required;
- every successful SQLite open uses the verified `file:/dev/fd/...` URI; the
  private main is unlinked before materialization, remaining exact-vnode cleanup
  uses `AT_UNIQUE`, and reader-owned source mutation, private scratch leaks, and
  FD leaks remain zero;
- content-free counters only: exact SHA, OS/build/arch, Python/SQLite versions,
  backend/flags, APFS/same-volume booleans, bounded sizes, outcomes, cleanup
  count, and an adjacent SHA-256 sidecar over the exact canonical JSON artifact
  bytes. No source paths or recovered row text, and no self-referential digest
  field inside the JSON.

The macOS proof job must explicitly checkout the pull-request head SHA, assert
that SHA inside the harness before probing capabilities, name the artifact with
that same SHA, and archive both the sanitized JSON and its exact-byte checksum
sidecar with the Actions URL/SHA. The default synthetic PR merge commit is not
exact-head proof. Ordinary mocked tests or a skipped CI lane cannot enable the
backend or close #263.

## Security-review decision record

The pre-production gate was satisfied on mapping commit `ca3e7b80d5` before
production files were edited:

1. rows 1-10: **PASS** in the detailed review;
2. row 11: **PASS** after adding the final descriptor-relative journal gate;
3. non-preemptible atomic clone deadline boundary: **ACCEPT**; and
4. overall mapping verdict: **APPROVE-equivalent / no remaining BLOCK row**.

Evidence: [decision record](https://github.com/ImL1s/resume-skills/pull/268#issuecomment-5266166606)
and two exact-mapping Codex callbacks with no major issues
([first](https://github.com/ImL1s/resume-skills/pull/268#issuecomment-5266014882),
[second](https://github.com/ImL1s/resume-skills/pull/268#issuecomment-5266080079)).
Those callbacks approve only the map. The production implementation still
requires fresh exact-head gates, real APFS proof, CI artifact, and Codex review.

The first implementation review then found two gaps not covered by the original
map: a scratch-path swap could redirect SQLite before a post-open identity check
([P1](https://github.com/ImL1s/resume-skills/pull/268#discussion_r3767163004)),
and stat-then-`rmdir` cleanup could delete a replacement while leaking the owned
directory
([P2](https://github.com/ImL1s/resume-skills/pull/268#discussion_r3767163012)).
Steps 11-13 and evidence rows 5/8 are the mandatory remediation. The earlier
mapping approvals do not approve this revision; only a fresh review on the
final implementation SHA can clear it.

The next implementation review found one additional P1 and two P2 evidence /
resource gaps: the proof job checked out GitHub's synthetic PR merge commit
instead of the exact head
([P1](https://github.com/ImL1s/resume-skills/pull/268#discussion_r3767439033));
the JSON embedded a digest of a different pre-digest serialization
([P2](https://github.com/ImL1s/resume-skills/pull/268#discussion_r3767439048));
and cleanup materialized every unknown scratch entry with `listdir`
([P2](https://github.com/ImL1s/resume-skills/pull/268#discussion_r3767439060)).
The exact-head checkout/assertion, adjacent exact-byte checksum sidecar, and
single-entry incremental rejection above are mandatory before the final review.

The next exact-head implementation review found that the pathname result of
`fclonefileat` could still be substituted before the reader opened it
([P1](https://github.com/ImL1s/resume-skills/pull/268#discussion_r3768549006)).
The source/destination clone-data-ID comparison, immediate exact unlink,
descriptor URI, retained-ID phase checks, same-size valid-database regression,
and real forced proof rejection above are the mandatory remediation. Earlier
green CI and review evidence do not apply to the amended implementation SHA.
