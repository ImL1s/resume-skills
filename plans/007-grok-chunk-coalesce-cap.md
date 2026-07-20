# Plan 007: Cap Grok message-chunk coalesce under content budget

> Drift: `git diff --stat bc7baf0..HEAD -- src/portable_resume/adapters/grok.py tests/`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (benefits from plan 006 if both touch budgets)
- **Category**: bug
- **Planned at**: commit `bc7baf0`, 2026-07-21

## Why this matters

Each `user_message_chunk` / `agent_message_chunk` is sanitized with `max_chars=normalized_content_bytes` (~8Mi code points). Adjacent same-role chunks are concatenated with `prior.content + turn.content` **without** re-capping. Many streaming chunks can allocate multi×8Mi intermediate strings before `sanitize_session` rebounds — OOM / huge peaks on live `updates.jsonl`.

## Current state

Coalesce logic around `grok.py:502-517` (per-chunk sanitize) and `581-591` (merge same-role chunks). Confirm with `rg -n 'message_chunk|coalesce|prior.content' src/portable_resume/adapters/grok.py` if lines drifted.

## Scope

**In scope**: `adapters/grok.py`; unit test with many small chunks  
**Out of scope**: Changing default bounds; other adapters’ turn merge

## Steps

### Step 1: Cap on merge

When appending to prior same-role content:

```python
limit = DEFAULT_BOUNDS.normalized_content_bytes  # or UTF-8 byte cap if aligning with sanitize_session
room = limit - len(prior.content)  # if using char semantics matching current sanitize_text
if room <= 0:
    prior.truncated = True
    # skip further appends for this role until role changes
else:
    prior.content = prior.content + turn.content[:room]
    if len(turn.content) > room:
        prior.truncated = True
```

Prefer matching whatever unit `sanitize_text` uses today; if plan 016/character-vs-bytes is open, keep char semantics consistent with current grok path.

Stop `consume_turns()` for further chunks of the same role once full (optional but recommended).

### Step 2: Test

Synthetic updates.jsonl or direct function test: N chunks of size M where N*M >> limit; assert final turn length ≤ limit, `truncated` True, process completes without multi-limit allocation expectation (assert max content length).

**Verify**: unittest + full suite.

## Done criteria

- [ ] Coalesce never exceeds one max-sized content string per turn
- [ ] Truncation warning preserved
- [ ] Suite green; README DONE

## STOP conditions

- Chunk types other than user/agent also merge unsafely — fix those in the same loop; if architecture differs wildly, STOP and report

## Maintenance notes

Follow-up: align char vs UTF-8 with `sanitize_session` (audit CORR-11; may fold into plan 016).
