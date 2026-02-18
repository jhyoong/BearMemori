# Phase 2 - Group 4: Allowlist Filter and Bot Entrypoint

## Goal

Set up the PTB Application, user allowlist filtering, and the main entrypoint that wires together all handlers, shared resources, and the Redis consumer. This is the central orchestration point for the entire Telegram Gateway.

**Depends on:** Groups 1-3
**Blocks:** Groups 5-8

---

## Context

### PTB Application Architecture

`python-telegram-bot` v20+ uses an `Application` object as the central hub. It:
- Manages the bot connection (long-polling or webhook)
- Routes incoming updates to registered handlers in priority order
- Provides `bot_data` (shared dict accessible from all handlers) and `user_data` (per-user dict)
- Supports lifecycle hooks: `post_init` (after initialization), `post_shutdown` (on exit)
- Can run background tasks via `application.create_task()`

### Shared Resources

All handlers need access to:
- `CoreClient` -- HTTP client for the Core REST API
- Redis client -- for publishing LLM jobs and consuming notifications
- `TelegramGateway` -- the concrete gateway implementation
- `TelegramConfig` -- configuration values

These are stored in `application.bot_data` during `post_init` and accessed in handlers via `context.bot_data`.

### Handler Registration Order

PTB processes handlers in registration order. First match wins. Order:
1. Commands (highest priority -- `/find`, `/tasks`, `/pinned`, `/help`, `/cancel`)
2. Text message handler (captures text or handles pending conversation state)
3. Photo message handler (captures images)
4. Callback query handler for `InvalidCallbackData` (expired buttons)
5. General callback query handler (all button presses)
6. Catch-all for non-allowlisted users (rejection message)

### Key Configuration Choices

- `arbitrary_callback_data=True` -- enables storing Python objects as callback data (see Group 3)
- `concurrent_updates=False` -- ensures conversation state in `user_data` is not corrupted by concurrent updates. Acceptable for 2-4 users.
- `drop_pending_updates=True` -- on restart, discard updates that accumulated while the bot was offline. Prevents processing stale callbacks.

---

## Files to Create

### `telegram/tg_gateway/filters.py`

A custom PTB filter that only passes updates from allowlisted users.

#### `AllowedUsersFilter(UpdateFilter)`

- Constructor: `__init__(self, allowed_ids: set[int])`
- `filter(self, update: Update) -> bool`:
  - Get `update.effective_user`
  - If no user (e.g., channel post): return `False`
  - Return `user.id in self._allowed_ids`

This filter is combined with PTB's built-in filters in handler registration:
- `allowed_filter & filters.TEXT & ~filters.COMMAND` -- text messages from allowed users (excluding commands)
- `allowed_filter & filters.PHOTO` -- photos from allowed users
- `~allowed_filter & (filters.TEXT | filters.PHOTO | filters.COMMAND)` -- anything from non-allowed users

---

### `telegram/tg_gateway/main.py`

The bot entrypoint. Structured as follows:

#### `async def post_init(application: Application) -> None`

Called after `Application.initialize()`. Sets up shared resources:
1. Load `TelegramConfig` from `application.bot_data["config"]`
2. Create `CoreClient(config.core_api_url)` -> store in `bot_data["core_client"]`
3. Create `redis.asyncio.from_url(config.redis_url)` -> store in `bot_data["redis"]`
4. Create `TelegramGateway(application.bot)` -> store in `bot_data["gateway"]`
5. Start Redis consumer: `application.create_task(run_notify_consumer(application), name="redis_consumer")`

Using `application.create_task()` (PTB v20.4+) ensures the task is managed by PTB's lifecycle -- it will be cancelled automatically on shutdown.

#### `async def post_shutdown(application: Application) -> None`

Cleanup:
1. `await application.bot_data["core_client"].close()`
2. `await application.bot_data["redis"].aclose()`

#### `def main()`

1. `config = TelegramConfig()`
2. `allowed_filter = AllowedUsersFilter(config.allowed_ids_set)`
3. Build application:
   ```python
   app = (
       ApplicationBuilder()
       .token(config.telegram_bot_token)
       .arbitrary_callback_data(True)
       .post_init(post_init)
       .post_shutdown(post_shutdown)
       .concurrent_updates(False)
       .build()
   )
   ```
4. Store config: `app.bot_data["config"] = config`
5. Register handlers (order matters):
   - `CommandHandler("help", command.help_command, filters=allowed_filter)`
   - `CommandHandler("find", command.find_command, filters=allowed_filter)`
   - `CommandHandler("tasks", command.tasks_command, filters=allowed_filter)`
   - `CommandHandler("pinned", command.pinned_command, filters=allowed_filter)`
   - `CommandHandler("cancel", command.cancel_command, filters=allowed_filter)`
   - `MessageHandler(allowed_filter & filters.TEXT & ~filters.COMMAND, message.handle_text)`
   - `MessageHandler(allowed_filter & filters.PHOTO, message.handle_image)`
   - `CallbackQueryHandler(callback.handle_invalid, pattern=InvalidCallbackData)`
   - `CallbackQueryHandler(callback.handle_callback)`
   - `MessageHandler(~allowed_filter & (filters.TEXT | filters.PHOTO | filters.COMMAND), message.handle_unauthorized)`
6. `app.run_polling(drop_pending_updates=True)`

#### `if __name__ == "__main__": main()`

### Handler Imports

The entrypoint imports handler functions from:
- `tg_gateway.handlers.message` -- `handle_text`, `handle_image`, `handle_unauthorized`
- `tg_gateway.handlers.callback` -- `handle_callback`, `handle_invalid`
- `tg_gateway.handlers.command` -- `help_command`, `find_command`, `tasks_command`, `pinned_command`, `cancel_command`
- `tg_gateway.consumer` -- `run_notify_consumer`

Also create `telegram/tg_gateway/handlers/__init__.py` (empty file).

---

## Logging Setup

Configure in `main.py` before building the application:
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
```

---

## Acceptance Criteria

1. Bot starts and connects to Telegram via long-polling
2. `post_init` creates CoreClient, Redis client, and TelegramGateway in `bot_data`
3. Allowed user's text messages reach `handle_text`
4. Allowed user's photos reach `handle_image`
5. Non-allowlisted user receives rejection message
6. Commands are routed to the correct handler functions
7. Redis consumer task starts during `post_init`
8. `post_shutdown` cleanly closes HTTP client and Redis connection
9. SIGTERM triggers graceful shutdown (PTB handles this)
10. Handler registration order is correct (commands first, catch-all last)
