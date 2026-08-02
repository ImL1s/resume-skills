# Kilo source Track B2 — qualification (#202 / #46)

**Date:** 2026-08-02  
**Verdict: NO-GO for Kilo source enablement** (destination remains shipped)

## Scope

Qualify event / `session_message` / legacy message-part authority with synthetic DB/WAL fixtures before registering a Kilo **source** format ID or adapter.

## Evidence reviewed

- Destination Track A: filesystem install paths for Kilo **done** on main
- Prior qualification: `docs/research/kilo-cli-v7.4.17-qualification.md` — **NO-GO** for source
- Registry: Kilo destination enabled; source remains research / not in enabled sources

## Findings

1. Multiple authority surfaces (`event`, `session_message`, legacy `message`/`part`) can disagree; without synthetic fixtures, enablement is unsafe.
2. Cloud-import / migration provenance remains unresolved for clean-room offline reading.
3. Wrong-adapter rejection vs OpenCode still required before format registration.

## GO criteria (not met)

- [ ] Exact-version synthetic DB/WAL fixtures (no real home paths)
- [ ] Written authority/conflict matrix
- [ ] Bidirectional wrong-adapter rejection tests
- [ ] Registry `format_ids` + adapter only after GO

## Disposition

**NO-GO.** Kilo **source** stays disabled. #46 umbrella + #202 remain the research track; destination support is unaffected. Matrix stays **17×18=306** without a Kilo source axis.
