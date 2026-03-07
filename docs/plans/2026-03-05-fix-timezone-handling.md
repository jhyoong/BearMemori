# Fix Timezone Handling in LLM Intent Classification and Assistant

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix timezone and timestamp context being lost during followup intent classification, improve the initial intent classify prompt to be explicit about timezone conversion, and add time/timezone awareness to the assistant service.

**Architecture:** There are three independent issues causing incorrect reminder times: (1) the LLM worker's IntentHandler does not forward `original_timestamp`, `user_timezone`, `source_chat_id`, `source_message_id` from the job payload to the result, so the Telegram consumer receives `None` for these fields when storing `PENDING_LLM_CONVERSATION` state for ambiguous intents; (2) the initial `INTENT_CLASSIFY_PROMPT` is vague about timezone-to-UTC conversion while the `RECLASSIFY_PROMPT` is explicit; (3) the assistant service system prompt has no time/timezone context and the `create_reminder` tool schema does not specify that `fire_at` must be UTC.

**Tech Stack:** Python, asyncio, pytest, OpenAI API prompts

---

### Task 1: Forward payload metadata through IntentHandler result

The root cause of the followup timezone loss. The `IntentHandler.handle()` returns a `structured_result` dict that is published as `content` in the notification to the Telegram consumer. The consumer reads `content.get("user_timezone")` etc., but these fields are never added to the result.

**Files:**
- Modify: `llm_worker/worker/handlers/intent.py:106-116`
- Test: `tests/test_llm_worker/test_intent.py`

**Step 1: Write the failing test**

Add to `tests/test_llm_worker/test_intent.py`:

```python
@pytest.mark.asyncio
async def test_intent_result_includes_payload_metadata(self, handler, mock_llm_client):
    """Test that original_timestamp, user_timezone, source_chat_id, and
    source_message_id from the payload are forwarded to the result."""
    mock_llm_client.complete = AsyncMock(
        return_value='{"intent": "ambiguous", "followup_question": "Task or reminder?", "possible_intents": ["reminder", "task"]}'
    )

    payload = {
        "message": "remind me about the meeting",
        "original_timestamp": "2026-03-05T13:06:54+00:00",
        "user_timezone": "Asia/Singapore",
        "source_chat_id": "123456",
        "source_message_id": "789",
    }

    result = await handler.handle("job-meta", payload, user_id=12345)

    assert result["original_timestamp"] == "2026-03-05T13:06:54+00:00"
    assert result["user_timezone"] == "Asia/Singapore"
    assert result["source_chat_id"] == "123456"
    assert result["source_message_id"] == "789"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_worker/test_intent.py::TestIntentHandler::test_intent_result_includes_payload_metadata -v`
Expected: FAIL — the result dict does not contain these keys.

**Step 3: Write minimal implementation**

In `llm_worker/worker/handlers/intent.py`, after building `structured_result` (around line 116), add:

```python
# Forward payload metadata so the Telegram consumer can store it
# for followup conversations (timezone, timestamp, source IDs).
for meta_key in ("original_timestamp", "user_timezone", "source_chat_id", "source_message_id"):
    if meta_key not in structured_result:
        structured_result[meta_key] = payload.get(meta_key)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_worker/test_intent.py::TestIntentHandler::test_intent_result_includes_payload_metadata -v`
Expected: PASS

**Step 5: Run all intent tests to check for regressions**

Run: `pytest tests/test_llm_worker/test_intent.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add llm_worker/worker/handlers/intent.py tests/test_llm_worker/test_intent.py
git commit -m "fix: forward payload metadata (timezone, timestamp) through IntentHandler result"
```

---

### Task 2: Make INTENT_CLASSIFY_PROMPT explicit about timezone conversion

The initial classify prompt says "accounting for the user's timezone" but only shows an example of adding a relative offset. The reclassify prompt is much clearer. Align them.

**Files:**
- Modify: `llm_worker/worker/prompts.py:11-53`

**Step 1: Update the INTENT_CLASSIFY_PROMPT**

In `llm_worker/worker/prompts.py`, replace the time resolution paragraph (lines 50-52) and update the reminder/task examples (lines 36, 39) to be explicit about timezone conversion. The key changes:

1. Add a CRITICAL timezone block (matching the style in RECLASSIFY_PROMPT):

Replace line 50-52 (the paragraph starting with "Resolve relative time references"):

```python
CRITICAL: When resolving time references, use the provided user_timezone ({user_timezone})
to convert to UTC. For absolute times like "5pm" or "at 10pm", interpret them in the
user's timezone and convert to UTC. For example, if user_timezone is "Asia/Singapore"
(UTC+8) and user says "at 10pm", resolved_time = 2026-03-05T14:00:00Z (10pm SGT = 22:00 - 8h = 14:00 UTC).
For relative times like "in 10 minutes", add the offset to original_timestamp.
Do NOT assume times are in UTC - always use the provided user_timezone.
NEVER return the original_timestamp unchanged - always compute the correct resolved time.
```

2. Update the reminder example at line 36 to include a timezone example:

```python
{{"intent": "reminder", "action": "what the user wants to be reminded about", "time": "raw time reference from message", "resolved_time": "absolute ISO8601 datetime in UTC. For relative times (e.g. 'in 10 minutes'), add offset to original_timestamp. For absolute times (e.g. 'at 5pm'), interpret in user_timezone and convert to UTC."}}
```

