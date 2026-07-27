# Host UI live activation smoke protocol

## Do not conflate the layers

| Layer | What it proves | Status |
|---|---|---|
| Packaging matrix | Enabled destinations × sources render safely (currently **9×9** on `main`) | **81/81** on this release (published `0.3.3` remains historical **64/64**) |
| Installed runner | Installed `run_reader` list/show works on fixtures | **81/81** on this release (published `0.3.3` remains historical **64/64**) |
| Native package install | Host CLI/TUI accepts the generated local plugin/extension | **7/7 tested on v0.3.2** |
| Host-native headless activation | Host discovers/invokes the Skill and runs its owned reader | **8/8 tested** (Pi native activation **not-run**) |
| Public marketplace install | Host installs a published listing | **6/6 compatible hosts tested on v0.3.2**; fresh v0.3.4 reinstall **not-run** |
| Visual marketplace picker | A human-visible marketplace picker was opened and selected | **Cursor and Kimi tested on v0.3.2**; fresh v0.3.4 picker flow **not-run** |
| Other visual Skill pickers | Host-specific Skill picker selection | **not-run** |

Run the automated layer with:

```bash
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py --json
```

The harness uses a distinct root per host and never launches a source agent CLI.

## Manual or host-native evidence procedure

1. Install the exact release archive using [`install-hosts.md`](install-hosts.md).
2. Record the host version and package SHA-256.
3. Invoke the host-specific form (`/resume-*`, `$resume-*`, `/skill:resume-*`, or a name mention).
4. Confirm the installed `scripts/run_reader.py` ran and the output contains the untrusted/stale banner.
5. Confirm no source CLI was launched and no transcript was sent to a network service automatically.
6. Add one evidence row; do not infer untested cells from it.

## Host-native headless invocation evidence

| host | source | host_version | activation | result | artifact_sha256 | notes | date |
|---|---|---|---|---|---|---|---|
| claude | claude | 2.1.218 | `/resume-claude` | pass | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` | Public PyPI 0.3.1 project install; event result matched the synthetic session and inert/untrusted flags | 2026-07-24 |
| codex | claude | 0.145.0 | `$resume-claude` | pass | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` | Ephemeral `codex exec` read the project Skill and executed its reader | 2026-07-24 |
| cursor | claude | 2026.07.23-e383d2b | `/resume-claude` with `--plugin-dir` | pass | `efd1befeb5b7f40965e77b7b1c47a48bab813c6f6b89df4a63e4206347075724` | Exact 0.3.2 Cursor archive loaded; tool event used the extracted plugin reader | 2026-07-24 |
| opencode | claude | 1.15.10 | model loads `resume-claude` by name | pass | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` | Isolated config/data roots; Skill loader and bash event both resolved to the project install | 2026-07-24 |
| antigravity | claude | 1.1.6 | name mention in `agy --print` | pass | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` | Print mode ran the exact project reader and verified the structured result | 2026-07-24 |
| grok | claude | 0.2.111 | `/resume-claude` | pass | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` | Exported transcript records Skill read, exact reader command, and pass marker | 2026-07-24 |
| qwen | claude | 0.20.1 | `/resume-claude` | pass | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` | `--approval-mode=yolo` exposed shell execution; stream JSON records command/output | 2026-07-24 |
| kimi | claude | 0.29.0 | `/skill:resume-claude` with `--skills-dir` | pass | `8a5c1050af154d4cc5dce9499e4f2dd93a3b19a880aa0c26d9ac18956e7765b8` | Stream JSON records native Skill load, Bash command, structured output, and pass marker | 2026-07-24 |

All rows use the same synthetic Claude fixture and expected session ID. They
prove non-interactive native discovery/invocation, not a visual picker click.

## Visual picker evidence

| host | picker | result | notes | date |
|---|---|---|---|---|
| cursor | `/plugin` → Marketplace → `portable-resume` → user install | pass | Installed tab showed Portable Resume 0.3.2 with eight Skills | 2026-07-24 |
| kimi | `/plugins marketplace <catalog-url>` → Portable Resume → Trust and install | pass | `/plugins list` showed Portable Resume 0.3.2 with eight Skills | 2026-07-24 |
| remaining hosts | native visual Skill picker | not-run | Claude, Codex, OpenCode, Antigravity, Grok, and Qwen visual Skill pickers were not exercised | 2026-07-24 |

## Local native package install evidence

