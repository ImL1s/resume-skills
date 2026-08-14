# portable-resume-skills

<p align="center">
  <img src="docs/assets/portable-resume-skills-hero-v2.jpg" alt="Local coding-agent session stores flow into a sealed context archive, then into fresh destination sessions" width="920" />
</p>

<p align="center">
  <em>Offline, local-only context migration · 17 sources × 18 hosts (derived from registries) · inert handoff, not live restore</em>
</p>

[English](docs/i18n/en.md) · [繁體中文](docs/i18n/zh-TW.md) · [简体中文](docs/i18n/zh-CN.md) · [日本語](docs/i18n/ja.md) · [한국어](docs/i18n/ko.md) · [Español](docs/i18n/es.md) · [Português](docs/i18n/pt-BR.md) · [Français](docs/i18n/fr.md) · [Deutsch](docs/i18n/de.md) · [Русский](docs/i18n/ru.md) · [العربية](docs/i18n/ar.md) · [हिन्दी](docs/i18n/hi.md) · [All languages](docs/i18n/README.md)

Clean-room-oriented Agent Skills for migrating bounded local coding-agent context into a **fresh** session. Readers never invoke the source agent CLI and never add a network path; recovered text is marked untrusted and stale.

**Current release:** [`0.4.3`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.3)
· [PyPI](https://pypi.org/project/portable-resume/0.4.3/) · **306/306** packaging and
Ubuntu installed-runner cells (17 sources × 18 destinations). Windows native
mutating install is **supported** (#125); Windows hard gate is focused product-install
smoke (3 hosts), **not** full 306/306 on Windows. Published `v0.4.2` / `v0.4.1` /
`v0.4.0` remain historical; published `v0.3.4` remains historical 81.

**Host evidence boundary:** v0.3.2-era checks cover 7/7 exact native local
plugin/extension installs, 8/8 host-native headless Skill invocations, 6/6
compatible public marketplace installs, and Cursor/Kimi pickers. Fresh through
0.4.3 host reinstall/picker flows and Pi/OpenClaw native UI remain **not-run**
(still not re-run on this tip).

**Current `main` development version:** `0.4.4.dev0`. Explicit build/release
reports add `+g<commit>[.dirty]` while package metadata keeps the PEP 440 base.
Artifact builds pin one canonical identity before producing bytes. Repository-level
immutable `v*` tag enforcement remains active ([ruleset `20148806`](https://github.com/ImL1s/resume-skills/rules/20148806)).

## Sources and destinations

| Resume skill | Source store family |
|---|---|
| `resume-claude` | Claude Code projects JSONL |
| `resume-codex` | Codex SQLite / rollout JSONL |
| `resume-cursor` | Cursor CLI chats / Desktop vscdb |
| `resume-opencode` | OpenCode SQLite / file store |
| `resume-antigravity` | Antigravity transcript JSONL |
| `resume-grok` | Grok Build session updates JSONL |
| `resume-qwen` | Qwen Code chat JSONL, including archived chats |
| `resume-kimi` | Current Kimi Code wire JSONL + legacy Kimi CLI context JSONL |
| `resume-pi` | Pi agent versioned tree JSONL (`agent/sessions/--cwd-slug--/`) |
| `resume-openclaw` | OpenClaw per-agent SQLite (`agents/<id>/agent/openclaw-agent.sqlite`) |
| `resume-goose` | goose sessions.db SQLite (`sessions/sessions.db`, schema v15) |
| `resume-crush` | Crush project SQLite (`crush.db`, goose_db_version 7) |
| `resume-cline` | Cline sessions index + messages JSON (`~/.cline/data`) |
| `resume-openhands` | OpenHands CLI conversation events (`~/.openhands/conversations`) |
| `resume-hermes` | Hermes Agent state.db sessions (`~/.hermes/state.db`) |
| `resume-gemini` | Gemini CLI session JSONL (`~/.gemini/tmp/.../chats`) — not Antigravity |
| `resume-github-copilot` | GitHub Copilot CLI local `session-state/<id>/events.jsonl` |

Destination profiles: Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code, Kimi Code CLI, Pi agent, OpenClaw, goose, Crush, Cline, OpenHands, Hermes Agent, GitHub Copilot CLI, Gemini CLI (compat, not Antigravity), and Kilo CLI (destination-only).

## Requirements

- Python **3.11+**; CI covers 3.11–3.14 on Ubuntu and macOS.
- Product runtime is **stdlib-only**.
- Optional trusted `zstd` binary for compressed Codex rollouts.

## Quick start

Install the published package, then install every destination profile into its
user-global Skill root:

```bash
pipx install portable-resume
install-resume-skills quick-install all
```

From a source checkout, use `pipx install .` instead. To install only one host
or one project:

```bash
install-resume-skills quick-install qwen
install-resume-skills quick-install qwen --project "$PWD"
```

### Windows without pipx

Use Python's actual user-base Scripts directory rather than a hard-coded
`Python311` path (the directory changes with the interpreter and install
layout):

```powershell
python -m pip install --user portable-resume
$scripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @($userPath -split ';' | Where-Object { $_ })
if ($parts -notcontains $scripts) {
  [Environment]::SetEnvironmentVariable('Path', (@($parts + $scripts) -join ';'), 'User')
}
```

Open a **new** PowerShell after changing the User PATH, then install and verify
the profiles you use:

```powershell
install-resume-skills quick-install claude
install-resume-skills verify --host claude --scope global
```

Start with and verify the hosts you actually use. `quick-install all` is a
transactional convenience across the registry-derived profiles, not evidence
that every destination UI was activated. On Windows, the release hard gate is
the focused Claude/Cursor/Codex product smoke, **not** 306/306. Shared
symlink/junction roots are grouped by their physical root and require an
ownership claim for every intended host. See
[Windows user install and shared Skill roots](docs/install-hosts.md#windows-user-install-and-shared-skill-roots).

For a host-native public marketplace install, add the
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace):

```bash
# Claude Code
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user

# Codex
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

Verified Cursor, Qwen, Grok, and Kimi commands plus direct Antigravity/OpenCode
fallbacks are in [`docs/install-hosts.md`](docs/install-hosts.md).

The lower-level transactional command remains available for previews, custom
roots, verification, and uninstall:

Installed (pipx/pip):

```bash
# Inspect capabilities and the registry-derived matrix
portable-resume --version
install-resume-skills --version
portable-resume self-check --json
install-resume-skills matrix
install-resume-skills hosts --json

# Preview, install, verify, and uninstall one destination
install-resume-skills install \
  --host qwen --scope project --project "$PWD" --dry-run
install-resume-skills install \
  --host qwen --scope project --project "$PWD"
# Selected sources are recorded in the ownership claim; verify intentionally
# takes no --sources argument and checks the recorded install plan.
install-resume-skills install \
  --host qwen --scope project --project "$PWD" --sources codex,grok
install-resume-skills verify \
  --host qwen --scope project --project "$PWD"
install-resume-skills uninstall \
  --host qwen --scope project --project "$PWD" --dry-run
```

From a source checkout (no install):

```bash
PYTHONPATH=src python3 scripts/portable-resume --version
PYTHONPATH=src python3 scripts/install-resume-skills --version
python3 scripts/check_version_state.py --require-git --json
PYTHONPATH=src python3 scripts/portable-resume self-check --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix
PYTHONPATH=src python3 scripts/install-resume-skills hosts --json
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --dry-run
```

The synthetic fixture exists only in a source checkout:

```bash
PYTHONPATH=src python3 scripts/portable-resume claude show latest \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --format handoff
```

Full roots, activation grammar, direct archives, and marketplace/plugin routes are in [`docs/install-hosts.md`](docs/install-hosts.md). Release assets are generated with:

```bash
python3 scripts/build_host_packages.py --output-dir host-packages
```

Published `v0.3.4` archives include nine direct-skill ZIPs (including Pi) plus
supported Claude, Codex, Cursor, Antigravity, Grok, Qwen, and Kimi
plugin/marketplace bundles. Current `main` development builds derive direct ZIPs
from all 18 enabled destinations. OpenCode remains a direct Skill install because
its plugin surface is executable JavaScript/TypeScript rather than a Skill bundle.

## Skill contract

```bash
python3 <skill>/scripts/run_reader.py show latest --cwd "$PWD" --json
python3 <skill>/scripts/run_reader.py show <session-id|path|text> --cwd "$PWD" --json
python3 <skill>/scripts/run_reader.py list --cwd "$PWD" --json
```

Activate `resume-<source>` using the host's documented grammar, run only the installed reader, and summarize its inert output after re-checking the repository. `portable-resume/request-v1` files remain an optional advanced interface.

## Safety invariants

- Source stores are immutable; stable no-follow reads fail closed on races.
- Source CLIs are never invoked.
- Recovered text is inert/untrusted and only best-effort redacted.
- Installer paths are contained under the selected skill root.
- Non-owned collisions require `--force-with-backup`; multi-root installs compensate on failure.
- Shared physical roots with divergent host renders fail before mutation.

## Tests and CI/CD

Run all required local gates:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

`.github/workflows/ci.yml` runs those gates across Ubuntu/macOS and Python
3.11–3.14, then builds the wheel/sdist twice from one identity pin and epoch
under different parent umasks, requires byte-for-byte reproducibility, proves
the source package was not mutated, verifies the same embedded identity across
all 27 generated artifacts in four artifact families,
and smoke-installs the exact wheel and sdist with poisoned build-pin
environment variables removed from child processes.
`.github/workflows/release.yml` accepts only annotated `vMAJOR.MINOR.PATCH` tags
reachable from `main`, re-runs dual-OS
gates, builds release bytes once from one pinned identity, tests those exact
bytes, creates SHA-256 checksums and GitHub attestations, stages a GitHub
Release, and publishes through PyPI Trusted Publishing.

`src/portable_resume/resources/latest-release.json` records the immutable latest
published identity. Normal CI fetches release tags and fails if changed source
reuses a published stable version. The protected release path rejects
development versions; after every release, `main` advances immediately to the
next `.dev0` line.

Published release `v0.3.4` also verifies the GitHub Release layout itself:
every `SHA256SUMS` entry is a flat asset basename, and both Ubuntu and macOS
validate a simulated flat download before publication. The immutable v0.3.4
[release run](https://github.com/ImL1s/resume-skills/actions/runs/30269713516),
commit, public checksum/attestation checks, GitHub Release, PyPI, and marketplace
evidence are archived in [`docs/evidence-summary.md`](docs/evidence-summary.md).

## Key documentation

- [`docs/i18n/README.md`](docs/i18n/README.md) — 12 localized quick-start guides
- [`docs/diagnostics.md`](docs/diagnostics.md) — exit codes and machine diagnostics
- [`docs/STATUS.md`](docs/STATUS.md) — done/not-done truth
- [`docs/install-hosts.md`](docs/install-hosts.md) — per-host installation
- [`docs/source-formats.md`](docs/source-formats.md) — format and provenance registry
- [`docs/host-ui-smoke.md`](docs/host-ui-smoke.md) — live activation evidence protocol
- [`docs/release-claim.md`](docs/release-claim.md) — release gates and external setup
- [`SECURITY.md`](SECURITY.md) — threat model
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contributor workflow

## License and limitations

Apache-2.0. This project is not affiliated with the host vendors. Do not copy `~/.grok/bundled/skills/**` into this tree.

Eight host CLI surfaces have recorded headless slash/name activation evidence;
Pi native activation remains **not-run**. Public marketplace installation on six
compatible hosts, including Cursor and Kimi picker flows, is recorded for
v0.3.2; fresh through 0.4.1 host-by-host reinstall remains **not-run**. Other
visual Skill pickers and vendor-curated directory listings are not claimed;
Cursor's full bubble graph is not claimed; redaction is not complete DLP.