3. Update the task example at line 39 similarly.

**Step 2: Run all intent tests to check for regressions**

Run: `pytest tests/test_llm_worker/test_intent.py -v`
Expected: All PASS (prompt changes don't break mocked tests)

**Step 3: Commit**

```bash
git add llm_worker/worker/prompts.py
git commit -m "fix: make INTENT_CLASSIFY_PROMPT explicit about timezone-to-UTC conversion"
```

---

### Task 3: Add time and timezone context to assistant system prompt

The assistant service has no awareness of the current time or the user's timezone. This means the LLM cannot correctly interpret time-based requests or construct correct `fire_at` values for reminders.

**Files:**
- Modify: `assistant/assistant_svc/agent.py:8-20,46-53`
- Modify: `assistant/assistant_svc/briefing.py:16-74`
- Test: `tests/test_assistant/test_briefing.py`
- Test: `tests/test_assistant/test_agent.py`

**Step 1: Write the failing test for briefing**

Add to `tests/test_assistant/test_briefing.py`:

```python
@pytest.mark.asyncio
async def test_briefing_includes_timezone_and_current_time(self, builder, mock_core_client):
    """Briefing includes the user's timezone and current time."""
    mock_core_client.list_tasks.return_value = []
    mock_core_client.list_reminders.return_value = []
    settings = MagicMock()
    settings.timezone = "Asia/Singapore"
    mock_core_client.get_settings.return_value = settings

    text = await builder.build(user_id=1)
    assert "Asia/Singapore" in text
    assert "Current time" in text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_assistant/test_briefing.py::TestBriefingBuilder::test_briefing_includes_timezone_and_current_time -v`
Expected: FAIL — briefing does not include timezone info.

**Step 3: Update BriefingBuilder to include timezone context**

In `assistant/assistant_svc/briefing.py`, update the `build` method to fetch user settings and prepend time context:

```python
async def build(self, user_id: int) -> str:
    sections = []

    # 0. Time and timezone context
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    try:
        settings = await self._core_client.get_settings(user_id)
        tz_name = settings.timezone
    except Exception:
        tz_name = "UTC"

    now_utc = datetime.now(timezone.utc)
    user_tz = ZoneInfo(tz_name)
    now_user = now_utc.astimezone(user_tz)

    sections.append(
        f"## Time Context\n"
        f"User timezone: {tz_name}\n"
        f"Current time (user): {now_user.strftime('%Y-%m-%d %H:%M %Z')}\n"
        f"Current time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    # ... rest of the method unchanged (tasks, reminders, summary) ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_assistant/test_briefing.py::TestBriefingBuilder::test_briefing_includes_timezone_and_current_time -v`
Expected: PASS

**Step 5: Run all briefing and agent tests**

Run: `pytest tests/test_assistant/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add assistant/assistant_svc/briefing.py tests/test_assistant/test_briefing.py
git commit -m "feat: add timezone and current time context to assistant briefing"
```

---

### Task 4: Update create_reminder tool schema to specify UTC

The `fire_at` parameter description just says "ISO 8601 format" without specifying that it must be in UTC. This is ambiguous for the LLM.

**Files:**
- Modify: `assistant/assistant_svc/tools/reminders.py:44-68`

**Step 1: Update the schema description**

In `assistant/assistant_svc/tools/reminders.py`, update the `fire_at` description:

```python
"fire_at": {
    "type": "string",
    "description": (
        "When to fire the reminder, as an ISO 8601 datetime in UTC "
        "(e.g., '2026-03-06T09:00:00Z'). Convert the user's local "
        "time to UTC using their timezone before providing this value."
    ),
},
```

**Step 2: Commit**

```bash
git add assistant/assistant_svc/tools/reminders.py
git commit -m "fix: clarify that create_reminder fire_at must be UTC in tool schema"
```

---

### Task 5: Add timezone instruction to assistant system prompt

The system prompt should instruct the LLM to always convert times to UTC when creating reminders.

**Files:**
- Modify: `assistant/assistant_svc/agent.py:8-20`

**Step 1: Update SYSTEM_PROMPT**

In `assistant/assistant_svc/agent.py`, add a time handling section to the system prompt:

```python
SYSTEM_PROMPT = """You are a personal assistant with access to the user's memories, tasks, reminders, and events from BearMemori.

You help the user by:
- Answering questions about their stored memories
- Finding relevant information from their data
- Creating tasks and reminders when asked (always confirm before writing)
- Providing proactive suggestions based on their context

For write operations (creating tasks, reminders), ALWAYS ask the user to confirm before executing.

## Time Handling
- The Time Context section below shows the user's timezone and current time.
- When the user mentions a time (e.g., "5pm", "tomorrow morning"), interpret it in their timezone.
- When calling create_reminder or create_task, always convert to UTC for the fire_at/due_at parameter.
- When displaying times to the user, convert from UTC to their timezone.

## Current Context
{briefing}
"""
```

**Step 2: Run all assistant tests**

Run: `pytest tests/test_assistant/ -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add assistant/assistant_svc/agent.py
git commit -m "feat: add time handling instructions to assistant system prompt"
```

---

### Task 6: Run full test suite and verify

**Step 1: Run all tests**

Run: `pytest -v`
Expected: All PASS

**Step 2: Verify no regressions**

Run: `pytest --tb=short`
Expected: All PASS, no warnings about the changed files.
