# Phase 2 - Group 6: Callback Handlers (Inline Button Actions)

## Goal

Implement all inline keyboard callback handling -- the logic that runs when a user taps a button. This covers Task creation, Remind creation, Tag management, Pin, Delete, search detail viewing, and task completion.

**Depends on:** Groups 3 (callback data types), 5 (message handlers create the memories that callbacks act on)
**Blocks:** Group 7 (conversation handlers deal with the "custom" branches that callbacks initiate)

---

## Context

### How Callbacks Work

When a user taps an inline button, Telegram sends a `CallbackQuery` update. Because we use `arbitrary_callback_data=True`, PTB resolves the callback data from its cache and provides the original Python object (e.g., `MemoryAction`, `DueDateChoice`).

The general callback handler dispatches based on `isinstance(query.data, ...)` -- each callback data type maps to a specific handler function.

### Error Handling Patterns

Every callback handler must:
1. Call `await query.answer()` first -- this stops the "loading" spinner on the button
2. Wrap Core API calls in try/except:
   - `CoreUnavailableError` -> edit message to "I'm having trouble reaching my backend."
   - `CoreNotFoundError` -> edit message to "This item no longer exists."

### Expired Buttons

If the bot restarts, PTB's callback data cache is lost. Tapping a button from before restart returns `InvalidCallbackData`. A dedicated handler shows an alert: "This button has expired. Please send your message again."

### Flow Details

Each callback flow:

**Task (MemoryAction.action == "task")**:
1. Show `due_date_keyboard` with options: Today, Tomorrow, Next Week, No Date, Custom
2. User taps a quick option -> calculate due date -> fetch memory content for task description -> `core.create_task(...)` -> edit message with "Task created: {description} (due: {date})"
3. User taps Custom -> set `user_data["pending_task_memory_id"]` -> edit message to ask for date -> Group 7 handles the response

**Remind (MemoryAction.action == "remind")**:
1. Show `reminder_time_keyboard` with options: 1 Hour, Tomorrow 9am, Custom
2. User taps 1 Hour -> `fire_at = now + 1h` -> `core.create_reminder(...)` -> edit message with "Reminder set for {time}"
3. User taps Tomorrow 9am -> fetch user settings for `default_reminder_time` -> calculate `fire_at` -> create reminder
4. User taps Custom -> set `user_data["pending_reminder_memory_id"]` -> ask for time -> Group 7 handles

**Tag (MemoryAction.action == "tag" or "edit_tags")**:
1. Set `user_data["pending_tag_memory_id"] = memory_id`
2. Edit message to "Send me the tags you want to add (comma-separated):"
3. Group 7 handles the user's text response

**Pin (MemoryAction.action == "pin")**:
1. `core.update_memory(memory_id, MemoryUpdate(is_pinned=True, status="confirmed"))`
2. Setting `status="confirmed"` also confirms pending images (pinning counts as user interaction per PRD)
3. Edit message to "Pinned and confirmed!"

**Delete (MemoryAction.action == "delete")**:
1. Show `delete_confirm_keyboard` with "Yes, delete" / "No, cancel"
2. User taps Yes -> `core.delete_memory(memory_id)` -> edit message to "Deleted."
3. User taps No -> restore original `memory_actions_keyboard` -> edit message to "Cancelled."

**Confirm Tags (MemoryAction.action == "confirm_tags")**:
1. Fetch memory with tags: `core.get_memory(memory_id)`
2. Find suggested tags: `[t.tag for t in memory.tags if t.status == "suggested"]`
3. Confirm them: `core.add_tags(memory_id, TagAdd(tags=suggested_tags, status="confirmed"))`
4. Confirm the memory itself: `core.update_memory(memory_id, MemoryUpdate(status="confirmed"))`
5. Edit message to "Tags confirmed: {tags}"

**Search Detail (SearchDetail)**:
1. Fetch full memory: `core.get_memory(memory_id)`
2. Build detail text: content, created_at, status, pinned, confirmed tags
3. If memory has `media_file_id`: send the image with caption (using `context.bot.send_photo`) -- this sends a NEW message because you cannot embed an image in an edited text message
4. If text only: edit the message with the detail text

**Mark Done (TaskAction.action == "mark_done")**:
1. `core.update_task(task_id, TaskUpdate(state=TaskState.DONE))`
2. Edit message to "Task '{description}' marked as done."
3. If the task has `recurrence_minutes`: append "Next instance created (recurs every {n} min)."

