# BearMemori Bug Fix Tasks

## Index

| ID | Title | Status |
|----|-------|--------|
| T005 | Store full context in PENDING_LLM_CONVERSATION | [x] |
| T006 | Pass full context in followup LLM job payload | [x] |
| T007 | Add explicit timezone instruction to RECLASSIFY_PROMPT | [x] |
| T008 | Unit tests for PENDING_LLM_CONVERSATION context | [x] |
| T009 | Unit tests for followup job payload | [x] |
| T010 | Integration test for timezone-aware followup | [x] |

---

## T005: Store full context in PENDING_LLM_CONVERSATION

### Objective
In consumer.py, when storing the followup state in PENDING_LLM_CONVERSATION, include user_timezone, original_timestamp, source_chat_id, and source_message_id so the context persists through the conversation.

### Scope files
- **Allowed:** `telegram/tg_gateway/consumer.py`
- **Avoid touching:** Other files in telegram/, llm_worker/, core/

### Testing Strategy
- Test file location: `tests/test_telegram/test_consumer_followup.py` (create)
- Test framework: pytest with pytest-asyncio
- Behaviors to assert:
  - Given a message with user_timezone and original_timestamp in content
  - When PENDING_LLM_CONVERSATION is stored
  - Then the stored dict should contain all 4 new fields: user_timezone, original_timestamp, source_chat_id, source_message_id
- Mock/stub requirements: Mock redis client, mock user_data dict
- Must NOT test: Database operations, actual LLM processing

### Read hints
- Grep queries: "PENDING_LLM_CONVERSATION", "followup_question", "memory_id"
- Key entrypoints: Line ~419 in `telegram/tg_gateway/consumer.py`

### Details
Current code at line 419-423:
```python
user_data[PENDING_LLM_CONVERSATION] = {
    "memory_id": memory_id,
    "original_text": query,
    "followup_question": followup_question,
}
```
**Implementation required:**
1. Extract `content.get("original_timestamp")` and `content.get("source_chat_id")` and `content.get("source_message_id")` from the incoming message
2. Extract `tz_name` (user_timezone) - look for it in user object or content
3. Add all 4 fields to the stored dict:
```python
user_data[PENDING_LLM_CONVERSATION] = {
    "memory_id": memory_id,
    "original_text": query,
    "original_timestamp": content.get("original_timestamp"),
    "user_timezone": tz_name,
    "source_chat_id": content.get("source_chat_id"),
    "source_message_id": content.get("source_message_id"),
    "followup_question": followup_question,
}
```

### Acceptance checks
- Behavioral: PENDING_LLM_CONVERSATION stores all context needed for timezone-aware followup processing
- Commands: `pytest tests/test_telegram/test_consumer_followup.py -v`

### Context budget
- Expected excerpts to read: ~30 lines from consumer.py around line 400-430
- Notes: Verify where tz_name and source IDs come from in the existing code

---

## T006: Pass full context in followup LLM job payload

### Objective
In conversation.py, when the user answers a followup question, pass user_timezone, original_timestamp, source_chat_id, and source_message_id to the LLM job. Also include conversation_history for the LLM to have full context.

### Scope files
- **Allowed:** `telegram/tg_gateway/handlers/conversation.py`
- **Avoid touching:** consumer.py, other handlers

### Testing Strategy
- Test file location: `tests/test_telegram/test_conversation_followup.py` (create)
- Test framework: pytest with pytest-asyncio
- Behaviors to assert:
  - Given a pending followup with all context fields stored
  - When receive_followup_answer is called
  - Then the created LLMJobCreate payload should contain:
    - user_timezone
    - original_timestamp
    - source_chat_id
    - source_message_id
    - followup_context with conversation_history array (3 messages: original user message, assistant question, user answer)
- Mock/stub requirements: Mock core_client.create_llm_job
- Must NOT test: Actual LLM processing, database operations

### Read hints
- Grep queries: "receive_followup_answer", "LLMJobCreate", "followup_context"
- Key entrypoints: Line ~371 in `telegram/tg_gateway/handlers/conversation.py`

