<!-- portable-resume-i18n: en v0.3.2 -->
# Portable Resume — English quick start

**Current published release:** [`0.3.2`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2)

Portable Resume moves bounded local context from Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, or Kimi into a **fresh** coding-agent session. It is not live-session restore. Readers are offline, stdlib-only, never invoke a source CLI, and label recovered text as inert and untrusted.

## Install

Requires Python 3.11+. Install the published package from PyPI:

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

Current local host smoke passed 8/8 CLI invocations; the exact `0.3.2`
packages passed 7/7 supported native plugin/extension installations. Visual
picker interaction and public marketplace publication remain separate not-run
claims.

See [project status](../STATUS.md) for verified claims and explicit not-run UI/release gates.
