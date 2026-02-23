# Plan D: Implementation — Text Message Queue Flow

## Context

This plan covers the Telegram gateway changes needed to support the queue-first text message flow. Currently, `handle_text` in `message.py` saves text immediately as a confirmed memory and shows action buttons. The new flow queues text for LLM classification and sends a context-aware acknowledgment: "Processing..." if the queue is empty/idle, or "Added to queue" if the queue already has items or is mid-processing.

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
- ADD a new check: if `PENDING_LLM_CONTEXT` is set in `context.user_data`, route to a new `receive_followup_answer()` handler in conversation.py (this message is the answer to an LLM follow-up question, not a new message).
- REPLACE the "create memory + reply Saved!" block with:
  1. Check the user's queue state (is the queue empty and idle, or does it have pending items / is mid-processing?).
  2. If queue is empty and idle: reply "Processing..." to the user.
  3. If queue has items or is mid-processing: reply "Added to queue" to the user.
  4. Create an LLM job via `core_client.create_llm_job()` with `job_type=JobType.intent` (or a new `JobType.text_classify`), including the text content and the original message timestamp in the payload.
  5. Do NOT create a memory yet — the memory is created after LLM classification.

**Queue state tracking:** The queue state per user can be tracked via:
- A counter or flag in `context.user_data` (e.g., `USER_QUEUE_COUNT`), incremented on message receive, decremented when a result is delivered.
- Or by querying the core API / Redis for pending LLM jobs for this user.
The simplest approach is an in-memory counter in `context.user_data` since `python-telegram-bot` persists user_data across the session.

### 2. `telegram/tg_gateway/handlers/conversation.py` — Add follow-up context tracking

**Add new state key:**
- `PENDING_LLM_CONTEXT = "pending_llm_context"`

**Add new handler `receive_followup_answer(update, context)`:**
- Pop `PENDING_LLM_CONTEXT` from `context.user_data`.
- Extract: original message text, LLM's question, memory_id from the context.
- Create a new LLM job for re-classification, including both the original message and the user's answer in the payload.
- Reply "Processing..." (the re-classification result will come via the consumer).

**Add context timeout mechanism:**
- When setting `PENDING_LLM_CONTEXT`, also store a timestamp.
- In `handle_text`, before checking `PENDING_LLM_CONTEXT`, compare the stored timestamp against the current time. If more than 5 minutes have elapsed:
  - Clear the context.
  - Resume queue processing (the memory from the original message stays as-is).
  - Treat the current message as a new message (queue it normally).

**Fix hardcoded strings:**
- `receive_custom_date()`: pull description from the actual memory content instead of `"Task for memory"`.
- `receive_custom_reminder()`: pull text from the actual memory content instead of `"Custom reminder"`.

### 3. `telegram/tg_gateway/consumer.py` — Handle enriched intent results + flood control

**Rework `llm_intent_result` handler:**
The current handler just displays the intent label. Replace with intent-specific routing:

- **reminder**: Create memory via core API, send reminder proposal message with `reminder_proposal_keyboard(memory_id)`.
- **task**: Create memory via core API, send task proposal message with `task_proposal_keyboard(memory_id)`.
- **search**: Do NOT create memory. Call core API search endpoint. Send results with `search_results_keyboard(results)`.
- **general_note**: Create memory via core API. Send "Saved!" with LLM-suggested tags and `memory_actions_keyboard(memory_id, is_image=False)` plus tag suggestion row.
- **ambiguous**: Create memory via core API. Send follow-up question. Set `PENDING_LLM_CONTEXT` in user's context (this requires accessing the Application's user_data — may need to pass the Application object instead of just bot).

**Add flood control:**
- When processing backlog messages, add a configurable delay (e.g., `asyncio.sleep(FLOOD_CONTROL_DELAY_SECONDS)`) between delivering results for consecutive messages from the same user.
- Each result should reference the original message for context (e.g., "Re: your message 'Buy groceries' from Feb 10").

**Add stale message handling:**
- When `llm_intent_result` includes a resolved datetime that is in the past, send the stale message notification with `reschedule_keyboard(memory_id)`.

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

### 6. `telegram/tg_gateway/handlers/callback.py` — Handle new callback types

**Add handlers for:**
- `IntentConfirm` callbacks: on confirm_reminder, create the reminder; on confirm_task, create the task; on just_a_note, do nothing (memory already saved); on edit, prompt for new time/details.
- `RescheduleAction` callbacks: on reschedule, show date picker; on dismiss, do nothing.

### 7. Core API — Potential endpoint changes

**Check if needed:**
- The current `create_llm_job()` endpoint may need to accept the original message timestamp in the payload.
- May need a way to query queued-but-not-yet-classified messages per user (for queue status).
- Evaluate whether the existing LLM job table structure can represent the new "text_classify" job type or if a new `JobType` enum value is needed in `shared_lib/enums.py`.

---

## Files to Edit

1. `telegram/tg_gateway/handlers/message.py` — queue text, check follow-up context
2. `telegram/tg_gateway/handlers/conversation.py` — add `PENDING_LLM_CONTEXT`, follow-up handler, timeout, fix hardcoded strings
3. `telegram/tg_gateway/consumer.py` — rework intent result handling, add flood control, stale message handling, remove duplicated helper
4. `telegram/tg_gateway/keyboards.py` — add reminder_proposal, task_proposal, reschedule keyboards
5. `telegram/tg_gateway/callback_data.py` — add IntentConfirm, RescheduleAction
6. `telegram/tg_gateway/handlers/callback.py` — handle new callback types
7. `shared/shared_lib/enums.py` — possibly add new JobType value
8. Core API endpoint(s) — if payload changes are needed

## Dependencies

- Plan A (PRD) and Plans B+C (BDD) should be completed first.
- Plan E (LLM Intent & Retry) must be implemented alongside or before this plan, since this plan depends on the LLM worker returning enriched intent results with extracted entities.

## Testing

- Add tests in `tests/test_telegram/` for:
  - `handle_text` queuing behaviour (mock core_client)
  - `receive_followup_answer` handler
  - Follow-up context timeout
  - New keyboard builders
  - New callback handlers
