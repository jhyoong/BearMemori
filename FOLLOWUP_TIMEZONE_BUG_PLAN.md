# Investigation: Followup Timezone Bug

## Summary

When a user responds to a followup question with a time like "5pm", the LLM incorrectly converts it to UTC without knowing the user's timezone. Result: reminder was set for 17:00 UTC instead of 09:00 UTC (user is in +8 timezone).

## Investigation Findings

### How the Current System Works

1. **Initial Message**: User sends "prep dinner for picnic later"
   - `message.py` creates LLM job WITH full context:
     ```python
     {
       "message": "prep dinner for picnic later",
       "original_timestamp": "2026-03-04T03:56:47+00:00",
       "source_chat_id": 46646397,
       "source_message_id": 670,
       "user_timezone": "Asia/Singapore"
     }
     ```

2. **LLM Response (ambiguous)**: LLM returns:
   ```json
   {
     "intent": "ambiguous",
     "followup_question": "When would you like to prep dinner for the picnic?",
     "memory_id": "30083fd2-614b-4aee-bff7-30cef9f18439"
   }
   ```

3. **Consumer Stores State**: `consumer.py` stores in `PENDING_LLM_CONVERSATION`:
   ```python
   user_data[PENDING_LLM_CONVERSATION] = {
       "memory_id": memory_id,
       "original_text": query,
       "followup_question": followup_question,
   }
   ```
   **MISSING**: `user_timezone` and `original_timestamp`

4. **User Answers "5pm"**: `conversation.py::receive_followup_answer` creates job:
   ```python
   LLMJobCreate(
       job_type=JobType.intent_classify,
       payload={
           "message": original_text,
           "memory_id": memory_id,
           "followup_context": {
               "followup_question": followup_question,
               "user_answer": user_answer,
           }
       }
   )
   ```
   **MISSING**: `user_timezone` and `original_timestamp`

### Database Evidence

From `llm_jobs` table:
```json
// Job #1: Initial message - CORRECT
{"message": "prep dinner for picnic later", ..., "user_timezone": "Asia/Singapore"}

// Job #2: Followup answer - MISSING timezone
{"message": "prep dinner for picnic later", "memory_id": "30083fd2-...", "followup_context": {"followup_question": "...", "user_answer": "5pm"}}
// NO user_timezone!
```

The LLM then converted "5pm" → `2026-03-04T17:00:00Z` (wrong - assumes UTC instead of +8).

---

## Proposed Fix: Include Full Conversation Context in Followups

### Why Current Approach is Fragile

The current approach tries to pass only `user_timezone` and `original_timestamp` as separate fields, but:
1. It's easy to forget these fields (the bug)
2. It doesn't give the LLM full context of the conversation
3. The LLM's prompt instructions reference these fields but they're missing

### Better Approach: Pass Full Conversation History

The LLM should receive the entire conversation so far, including:
- Original user message
- The followup question that was asked
- All previous user answers
- The user's timezone (so it can properly calculate time conversions)
- The original timestamp

This is how the **Assistant Service** already works (using `assistant:chat:{user_id}` in Redis).

### Implementation Plan

#### Step 1: Enhance PENDING_LLM_CONVERSATION to store full context

In `consumer.py`, when storing the followup state, include:
- `user_timezone`
- `original_timestamp`
- `source_chat_id`
- `source_message_id`

**Current (line 419-423):**
```python
user_data[PENDING_LLM_CONVERSATION] = {
    "memory_id": memory_id,
    "original_text": query,
    "followup_question": followup_question,
}
```

**Proposed:**
```python
user_data[PENDING_LLM_CONVERSATION] = {
    "memory_id": memory_id,
    "original_text": query,
    "original_timestamp": content.get("original_timestamp"),  # NEW
    "user_timezone": tz_name,  # NEW
    "source_chat_id": content.get("source_chat_id"),  # NEW
    "source_message_id": content.get("source_message_id"),  # NEW
    "followup_question": followup_question,
}
```

#### Step 2: Include full context in followup job payload

In `conversation.py::receive_followup_answer`, include all context:

**Current (line 371-377):**
```python
payload={
    "message": original_text,
    "memory_id": memory_id,
    "followup_context": {
        "followup_question": followup_question,
        "user_answer": user_answer,
    },
}
```

**Proposed:**
```python
payload={
    "message": original_text,
    "original_timestamp": pending.get("original_timestamp"),
    "user_timezone": pending.get("user_timezone"),
    "source_chat_id": pending.get("source_chat_id"),
    "source_message_id": pending.get("source_message_id"),
    "followup_context": {
        "followup_question": followup_question,
        "user_answer": user_answer,
        "conversation_history": [  # NEW: Full context for LLM
            {"role": "user", "content": original_text},
            {"role": "assistant", "content": followup_question},
            {"role": "user", "content": user_answer},
        ],
    },
}
```

#### Step 3: Update RECLASSIFY_PROMPT to use conversation history

The prompt already passes `original_timestamp` and `user_timezone`, but we should make it clearer that the conversation history should be used for time calculations.

**In `prompts.py` RECLASSIFY_PROMPT:**

Add explicit instruction that the LLM should use the user_timezone when resolving time references:

```
CRITICAL: When resolving time references like "5pm", use the provided
user_timezone ({user_timezone}) to convert to UTC. For example, if
user_timezone is "Asia/Singapore" and user says "5pm", the resolved
time should be computed as 5pm in Singapore = 17:00 - 8 hours = 09:00 UTC.
```

Alternatively, we could simplify by passing conversation history and letting the LLM figure out the context naturally.

---

## Alternative: Use Redis for Conversation History

Instead of passing context through the job payload, we could:

1. **Store conversation in Redis** when processing initial message
2. **Append to conversation** when user answers followup
3. **Pass conversation history ID** in the followup job

But this adds complexity (Redis key management, TTL, cleanup). The inline approach (Steps 1-3 above) is simpler and more reliable.

---

## Summary of Changes Needed

| File | Change | Purpose |
|------|---------|---------|
| `consumer.py` (line ~419) | Store `user_timezone`, `original_timestamp`, `source_chat_id`, `source_message_id` in PENDING_LLM_CONVERSATION | Persist context through conversation |
| `conversation.py` (line ~371) | Pass `user_timezone` and `original_timestamp` in job payload | Send to LLM worker |
| `prompts.py` (optional) | Add explicit instruction about timezone conversion | Ensure LLM uses timezone correctly |

---

## Testing Plan

1. **Unit tests**: Verify `PENDING_LLM_CONVERSATION` includes timezone
2. **Integration test**: Send "prep dinner for picnic later" → followup "5pm" → verify reminder time is correct (09:00 UTC for +8 timezone)
3. **Manual test**: Repeat with different timezones
