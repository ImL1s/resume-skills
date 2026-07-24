# Host UI live activation smoke protocol

## Do not conflate the layers

| Layer | What it proves | Status |
|---|---|---|
| Packaging matrix | 8 hosts × 8 source Skills render safely | **64/64** |
| Installed runner | Installed `run_reader` list/show works on fixtures | **64/64** |
| Native package install | Host CLI/TUI accepts the generated local plugin/extension | **6/7 tested** |
| Host UI activation | Host discovers and invokes the Skill in its UI/TUI | **not-run** |
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

## Natural-language / picker evidence

| host | source | host_version | activation | result | artifact_sha256 | notes | date |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## Marketplace/plugin install evidence

| host | host_version | package_type | install_path_or_ui | result | artifact_sha256 | notes | date |
|---|---|---|---|---|---|---|---|
| claude | 2.1.218 | marketplace + plugin | `claude plugin marketplace add`; `claude plugin install --scope user` | pass | `fb5821cf695b73ed88c3f27ae765f6146deed2e91b05d9605f1519346bce83fa` | strict validation and isolated user-scope install; enabled as 0.3.0 | 2026-07-24 |
| codex | 0.145.0 | marketplace + plugin | `codex plugin marketplace add`; `codex plugin add` | pass | `5ba1bb5adf5536324ef7f9b9a692e3a8ec568933d495b0fc440091ed5bcefef2` | isolated local marketplace install; enabled as 0.3.0 | 2026-07-24 |
| qwen | 0.20.1 | extension | `qwen extensions install --consent --scope user` | pass | `c8e408a5bc3d45e922d1df2f90b4bba831707a8013e64a10d47f856657d0ffce` | isolated install; extension lists eight Skills | 2026-07-24 |
| grok | 0.2.111 | plugin | `grok plugin validate`; `grok plugin install --trust` | pass | `cca96d4c86d320be58c802c9d20d583784f3063c2a622efc9623fd657684be2b` | isolated local-path validation and install | 2026-07-24 |
| antigravity | 1.1.6 | plugin | `agy plugin validate`; `agy plugin install` | pass | `6c757ae110a6113c448f81ec68108e70ee6e8bd94ad0fc11fdcf40738a28de80` | isolated local-path install; eight Skills discovered | 2026-07-24 |
| kimi | 0.29.0 | plugin | TUI `/plugins install <local-path>`; `/plugins list` | pass | `c952ab85c97513231891207fa72079b67bb744fcf9d57fb5234cbef0a925802b` | trust prompt accepted; 0.3.0 local-path plugin lists eight Skills | 2026-07-24 |
| cursor | not-run | plugin | local plugin directory / marketplace UI | not-run | `98cdb158a544a6d67a2ec17cf598dec01163bbd07663fc2cbe6f8afc968f9c53` | package schema tested; live host load remains unverified | 2026-07-24 |

Valid hosts: `claude`, `codex`, `cursor`, `opencode`, `antigravity`, `grok`, `qwen`, `kimi`. OpenCode has no plugin-package row because this project intentionally uses its data-only Skill surface.

## Policy

Local CLI/TUI installation proves only that the native host accepted the local
archive. It does not prove publication in a public marketplace or
natural-language/picker activation. Keep those claims at `not-run` until their
own evidence rows exist. A green 64-cell filesystem/runner matrix is not
evidence that a host picker, marketplace, or natural-language router worked.
