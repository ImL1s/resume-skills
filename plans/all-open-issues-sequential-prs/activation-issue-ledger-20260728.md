# Activation Issue Ledger — 2026-07-28

## Frozen baseline

- Planning activation snapshot: `/tmp/resume-skills-issue-inventory/issues.json` captured at `2026-07-28T01:23:52Z`; this temporary file is an input, not durable authority.
- Snapshot issue count: `44`; every snapshot row was `OPEN`.
- Activation/live-refreshed `main`: [`ef2a2f709290cb9e56c6c669bca03f15a12829a9`](https://github.com/ImL1s/resume-skills/commit/ef2a2f709290cb9e56c6c669bca03f15a12829a9).
- Live issue enrichment: `.omx/tmp/live-open-issues-20260728.json` captured at `2026-07-28T02:36:07Z`; the open set still contained the same 44 issue numbers and every issue `updatedAt` exactly matched activation.
- Complete prepared baseline: `.omx/plans/activation-baseline-20260728.jsonl` (raw-byte SHA-256 `015bc85de1fdcdbfa2b2cc0f7d4b175cbc51cd99b97589dbc95f4c02b269d3aa`) plus `.omx/plans/activation-baseline-20260728.manifest.json` (canonical self-hash `72af3d77babab06250bb6682bf9c649e2021e68bc86db4cf9af690476fe6b303`; distinct formatted-file raw SHA-256 `6b8b460581729929d87931d6640b9c9c71508cacba26541e13eab0e8b4612eec`). These are planning bootstrap payloads only.
- Required durable Wave 0 copies: `plans/all-open-issues-sequential-prs/activation-baseline-20260728.jsonl`, `plans/all-open-issues-sequential-prs/activation-baseline-20260728.manifest.json`, and stdlib validator `scripts/validate_activation_baseline.py`. Activation-issue implementation is forbidden until byte-identical copies merge and the tracked validator reproduces every hash/contract from a clean checkout.
- Required dependency/order authority:
  `plans/all-open-issues-sequential-prs/activation-dependency-pairs-20260728.json`
  (212 freshly derived unique pairs; raw SHA-256
  `341592eeb1b7bbacd3ff28c8db7073da1042c92cf75e1a474f512cc71268ec3f`)
  and `plans/all-open-issues-sequential-prs/activation-order-20260728.json`
  (44 reviewed entries; raw SHA-256
  `c0d171be7406c7cae1475e40c51cbbc0ba4c913e4217507ce8decdecb806f36d`).
  Both must merge byte-identically in Wave 0 and be re-derived/validated.
- Manifest contract: omit only top-level `manifest_sha256`, serialize with `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` to UTF-8 with no BOM/trailing newline and preserved array order, then SHA-256. This canonical self-hash is intentionally not the formatted file's raw-byte hash.
- Live CI receipt refreshed at `2026-07-28T02:36:07Z`: [`30320034677`](https://github.com/ImL1s/resume-skills/actions/runs/30320034677), workflow `ci`, event `push`, status `completed`, conclusion `failure`, exact head `ef2a2f709290cb9e56c6c669bca03f15a12829a9`.
- All eight OS/Python matrix jobs failed at step `Self verify`; `build and smoke distributions` was skipped.
- Scope rule: every activation row remains obligated until its activation acceptance criteria are fully discharged with traceable evidence.
- Honesty rule: body references are not automatically dependencies. Unproved dependency or acceptance lineage stays explicitly nonterminal.

## Program-state contract

Allowed working states: `queued`, `selected`, `implementing`,
`continue-required`, `partial-nonterminal`, `successor-opened-nonterminal`,
`blocked-program`, and `resolved`.

Authoritative execution receipts and ownership live on `refs/heads/program-state/all-open-issues-20260728` under the program-state protocol; this Markdown ledger is a planning/readability mirror. Only `resolved` is completion-terminal. Provider `closed`, `duplicate`, or `superseded` state is insufficient without complete acceptance lineage to the resolving final HEAD, tests, CI, AI review, merge, post-merge green main, issue readback, and durable state receipt/pointer release. A hard stop sets the whole program to `blocked-program` and forbids selecting another issue.

An activation issue may have multiple sequential implementation PRs. A merged
PR with remaining acceptance becomes `continue-required`, retains the same
authoritative owner and epoch, and must publish/read back `pr-checkpointed`
before its next PR. It may not release to `idle` or allow another issue.
PR count is therefore not fixed at 44.

The state ref inherits the complete Wave 0 repository tree. Its frozen
commit/tree/path-mode-OID inventory is the non-state anchor; later state
operations must prove exact changed-path equality and may never alter a
non-`state/` path. Authoritative record path components are validated lowercase
UUIDv4 values placed only through trusted fixed templates.

The exact authoritative selection order is persisted by the reviewed order
payload:

```text
Wave 1: 12, 13
Wave 2: 62, 68, 61, 17, 63, 35, 28, 26, 29
Wave 3: 10, 16, 36, 38
Wave 4: 69, 67, 66, 65, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39,
        37, 34, 33, 32, 30, 27, 25, 24, 23, 22, 19, 18, 15, 8, 7
```

`ledger_ordinal` is the one-based concatenated position. Replay derives
prerequisite promotion and selects the minimum
`(selection_wave_number, ledger_ordinal, issue_number)`; this Markdown is only
the human-readable mirror of the tracked JSON authority.

## Required per-row evidence fields

| Field | Required evidence |
|---|---|
| Activation identity | Issue number, exact snapshot title/URL/labels, activation state, snapshot timestamp |
| Dependency lineage | Ordered-pair dependency IDs, subject/related direction, current classification event/ref, derived predecessor/successor/status; otherwise typed `unknown` |
| Acceptance lineage | Tracked complete normalized activation body/contract, full hashes/timestamps/provenance, typed criterion evidence, and exact `unresolved|direct|duplicate|superseded` lineage |
| Selection | Immutable ledger ordinal, planned band, deterministic selector tuple/rationale, branch, authoritative PR authorization, base SHA, final HEAD |
| Local proof | Targeted tests and all four canonical gates tied to final HEAD |
| CI receipt | Stable URL/ID, completed conclusion, checks/jobs, timestamps, exact final-HEAD association |
| AI-review receipt | Non-empty completed review, stable URL/ID, reviewer, timestamp, exact final-HEAD association |
| Findings | Every P1 resolution; every P2 fixed or independently verified as unnecessary for acceptance/invariants/regression/merge/transition safety |
| Transition proof | Pre-publication receipt for merge/green-main/issue/findings/expected-head facts, then separate exact-head-CAS state commit plus remote receipt/manifest/replay readback: same-owner `owned` for partial continuation or `idle` for terminal release |
| Limitations | Unsupported evidence tiers and any blocker without promoting it to completion |

The authoritative per-issue projection additionally requires:

- immutable `activation_id`, issue number/node ID, wave, dependency IDs, and
  acceptance-criterion IDs;
- immutable `ledger_ordinal`; incoming/outgoing/current-unknown dependency IDs;
- lineage mode, sorted target activation identities, typed lineage evidence
  references, and derived `effective_terminal`;
- status, owner identity/token, epoch, per-issue sequence, and current PR
  ordinal;
- planned/current branch, authorization ID, and PR identity/checkpoint;
- ordered completed-PR receipt hashes and any current PR;
- last issue-readback evidence and terminal receipt hash.

The program summary derived by deterministic state replay must report:

- total activation identities (exactly 44);
- effective-terminal baseline count, resolved, owned, queued/eligible, and
  blocked counts;
- blocking/unresolved dependency count and unresolved-lineage count;
- open program-authorized PR count (zero or one; unrelated/Dependabot PRs are
  excluded and cannot satisfy evidence);
- issues with multi-PR history;
- unresolved/unfinalized transition count; and
- completion eligibility, which is true only for 44 unique baseline roots
  evaluated effective-terminal, zero other states, zero active owner/program
  authorization, zero unresolved dependency/lineage, zero invalid transition,
  and fresh final-main evidence.

## Frozen inventory

Rows preserve activation order. Body references are not inferred dependencies. Row digest prefixes are convenience indexes only; the prepared full JSONL and its future byte-identical tracked copy contain the complete body/contract and full hashes. Acceptance remains unresolved until execution evidence discharges every criterion.

| Issue | Exact activation title | URL | Labels | Activation | Planned band | Dependency lineage | Acceptance source | Program state |
|---:|---|---|---|---|---|---|---|---|
| #69 | Make plan and status documentation machine-checkable and remove contradictory completion claims | [issue](https://github.com/ImL1s/resume-skills/issues/69) | `bug`, `priority:P2`, `architecture` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #36, #38, #67 | issue #69 body @ `2026-07-28T02:36:07Z`; `sha256:dfc7722d9f6c2ddd`; unresolved | `queued` |
| #68 | Do not canonicalize away symlinks before exact-path validation | [issue](https://github.com/ImL1s/resume-skills/issues/68) | `bug`, `source-adapter`, `priority:P1`, `architecture`, `security` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 security/correctness | unproven body refs #16, #19, #21, #62 | issue #68 body @ `2026-07-28T02:36:07Z`; `sha256:232395332e310105`; unresolved | `queued` |
| #67 | Stop running documentation checks and the full test suite twice in every CI matrix cell | [issue](https://github.com/ImL1s/resume-skills/issues/67) | `enhancement`, `priority:P2`, `architecture` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #17, #18, #36 | issue #67 body @ `2026-07-28T02:36:07Z`; `sha256:41ec1be28b7eed14`; unresolved | `queued` |
| #66 | Make hosts report commands executable from installed distributions and context-aware | [issue](https://github.com/ImL1s/resume-skills/issues/66) | `bug`, `priority:P2`, `installer` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #24, #32, #34, #36 | issue #66 body @ `2026-07-28T02:36:07Z`; `sha256:8c2a56cacfe7b7a6`; unresolved | `queued` |
| #65 | Reader CLI accepts ignored options and bypasses argument validation for self-check | [issue](https://github.com/ImL1s/resume-skills/issues/65) | `bug`, `priority:P2`, `architecture` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #26, #28, #32 | issue #65 body @ `2026-07-28T02:36:07Z`; `sha256:085f185ba782bf71`; unresolved | `queued` |
| #63 | Make handoff rendering use an explicit serialized-output budget | [issue](https://github.com/ImL1s/resume-skills/issues/63) | `bug`, `priority:P1`, `architecture` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 security/correctness | unproven body refs #8, #10, #12, #17 | issue #63 body @ `2026-07-28T02:36:07Z`; `sha256:c4259e16b649d139`; unresolved | `queued` |
| #62 | Bind request-v1 validation to the inode actually opened by the reader | [issue](https://github.com/ImL1s/resume-skills/issues/62) | `bug`, `priority:P1`, `security` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 security/correctness | unproven body refs #21, #26, #31 | issue #62 body @ `2026-07-28T02:36:07Z`; `sha256:6e6ca43ce39e7c53`; unresolved | `queued` |
| #61 | Separate internal session identity from sanitized display data before selection and show | [issue](https://github.com/ImL1s/resume-skills/issues/61) | `bug`, `priority:P1`, `architecture`, `security` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 security/correctness | unproven body refs #16, #18, #28, #36 | issue #61 body @ `2026-07-28T02:36:07Z`; `sha256:c47a31094a66dec2`; unresolved | `queued` |
| #48 | New-agent support roadmap: OpenClaw, Pi, goose, Crush, Cline, OpenHands, Hermes, Copilot, Gemini, Kilo, and qualification backlog | [issue](https://github.com/ImL1s/resume-skills/issues/48) | `enhancement`, `roadmap`, `priority:P1` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #10, #16, #17, #18, #20, #30, #34, #36, #37, #38, #39, #40, #41, #42, #43, #44, #45, #46, #47 | issue #48 body @ `2026-07-28T02:36:07Z`; `sha256:3e57f323f398bd9f`; unresolved | `queued` |
| #47 | Qualify second-wave agents: Aider, Amp, Droid, Codebuff, Kiro, Zed, Roo, Warp, Windsurf, Junie, and others | [issue](https://github.com/ImL1s/resume-skills/issues/47) | `research`, `roadmap`, `priority:P2` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #24, #36, #37, #46 | issue #47 body @ `2026-07-28T02:36:07Z`; `sha256:e6a4420a65b5bf69`; unresolved | `queued` |
| #46 | Add Kilo Code CLI support without assuming OpenCode storage or Skill parity | [issue](https://github.com/ImL1s/resume-skills/issues/46) | `enhancement`, `research`, `source-adapter`, `priority:P1`, `destination-host`, `compatibility` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #18, #26, #27, #30, #34, #36 | issue #46 body @ `2026-07-28T02:36:07Z`; `sha256:de8aca5b86950188`; unresolved | `queued` |
| #45 | Preserve Gemini CLI source/destination compatibility after the Antigravity consumer transition | [issue](https://github.com/ImL1s/resume-skills/issues/45) | `enhancement`, `research`, `priority:P2`, `source-adapter`, `destination-host`, `compatibility` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #18, #30, #34, #36 | issue #45 body @ `2026-07-28T02:36:07Z`; `sha256:cbe98f7a8acd8428`; unresolved | `queued` |
| #44 | Add GitHub Copilot CLI destination support; gate source adapter on pinned session-event schema | [issue](https://github.com/ImL1s/resume-skills/issues/44) | `enhancement`, `research`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #10, #18, #26, #27, #30, #34, #36 | issue #44 body @ `2026-07-28T02:36:07Z`; `sha256:b845bf11f127da90`; unresolved | `queued` |
| #43 | Add Hermes Agent source adapter and destination Skill support for WAL SQLite sessions | [issue](https://github.com/ImL1s/resume-skills/issues/43) | `enhancement`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #18, #25, #26, #27, #30, #36 | issue #43 body @ `2026-07-28T02:36:07Z`; `sha256:10cb0d84dc077004`; unresolved | `queued` |
| #42 | Add OpenHands CLI source adapter and destination Skill support for event-file conversations | [issue](https://github.com/ImL1s/resume-skills/issues/42) | `enhancement`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #10, #16, #18, #26, #30, #34, #36 | issue #42 body @ `2026-07-28T02:36:07Z`; `sha256:f1b16234e11c3236`; unresolved | `queued` |
| #41 | Add Cline source adapter and destination Skill support for authoritative JSON sessions | [issue](https://github.com/ImL1s/resume-skills/issues/41) | `enhancement`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #10, #18, #26, #30, #34, #36 | issue #41 body @ `2026-07-28T02:36:07Z`; `sha256:c4db9566e28f724e`; unresolved | `queued` |
| #40 | Add Crush source adapter and destination Skill support for project SQLite sessions | [issue](https://github.com/ImL1s/resume-skills/issues/40) | `enhancement`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #18, #24, #25, #26, #30, #34, #36 | issue #40 body @ `2026-07-28T02:36:07Z`; `sha256:188cb23b7835eaee`; unresolved | `queued` |
| #39 | Add goose source adapter and destination Skill support for SQLite sessions | [issue](https://github.com/ImL1s/resume-skills/issues/39) | `enhancement`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #10, #18, #24, #25, #26, #30, #34, #36 | issue #39 body @ `2026-07-28T02:36:07Z`; `sha256:c5210dcef1751bbf`; unresolved | `queued` |
| #38 | Add Pi source adapter and destination Skill support for versioned tree JSONL sessions | [issue](https://github.com/ImL1s/resume-skills/issues/38) | `enhancement`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 3 foundation/partial | unproven body refs #10, #18, #26, #30, #34, #36 | issue #38 body @ `2026-07-28T02:36:07Z`; `sha256:42f1b8bb4754b182`; unresolved | `queued` |
| #37 | Add OpenClaw source adapter and destination Skill support for the SQLite session era | [issue](https://github.com/ImL1s/resume-skills/issues/37) | `enhancement`, `source-adapter`, `priority:P1`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #10, #18, #26, #30, #34, #36 | issue #37 body @ `2026-07-28T02:36:07Z`; `sha256:d03f067029ed68af`; unresolved | `queued` |
| #36 | Next-wave support architecture: decouple source adapters, destination hosts, and native package surfaces | [issue](https://github.com/ImL1s/resume-skills/issues/36) | `enhancement`, `priority:P1`, `architecture` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 3 foundation/partial | unproven body refs #10, #18, #24, #25, #27, #30 | issue #36 body @ `2026-07-28T02:36:07Z`; `sha256:f29b9ace447789bb`; unresolved | `queued` |
| #35 | Install must rebuild and authorize the plan under lock from the exact current manifest generation | [issue](https://github.com/ImL1s/resume-skills/issues/35) | `bug`, `priority:P1`, `security`, `installer` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 installer (dependency recheck required) | unproven body refs #21, #23, #25, #28, #31, #32 | issue #35 body @ `2026-07-28T02:36:07Z`; `sha256:b8e9c4400530ccb7`; unresolved | `queued` |
| #34 | Detect duplicate and shadowed Portable Resume Skills across each host's discovery roots | [issue](https://github.com/ImL1s/resume-skills/issues/34) | `enhancement`, `priority:P1`, `destination-host`, `compatibility` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #24, #25, #26, #27, #30, #33 | issue #34 body @ `2026-07-28T02:36:07Z`; `sha256:c4208c0af8be6253`; unresolved | `queued` |
| #33 | Project-scope installs must separate shareable Skill payloads from machine-local transaction state | [issue](https://github.com/ImL1s/resume-skills/issues/33) | `enhancement`, `priority:P1`, `architecture`, `installer`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #20, #21, #22, #23, #24, #25, #28, #31, #32 | issue #33 body @ `2026-07-28T02:36:07Z`; `sha256:d6ca72c787019459`; unresolved | `queued` |
| #32 | Installer CLI flags and output formats need one truthful stable contract | [issue](https://github.com/ImL1s/resume-skills/issues/32) | `bug`, `priority:P2`, `installer` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #22, #23, #24, #28, #30 | issue #32 body @ `2026-07-28T02:36:07Z`; `sha256:ae07e32e1f8c229c`; unresolved | `queued` |
| #30 | Destination CLI integration and installer hardening umbrella | [issue](https://github.com/ImL1s/resume-skills/issues/30) | `roadmap`, `priority:P1`, `installer`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #18, #20, #21, #22, #23, #24, #25, #26, #27, #28, #29, #31, #32, #33, #34 | issue #30 body @ `2026-07-28T02:36:07Z`; `sha256:b19b71a20c444781`; unresolved | `queued` |
| #29 | Windows mutating installer commands need exclusive locking or an explicit fail-closed platform gate | [issue](https://github.com/ImL1s/resume-skills/issues/29) | `bug`, `priority:P1`, `security`, `installer` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 installer (dependency recheck required) | unproven body refs #21, #22, #23, #28 | issue #29 body @ `2026-07-28T02:36:07Z`; `sha256:6cf91cd60e84c124`; unresolved | `queued` |
| #28 | Installer manifest and journal need closed bounded schemas with strict validation | [issue](https://github.com/ImL1s/resume-skills/issues/28) | `bug`, `priority:P1`, `architecture`, `security`, `installer` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 installer (dependency recheck required) | unproven body refs #20, #21, #22 | issue #28 body @ `2026-07-28T02:36:07Z`; `sha256:a1e90dda89f7a82c`; unresolved | `queued` |
| #27 | Native host package compatibility must be versioned and gated beyond static ZIP shape tests | [issue](https://github.com/ImL1s/resume-skills/issues/27) | `enhancement`, `priority:P1`, `destination-host`, `compatibility` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #20, #23, #24, #25, #26 | issue #27 body @ `2026-07-28T02:36:07Z`; `sha256:fc247a64a6ca11bb`; unresolved | `queued` |
| #26 | Skill runners need deterministic owned paths and typed argument transport across destination CLIs | [issue](https://github.com/ImL1s/resume-skills/issues/26) | `bug`, `priority:P1`, `security`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 installer (dependency recheck required) | unproven body refs #24, #25 | issue #26 body @ `2026-07-28T02:36:07Z`; `sha256:e947e82fc2f74625`; unresolved | `queued` |
| #25 | Make direct Skill payloads host-neutral so shared `.agents/skills` roots can coexist | [issue](https://github.com/ImL1s/resume-skills/issues/25) | `enhancement`, `priority:P1`, `architecture`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #23, #24 | issue #25 body @ `2026-07-28T02:36:07Z`; `sha256:053779c4ffdba384`; unresolved | `queued` |
| #24 | Destination root resolution must honor host-specific configured homes and report provenance | [issue](https://github.com/ImL1s/resume-skills/issues/24) | `bug`, `priority:P1`, `installer`, `destination-host` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unknown; no body refs | issue #24 body @ `2026-07-28T02:36:07Z`; `sha256:183b047e4920ce43`; unresolved | `queued` |
| #23 | Multi-root install must lock and checkpoint one coherent generation before mutation | [issue](https://github.com/ImL1s/resume-skills/issues/23) | `bug`, `priority:P1`, `installer` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #21, #22 | issue #23 body @ `2026-07-28T02:36:07Z`; `sha256:56afe853cc5cb196`; unresolved | `queued` |
| #22 | Installer uninstall and verify must be transactionally consistent with install and recovery | [issue](https://github.com/ImL1s/resume-skills/issues/22) | `bug`, `priority:P1`, `installer` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #20, #21 | issue #22 body @ `2026-07-28T02:36:07Z`; `sha256:6e64576c5e33bf5d`; unresolved | `queued` |
| #19 | Claude exact references: avoid broad project scans when a direct path is available | [issue](https://github.com/ImL1s/resume-skills/issues/19) | `enhancement`, `priority:P2`, `source-adapter` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #16, #18 | issue #19 body @ `2026-07-28T02:36:07Z`; `sha256:cdff615dd70692db`; unresolved | `queued` |
| #18 | Cross-adapter large-session and discovery parity after v0.3.3 | [issue](https://github.com/ImL1s/resume-skills/issues/18) | `roadmap`, `source-adapter`, `priority:P1` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #4, #7, #8, #10, #11, #12, #13, #14, #15, #16, #17, #19 | issue #18 body @ `2026-07-28T02:36:07Z`; `sha256:5214e1b32236db8f`; unresolved | `queued` |
| #17 | ReadBudget invariants: reject all caller-raised global ceilings | [issue](https://github.com/ImL1s/resume-skills/issues/17) | `bug`, `priority:P1`, `architecture`, `security` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 2 security/correctness | unproven body refs #10 | issue #17 body @ `2026-07-28T02:36:07Z`; `sha256:b705c76d772e843d`; unresolved | `queued` |
| #16 | Snapshot exact reads: remove whole-parent 2,000-sibling failure mode | [issue](https://github.com/ImL1s/resume-skills/issues/16) | `bug`, `source-adapter`, `priority:P1`, `architecture` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 3 foundation/partial | unknown; no body refs | issue #16 body @ `2026-07-28T02:36:07Z`; `sha256:347b5408de436a28`; unresolved | `queued` |
| #15 | Grok and Antigravity large histories: stream JSONL and preserve exact references | [issue](https://github.com/ImL1s/resume-skills/issues/15) | `bug`, `source-adapter`, `priority:P1` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #10 | issue #15 body @ `2026-07-28T02:36:07Z`; `sha256:ad86af2d0ed4c9e5`; unresolved | `queued` |
| #13 | OpenCode exact selection and large transcripts: filter before LIMIT and scope reads | [issue](https://github.com/ImL1s/resume-skills/issues/13) | `bug`, `source-adapter`, `priority:P0` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 1 P0 | unproven body refs #10 | issue #13 body @ `2026-07-28T02:36:07Z`; `sha256:8205a9fb7aecfb72`; unresolved | `queued` |
| #12 | Qwen large chats: separate file, line, and discovery budgets | [issue](https://github.com/ImL1s/resume-skills/issues/12) | `bug`, `source-adapter`, `priority:P0` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 1 P0 | unproven body refs #10 | issue #12 body @ `2026-07-28T02:36:07Z`; `sha256:22a9b17a1ac65bf3`; unresolved | `queued` |
| #10 | Shared JSONL infrastructure: stable streaming scanner and metadata reducers | [issue](https://github.com/ImL1s/resume-skills/issues/10) | `enhancement`, `source-adapter`, `priority:P1`, `architecture` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 3 foundation/partial | unproven body refs #8 | issue #10 body @ `2026-07-28T02:36:07Z`; `sha256:72ab89d110218131`; unresolved | `queued` |
| #8 | Codex show: stable streaming reader and large-rollout regression | [issue](https://github.com/ImL1s/resume-skills/issues/8) | `bug`, `source-adapter`, `priority:P1` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #7, #10, #11, #15, #16, #17 | issue #8 body @ `2026-07-28T02:36:07Z`; `sha256:ab3e3e357c61dd7f`; unresolved | `queued` |
| #7 | Codex probe/list discovery: head-only probe and read-only FS fallback | [issue](https://github.com/ImL1s/resume-skills/issues/7) | `bug`, `source-adapter`, `priority:P1` | `OPEN` @ `2026-07-28T01:23:52Z` | Wave 4 remaining (dependency recheck required) | unproven body refs #3, #4, #8, #10, #16, #17 | issue #7 body @ `2026-07-28T02:36:07Z`; `sha256:b8be36597424fc4c`; unresolved | `queued` |

## Transition gate for selecting the next branch or issue

Every later implementation branch requires the preceding PR's merge, green
merge-containing `main`, linked issue readback, exact-final-HEAD CI and non-empty
AI review, strict P1/P2 disposition, a unique immutable pre-publication receipt
plus pointer/manifest update through exact-head GraphQL CAS, complete
closed-schema/hash/sequence replay, and separate same-head remote readback.

After a branch PR is opened, no CI/review receipt is accepted until a fresh
GitHub live-provider guard and `pr-opened` CAS/readback bind its exact
node/number/URL/base/head/opener to the active issue/owner/epoch. At most one
such program authorization may be open. Unrelated and Dependabot PRs are
excluded from the count and never substitute for the authorization.

If acceptance remains partial, the transition is `pr-checkpointed`: the pointer
stays `owned` by the same issue/owner/epoch, the prior receipt joins its ordered
multi-PR history, and only the same issue's next PR may begin. If acceptance is
complete, `issue-released` appends the terminal receipt and produces verified
`idle`, after which another issue may be acquired. The receipt never attests to
its own future commit/readback. Ignored `.omx` edits, comments, or pending
mutations do not satisfy the gate.

After lineage evaluation makes all 44 exact activation roots
effective-terminal, a separate `idle -> complete` CAS requires zero unresolved
dependency/lineage, zero program authorizations, all terminal/multi-PR receipts,
and fresh final-main proof. Target references never enlarge the denominator.
Same-head remote readback must prove `complete`; that state permanently rejects
acquisition or mutation for this program ID.

## Wave 0 pinned evidence and repair decision

- Provider readback confirms [`ci` run `30320034677`](https://github.com/ImL1s/resume-skills/actions/runs/30320034677) is the latest `ci` push run on current `main` `ef2a2f709290cb9e56c6c669bca03f15a12829a9` at `2026-07-28T02:36:07Z`.
- Run metadata: created `2026-07-28T01:21:55Z`, updated `2026-07-28T01:23:03Z`, completed/failure.
- Failure classification: every Ubuntu/macOS Python matrix job failed at `Self verify`; distribution build/smoke was skipped.
- Repo-local reproduction identified the STATUS honesty mismatch: `docs/STATUS.md` uses `**407 collected**`, while `tests/unit/test_status_honesty.py` requires `**<count> pass locally**`.
- Repair rule: prove the current failure from a clean checkout, preserve the honesty assertion, and use a standalone baseline PR unless a fully resolving activation-issue mapping is proven. Do not close #69 from a one-line baseline repair unless all #69 criteria are satisfied.

## Ledger mutation rule

Never rewrite tracked activation identity/body/contract fields or prior
receipt/dependency-event/evidence files. Append unique correction/supersession receipts
through exact-head CAS on
`refs/heads/program-state/all-open-issues-20260728`. Pointer, manifest, receipt,
dependency-event, and typed evidence records must satisfy the closed schema, stdlib canonical
hash, contiguous sequence, Git ancestry, and deterministic replay contract. If
an issue body changes, retain the activation contract and append the new
digest/timestamp. Any dependency/order change appends one ordered-pair event
with closed direction/classification, typed evidence refs, classifier,
timestamp, rationale, and exact current superseded-event hash. Replay derives
projection/status/count/eligibility; updating this ignored Markdown alone is
non-authoritative.
