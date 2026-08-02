# Kimi Code wire compaction / clear / undo — qualification (#200)

**Date:** 2026-08-02  
**Tip context:** main after Wave 0+1 (`055c071`+)  
**Verdict: NO-GO for claiming active-context parity**

## Scope

Qualify wire compaction, clear, and undo semantics before claiming that Portable Resume restores the same “active context” a live Kimi session would show after those operations.

## Evidence reviewed

- Existing product path: `kimi-code-wire-jsonl-v1` + stream index/list/show on main (PR #58 era; STATUS closed for #14 large-session path).
- Product invariants: offline, immutable source, inert handoff, no source CLI.

## Findings

1. **Compaction / clear / undo are control-plane events** whose on-disk authority is not fully fixture-proven in this tree as a complete active-context graph.
2. Current reader reconstructs **bounded public transcript slices** from wire/index with honest truncation warnings — **not** a full replica of Kimi’s post-compaction in-memory context.
3. Without synthetic fixtures that encode compaction tombstones, clear epochs, and undo stacks, any “active-context parity” claim would be **overclaim**.

## GO criteria (not met)

- [ ] Hand-authored synthetic fixtures for compaction, clear, and undo sequences
- [ ] Deterministic tests that selected “latest active” matches the post-op public transcript only
- [ ] Explicit STATUS row for active-context parity

## Disposition

**NO-GO.** Keep Kimi filesystem list/show as shipped; do **not** market or STATUS-claim active-context parity after wire compaction/clear/undo until fixtures land. Issue #200 remains the tracker for that qualification work (may stay open as research or close as deferred-with-note).
