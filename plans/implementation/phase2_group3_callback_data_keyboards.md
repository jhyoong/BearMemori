# Phase 2 - Group 3: Callback Data Encoding and Keyboards

## Goal

Define the callback data structures used by inline keyboard buttons and build all keyboard layout functions. This group establishes the contract between keyboards (Group 3), callbacks (Group 6), and message handlers (Group 5).

**Depends on:** Group 2 (gateway abstraction)
**Blocks:** Groups 4, 5, 6, 7

---

## Context

### Telegram's 64-byte callback_data limit

Telegram limits `callback_data` on inline keyboard buttons to 64 bytes UTF-8. Since memory IDs are UUIDs (36 chars), encoding an action type plus an ID plus any secondary context within 64 bytes is fragile.

### Solution: PTB's `arbitrary_callback_data`

`python-telegram-bot` v20+ provides `arbitrary_callback_data=True` on the `ApplicationBuilder`. This feature:
- Stores actual callback data (any hashable Python object) in an in-memory cache
- Sends only a short UUID to Telegram as the callback_data string
- When a callback arrives, PTB looks up the UUID and returns the original Python object
- If the bot restarts, the cache is lost and expired buttons return `InvalidCallbackData`

This is acceptable for a personal bot (2-4 users). If buttons expire, users re-send their message.

### Keyboard Flows in the Bot

After a memory is captured, the bot replies with inline buttons. Each button press leads to one of these flows:

1. **Task** -> Due date selection -> Task created
2. **Remind** -> Time selection -> Reminder created
3. **Tag** / **Edit Tags** -> User types tags -> Tags saved
4. **Pin** -> Memory pinned (and confirmed if pending)
5. **Delete** -> Confirmation -> Memory deleted
6. **Confirm Tags** -> All suggested tags confirmed
7. **Show details** (search results) -> Full memory displayed
8. **Mark Done** (task list) -> Task marked as done

---

## Files to Create

### `telegram/telegram_gw/callback_data.py`

Frozen dataclasses (hashable, as required by PTB's cache).

#### `MemoryAction`
- `action: str` -- one of: `"task"`, `"remind"`, `"tag"`, `"pin"`, `"delete"`, `"confirm_tags"`, `"edit_tags"`
- `memory_id: str`

#### `TaskAction`
- `action: str` -- one of: `"mark_done"`
- `task_id: str`

#### `DueDateChoice`
- `memory_id: str`
- `choice: str` -- one of: `"today"`, `"tomorrow"`, `"next_week"`, `"no_date"`, `"custom"`

#### `ReminderTimeChoice`
- `memory_id: str`
- `choice: str` -- one of: `"1h"`, `"tomorrow_9am"`, `"custom"`

#### `ConfirmDelete`
- `memory_id: str`
- `confirmed: bool`

#### `SearchDetail`
- `memory_id: str`

#### `TagConfirm`
- `memory_id: str`
- `action: str` -- one of: `"confirm_all"`, `"edit"`

All dataclasses use `@dataclass(frozen=True)` from the `dataclasses` module.

---

### `telegram/telegram_gw/keyboards.py`

Functions that return `InlineKeyboardMarkup` objects. Each function is pure (no side effects, no async).

Import: `from telegram import InlineKeyboardButton, InlineKeyboardMarkup`
Import all callback data types from `callback_data.py`.

#### `memory_actions_keyboard(memory_id: str, is_image: bool = False) -> InlineKeyboardMarkup`

Standard keyboard shown after capturing a memory.

Layout for text memories:
```
[Task] [Remind]
[Tag] [Pin] [Delete]
```

Layout for image memories (additional first row):
```
[Confirm Tags] [Edit Tags]
[Task] [Remind]
[Tag] [Pin] [Delete]
```

- "Confirm Tags" uses `MemoryAction("confirm_tags", memory_id)`
- "Edit Tags" uses `MemoryAction("edit_tags", memory_id)`
- "Task" uses `MemoryAction("task", memory_id)`
- "Remind" uses `MemoryAction("remind", memory_id)`
- "Tag" uses `MemoryAction("tag", memory_id)`
- "Pin" uses `MemoryAction("pin", memory_id)`
- "Delete" uses `MemoryAction("delete", memory_id)`

#### `due_date_keyboard(memory_id: str) -> InlineKeyboardMarkup`

Shown when user taps "Task":
```
[Today] [Tomorrow] [Next Week]
[No Date] [Custom]
```

Each button uses `DueDateChoice(memory_id, choice)`.

#### `reminder_time_keyboard(memory_id: str) -> InlineKeyboardMarkup`

Shown when user taps "Remind":
```
[1 Hour] [Tomorrow 9am]
[Custom]
```

Each button uses `ReminderTimeChoice(memory_id, choice)`.

#### `delete_confirm_keyboard(memory_id: str) -> InlineKeyboardMarkup`

Shown when user taps "Delete":
```
[Yes, delete] [No, cancel]
```

- "Yes, delete" uses `ConfirmDelete(memory_id, confirmed=True)`
- "No, cancel" uses `ConfirmDelete(memory_id, confirmed=False)`

#### `search_results_keyboard(results: list[tuple[str, str]]) -> InlineKeyboardMarkup`

Shown after `/find` results. `results` is a list of `(memory_id, label)` tuples.

Layout: one button per result, vertically stacked:
```
[Show details 1]
[Show details 2]
[Show details 3]
```

Each button uses `SearchDetail(memory_id)`.

#### `task_list_keyboard(tasks: list[tuple[str, str]]) -> InlineKeyboardMarkup`

Shown after `/tasks`. `tasks` is a list of `(task_id, label)` tuples.

Layout: one button per task, vertically stacked:
```
[Mark Done 1]
[Mark Done 2]
[Mark Done 3]
```

Each button uses `TaskAction("mark_done", task_id)`.

#### `tag_suggestion_keyboard(memory_id: str) -> InlineKeyboardMarkup`

Shown when LLM tag suggestions arrive:
```
[Confirm Tags] [Edit Tags]
```

- "Confirm Tags" uses `TagConfirm(memory_id, "confirm_all")`
- "Edit Tags" uses `TagConfirm(memory_id, "edit")`

---

## Acceptance Criteria

1. All callback data classes are frozen (immutable) and hashable
2. Each keyboard function returns a valid `InlineKeyboardMarkup`
3. `memory_actions_keyboard` with `is_image=True` includes the Confirm/Edit Tags row
4. `memory_actions_keyboard` with `is_image=False` omits the Confirm/Edit Tags row
5. All buttons have correct callback data objects with proper types and fields
6. Keyboard functions are pure -- no side effects, no I/O
