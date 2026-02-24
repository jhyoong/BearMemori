# Plan D: Implementation — Text Message Queue Flow

## Context

This plan covers the Telegram gateway changes needed to support the queue-first text message flow. Currently, `handle_text` in `message.py` saves text immediately as a confirmed memory and shows action buttons. The new flow queues text for LLM classification and sends a context-aware acknowledgment: "Processing..." if the queue is empty/idle, or "Added to queue" if the queue already has items or is mid-processing.

**Key change from BDD revision:** All text memories start as **pending** after LLM classification. They are only confirmed when the user takes an explicit action via a system button. If no action is taken within 7 days, the pending memory is hard deleted. This aligns text handling with the existing image pending/confirmed model.

**Relevant BDD scenarios:** 10-15 (text input), 16-18 (ambiguous), 19-23 (inline actions), 45-51 (queue processing), 59 (LLM unavailable).

## Current State (from codebase exploration)

### `telegram/tg_gateway/handlers/message.py`
- `handle_text(update, context)`: checks for pending conversation states (`pending_tag_memory_id`, `pending_task_memory_id`, `pending_reminder_memory_id`), then creates a `MemoryCreate`, calls `core_client.create_memory()`, replies "Saved!" with `memory_actions_keyboard`.
- No queue logic exists.

### `telegram/tg_gateway/handlers/conversation.py`
- Tracks three pending states: `PENDING_TAG_MEMORY_ID`, `PENDING_TASK_MEMORY_ID`, `PENDING_REMINDER_MEMORY_ID`.
- Handlers: `receive_tags()`, `receive_custom_date()`, `receive_custom_reminder()`.
- `receive_custom_date()` hardcodes description as `"Task for memory"`.
- `receive_custom_reminder()` hardcodes text as `"Custom reminder"`.

### `telegram/tg_gateway/consumer.py`
- `_dispatch_notification(bot, data)` handles `llm_intent_result` by displaying intent label and (empty) results.
- No flood control logic.
- `_serialize_callback` is duplicated from `keyboards.py`.

### `telegram/tg_gateway/keyboards.py`
- `memory_actions_keyboard(memory_id, is_image=False)` — standard post-capture keyboard.
- No keyboards for reminder/task proposals or reschedule flow.

### `telegram/tg_gateway/callback_data.py`
- Defines: `MemoryAction`, `TaskAction`, `DueDateChoice`, `ReminderTimeChoice`, `ConfirmDelete`, `SearchDetail`, `TagConfirm`.
- No callback data types for intent-based proposal confirmation.

---

## Changes Required

### 1. `telegram/tg_gateway/handlers/message.py` — Queue text instead of immediate save

**Modify `handle_text`:**
- KEEP the existing pending conversation state checks at the top (tag, task, reminder).
- ADD a new check at the top of the routing logic: if `PENDING_LLM_CONVERSATION` is set in `context.user_data`, this means the LLM asked a follow-up question and the user is replying. Route to `receive_followup_answer()` in conversation.py. This only applies when the system is in conversation state (LLM asked for additional text input, per BDD Scenario 16).
- ADD a separate check: if the system is **awaiting button input** (i.e., `AWAITING_BUTTON_ACTION` flag is set but `PENDING_LLM_CONVERSATION` is NOT set), the user is sending new text while buttons are displayed. In this case, add the text to the queue as a new message — do NOT treat it as a conversation reply (BDD Scenario 49).
- REPLACE the "create memory + reply Saved!" block with:
  1. Check the user's queue state (is the queue empty and idle, or does it have pending items / is mid-processing?).
  2. If queue is empty and idle: reply "Processing..." to the user.
  3. If queue has items or is mid-processing: reply "Added to queue" to the user.
  4. Create an LLM job via `core_client.create_llm_job()` with `job_type=JobType.intent` (or a new `JobType.text_classify`), including the text content and the original message timestamp in the payload.
  5. Do NOT create a memory yet — the memory is created as **pending** after LLM classification by the consumer.

**Queue state tracking:** The queue state per user can be tracked via:
- A counter or flag in `context.user_data` (e.g., `USER_QUEUE_COUNT`), incremented on message receive, decremented when a result is delivered.
- Or by querying the core API / Redis for pending LLM jobs for this user.
The simplest approach is an in-memory counter in `context.user_data` since `python-telegram-bot` persists user_data across the session.

**Two distinct "waiting" states:**
- `AWAITING_BUTTON_ACTION`: set when the system displays buttons to the user. Cleared when the user presses any button or 7-day timeout fires. New text during this state goes to queue (BDD Scenario 49).
- `PENDING_LLM_CONVERSATION`: set when the LLM asks a follow-up question (ambiguous intent). Cleared when the user replies with text, presses a button, or 7-day timeout fires. Next text during this state is treated as the follow-up answer (BDD Scenarios 16, 46, 47).

