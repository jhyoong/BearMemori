# Plan F: Implementation — Telegram Result Delivery & UI

## Context

This plan covers the Telegram-side UI and delivery changes that depend on the enriched LLM results from Plan E and the queue flow from Plan D. It focuses on how results are presented to the user and the keyboard interactions for each intent type.

This plan overlaps with parts of Plan D (consumer.py, keyboards.py). The separation is:
- **Plan D** covers the core flow logic (queuing, conversation state tracking, message routing).
- **Plan F** covers the UI/UX details (keyboard layouts, message formatting, callback handling for intent-specific actions).

If implementing sequentially, Plan D should be done first, and Plan F refines the UI. If implementing together, treat Plan F's details as the specification for the UI portions of Plan D.

**Key change from BDD revision:** All memories (text and image) start as **pending**. Every button action must confirm the pending memory before performing its action. Messages to the user should not say "Saved!" since nothing is confirmed until the user acts. Pin auto-saves any suggested tags.

**Relevant BDD scenarios:** 1-9 (image), 10-15 (text), 19-23 (inline actions), 50 (stale message), 52-57 (LLM behavior).

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

**`llm_failure_keyboard(memory_id: str) -> InlineKeyboardMarkup`**
- Row 1: [Edit Tags] [Delete]
- Used when LLM processing fails after all retries (BDD Scenario 62). Allows user to manually tag or delete the pending memory.

### 2. Message Formatting in `consumer.py`

All messages reflect that the memory is **pending** until the user acts. No "Saved!" for text messages.

**Reminder proposal message (BDD Scenario 10):**
```
Set reminder for '{action}' at {time}?
```
With `reminder_proposal_keyboard(memory_id)`.

**Task proposal message (BDD Scenario 11):**
```
Create task '{description}' due at {due_time}?
```
With `task_proposal_keyboard(memory_id)`.

**Search results message (BDD Scenario 13):**
```
Search results for '{query}':

1. {result_1_snippet}
2. {result_2_snippet}
...
```
With `search_results_keyboard(results)`. No memory created.

**General note message (BDD Scenario 12):**
```
Suggested tags: {tag1}, {tag2}, {tag3}.
```
With `general_note_keyboard(memory_id, suggested_tags)`. Note: no "Saved!" prefix — the memory is pending until the user confirms.

**Ambiguous follow-up message (BDD Scenario 16):**
```
{followup_question}
```
No keyboard — user replies with text. The next text message from this user is treated as the answer to this follow-up, not a new message.

**Stale message notification (BDD Scenario 50):**
```
Your message from {original_date} mentioned a reminder for {resolved_date}, which has passed.
```
With `reschedule_keyboard(memory_id)`.

**Queue expiry notification — unavailable (BDD Scenario 54):**
```
Your {type} from {original_date} could not be processed because the service was unavailable and has expired.
```
No keyboard. `{type}` is "image" or "message" depending on the content.

**Queue expiry notification — failed (BDD Scenario 62):**
```
I couldn't generate tags for your image — you can add them manually.
```
With `llm_failure_keyboard(memory_id)`.

**LLM unavailable initial notification (BDD Scenario 56):**
```
Saved as pending! I couldn't generate tags — I'll retry when available.
```
No keyboard initially. Buttons appear when LLM recovers and processes the item.

**LLM invalid response failure notification (BDD Scenario 53):**
```
I couldn't process your {type} after multiple attempts. You can add tags manually.
```
With `llm_failure_keyboard(memory_id)`.

**Backlog context reference:**
When delivering results for queued messages (not the most recent one), prefix the message with:
```
Re: your message '{truncated_text}' from {date}:
```

### 3. Callback Handling in `callback.py`

All callback handlers must follow this pattern:
1. Confirm the pending memory (`status: pending -> confirmed`) via core API.
2. Perform the specific action (create reminder, task, etc.).
3. Clear the conversation state (`AWAITING_BUTTON_ACTION`).
4. Resume queue processing for this user.

**Handle `IntentConfirm` callbacks:**

