# Cursor bubble / composer graph — spike notes

**Status:** partial live only (`W_MISSING_BLOB` for full bubble chain).  
**Planned at:** v0.2.0 post-audit (`plans/023`).

## What works today

| Path | Format id | Restored content |
|------|-----------|------------------|
| CLI live `chats/*/store.db` | `cursor-cli-store-v1` | `blobs` rows ordered by `rowid`, JSON `{role,content}` |
| CLI meta | side-car `meta.json` | cwd/title/timestamps via stable no-follow read |
| Desktop live | `cursor-desktop-composer-v1` | `composerHeaders` list; `composerData:{id}` best-effort multi-turn via `_composer_data_turns` (messages/bubbles/conversation walks) |

## Not claimed

- Full multi-bubble conversation graph / parent links (still emit `W_MISSING_BLOB`)
- Picker parity with Cursor UI
- Assistant tool-call tree reconstruction from composer state

## Next spike steps (when prioritized)

1. Pin a Cursor version and sample a local `state.vscdb` / `store.db` under operator consent (scrub secrets).
2. Map bubble IDs → text blobs → ordering fields.
3. Grow synthetic fixtures in `tests/fixtures/cursor/` before removing `W_MISSING_BLOB`.

## Honesty

Until fixtures prove multi-turn bubble restore, keep `W_MISSING_BLOB` on desktop show and CHANGELOG “not claimed”.
