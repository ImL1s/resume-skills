# Cursor Desktop composer bubble graph — qualification (#201)

**Date:** 2026-08-02  
**Verdict: NO-GO for full bubble graph / complete active-lineage claim**

## Scope

Qualify Cursor Desktop composer bubble graph and active-lineage transcript authority before claiming completeness beyond best-effort recovery.

## Evidence reviewed

- STATUS: Cursor full bubble graph **not claimed**
- Plan 023 / prior research notes: bubble graph spike documented; not product-complete
- Live CLI path uses `stable_scan_lines` and bounded composerData handling; Desktop SQL filter-before-LIMIT fixes shipped under #11

## Findings

1. Multi-turn `composerData` / bubble linkage is **schema-volatile** and not covered by a complete clean-room fixture set for full graph reconstruction.
2. Product path provides **best-effort** list/show for CLI store and live SQLite with honest bounds — not a proof of complete bubble lineage.
3. Claiming “full bubble graph” would contradict STATUS honesty gates.

## GO criteria (not met)

- [ ] Synthetic fixtures covering multi-bubble graphs, sidechains, and active-lineage edges
- [ ] Tests proving selected transcript authority under concurrent Desktop writers
- [ ] STATUS flip from “not claimed” only with evidence rows

## Disposition

**NO-GO** for full graph completeness. Keep existing Cursor adapters; leave full bubble graph **not claimed**. #201 tracks future qualification only.