| host | host_version | package_type | install_path_or_ui | result | artifact_sha256 | notes | date |
|---|---|---|---|---|---|---|---|
| claude | 2.1.218 | marketplace + plugin | `claude plugin marketplace add`; `claude plugin install --scope user` | pass | `ef3d85aaf08e5e157cb390fa589f52f5461b20e537dccea995325fff51b01a2e` | Exact 0.3.2 archive passed strict validation and isolated install; listed enabled as 0.3.2 | 2026-07-24 |
| codex | 0.145.0 | marketplace + plugin | `codex plugin marketplace add`; `codex plugin add` | pass | `70d15c769f647ffa74dcfb694313c98a297ffc48077b6fa5ba12297834bce446` | Exact 0.3.2 archive installed in isolated `CODEX_HOME`; listed enabled as 0.3.2 | 2026-07-24 |
| cursor | 2026.07.23-e383d2b | plugin | `cursor-agent --plugin-dir <plugin>` | pass | `efd1befeb5b7f40965e77b7b1c47a48bab813c6f6b89df4a63e4206347075724` | Exact 0.3.2 plugin loaded and executed its bundled reader | 2026-07-24 |
| qwen | 0.20.1 | extension | `qwen extensions install --consent --scope user` | pass | `7667180e708f831be15f3a4b56fb3c585c0cddcb2058836c774e77c3d1df2000` | Exact 0.3.2 ZIP installed in isolated home; list reports eight Skills | 2026-07-24 |
| grok | 0.2.111 | plugin | `grok plugin validate`; `grok plugin install --trust` | pass | `ccbe3ac70bebb19ce135aa6b3878be7ef232eb54b582e62b146ca60b309a8083` | Exact 0.3.2 local path validated and installed in isolated `GROK_HOME` | 2026-07-24 |
| antigravity | 1.1.6 | plugin | `agy plugin validate`; `agy plugin install` | pass | `9ae1339f767ab57a58054b363ece2ddce8136b1451850531da67844dc80104cd` | Exact 0.3.2 archive extracted; isolated install reports eight Skills | 2026-07-24 |
| kimi | 0.29.0 | plugin | TUI `/plugins install <local-path>`; `/plugins list` | pass | `4b85bf855022411b8a94c727c26ad4f2536c6e9487eff6faee404dc99b119f5b` | Exact 0.3.2 local-path install in isolated `KIMI_CODE_HOME`; list reports Portable Resume 0.3.2 and eight Skills | 2026-07-24 |

Valid hosts: `claude`, `codex`, `cursor`, `opencode`, `antigravity`, `grok`, `qwen`, `kimi`. OpenCode has no plugin-package row because this project intentionally uses its data-only Skill surface.

## Public marketplace install evidence

Public catalog:
[`ImL1s/portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace),
publication commit `4997715cd8f2680ab9e196ba43ec4af323a56bd1`.
The sanitized host readbacks and raw-evidence digests are archived in
[`evidence/public-marketplace-v0.3.2.json`](evidence/public-marketplace-v0.3.2.json).

| host | host_version | public route | result | delivered source proof | notes | date |
|---|---|---|---|---|---|---|
| claude | 2.1.218 | `claude plugin marketplace add ImL1s/portable-resume-marketplace`; install `portable-resume@portable-resume` | pass | commit `4997715…`, `plugins/claude/portable-resume`, tree `fd069e937013dca2ba6d45aa5ee2665f2a869da0` | Isolated config listed version 0.3.2 enabled | 2026-07-24 |
| codex | 0.145.0 | `codex plugin marketplace add ImL1s/portable-resume-marketplace`; add `portable-resume@portable-resume` | pass | commit `4997715…`, `plugins/codex/portable-resume`, tree `8fb7002fc709664dd2b1f59b968b2086c3ae69ed` | Isolated `CODEX_HOME` listed version 0.3.2 enabled | 2026-07-24 |
| cursor | 2026.07.23-e383d2b | public Git marketplace; `/plugin` picker | pass | commit `4997715…`, `plugins/cursor/portable-resume`, tree `aab88c238265271d65ddf3cd3e739376643bbde5` | Installed tab showed the marketplace name and eight Skills | 2026-07-24 |
| qwen | 0.20.1 | public extension source; `extensions install ...:portable-resume --scope user` | pass | commit `4997715…`, compatibility path `plugins/claude/portable-resume`, tree `fd069e937013dca2ba6d45aa5ee2665f2a869da0` | Install metadata reports Claude-origin mapping; list showed version 0.3.2 and eight Skills | 2026-07-24 |
| grok | 0.2.111 | public marketplace; install `portable-resume@portable-resume-marketplace --trust` | pass | commit `4997715…`, compatibility path `plugins/claude/portable-resume`, tree `fd069e937013dca2ba6d45aa5ee2665f2a869da0` | Registry records the compatibility subdirectory; list showed the installed plugin | 2026-07-24 |
| kimi | 0.29.1 | public JSON catalog; TUI Trust and install | pass | release ZIP SHA-256 `4b85bf855022411b8a94c727c26ad4f2536c6e9487eff6faee404dc99b119f5b` | Managed install records the exact 0.3.2 GitHub Release ZIP; list showed eight Skills | 2026-07-24 |

Antigravity and OpenCode have no compatible public catalog for this package
shape, so their published release/direct routes remain the supported paths.
The public repository is an independently maintained marketplace. A listing in
a vendor-curated Claude or Cursor directory is not claimed.

## Policy

Local CLI/TUI installation proves only that the native host accepted the local
archive. Public marketplace and visual picker claims require their own rows;
the six public installation rows and two picker rows above satisfy only those
scoped v0.3.2 claims. A green filesystem/runner matrix (historical 64-cell or
current 81-cell) is not substitute evidence for a host picker, a public catalog,
or a vendor-curated directory.
