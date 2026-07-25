# Allowed references and clean-room attestation

## Allowed public references

- Repository documentation and independently authored synthetic fixtures.
- Official host documentation for Agent Skills, plugins, MCP, and data locations.
- Public open-source trees at recorded immutable commits, including Qwen Code, current/legacy Kimi CLI, Cursor plugins, Codex, and Apache-2.0 Grok Build.

These references are used to understand formats and public interfaces; vendor code or transcript content is not copied into fixtures.

## Explicit exclusions

`~/.grok/bundled/skills/**`, real user session stores, private exports, credentials, developer home paths, and copied vendor transcripts are excluded from product code and fixtures.

## Scoped attestation

Scope: shared core, eight source adapters, eight destination profiles, installer/package builders, and deterministic tests in this repository.

Product sources and fixtures are compatibility implementations over public shapes. Readers produce inert, untrusted handoffs for a fresh session; they do not restore a live process, invoke source CLIs, or add a network path.

The product sources and synthetic fixtures do **not** contain copied installed-bundle content or real vendor transcripts.

This source-content attestation does not itself claim host UI behavior, public
marketplace publication, or a complete Cursor bubble graph. Headless host
invocation, local/native and public marketplace installation, scoped picker
checks, and dual-OS release evidence are recorded separately in
`docs/host-ui-smoke.md` and `docs/evidence-summary.md`.
