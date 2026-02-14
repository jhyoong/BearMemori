# Phase 2 - Group 2: Core HTTP Client and Gateway Abstraction

## Goal

Build the async HTTP client that wraps all Core REST API calls, and the abstract gateway interface that decouples the bot logic from Telegram-specific APIs. Every handler in the Telegram Gateway depends on these two components.

**Depends on:** Group 1 (package setup)
**Blocks:** Groups 3-8

---

## Context

The Life Organiser architecture routes all database operations through the Core service's REST API. The Telegram Gateway never touches the database directly. Every user action (capture a memory, create a task, search, etc.) translates to one or more HTTP calls to Core.

The gateway abstraction exists because the PRD requires messaging integration to be isolated behind an interface so Telegram can be swapped for another platform (Discord, Signal, etc.) in the future.

### Core REST API Endpoints (from Phase 1)

The Core service exposes these endpoints that the Telegram Gateway will call:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /memories | Create a memory (text or image) |
| GET | /memories/{id} | Fetch memory with tags |
| PATCH | /memories/{id} | Update memory (pin, confirm, set local path) |
| DELETE | /memories/{id} | Hard delete memory |
| POST | /memories/{id}/tags | Add or confirm tags |
| DELETE | /memories/{id}/tags/{tag} | Remove a tag |
| POST | /memories/{id}/image | Upload image bytes, Core stores to disk |
| POST | /tasks | Create a task linked to a memory |
| GET | /tasks | List tasks with filters (state, owner) |
| PATCH | /tasks/{id} | Update task (mark done, change due date) |
| DELETE | /tasks/{id} | Delete a task |
| POST | /reminders | Create a reminder linked to a memory |
| GET | /reminders | List upcoming reminders |
| PATCH | /reminders/{id} | Update reminder |
| DELETE | /reminders/{id} | Delete reminder |
| GET | /search | FTS5 keyword search with params: q, owner, pinned |
| GET | /settings/{user_id} | Fetch user settings |
| PATCH | /settings/{user_id} | Update user settings |
| POST | /llm-jobs | Create an LLM job record |
| GET | /llm-jobs/{id} | Get LLM job status |
| PATCH | /llm-jobs/{id} | Update LLM job |

### Shared Schemas (from Phase 1)

Request/response models are defined in `shared.schemas`:
- `MemoryCreate`, `MemoryUpdate`, `MemoryResponse`, `MemoryWithTags`
- `TagAdd`, `TagResponse`
- `TaskCreate`, `TaskUpdate`, `TaskResponse`
- `ReminderCreate`, `ReminderUpdate`, `ReminderResponse`
- `SearchResult` (contains `memory: MemoryWithTags` and `score: float`)
- `UserSettingsResponse`, `UserSettingsUpdate`
- `LLMJobCreate`, `LLMJobResponse`

---

## Files to Create

### `telegram/telegram_gw/core_client.py`

#### Custom Exceptions

Define at the top of the file:
- `CoreClientError(Exception)` -- base exception for all Core API errors
- `CoreUnavailableError(CoreClientError)` -- Core is unreachable (connection error, timeout)
- `CoreNotFoundError(CoreClientError)` -- entity not found (404 response)

#### `CoreClient` Class

Constructor: `__init__(self, base_url: str, timeout: float = 10.0)`
- Creates an `httpx.AsyncClient(base_url=base_url, timeout=timeout)`

Cleanup: `async def close(self)`
- Calls `await self._client.aclose()`

#### Methods

Each method follows this pattern:
1. Serialize the Pydantic model to dict using `model_dump(exclude_none=True)`
2. Make the HTTP request
3. On `httpx.ConnectError` / `httpx.TimeoutException`: raise `CoreUnavailableError`
4. On 404 response: raise `CoreNotFoundError`
5. On other non-2xx: raise `CoreClientError` with status code and body
6. Parse response JSON into the corresponding Pydantic model and return

**Memory methods:**
- `async def create_memory(self, data: MemoryCreate) -> MemoryResponse` -- POST /memories
- `async def get_memory(self, memory_id: str) -> MemoryWithTags | None` -- GET /memories/{id}, returns None on 404
- `async def update_memory(self, memory_id: str, data: MemoryUpdate) -> MemoryResponse` -- PATCH /memories/{id}
- `async def delete_memory(self, memory_id: str) -> bool` -- DELETE /memories/{id}, returns True on success
- `async def add_tags(self, memory_id: str, data: TagAdd) -> MemoryWithTags` -- POST /memories/{id}/tags
- `async def upload_image(self, memory_id: str, file_bytes: bytes) -> str` -- POST /memories/{id}/image, sends as multipart/form-data, returns the local path from the response

