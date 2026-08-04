<!-- portable-resume-i18n: en v0.4.2.dev0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — English quick start

**Current published release:** [`0.4.1`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.1)

Portable Resume moves bounded local context from Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, or Kimi into a **fresh** coding-agent session. It is not live-session restore. Readers are offline, stdlib-only, never invoke a source CLI, and label recovered text as inert and untrusted.

## Install

Requires Python 3.11+. Install the published package from PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
From a checkout on current `main`, use `pipx install .`. Install all 18 destination profiles into their user-global roots with:

```bash
install-resume-skills quick-install all
```

For one project:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Enabled destinations on `main` are Antigravity / agy, Claude Code, Cline, Codex CLI / IDE, Crush, Cursor Agent, Gemini CLI, GitHub Copilot CLI, goose, Grok Build, Hermes Agent, Kilo CLI, Kimi Code CLI, OpenClaw, OpenCode, OpenHands, Pi agent, and Qwen Code.
<!-- portable-resume-current-registry:end -->

Published `0.4.0` ships nine destinations including Pi (filesystem install; native UI not-run). Exact direct-Skill, extension, plugin, and marketplace commands are in the [host installation guide](../install-hosts.md). Inspect third-party plugin archives and verify release checksums before trusting them.

## Public marketplace

The public
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
provides host-native installation for six compatible hosts:

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

The host guide contains the verified Cursor, Qwen, Grok, and Kimi routes plus
direct Antigravity/OpenCode fallbacks.

## Verify and use

From a checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Activate `resume-<source>` using the destination host’s documented grammar. Re-check the current repository before acting on a handoff.

Current host smoke passed 8/8 CLI invocations and 7/7 exact local native
package installs. Public marketplace installation passed 6/6 compatible
hosts; Cursor and Kimi marketplace pickers also passed. Other visual Skill
pickers and vendor-curated directories remain unclaimed.

These host-level results are v0.3.2-era evidence. Fresh through 0.4.1 host-by-host
reinstall and picker flows remain **not-run**.
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.4.1-host-reinstall-not-run -->

See [project status](../STATUS.md) for verified claims and explicit not-run UI/release gates.
