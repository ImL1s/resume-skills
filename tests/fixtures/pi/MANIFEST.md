# Pi session JSONL synthetic fixtures

All cases are independently authored (`synthetic: true`). No adapter or registry support is claimed.

| Case | Format ID | Notes |
|---|---|---|
| `s-pi-01-basic-v3` | `pi-session-jsonl-v3` | Header v3 + user/assistant on one branch |
| `s-pi-02-branch-compaction` | `pi-session-jsonl-v3` | Branch summary + compaction with `firstKeptEntryId` (legacy retained-range form) |
| `s-pi-03-tool-and-custom` | `pi-session-jsonl-v3` | Tool result, bash execution, and custom message entries |
| `s-pi-04-corrupt-interior` | `pi-session-jsonl-v3` | Interior corrupt JSONL line (`expected_code` 7 for future adapter) |
| `s-pi-05-v2-compat` | `pi-session-jsonl-v2` | Header version 2 minimal tree (read-only compatibility fixture) |

Provenance: `docs/source-formats.md#pi-pi-session-jsonl-v3` and `#pi-pi-session-jsonl-v2`.