### 2. `telegram/tg_gateway/handlers/conversation.py` — Add follow-up conversation tracking

**Add new state keys:**
- `PENDING_LLM_CONVERSATION = "pending_llm_conversation"` — set when LLM asks a follow-up question.
- `AWAITING_BUTTON_ACTION = "awaiting_button_action"` — set when buttons are displayed to the user.

**Add new handler `receive_followup_answer(update, context)`:**
- Pop `PENDING_LLM_CONVERSATION` from `context.user_data`.
- Extract: original message text, LLM's question, memory_id from the context.
- Create a new LLM job for re-classification, including both the original message and the user's answer in the payload.
- Reply "Processing..." (the re-classification result will come via the consumer).

**Conversation conclusion rules (no short timeout):**
A conversation (either `PENDING_LLM_CONVERSATION` or `AWAITING_BUTTON_ACTION`) is concluded ONLY by:
1. The user pressing a system button (callback handler clears the state).
2. A 7-day timeout (expiry job clears the state and hard deletes the pending memory).

There is NO 5-minute or other short timeout. This aligns with BDD Scenarios 17 and 48.

**7-day expiry mechanism:**
- When setting either conversation state, store `pending_expires_at` as the current time + 7 days.
- A periodic check (or the core API's expiry job) detects expired pending memories and:
  - Hard deletes the pending memory from the database.
  - Clears the conversation state for the user.
  - Resumes queue processing for the user.
  - Records the expiry in the audit log.

**Fix hardcoded strings:**
- `receive_custom_date()`: pull description from the actual memory content instead of `"Task for memory"`.
- `receive_custom_reminder()`: pull text from the actual memory content instead of `"Custom reminder"`.

### 3. `telegram/tg_gateway/consumer.py` — Handle enriched intent results + flood control

**Rework `llm_intent_result` handler:**
The current handler just displays the intent label. Replace with intent-specific routing. All intents that create a memory create it as **pending** (not confirmed). The memory is only confirmed when the user presses a system button:

- **reminder**: Create **pending** memory via core API. Send reminder proposal message with `reminder_proposal_keyboard(memory_id)`. Set `AWAITING_BUTTON_ACTION`. (BDD Scenario 10)
- **task**: Create **pending** memory via core API. Send task proposal message with `task_proposal_keyboard(memory_id)`. Set `AWAITING_BUTTON_ACTION`. (BDD Scenario 11)
- **search**: Do NOT create memory. Call core API search endpoint. Send results with `search_results_keyboard(results)`. No conversation state needed. Decrement queue counter. (BDD Scenario 13)
- **general_note**: Create **pending** memory via core API. Send tag suggestions with `general_note_keyboard(memory_id, suggested_tags)`. Set `AWAITING_BUTTON_ACTION`. (BDD Scenario 12)
- **ambiguous**: Create **pending** memory via core API. Send follow-up question text (no keyboard). Set `PENDING_LLM_CONVERSATION`. Queue paused for this user until conversation concludes. (BDD Scenario 16)

**Queue pause on conversation:**
- When `PENDING_LLM_CONVERSATION` is set, the queue must not process the next message for this user.
- When `AWAITING_BUTTON_ACTION` is set, the queue also must not process the next message — it waits for the button press or 7-day timeout (BDD Scenarios 45, 49).
- When the conversation concludes (button pressed or timeout), clear the state and resume queue processing.

**Add flood control:**
- When processing backlog messages, add a configurable delay (e.g., `asyncio.sleep(FLOOD_CONTROL_DELAY_SECONDS)`) between delivering results for consecutive messages from the same user.
- Each result should reference the original message for context (e.g., "Re: your message 'Buy groceries' from Feb 10").

**Add stale message handling:**
- When `llm_intent_result` includes a resolved datetime that is in the past, send the stale message notification with `reschedule_keyboard(memory_id)`. (BDD Scenario 50)

**Remove duplicated `_serialize_callback`:**
- Import from `keyboards.py` instead.

### 4. `telegram/tg_gateway/keyboards.py` — New context-dependent keyboards

**Add new keyboard builders:**

`reminder_proposal_keyboard(memory_id)` — For LLM-classified reminders:
- Row: [Confirm] [Edit time] [Just a note]
- Uses new callback data types (see below).

`task_proposal_keyboard(memory_id)` — For LLM-classified tasks:
- Row: [Confirm] [Edit] [Just a note]

`reschedule_keyboard(memory_id)` — For stale messages:
- Row: [Reschedule] [Dismiss]

### 5. `telegram/tg_gateway/callback_data.py` — New callback data types

**Add:**
- `IntentConfirm(memory_id: str, action: str)` — for confirming/editing/dismissing reminder and task proposals. Actions: `confirm_reminder`, `edit_reminder_time`, `confirm_task`, `edit_task`, `just_a_note`.
- `RescheduleAction(memory_id: str, action: str)` — for stale message reschedule. Actions: `reschedule`, `dismiss`.

### 6. `telegram/tg_gateway/handlers/callback.py` — Handle new callback types + confirm pending memories

All button press handlers must:
1. Confirm the pending memory (change status from pending to confirmed) via `core_client.update_memory(memory_id, status="confirmed")`.
2. Clear the conversation state (`AWAITING_BUTTON_ACTION` or `PENDING_LLM_CONVERSATION`).
3. Resume queue processing for the user (decrement counter, signal next item).

**Handle `IntentConfirm` callbacks:**
- `confirm_reminder`: Confirm memory. Create the reminder. Reply "Reminder set for {time}". (BDD Scenario 10)
- `edit_reminder_time`: Confirm memory. Show `reminder_time_keyboard(memory_id)`. (BDD Scenario 10 variant)
- `confirm_task`: Confirm memory. Create the task. Reply "Task created: {description}". (BDD Scenario 11)
- `edit_task`: Confirm memory. Show `due_date_keyboard(memory_id)`.
- `just_a_note`: Confirm memory. Reply "Kept as a note." Show `memory_actions_keyboard(memory_id)`. (BDD Scenario 14)

**Handle `RescheduleAction` callbacks:**
- `reschedule`: Confirm memory. Set `PENDING_REMINDER_MEMORY_ID` in context, prompt user for new date/time. Reuse existing `receive_custom_reminder()` flow. (BDD Scenario 50)
- `dismiss`: Confirm memory (keep as note, no reminder). Reply "Dismissed." Remove keyboard.

**Handle existing button actions (Tag, Pin, Delete, etc.):**
- All existing button handlers that operate on pending memories must also confirm the memory first.
- **Pin**: Confirm memory. Auto-save any suggested tags. Pin the memory. (BDD Scenarios 6, 21)
- **Delete on pending**: Hard delete the pending memory. (BDD Scenarios 7, 22)
- **Confirm Tags**: Confirm memory. Save suggested tags. (BDD Scenario 12)
- **Edit Tags**: Confirm memory. Prompt for manual tags. (BDD Scenario 20)
- **Task (from general_note)**: Confirm memory. Create task. (BDD Scenario 19)
- **Remind (from general_note)**: Confirm memory. Propose reminder time. (BDD Scenario 23)

### 7. Core API — Potential endpoint changes

**Check if needed:**
- The current `create_llm_job()` endpoint may need to accept the original message timestamp in the payload.
- May need a way to query queued-but-not-yet-classified messages per user (for queue status).
- Evaluate whether the existing LLM job table structure can represent the new "text_classify" job type or if a new `JobType` enum value is needed in `shared_lib/enums.py`.
- The `create_memory()` endpoint must support creating memories with `status=pending` for text (currently only images use pending status).
- May need an endpoint or mechanism to update memory status from `pending` to `confirmed`.

---

## Files to Edit

1. `telegram/tg_gateway/handlers/message.py` — queue text, check conversation state, route follow-up answers vs new messages
2. `telegram/tg_gateway/handlers/conversation.py` — add `PENDING_LLM_CONVERSATION`, `AWAITING_BUTTON_ACTION`, follow-up handler, 7-day expiry, fix hardcoded strings
3. `telegram/tg_gateway/consumer.py` — rework intent result handling (create pending memories), manage conversation states, add flood control, stale message handling, remove duplicated helper
4. `telegram/tg_gateway/keyboards.py` — add reminder_proposal, task_proposal, reschedule keyboards
5. `telegram/tg_gateway/callback_data.py` — add IntentConfirm, RescheduleAction
6. `telegram/tg_gateway/handlers/callback.py` — handle new callback types, confirm pending memories on all button actions, clear conversation state, resume queue
7. `shared/shared_lib/enums.py` — possibly add new JobType value
8. Core API endpoint(s) — support pending text memories, status update endpoint

## Dependencies

- Plan A (PRD) and Plans B+C (BDD) should be completed first.
- Plan E (LLM Intent & Retry) must be implemented alongside or before this plan, since this plan depends on the LLM worker returning enriched intent results with extracted entities.

## Testing

- Add tests in `tests/test_telegram/` for:
  - `handle_text` queuing behaviour (mock core_client)
  - `receive_followup_answer` handler
  - Text during button-waiting goes to queue (not treated as conversation)
  - Text during follow-up conversation treated as answer
  - 7-day expiry clears state and deletes pending memory
  - Pending memory confirmed on button press
  - Pin auto-saves suggested tags
  - New keyboard builders
  - New callback handlers
  - Queue pause/resume on conversation state changes
