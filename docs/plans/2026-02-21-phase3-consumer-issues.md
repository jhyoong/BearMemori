# Phase 3 Consumer Issues

Review of LLM worker consumer (`llm_worker/worker/consumer.py`) against the Phase 3 plans and the Telegram consumer's expected notification format.

## Issue 1: Notification format mismatch (CRITICAL) -- FIXING

The Telegram consumer at `telegram/tg_gateway/consumer.py` expects notifications on `notify:telegram` in this wrapper format:

```python
{"user_id": int, "message_type": str, "content": dict}
```

The LLM worker consumer publishes a flat dict instead:

```python
{"type": str, "job_id": str, "memory_id": str, **result}
```

Missing `user_id`, uses `type` instead of `message_type`, spreads handler result flat instead of nesting under `content`.

### Fix

Rewrite the notification publish in `_process_message()` to use the wrapper format. Same for failure notifications.

## Issue 2: Notification type names mismatch (CRITICAL) -- FIXING

The Telegram consumer dispatches on `message_type` using these values:

| Expected (Telegram consumer) | Actual (LLM worker) |
|---|---|
| `llm_image_tag_result` | `image_tag_result` |
| `llm_intent_result` | `intent_result` |
| `llm_followup_result` | `followup_result` |
| `llm_task_match_result` | `task_match_result` |
| `event_confirmation` | `event_confirmation` |
| `llm_failure` | `job_failed` |

Five of six names are wrong. The `NOTIFICATION_TYPE_*` constants and `STREAM_TO_NOTIFICATION_TYPE` mapping need to be updated.

### Fix

Update the constants and mapping to match the Telegram consumer's expected values. Remove the separate `NOTIFICATION_TYPE_*` constants in favor of inline values in the mapping (matching the plan's `STREAM_HANDLER_MAP` approach).

## Issue 3: Job not marked "processing" before handler runs (MINOR) -- NOT FIXING

The plan says to update the job to `processing` before calling the handler. The implementation skips this on the success path. This is a deliberate choice (commented in code). The job goes `queued -> completed` directly. Not fixing because:
- It reduces one HTTP call per job
- The `processing` state is still set on retry paths
- No downstream code depends on observing the `processing` state during normal flow

## Issue 4: shutdown_event in main.py is dead code (MINOR) -- NOT FIXING

`main.py` creates a `shutdown_event` and sets it on signal receipt, but `run_consumer()` never checks it. Shutdown works via `CancelledError` from `asyncio.run()`. This is harmless dead code. Could be cleaned up later but has no functional impact.

## Issue 5: record_attempt called before try block (MINOR) -- NOT FIXING

The retry tracker increments the attempt counter before the handler runs (not in the except block as the plan specifies). The `clear()` on success resets it, so this is functionally equivalent. No change needed.

## Test Updates

Consumer tests (`tests/test_llm_worker/test_consumer.py`) were written against the incorrect format, so they pass today. After fixing issues 1 and 2, the tests need to be updated to assert the correct wrapper format and message type names.