### Details
Current code at line ~371-381:
```python
await core_client.create_llm_job(
    LLMJobCreate(
        job_type=JobType.intent_classify,
        payload={
            "message": original_text,
            "memory_id": memory_id,
            "followup_context": {
                "followup_question": followup_question,
                "user_answer": user_answer,
            },
        },
        user_id=user.id,
    )
)
```
**Implementation required:**
1. Get the pending conversation from user_data[PENDING_LLM_CONVERSATION]
2. Extract all 4 context fields: user_timezone, original_timestamp, source_chat_id, source_message_id
3. Build conversation_history array:
```python
conversation_history = [
    {"role": "user", "content": original_text},
    {"role": "assistant", "content": followup_question},
    {"role": "user", "content": user_answer},
]
```
4. Update the payload:
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
        "conversation_history": conversation_history,
    },
}
```

### Acceptance checks
- Behavioral: Followup LLM job receives full context including timezone and conversation history
- Commands: `pytest tests/test_telegram/test_conversation_followup.py -v`

### Context budget
- Expected excerpts to read: ~50 lines from conversation.py around receive_followup_answer
- Notes: Verify where pending dict is retrieved

---

## T007: Add explicit timezone instruction to RECLASSIFY_PROMPT

### Objective
Update the RECLASSIFY_PROMPT in prompts.py to explicitly instruct the LLM on how to convert time references using the user's timezone.

### Scope files
- **Allowed:** `llm_worker/worker/prompts.py`
- **Avoid touching:** Other files

### Testing Strategy
- Test file location: `tests/test_llm_worker/test_prompts.py` (create or add to existing)
- Test framework: pytest
- Behaviors to assert:
  - Given RECLASSIFY_PROMPT template
  - When rendered with user_timezone="Asia/Singapore" and user_answer="5pm"
  - Then the prompt should contain explicit instruction about timezone conversion
  - The resolved UTC time should be computed correctly (5pm +8 = 09:00 UTC)
- Mock/stub requirements: None (just string template check)
- Must NOT test: Actual LLM behavior

### Read hints
- Grep queries: "RECLASSIFY_PROMPT", "user_timezone", "original_timestamp"
- Key entrypoints: Line ~55-60 in `llm_worker/worker/prompts.py`

### Details
Current prompt at lines 55-60:
```
RECLASSIFY_PROMPT = """\
The user originally sent: {original_message}
A clarifying question was asked: {followup_question}
The user answered: {user_answer}
Original timestamp: {original_timestamp}
User timezone: {user_timezone}
```
**Implementation required:**
Add explicit instruction about timezone conversion. Add this after the existing variables:
```
CRITICAL: When resolving time references like "5pm", use the provided
user_timezone ({user_timezone}) to convert to UTC. For example, if
user_timezone is "Asia/Singapore" and user says "5pm", the resolved
time should be computed as 5pm in Singapore = 17:00 - 8 hours = 09:00 UTC.
Do NOT assume times are in UTC - always use the provided user_timezone.
```

### Acceptance checks
- Behavioral: Prompt contains clear instruction on timezone conversion
- Commands: `pytest tests/test_llm_worker/test_prompts.py -v`

### Context budget
- Expected excerpts to read: ~20 lines from prompts.py RECLASSIFY_PROMPT
- Notes: Keep the instruction concise but explicit

---

## T008: Unit tests for PENDING_LLM_CONVERSATION context

### Objective
Write unit tests verifying that when a followup is created, the PENDING_LLM_CONVERSATION stores all required context fields.

### Scope files
- **Allowed:** `tests/test_telegram/test_consumer_followup.py`
- **Avoid touching:** Production code

### Testing Strategy
- Test file location: `tests/test_telegram/test_consumer_followup.py`
- Test framework: pytest with pytest-asyncio
- Behaviors to assert:
  - Given incoming message with all context fields
  - When handler processes followup
  - Then PENDING_LLM_CONVERSATION should have keys: memory_id, original_text, original_timestamp, user_timezone, source_chat_id, source_message_id, followup_question
  - Given incoming message missing some fields
  - Then those fields should be None/empty in stored dict
- Mock/stub requirements: Mock user_data dict, mock logger
- Must NOT test: Actual Redis storage, LLM job creation

### Read hints
- Grep queries: "PENDING_LLM_CONVERSATION", "test_"
- Key entrypoints: N/A - new test file

### Details
Test cases to write:
1. `test_pending_conversation_stores_all_fields` - verify all 7 fields are stored
2. `test_pending_conversation_handles_missing_fields` - verify None handling for missing fields
3. `test_pending_conversation_clears_after_store` - verify old state doesn't persist incorrectly

### Acceptance checks
- Behavioral: All context fields are properly stored in PENDING_LLM_CONVERSATION
- Commands: `pytest tests/test_telegram/test_consumer_followup.py -v`

### Context budget
- Expected excerpts to read: ~100 lines from test file
- Notes: Focus on T005 implementation verification

---

## T009: Unit tests for followup job payload

### Objective
Write unit tests verifying that when a user answers a followup, the LLM job payload contains all required fields including conversation_history.

### Scope files
- **Allowed:** `tests/test_telegram/test_conversation_followup.py`
- **Avoid touching:** Production code

### Testing Strategy
- Test file location: `tests/test_telegram/test_conversation_followup.py`
- Test framework: pytest with pytest-asyncio
- Behaviors to assert:
  - Given pending conversation with all context stored
  - When receive_followup_answer is called
  - Then LLMJobCreate should have user_timezone, original_timestamp, source_chat_id, source_message_id in payload
  - Then followup_context should have conversation_history with 3 entries
  - Given user_timezone is None
  - Then should still create job with default or empty timezone
- Mock/stub requirements: Mock core_client.create_llm_job
- Must NOT test: Actual LLM processing

### Read hints
- Grep queries: "receive_followup_answer", "LLMJobCreate"
- Key entrypoints: N/A - new test file

### Details
Test cases to write:
1. `test_followup_job_includes_timezone_context` - verify all timezone fields in payload
2. `test_followup_job_includes_conversation_history` - verify conversation_history array is correct
3. `test_followup_job_handles_missing_timezone` - verify graceful handling when timezone is None

### Acceptance checks
- Behavioral: Followup LLM job has complete context for timezone-aware processing
- Commands: `pytest tests/test_telegram/test_conversation_followup.py -v`

### Context budget
- Expected excerpts to read: ~100 lines from test file
- Notes: Focus on T006 implementation verification

---

## T010: Integration test for timezone-aware followup

### Objective
End-to-end test that verifies the entire followup flow correctly handles timezone-aware time resolution. Starting from user message with timezone, through followup question, to user's answer "5pm" being correctly converted to UTC.

### Scope files
- **Allowed:** `tests/test_telegram/test_timezone_followup_e2e.py`
- **Avoid touching:** Production code

### Testing Strategy
- Test file location: `tests/test_telegram/test_timezone_followup_e2e.py`
- Test framework: pytest with pytest-asyncio
- Behaviors to assert:
  - Given user in timezone Asia/Singapore (+8)
  - When user sends "prep dinner for picnic later"
  - And LLM returns ambiguous with followup question
  - And user answers "5pm"
  - Then the final LLM job should have user_timezone="Asia/Singapore"
  - And the resolved time should be 09:00 UTC (not 17:00 UTC)
- Mock/stub requirements: Mock LLM worker to capture the final resolved timestamp
- Must NOT test: Actual database storage, Redis operations

### Read hints
- Grep queries: "ambiguous", "followup", "intent_classify"
- Key entrypoints: Integration between consumer.py and conversation.py

### Details
Test scenario:
1. Mock the flow: user message -> LLM returns ambiguous -> store pending -> user answers "5pm" -> final LLM job created
2. Capture the final job payload
3. Assert user_timezone is present and conversation_history has 3 entries
4. This validates the complete fix works end-to-end

### Acceptance checks
- Behavioral: Timezone context flows through entire followup conversation, enabling correct time resolution
- Commands: `pytest tests/test_telegram/test_timezone_followup_e2e.py -v`

### Context budget
- Expected excerpts to read: ~150 lines from test file
- Notes: This is the final validation that the bug is fixed

---

## Summary

Remaining tasks for timezone followup bug fix (T005-T010):

- **T005**: Store full context in PENDING_LLM_CONVERSATION (consumer.py)
- **T006**: Pass full context in followup LLM job payload (conversation.py)
- **T007**: Add explicit timezone instruction to RECLASSIFY_PROMPT (prompts.py)
- **T008**: Unit tests for PENDING_LLM_CONVERSATION context
- **T009**: Unit tests for followup job payload
- **T010**: Integration test for timezone-aware followup

Note: T001-T004 (PEL recovery tasks) are already complete and have been removed from this file.
