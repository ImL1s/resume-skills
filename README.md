# portable-resume-skills

<p align="center">
  <img src="docs/assets/portable-resume-skills-hero-v2.jpg" alt="Eight local coding-agent sources flow into a sealed context archive, then into eight fresh destination sessions" width="920" />
</p>

<p align="center">
  <em>Offline, local-only context migration · 8 sources × 8 hosts · inert handoff, not live restore</em>
</p>

[English](docs/i18n/en.md) · [繁體中文](docs/i18n/zh-TW.md) · [简体中文](docs/i18n/zh-CN.md) · [日本語](docs/i18n/ja.md) · [한국어](docs/i18n/ko.md) · [Español](docs/i18n/es.md) · [Português](docs/i18n/pt-BR.md) · [Français](docs/i18n/fr.md) · [Deutsch](docs/i18n/de.md) · [Русский](docs/i18n/ru.md) · [العربية](docs/i18n/ar.md) · [हिन्दी](docs/i18n/hi.md) · [All languages](docs/i18n/README.md)

Clean-room-oriented Agent Skills for migrating bounded local coding-agent context into a **fresh** session. Readers never invoke the source agent CLI and never add a network path; recovered text is marked untrusted and stale.

**Current release:** [`0.3.2`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2)
· [PyPI](https://pypi.org/project/portable-resume/0.3.2/) · 64/64 packaging
cells · 64/64 installed-runner cells · 7/7 exact native local
plugin/extension installs verified · 8/8 host-native headless Skill
invocations verified · 6/6 compatible public marketplace installs verified.
Cursor and Kimi marketplace pickers were also exercised; other visual Skill
picker paths remain separate **not-run** claims.

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

Destination profiles: Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code, and current Kimi Code CLI.

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

```bash
# Inspect capabilities and the 8×8 matrix
PYTHONPATH=src python3 scripts/portable-resume self-check --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json
PYTHONPATH=src python3 scripts/install-resume-skills hosts

# Read a synthetic Claude fixture
PYTHONPATH=src python3 scripts/portable-resume claude show latest \
  --cwd /workspace/project \
  --source-root tests/fixtures/claude/s-cla-01-ordered-parent-chain/root \
  --format handoff

# Preview, install, verify, and uninstall one destination
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --dry-run --json
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --json
PYTHONPATH=src python3 scripts/install-resume-skills verify \
  --host qwen --scope project --project "$PWD" --json
```

Full roots, activation grammar, direct archives, and marketplace/plugin routes are in [`docs/install-hosts.md`](docs/install-hosts.md). Release assets are generated with:

```bash
python3 scripts/build_host_packages.py --output-dir host-packages
```

This produces eight direct-skill ZIPs plus supported Claude, Codex, Cursor, Antigravity, Grok, Qwen, and Kimi plugin/marketplace bundles. OpenCode remains a direct Skill install because its plugin surface is executable JavaScript/TypeScript rather than a Skill bundle.

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

`.github/workflows/ci.yml` runs those gates across Ubuntu/macOS and Python 3.11–3.14, then builds and smoke-installs the exact wheel and sdist. `.github/workflows/release.yml` accepts only annotated `vMAJOR.MINOR.PATCH` tags reachable from `main`, re-runs dual-OS gates, builds release bytes once, tests those exact bytes, creates SHA-256 checksums and GitHub attestations, stages a GitHub Release, and publishes through PyPI Trusted Publishing.

Published release `v0.3.2` also verifies the GitHub Release layout itself:
every `SHA256SUMS` entry is a flat asset basename, and both Ubuntu and macOS
validate a simulated flat download before publication. The immutable
[release run](https://github.com/ImL1s/resume-skills/actions/runs/30093776529),
commit, public artifact checks, GitHub Release, and PyPI evidence are archived
in [`docs/evidence-summary.md`](docs/evidence-summary.md).

## Key documentation

- [`docs/i18n/README.md`](docs/i18n/README.md) — 12 localized quick-start guides
- [`docs/STATUS.md`](docs/STATUS.md) — done/not-done truth
- [`docs/install-hosts.md`](docs/install-hosts.md) — per-host installation
- [`docs/source-formats.md`](docs/source-formats.md) — format and provenance registry
- [`docs/host-ui-smoke.md`](docs/host-ui-smoke.md) — live activation evidence protocol
- [`docs/release-claim.md`](docs/release-claim.md) — release gates and external setup
- [`SECURITY.md`](SECURITY.md) — threat model
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contributor workflow

## License and limitations

Apache-2.0. This project is not affiliated with the host vendors. Do not copy `~/.grok/bundled/skills/**` into this tree.

Headless slash/name activation is verified on all eight hosts. Public
marketplace installation is verified on all six compatible hosts, including
Cursor and Kimi picker flows. Other visual Skill pickers and vendor-curated
directory listings are not claimed; Cursor's full bubble graph is not claimed;
redaction is not complete DLP.
