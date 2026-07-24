<!-- portable-resume-i18n: en v0.3.0 -->
# Portable Resume — English quick start

Portable Resume moves bounded local context from Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, or Kimi into a **fresh** coding-agent session. It is not live-session restore. Readers are offline, stdlib-only, never invoke a source CLI, and label recovered text as inert and untrusted.

## Install

Requires Python 3.11+. After a PyPI release:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

From a checkout, use `pipx install .`. Install all eight destination profiles into their user-global roots with:

```bash
install-resume-skills quick-install all
```

For one project:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

The supported destinations are Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code, and Kimi Code CLI. Exact direct-Skill, extension, plugin, and marketplace commands are in the [host installation guide](../install-hosts.md). Inspect third-party plugin archives and verify release checksums before trusting them.

## Verify and use

From a checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Activate `resume-<source>` using the destination host’s documented grammar. Re-check the current repository before acting on a handoff.

Optional host-side web search and Context7 setup is documented in [network integrations](../network-integrations.md); the reader itself never gains network access. See [project status](../STATUS.md) for verified claims and explicit not-run UI/release gates.
