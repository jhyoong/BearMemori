# Phase 2 - Group 7: Commands and Conversation Helpers

## Goal

Implement all slash commands (`/find`, `/tasks`, `/pinned`, `/help`, `/cancel`) and the multi-step conversation helpers for tag entry, custom date, and custom reminder time. These are the final user-facing features that complete the Telegram Gateway.

**Depends on:** Groups 4 (entrypoint), 5 (message handlers call conversation helpers), 6 (callback handlers initiate conversation flows)
**Blocks:** None

---

## Context

### Slash Commands

The bot supports these commands:
- `/find <query>` -- search memories via Core's FTS5 search
- `/tasks` -- list open (NOT_DONE) tasks
- `/pinned` -- show pinned memories
- `/help` -- display available commands
- `/cancel` -- cancel any pending conversation action

Commands are registered as `CommandHandler` instances in `main.py` (Group 4) with the `AllowedUsersFilter`.

### Conversation Helpers

Instead of PTB's `ConversationHandler`, we use a simpler approach:
1. Callback handler (Group 6) sets a key in `context.user_data` and asks the user for input
2. The text message handler (Group 5) checks for these keys at the top and delegates to conversation helper functions
3. The helper parses the input, makes the API call, clears the key, and responds

This avoids the complexity of wiring `ConversationHandler` entry points from callback queries.

Pending state keys:
- `pending_tag_memory_id` -- expecting comma-separated tags
- `pending_task_memory_id` -- expecting a date string (YYYY-MM-DD or YYYY-MM-DD HH:MM)
- `pending_reminder_memory_id` -- expecting a datetime string (YYYY-MM-DD HH:MM)

### Search Behavior

`/find <query>` calls `GET /search?q=<query>&owner=<user_id>` on Core. Core returns results from the FTS5 index, ranked by relevance with a pin boost. Only confirmed memories are searched.

