# Provenance and clean-room policy

## Scope

This repository implements a host-neutral context-migration contract. It does not restore a live agent process and it does not redistribute vendor session readers or private transcripts.

## Allowed implementation references

Implementation and fixture authors may use only:

1. Repository plans and specs shipped in this tree under `docs/` (and, when present on a developer machine, local planning notes that are **not** required to build or test);
2. Tracked, publicly licensed source such as the Apache-2.0 [xAI Grok Build](https://github.com/xai-org/grok-build) repository, used only as *behavioral* reference;
3. Official public product documentation for Agent Skills and host skill roots; and
4. Independently authored synthetic fixtures containing no real user transcript.

Public behavior is requirements evidence only. Vendor implementation bodies are not mechanically translated into this tree.

## Prohibited references and data

**Hard prohibition for product code and fixtures:** do not copy, paste, translate, or ship bodies from `~/.grok/bundled/skills/**` or private user transcripts. Do not embed credentials, account identifiers, or absolute developer home paths in fixtures.

## Author attestation (deterministic V1)

Implementation is an independently written **compatibility reimplementation**.

Planning-time observation of installed tools may have informed *requirements*. That is not a license to redistribute those files. Public clones must not require private bundles.

Product sources, tests, and fixtures in this repository:

- are independently authored or synthetic;
- do not contain copied installed-bundle skill bodies;
- do not invoke source agent CLIs as recovery backends.

This attestation covers **deterministic packaging and reader behavior**. It does **not** claim live host UI activation completeness or dual-OS release completeness (see `docs/STATUS.md` and `docs/evidence-summary.md`).

## Fixture policy

Every adapter fixture must have a strict `fixture.json` manifest validated by `tests/helpers/fixture_manifest.py`. `synthetic` must be literal `true`; source, provider ID, case, expected operation/code, warnings, and a `docs/source-formats.md#...` provenance anchor are mandatory. Unknown keys, duplicate keys, private-looking paths, and unsupported warning/source values fail closed.

## Schema extension for the normalized-content budget

The session definition in `schemas/portable-resume-v1.schema.json` uses the documented extension keyword `x-portable-resume-max-total-utf8-bytes`. Its `limit` applies to the UTF-8 encoded byte sum of every field named by `stringFields` plus the field named by `arrayStringField` in every object in `arrayField`. For V1, that is the aggregate of `last_user_request`, `last_assistant_action`, and every turn's `content`, capped at 8 MiB.

Standard JSON Schema validators are allowed to ignore unknown `x-*` keywords. Consumers that require the V1 resource bound must therefore use the runtime contract validator or an extension-aware validator; the dependency-free evaluator in `tests/helpers/json_schema.py` is the executable reference for the checked-in corpus.
