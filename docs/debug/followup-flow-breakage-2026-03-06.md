# Followup Flow Breakage Debug Report

**Date:** 2026-03-06
**Issue:** Followup conversation flow is broken - user lock never released

---

## Root Cause

The user lock is never released after an `ambiguous` intent followup flow completes.

---

## Timeline of Events

| Event | Timestamp | Details |
|-------|-----------|---------|
| Original message received | 01:34:43 | User: "remind me to buy lunch later" |
| Lock acquired | 01:34:44 | `Lock ACQUIRED for user 46646397 (ttl=604800s)` |
| Intent classified | 01:35:43 | LLM returned `intent: "ambiguous"` with `followup_question` |
| Notification published | 01:35:43 | `llm_intent_result` notification sent to Telegram |
| Followup question sent | 01:35:43 | Telegram gateway sent followup to user |
| Followup answer sent | ~01:35:52 | User replied "in 1 hour" (job `e7a68244` created) |
| **Lock still held** | Now | `redis-cli GET "llm:user_lock:46646397"` returns `1` |

---

## Redis Stream Analysis

- **Stream:** `llm:intent`
- **Total entries:** 99
- **Consumer group:** `llm-worker-group`
- **Entries read:** 97
- **Pending (lag):** 2

**Pending messages in PEL:**
1. `9b47929a-...` ("do some courses on powershell") - deferred due to lock
2. `d6618da1-...` ("write up basic report later") - new message

**Followup job status:** Job `e7a68244` (with `followup_context`) is in the stream but was read by the consumer.

---

## Key Log Evidence

### LLM Worker (`bearmemori-llm-worker-1`)
```
2026-03-06 01:34:44,345 shared_lib.redis_streams INFO Lock ACQUIRED for user 46646397 (ttl=604800s)
2026-03-06 01:34:44,345 worker.consumer INFO Calling handler intent_classify for job 84b3b399-20f4-4cb1-9c8a-8c2547fab4b2...
2026-03-06 01:35:43,145 worker.consumer INFO Publishing notification for job 84b3b399-20f4-4cb1-9c8a-8c2547fab4b2: type=llm_intent_result
```

**Note:** Only ONE lock acquisition in the logs. No lock release detected.

### Telegram Gateway (`bearmemori-telegram-1`)
```
2026-03-06 01:35:43,851 - tg_gateway.consumer - INFO - Sent ambiguous followup question to user 46646397 for memory f8669fa2-4ca1-4b00-b80f-43527d06c4c7
```

**Note:** Followup question sent, but no subsequent processing of the user's answer logged.

---

## Flow Breakdown

### Expected Flow (Before Changes)
```
1. Original job acquires lock
2. LLM returns ambiguous with followup_question
3. receive_followup_answer releases lock, creates new job
4. New job (with followup_context) re-acquires lock
5. New job processes and completes
6. Lock released via callback confirmation
```

### Current Flow (After Task 1 & 2 Changes)
```
1. Original job acquires lock (no followup_context)
2. Job processes, LLM returns ambiguous intent
3. Job publishes notification, is acked
4. LOCK IS NOT RELEASED - bug!
5. User replies with followup answer
6. receive_followup_answer creates NEW job with followup_context
7. NEW job bypasses lock acquisition (Task 1 fix)
8. NEW job processes and publishes result
9. NEW job is acked
10. LOCK STILL NOT RELEASED - original lock still held!
```

---

## Code Analysis

### `llm_worker/worker/consumer.py` (lines 262-267)
```python
# Ack the message after successful processing
await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)
# NOTE: user lock is NOT released here. It is released by the Telegram
# gateway when the user completes the conversation (confirm/reject/cancel).
# This prevents the next job from being processed while the user is still
# interacting with the current one.
```

**Problem:** The comment assumes the Telegram gateway will release the lock, but for `ambiguous` intent, the lock is never released.

### `telegram/tg_gateway/consumer.py` - `handle_llm_intent_result` (lines 414-428)
```python
elif intent == "ambiguous":
    await bot.send_message(chat_id=user_id, text=followup_question)
    user_data[PENDING_LLM_CONVERSATION] = {
        "memory_id": memory_id,
        "original_text": query,
        "original_timestamp": content.get("original_timestamp"),
        "user_timezone": content.get("user_timezone"),
        "source_chat_id": content.get("source_chat_id"),
        "source_message_id": content.get("source_message_id"),
        "followup_question": followup_question,
    }
```

**Problem:** No lock release here. The lock should be released after the followup flow completes.

### Lock Release Locations

Lock is released in these scenarios:
1. `search` intent completion (lines 400-409 in consumer.py)
2. Callback handlers via `_clear_conversation_state` (callback.py lines 58-85)

**Missing:** Lock release after `ambiguous` intent notification is sent OR after reclassification result is processed.

---

## Root Cause Summary

**The original job's lock is never released because:**

1. The original job (`84b3b399`) acquired the lock with `user_id=46646397`
2. The job processed successfully and published a notification with `intent="ambiguous"`
3. The job was acked, but the lock was NOT released
4. The lock release mechanism only triggers for:
   - `search` intent (special case in consumer.py)
   - Callback confirmation (via `_clear_conversation_state`)
5. For `ambiguous` intent, the flow is supposed to continue with followup, but the original lock remains held
6. The followup job (`e7a68244`) with `followup_context` bypasses lock acquisition but doesn't acquire/release the lock
7. **Result:** The original lock stays held indefinitely

---

## Impact

- New messages from the user are deferred because the lock is held
- The `llm:followup` stream shows 2 pending messages that could be processed
- The conversation flow is blocked

---

## Fix Strategy

The lock should be released when:
1. The `ambiguous` intent notification is sent, OR
2. The reclassification result is processed (when user confirms via callback)

Option 1 is cleaner - release lock immediately after sending followup question since the followup job will bypass lock acquisition anyway.