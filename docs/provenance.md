# Provenance and clean-room policy

## Scope

This repository implements a new, host-neutral context-migration contract. It does not restore a live agent process and it does not redistribute vendor session readers or private transcripts.

## Allowed implementation references

Implementation and fixture authors may use only:

1. the approved repository-local requirements and plans under `.omx/specs/`, `.omx/plans/`, and the frozen official-evidence context;
2. tracked, publicly licensed source in the upstream [xAI Grok Build repository](https://github.com/xai-org/grok-build), including its Apache-2.0 license;
3. official public product documentation enumerated in `docs/clean-room-attestation.md`; and
4. independently authored synthetic fixtures containing no real user transcript.

Public behavior is requirements evidence only. Vendor implementation bodies are not mechanically translated.

## Prohibited references and data

Implementation and test work must not open, inspect, hash-match, copy, translate, or derive code/fixtures from `~/.grok/bundled/skills/**`. It must not read a real Claude, Codex, Cursor, OpenCode, Antigravity, or Grok session store. Private transcripts, credentials, account identifiers, and absolute developer home paths are forbidden in fixtures.

## Author attestation (G001–G004)

The foundation, six source adapters, packaging/installer, and deterministic integration/e2e suites were authored from the approved plans, public/official evidence under `.omx/context/`, and independently written synthetic fixtures only. Implementation/test authors did not inspect `~/.grok/bundled/skills/**`, did not copy private transcripts into fixtures, and did not use source CLIs as recovery backends.

This attestation covers deterministic V1 implementation and packaging proof. It does **not** claim live installed-version host activation smokes (`docs/host-support.md` rows remain `not-run` until proven) and does **not** claim dual-OS clean-runner evidence beyond the OS that actually executed the gate.

## Fixture policy

Every future adapter fixture must have a strict `fixture.json` manifest validated by `tests/helpers/fixture_manifest.py`. `synthetic` must be literal `true`; source, provider ID, case, expected operation/code, warnings, and a `docs/source-formats.md#...` provenance anchor are mandatory. Unknown keys, duplicate keys, private-looking paths, and unsupported warning/source values fail closed.

## Schema extension for the normalized-content budget

The session definition in `schemas/portable-resume-v1.schema.json` uses the documented extension keyword `x-portable-resume-max-total-utf8-bytes`. Its `limit` applies to the UTF-8 encoded byte sum of every field named by `stringFields` plus the field named by `arrayStringField` in every object in `arrayField`. For V1, that is the aggregate of `last_user_request`, `last_assistant_action`, and every turn's `content`, capped at 8 MiB.

Standard JSON Schema validators are allowed to ignore unknown `x-*` keywords. Consumers that require the V1 resource bound must therefore use the runtime contract validator or an extension-aware validator; the dependency-free evaluator in `tests/helpers/json_schema.py` is the executable reference for the checked-in corpus.
