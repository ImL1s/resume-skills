# Allowed references and clean-room attestation

## Allowed reference manifest

- `.omx/specs/portable-resume-skills.md`
- `.omx/plans/prd-portable-resume-skills.md`
- `.omx/plans/test-spec-portable-resume-skills.md`
- `.omx/plans/adr-portable-resume-skills.md`
- `.omx/context/host-profile-official-evidence-20260720.md`
- `https://github.com/xai-org/grok-build` tracked Apache-2.0 source only
- Official public host documentation linked from the frozen host-profile evidence
- Synthetic data created specifically inside this repository's tests

## Explicit exclusion

`~/.grok/bundled/skills/**`, all real user session stores, private exports, credentials, and copied vendor transcript content are excluded.

## Attestation

For G001, the implementation/test author used only the allowed references above and synthetic temporary files. No excluded source was opened, inspected, hashed, copied, or used to derive code or fixtures. This statement is intentionally limited to G001 and makes no adapter or live-host completion claim.