**Task methods:**
- `async def create_task(self, data: TaskCreate) -> TaskResponse` -- POST /tasks
- `async def list_tasks(self, owner_user_id: int, state: str | None = None) -> list[TaskResponse]` -- GET /tasks with query params
- `async def update_task(self, task_id: str, data: TaskUpdate) -> TaskResponse` -- PATCH /tasks/{id}

**Reminder methods:**
- `async def create_reminder(self, data: ReminderCreate) -> ReminderResponse` -- POST /reminders

**Search methods:**
- `async def search(self, query: str, owner: int, pinned: bool = False) -> list[SearchResult]` -- GET /search?q=&owner=&pinned=

**Settings methods:**
- `async def get_settings(self, user_id: int) -> UserSettingsResponse` -- GET /settings/{user_id}

**LLM Job methods:**
- `async def create_llm_job(self, data: LLMJobCreate) -> LLMJobResponse` -- POST /llm-jobs

Note: `get_memory` returns `None` on 404 instead of raising, because callers frequently check if a memory exists. All other methods raise on 404.

---

### `telegram/telegram_gw/gateway.py`

Abstract base class defining the platform-agnostic messaging interface.

```python
from abc import ABC, abstractmethod
from typing import Any
```

#### `Gateway(ABC)` Methods

- `async def send_text(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> int`
  - Send a plain text message. Returns the sent message ID.

- `async def send_image(self, chat_id: int, image: str | bytes, caption: str | None = None) -> int`
  - Send an image. `image` can be a Telegram file_id string or raw bytes. Returns the sent message ID.

- `async def send_inline_keyboard(self, chat_id: int, text: str, buttons: list[list[dict[str, Any]]], reply_to_message_id: int | None = None) -> int`
  - Send a message with inline keyboard. `buttons` is a list of rows; each row is a list of dicts with `text` and `callback_data` keys. Returns the sent message ID.

- `async def edit_message_text(self, chat_id: int, message_id: int, text: str, buttons: list[list[dict[str, Any]]] | None = None) -> None`
  - Edit an existing message's text and optionally replace its inline keyboard.

- `async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None`
  - Acknowledge a callback query (stops the loading spinner on the button).

- `async def delete_message(self, chat_id: int, message_id: int) -> None`
  - Delete a message.

The `buttons` parameter uses plain dicts so the interface is not tied to any Telegram-specific types.

---

### `telegram/telegram_gw/telegram_gateway.py`

Concrete implementation of `Gateway` for Telegram using `python-telegram-bot`.

#### `TelegramGateway(Gateway)` Class

Constructor: `__init__(self, bot: telegram.Bot)`

Each method wraps the corresponding `self._bot` method:
- `send_text` -> `bot.send_message(chat_id, text, reply_to_message_id)`
- `send_image` -> `bot.send_photo(chat_id, photo=image, caption=caption)`
- `send_inline_keyboard` -> `bot.send_message(chat_id, text, reply_markup=self._build_markup(buttons), reply_to_message_id)`
- `edit_message_text` -> `bot.edit_message_text(text, chat_id, message_id, reply_markup=self._build_markup(buttons) if buttons else None)`
- `answer_callback` -> `bot.answer_callback_query(callback_query_id, text)`
- `delete_message` -> `bot.delete_message(chat_id, message_id)`

Static helper: `_build_markup(buttons) -> InlineKeyboardMarkup`
- Converts the list-of-lists-of-dicts format into `InlineKeyboardMarkup` with `InlineKeyboardButton` objects

---

## Acceptance Criteria

1. `CoreClient` methods serialize requests and parse responses correctly
2. `CoreUnavailableError` is raised when Core is unreachable (test by pointing at a non-existent host)
3. `CoreNotFoundError` is raised on 404 responses
4. `get_memory` returns `None` on 404 (not an exception)
5. `upload_image` sends bytes as multipart/form-data
6. `TelegramGateway` implements all `Gateway` abstract methods
7. `_build_markup` correctly converts dict-based button definitions to `InlineKeyboardMarkup`