- `confirm_reminder`: Confirm memory. Create a reminder via `core_client.create_reminder()` using the extracted time. Reply "Reminder set for {time}". (BDD Scenario 10)
- `edit_reminder_time`: Confirm memory. Show `reminder_time_keyboard(memory_id)` (reuse existing keyboard).
- `confirm_task`: Confirm memory. Create a task via `core_client.create_task()` using the extracted description and due time. Reply "Task created: {description}". (BDD Scenario 11)
- `edit_task`: Confirm memory. Show `due_date_keyboard(memory_id)` (reuse existing keyboard).
- `just_a_note`: Confirm memory. Reply "Kept as a note." Edit the message to show `general_note_keyboard(memory_id, [])` for further actions. (BDD Scenario 14)

**Handle `RescheduleAction` callbacks:**

- `reschedule`: Confirm memory. Set `PENDING_REMINDER_MEMORY_ID` in context, prompt user for new date/time. Reuse existing `receive_custom_reminder()` flow. (BDD Scenario 50)
- `dismiss`: Confirm memory (keep as note, no reminder). Reply "Dismissed." Remove the keyboard.

**Handle general_note button actions:**

- `confirm_tags`: Confirm memory. Save suggested tags. Reply "Tags saved." Remove keyboard. (BDD Scenario 12)
- `edit_tags`: Confirm memory. Prompt for manual tag input. (BDD Scenario 20)
- `task` (from general_note): Confirm memory. Create task. (BDD Scenario 19)
- `remind` (from general_note): Confirm memory. Show `reminder_time_keyboard(memory_id)`. (BDD Scenario 23)
- `pin`: Confirm memory. Auto-save any suggested tags. Pin the memory. Reply "Pinned!" (BDD Scenarios 6, 21)
- `delete` (on pending): Hard delete the pending memory. Reply "Deleted." (BDD Scenarios 7, 22)

### 4. Flood Control in `consumer.py`

**Add delay between consecutive result deliveries:**
- Define `FLOOD_CONTROL_DELAY_SECONDS = 7` (configurable).
- In `_dispatch_notification`, after sending a result message, check if the next message in the batch is for the same user. If so, `await asyncio.sleep(FLOOD_CONTROL_DELAY_SECONDS)`.
- This is a simple implementation. The one-at-a-time queue processing already provides natural throttling.

### 5. `event_confirmation` — Out of scope

**Current:** Sends `[Yes] [No]` as plain text strings, not real buttons.

**Decision:** Mark as out of scope. Email integration is not in the current scope (Phase 4). No changes needed.

### 6. Remove duplicated `_serialize_callback` in `consumer.py`

- Delete the inline definition.
- Import `_serialize_callback` from `keyboards.py` (or make it a public function `serialize_callback`).

---

## Files to Edit

1. `telegram/tg_gateway/keyboards.py` — add reminder_proposal, task_proposal, reschedule, general_note, llm_failure keyboards
2. `telegram/tg_gateway/callback_data.py` — add IntentConfirm, RescheduleAction dataclasses
3. `telegram/tg_gateway/consumer.py` — rework message formatting per intent (pending-aware), add flood control, remove duplicated helper
4. `telegram/tg_gateway/handlers/callback.py` — add handlers for IntentConfirm and RescheduleAction callbacks, confirm pending memories on all button actions, auto-save tags on pin

## Dependencies

- Plan D (Text Message Queue Flow) — this plan refines the UI for the flow defined in Plan D.
- Plan E (LLM Intent & Retry) — the enriched result payloads and differentiated failure notifications defined in Plan E determine the data available for message formatting.

## Testing

- Add tests for each new keyboard builder (verify button labels, callback data structure).
- Add tests for `llm_failure_keyboard`.
- Add tests for the `IntentConfirm` and `RescheduleAction` callback handlers.
- Add tests verifying that all button actions confirm the pending memory before performing their action.
- Add tests verifying pin auto-saves suggested tags.
- Add tests for flood control delay behaviour.
- Add tests for differentiated failure/expiry message formatting.
- Manual testing: send various text messages and verify the correct keyboard appears for each intent type.