The bot displays the top 5 results as a numbered list with brief snippets. Each result has a "Show details" button (handled by Group 6's `SearchDetail` callback).

### Pinned Items

`/pinned` calls `GET /search?q=*&owner=<user_id>&pinned=true` on Core. This returns all pinned memories for the user. Display is identical to search results.

Note: The `q=*` parameter may need adjustment depending on how Core's search endpoint handles the pinned-only filter. If Core supports a separate endpoint or empty query with `pinned=true`, adjust accordingly.

---

## Files to Create

### `telegram/telegram_gw/handlers/command.py`

#### `async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

Reply with:
```
Available commands:
/find <query> -- Search your memories
/tasks -- List open tasks
/pinned -- Show pinned items
/help -- Show this message
/cancel -- Cancel current action

You can also just send me text or images to save them.
```

#### `async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Parse query: `query = " ".join(context.args) if context.args else ""`
2. If empty: reply "Usage: /find <search terms>" and return
3. Call `core.search(query, owner=user.id)`
4. On `CoreUnavailableError`: reply with error message
5. If no results: reply "No results found."
6. Otherwise, build result list (top 5):
   - For each result: `"{i}. {snippet} [image] [pinned]"` where snippet is first 80 chars of content, `[image]` shown if `media_type` is set, `[pinned]` shown if `is_pinned`
   - Header: `"Found {n} result(s):"`
7. Build `search_results_keyboard([(memory_id, f"Show details {i}"), ...])` from `keyboards.py`
8. Reply with the text and keyboard

#### `async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Call `core.list_tasks(owner_user_id=user.id, state="NOT_DONE")`
2. On `CoreUnavailableError`: reply with error message
3. If no tasks: reply "No open tasks."
4. Otherwise, build task list (top 10):
   - For each task: `"{i}. {description} (due: {due_at}) [recurring]"` where `(due: ...)` only shown if `due_at` is set, `[recurring]` shown if `recurrence_minutes` is set
   - Header: `"Open tasks ({n}):"`
5. Build `task_list_keyboard([(task_id, f"Mark Done {i}"), ...])` from `keyboards.py`
6. Reply with the text and keyboard

#### `async def pinned_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Call `core.search("*", owner=user.id, pinned=True)`
2. On `CoreUnavailableError`: reply with error message
3. If no results: reply "No pinned items."
4. Otherwise, build result list (same format as find_command, top 10)
5. Reply with text and `search_results_keyboard`

#### `async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Clear all pending conversation keys from `context.user_data`:
   - `context.user_data.pop("pending_tag_memory_id", None)`
   - `context.user_data.pop("pending_task_memory_id", None)`
   - `context.user_data.pop("pending_reminder_memory_id", None)`
2. Reply "Cancelled."

---

### `telegram/telegram_gw/handlers/conversation.py`

Public functions called from `message.py` when `user_data` has pending state.

#### `async def receive_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Get `memory_id = context.user_data["pending_tag_memory_id"]`
2. Parse tags: `tags = [t.strip() for t in update.message.text.split(",") if t.strip()]`
3. If no valid tags: reply "No valid tags found. Please send comma-separated tags, or /cancel to abort." and return (keep state)
4. Call `core.add_tags(memory_id, TagAdd(tags=tags, status="confirmed"))`
5. Confirm the memory if pending: `core.update_memory(memory_id, MemoryUpdate(status="confirmed"))`
6. On `CoreUnavailableError`: reply with error message and return (keep state for retry)
7. Clear state: `del context.user_data["pending_tag_memory_id"]`
8. Reply: `"Tags saved: {comma-separated tags}"`

#### `async def receive_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Get `memory_id = context.user_data["pending_task_memory_id"]`
2. Parse date: `due = parse_datetime(update.message.text.strip())`
3. If parse fails: reply "Could not parse that date. Please use YYYY-MM-DD or YYYY-MM-DD HH:MM, or /cancel." and return (keep state)
4. Fetch memory for description: `memory = await core.get_memory(memory_id)`
5. Description: `memory.content if memory and memory.content else "Task"`
6. Call `core.create_task(TaskCreate(memory_id=memory_id, owner_user_id=user.id, description=description, due_at=due))`
7. On `CoreUnavailableError`: reply with error message and return
8. Clear state: `del context.user_data["pending_task_memory_id"]`
9. Reply: `"Task created: {description} (due: {formatted date})"`

#### `async def receive_custom_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Get `memory_id = context.user_data["pending_reminder_memory_id"]`
2. Parse datetime: `fire_at = parse_datetime(update.message.text.strip())`
3. If parse fails: reply "Could not parse that time. Please use YYYY-MM-DD HH:MM, or /cancel." and return (keep state)
4. Call `core.create_reminder(ReminderCreate(memory_id=memory_id, owner_user_id=user.id, fire_at=fire_at))`
5. On `CoreUnavailableError`: reply with error message and return
6. Clear state: `del context.user_data["pending_reminder_memory_id"]`
7. Reply: `"Reminder set for {formatted time}"`

#### `def parse_datetime(text: str) -> datetime | None`

Try these formats in order:
1. `"%Y-%m-%d %H:%M"` (e.g., "2026-03-15 14:30")
2. `"%Y-%m-%d"` (e.g., "2026-03-15")
3. `"%d/%m/%Y %H:%M"` (e.g., "15/03/2026 14:30")
4. `"%d/%m/%Y"` (e.g., "15/03/2026")

On successful parse, set timezone to UTC (`dt.replace(tzinfo=timezone.utc)`) and return. If all formats fail, return `None`.

---

## Imports Required

From `shared`:
- `shared.schemas.TagAdd, MemoryUpdate, TaskCreate, ReminderCreate`

From `telegram_gw`:
- `CoreClient, CoreUnavailableError` from `core_client.py`
- `search_results_keyboard, task_list_keyboard` from `keyboards.py`
- `SearchDetail, TaskAction` from `callback_data.py`

---

## Acceptance Criteria

1. `/help` displays the command list
2. `/find butter` returns search results with snippets and "Show details" buttons
3. `/find` with no query shows usage instructions
4. `/find nonexistent` returns "No results found."
5. `/tasks` lists open tasks with due dates and "Mark Done" buttons
6. `/tasks` with no open tasks shows "No open tasks."
7. `/pinned` shows pinned memories
8. `/cancel` clears all pending conversation state
9. Tag entry: sending "food, grocery, receipt" saves three tags and confirms the memory
10. Tag entry: sending empty/whitespace asks the user to try again
11. Custom date: sending "2026-03-15" creates a task with that due date
12. Custom date: sending invalid text shows parse error and asks again
13. Custom reminder: sending "2026-03-15 09:00" creates a reminder at that time
14. Custom reminder: sending invalid text shows parse error and asks again
15. If Core is unreachable during any command or conversation step, user gets a friendly error
