# Host UI live activation smoke protocol

## Do not conflate the layers

| Layer | What it proves | Status |
|---|---|---|
| Packaging matrix | 8 hosts × 8 source Skills render safely | **64/64** |
| Installed runner | Installed `run_reader` list/show works on fixtures | **64/64** |
| Native package install | Host CLI/TUI accepts the generated local plugin/extension | **7/7 tested** |
| Host-native headless activation | Host discovers/invokes the Skill and runs its owned reader | **8/8 tested** |
| Visual picker interaction | A human-visible picker was opened and selected | **not-run** |
| Public marketplace install | Host installs a published listing | **not-run** |

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
| cursor | claude | 2026.07.23-e383d2b | `/resume-claude` with `--plugin-dir` | pass | `c3dc56b428612d2a99ef407bdb6f0560a3b6a28f5c11ae2660ad698a44267aa2` | Exact 0.3.1 Cursor archive loaded; tool event used the extracted plugin reader | 2026-07-24 |
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
| all | native visual Skill picker | not-run | No screenshot/interactive selection evidence is archived | 2026-07-24 |

## Marketplace/plugin install evidence

| host | host_version | package_type | install_path_or_ui | result | artifact_sha256 | notes | date |
|---|---|---|---|---|---|---|---|
| claude | 2.1.218 | marketplace + plugin | `claude plugin marketplace add`; `claude plugin install --scope user` | pass | `c1fafa5ec05d974657552cb40366824b2d7b473efc713eceaed26138ee206d39` | Exact 0.3.1 archive passed strict validation and isolated install; listed enabled as 0.3.1 | 2026-07-24 |
| codex | 0.145.0 | marketplace + plugin | `codex plugin marketplace add`; `codex plugin add` | pass | `755083cf5aa8fd6e9375ebed058f0f3b0a92e2b90b30e2eabbfe3453ee48b8f7` | Exact 0.3.1 archive installed in isolated `CODEX_HOME`; listed enabled as 0.3.1 | 2026-07-24 |
| cursor | 2026.07.23-e383d2b | plugin | `cursor-agent --plugin-dir <plugin>` | pass | `c3dc56b428612d2a99ef407bdb6f0560a3b6a28f5c11ae2660ad698a44267aa2` | Exact 0.3.1 plugin loaded and executed its bundled reader | 2026-07-24 |
| qwen | 0.20.1 | extension | `qwen extensions install --consent --scope user` | pass | `3a53e9b5af42cdc0516bae113c34edb5fb74190fa883e50c7d2041c455d031ab` | Exact 0.3.1 ZIP installed in isolated home; list reports eight Skills | 2026-07-24 |
| grok | 0.2.111 | plugin | `grok plugin validate`; `grok plugin install --trust` | pass | `c3fb0b33bf1f5a601fd26e5a666d33b556934aa87b5a378c005842514826f2f9` | Exact 0.3.1 local path validated and installed in isolated `GROK_HOME` | 2026-07-24 |
| antigravity | 1.1.6 | plugin | `agy plugin validate`; `agy plugin install` | pass | `86466f51590810a39d6e56400a5dfd671be6b3ae86d7c35a5ec6341c8f56868a` | Exact 0.3.1 archive extracted; isolated install reports eight Skills | 2026-07-24 |
| kimi | 0.29.0 | plugin | TUI `/plugins install <local-path>`; `/plugins list` | pass | `4212ef946019e149fc627c0ec7b0e0cc1752601a0ecc523138dca4e57774b7a6` | Exact 0.3.1 local-path install in isolated `KIMI_CODE_HOME`; list reports eight Skills | 2026-07-24 |

Valid hosts: `claude`, `codex`, `cursor`, `opencode`, `antigravity`, `grok`, `qwen`, `kimi`. OpenCode has no plugin-package row because this project intentionally uses its data-only Skill surface.

## Policy

Local CLI/TUI installation proves only that the native host accepted the local
archive. It does not prove publication in a public marketplace or
visual picker activation. Keep those claims at `not-run` until their own
evidence rows exist. A green 64-cell filesystem/runner matrix is not evidence
that a host picker or public marketplace worked.