**Tag Confirm from LLM suggestions (TagConfirm)**:
1. `confirm_all`: same flow as MemoryAction.confirm_tags
2. `edit`: same flow as MemoryAction.edit_tags (set user_data, ask for tags)

---

## Files to Create

### `telegram/telegram_gw/handlers/callback.py`

#### `async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

Central dispatcher:
1. `query = update.callback_query`
2. `await query.answer()` -- acknowledge immediately
3. `data = query.data`
4. `core = context.bot_data["core_client"]`
5. Try/except block wrapping the dispatch:
   - `isinstance(data, MemoryAction)` -> `_handle_memory_action(query, context, core, data)`
   - `isinstance(data, DueDateChoice)` -> `_handle_due_date_choice(query, context, core, data)`
   - `isinstance(data, ReminderTimeChoice)` -> `_handle_reminder_time_choice(query, context, core, data)`
   - `isinstance(data, ConfirmDelete)` -> `_handle_delete_confirm(query, context, core, data)`
   - `isinstance(data, SearchDetail)` -> `_handle_search_detail(query, context, core, data)`
   - `isinstance(data, TaskAction)` -> `_handle_task_action(query, context, core, data)`
   - `isinstance(data, TagConfirm)` -> `_handle_tag_confirm(query, context, core, data)`
   - Unknown type -> log warning
6. Except `CoreUnavailableError` -> edit message "I'm having trouble reaching my backend."
7. Except `CoreNotFoundError` -> edit message "This item no longer exists."

#### `async def handle_invalid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

For expired/invalid callback data:
- `await update.callback_query.answer(text="This button has expired. Please send your message again.", show_alert=True)`

#### Private handler functions

- `_handle_memory_action(query, context, core, data)` -- match on `data.action` using `match/case`
- `_handle_due_date_choice(query, context, core, data)` -- calculate due date, create task
- `_handle_reminder_time_choice(query, context, core, data)` -- calculate fire_at, create reminder
- `_handle_delete_confirm(query, context, core, data)` -- delete or cancel
- `_handle_search_detail(query, context, core, data)` -- show full memory
- `_handle_task_action(query, context, core, data)` -- mark task done
- `_handle_tag_confirm(query, context, core, data)` -- confirm or edit tags

### Date/Time Calculations

- **Today**: `now.replace(hour=23, minute=59, second=0, microsecond=0)`
- **Tomorrow**: `(now + timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)`
- **Next Week**: `(now + timedelta(weeks=1)).replace(hour=23, minute=59, second=0, microsecond=0)`
- **1 Hour**: `now + timedelta(hours=1)`
- **Tomorrow 9am**: Fetch user settings -> parse `default_reminder_time` (HH:MM) -> `(now + timedelta(days=1)).replace(hour=H, minute=M, second=0, microsecond=0)`

All datetimes in UTC (`datetime.now(timezone.utc)`).

---

## Imports Required

From `shared`:
- `shared.schemas.MemoryUpdate, TaskCreate, TaskUpdate, ReminderCreate, TagAdd`
- `shared.enums.TaskState`

From `telegram_gw`:
- All callback data types from `callback_data.py`
- All keyboard functions from `keyboards.py`
- `CoreClient, CoreUnavailableError, CoreNotFoundError` from `core_client.py`

---

## Acceptance Criteria

1. Tapping "Task" shows due date options
2. Selecting a quick due date (Today/Tomorrow/Next Week/No Date) creates a task and confirms in the message
3. Selecting "Custom" prompts for date entry (hands off to conversation handler)
4. Tapping "Remind" shows time options
5. Selecting "1 Hour" creates a reminder 1 hour from now
6. Selecting "Tomorrow 9am" uses the user's default reminder time from settings
7. Tapping "Pin" pins the memory and confirms pending images (status -> confirmed)
8. Tapping "Delete" shows Yes/No confirmation
9. Confirming delete removes the memory; cancelling restores the original keyboard
10. "Confirm Tags" confirms all suggested tags and sets memory status to confirmed
11. "Edit Tags" prompts for comma-separated tag input
12. "Show details" displays full memory content; images are re-sent via `file_id`
13. "Mark Done" marks task as DONE and notes recurring task creation
14. Expired buttons show alert "This button has expired"
15. Core unavailable shows friendly error message
16. Memory not found (deleted) shows "This item no longer exists"
