# Allowed references and clean-room attestation

## Allowed reference manifest (public)

- `docs/*` shipped with this repository (STATUS, host-support, provenance, source-formats, evidence-summary)
- Official public host documentation for Agent Skills roots and frontmatter
- `https://github.com/xai-org/grok-build` tracked Apache-2.0 source only (behavioral reference)
- Synthetic data created specifically inside this repository's tests

Local planning notes (if present on a developer machine under private directories) may inform requirements but are **not** required to build, test, or use this package and are not shipped.

## Explicit exclusion

`~/.grok/bundled/skills/**`, all real user session stores, private exports, credentials, and copied vendor transcript content are excluded from product code and fixtures.

## Attestation (scoped)

**Scope:** foundation, six source adapters, packaging/installer, and deterministic test suites in this repository.

Product sources and fixtures do **not** contain copied installed-bundle skill bodies. Implementation is a compatibility reimplementation of documented behavior, not a redistribution of untracked installed readers.

This statement makes no live-host UI activation claim and no dual-OS release claim (see `docs/STATUS.md`).
