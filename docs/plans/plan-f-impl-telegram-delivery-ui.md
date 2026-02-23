# Plan F: Implementation — Telegram Result Delivery & UI

## Context

This plan covers the Telegram-side UI and delivery changes that depend on the enriched LLM results from Plan E and the queue flow from Plan D. It focuses on how results are presented to the user and the keyboard interactions for each intent type.

This plan overlaps with parts of Plan D (consumer.py, keyboards.py). The separation is:
- **Plan D** covers the core flow logic (queuing, context tracking, message routing).
- **Plan F** covers the UI/UX details (keyboard layouts, message formatting, callback handling for intent-specific actions).

If implementing sequentially, Plan D should be done first, and Plan F refines the UI. If implementing together, treat Plan F's details as the specification for the UI portions of Plan D.

---

## Current State

### `telegram/tg_gateway/keyboards.py`
- `memory_actions_keyboard(memory_id, is_image)` — standard post-capture keyboard with rows for [Confirm Tags / Edit Tags] (image only), [Task / Remind], [Tag / Pin / Delete].
- `due_date_keyboard(memory_id)` — [Today / Tomorrow / Next Week] + [No Date / Custom].
- `reminder_time_keyboard(memory_id)` — [1 Hour / Tomorrow 9am] + [Custom].
- `delete_confirm_keyboard(memory_id)` — [Yes, delete / No, cancel].
- `search_results_keyboard(results)` — one button per result.
- `tag_suggestion_keyboard(memory_id)` — [Confirm Tags / Edit Tags].
- No keyboards for intent-based proposals or reschedule.

### `telegram/tg_gateway/consumer.py`
- `llm_intent_result` handler currently shows intent label + empty results.
- `llm_task_match_result` handler duplicates `_serialize_callback` from keyboards.py.
- No flood control.
- No stale message handling.
- `event_confirmation` sends plain text with `[Yes] [No]` as text (not real buttons).

---

## Changes Required

### 1. New Keyboards in `keyboards.py`

**`reminder_proposal_keyboard(memory_id: str) -> InlineKeyboardMarkup`**
- Row 1: [Confirm] [Edit time] [Just a note]
- Callback data: `IntentConfirm(memory_id=memory_id, action="confirm_reminder")`, etc.

**`task_proposal_keyboard(memory_id: str) -> InlineKeyboardMarkup`**
- Row 1: [Confirm] [Edit] [Just a note]
- Callback data: `IntentConfirm(memory_id=memory_id, action="confirm_task")`, etc.

**`reschedule_keyboard(memory_id: str) -> InlineKeyboardMarkup`**
- Row 1: [Reschedule] [Dismiss]
- Callback data: `RescheduleAction(memory_id=memory_id, action="reschedule")`, etc.

**`general_note_keyboard(memory_id: str, suggested_tags: list[str]) -> InlineKeyboardMarkup`**
- Row 1: [Confirm Tags] [Edit Tags] (same as tag_suggestion_keyboard)
- Row 2: [Task] [Remind]
- Row 3: [Pin] [Delete]
- This combines tag suggestions with the standard action buttons.

### 2. Message Formatting in `consumer.py`

**Reminder proposal message:**
```
Set reminder for '{action}' at {time}?
```
With `reminder_proposal_keyboard(memory_id)`.

**Task proposal message:**
```
Create task '{description}' due at {due_time}?
```
With `task_proposal_keyboard(memory_id)`.

**Search results message:**
```
Search results for '{query}':

1. {result_1_snippet}
2. {result_2_snippet}
...
```
With `search_results_keyboard(results)`.

**General note message:**
```
Saved! Suggested tags: {tag1}, {tag2}, {tag3}.
```
With `general_note_keyboard(memory_id, suggested_tags)`.

**Ambiguous follow-up message:**
```
{followup_question}
```
No keyboard — user replies with text.

**Stale message notification:**
```
Your message from {original_date} mentioned a reminder for {resolved_date}, which has passed.
```
With `reschedule_keyboard(memory_id)`.

**Queue expiry notification:**
```
Your message '{truncated_text}' from {original_date} could not be processed and has expired.
```
No keyboard.

**Backlog context reference:**
When delivering results for queued messages (not the most recent one), prefix the message with:
```
Re: your message '{truncated_text}' from {date}:
```

### 3. Callback Handling in `callback.py`

**Handle `IntentConfirm` callbacks:**

- `confirm_reminder`: Create a reminder via `core_client.create_reminder()` using the extracted time from the LLM result. The time should be available in the message data or stored in a temporary context. Reply "Reminder set for {time}".
- `edit_reminder_time`: Show `reminder_time_keyboard(memory_id)` (reuse existing keyboard).
- `confirm_task`: Create a task via `core_client.create_task()` using the extracted description and due time. Reply "Task created: {description}".
- `edit_task`: Show `due_date_keyboard(memory_id)` (reuse existing keyboard).
- `just_a_note`: Do nothing extra — memory is already saved. Reply "Kept as a note." Edit the message to show `memory_actions_keyboard(memory_id)`.

**Handle `RescheduleAction` callbacks:**

- `reschedule`: Set `PENDING_REMINDER_MEMORY_ID` in context, prompt user for new date/time. Reuse existing `receive_custom_reminder()` flow.
- `dismiss`: Do nothing extra — memory stays. Reply "Dismissed." Remove the keyboard.

### 4. Flood Control in `consumer.py`

**Add delay between consecutive result deliveries:**
- Define `FLOOD_CONTROL_DELAY_SECONDS = 7` (configurable).
- In `_dispatch_notification`, after sending a result message, check if the next message in the batch is for the same user. If so, `await asyncio.sleep(FLOOD_CONTROL_DELAY_SECONDS)`.
- This is a simple implementation. The one-at-a-time queue processing already provides natural throttling.

### 5. Fix `event_confirmation` message type

**Current:** Sends `[Yes] [No]` as plain text strings, not real buttons.

**Fix:** Create a proper inline keyboard for event confirmation with real callback buttons, or mark as out of scope (Phase 4 email integration).

### 6. Remove duplicated `_serialize_callback` in `consumer.py`

- Delete the inline definition.
- Import `_serialize_callback` from `keyboards.py` (or make it a public function `serialize_callback`).

---

## Files to Edit

1. `telegram/tg_gateway/keyboards.py` — add reminder_proposal, task_proposal, reschedule, general_note keyboards
2. `telegram/tg_gateway/callback_data.py` — add IntentConfirm, RescheduleAction dataclasses
3. `telegram/tg_gateway/consumer.py` — rework message formatting per intent, add flood control, fix event_confirmation, remove duplicated helper
4. `telegram/tg_gateway/handlers/callback.py` — add handlers for IntentConfirm and RescheduleAction callbacks

## Dependencies

- Plan D (Text Message Queue Flow) — this plan refines the UI for the flow defined in Plan D.
- Plan E (LLM Intent & Retry) — the enriched result payloads defined in Plan E determine the data available for message formatting.

## Testing

- Add tests for each new keyboard builder (verify button labels, callback data structure).
- Add tests for the `IntentConfirm` and `RescheduleAction` callback handlers.
- Add tests for flood control delay behaviour.
- Manual testing: send various text messages and verify the correct keyboard appears for each intent type.
