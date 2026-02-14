# Phase 2 - Group 5: Message Handlers (Text and Image Capture)

## Goal

Implement the core capture flow -- text messages become confirmed memories, images become pending memories with LLM tagging jobs published. This is the primary entry point for all user data.

**Depends on:** Group 4 (bot entrypoint, shared resources in bot_data)
**Blocks:** Group 7 (conversation helpers are called from here)

---

## Context

### Capture Behavior (from PRD)

- **Text messages:** Immediately stored as a confirmed Memory. No confirmation required. The bot replies with inline action buttons.
- **Images:** Stored as a pending Memory with a 7-day retention window. The bot downloads the image and uploads it to Core. If LLM is available, a tagging job is published to Redis. The bot replies with inline action buttons including tag confirm/edit options.

### Conversation State Check

The text message handler has a dual role:
1. **Primary:** Capture new text memories
2. **Secondary:** Handle pending conversation actions (tag entry, custom date, custom reminder)

When a callback handler starts a multi-step flow (e.g., user taps "Tag"), it sets a key in `context.user_data` (e.g., `pending_tag_memory_id`). The next text message the user sends should be routed to the conversation handler, not treated as a new memory.

The text handler checks for these keys at the top before proceeding with capture. This approach is simpler than using PTB's `ConversationHandler` for callback-triggered flows.

Pending conversation keys:
- `pending_tag_memory_id` -- user is expected to send comma-separated tags
- `pending_task_memory_id` -- user is expected to send a custom due date
- `pending_reminder_memory_id` -- user is expected to send a custom reminder time

### Image Upload Flow

The Telegram Gateway downloads image bytes from the Telegram API, then uploads them to Core via `POST /memories/{id}/image`. Core handles writing the file to disk and updating the `media_local_path` field on the memory record.

This flow is asynchronous relative to the user response -- if the download/upload fails, the bot still responds with buttons. The `file_id` stored on the memory record is a fallback for serving the image later.

### Redis LLM Job Publishing

After image capture, the gateway publishes a job to the `llm:image_tag` Redis stream. The LLM Worker (Phase 3) will consume this and generate tag suggestions. The data format:

```json
{
    "memory_id": "uuid",
    "file_id": "telegram_file_id",
    "caption": "user caption or empty string",
    "user_id": 123456,
    "chat_id": 789012
}
```

If Redis is unreachable or the publish fails, this is non-fatal. The user can still tag manually.

---

## Files to Create

### `telegram/telegram_gw/handlers/message.py`

Three handler functions:

#### `async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. **Check for pending conversation state** (order matters):
   - If `"pending_tag_memory_id"` in `context.user_data`: call `conversation.receive_tags(update, context)` and return
   - If `"pending_task_memory_id"` in `context.user_data`: call `conversation.receive_custom_date(update, context)` and return
   - If `"pending_reminder_memory_id"` in `context.user_data`: call `conversation.receive_custom_reminder(update, context)` and return

2. **Capture as new memory:**
   - Get `core_client` from `context.bot_data["core_client"]`
   - Call `core.create_memory(MemoryCreate(owner_user_id=user.id, content=msg.text, source_chat_id=msg.chat_id, source_message_id=msg.message_id))`
   - On `CoreUnavailableError`: reply "I'm having trouble right now, please try again in a moment." and return
   - Build keyboard: `memory_actions_keyboard(memory.id, is_image=False)`
   - Reply: `"Saved!"` with the keyboard

#### `async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

1. Get the highest resolution photo: `photo = update.message.photo[-1]`
2. Get caption: `caption = update.message.caption or ""`
3. Call `core.create_memory(MemoryCreate(owner_user_id=user.id, content=caption, media_type=MediaType.image, media_file_id=photo.file_id, source_chat_id=msg.chat_id, source_message_id=msg.message_id))`
4. On `CoreUnavailableError`: reply with error message and return
5. Download and upload image (non-fatal):
   - Call `media.download_and_upload_image(context.bot, core_client, memory.id, photo.file_id)`
   - Wrap in try/except, log errors, continue
6. Publish LLM tagging job (non-fatal):
   - Call `publish(redis_client, STREAM_LLM_IMAGE_TAG, {memory_id, file_id, caption, user_id, chat_id})`
   - Wrap in try/except, log errors, continue
7. Build keyboard: `memory_actions_keyboard(memory.id, is_image=True)`
8. Reply: `"Saved as pending! ..."` with the keyboard

#### `async def handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None`

- Reply: `"Sorry, I'm a private bot. You are not authorized to use me."`

---

### `telegram/telegram_gw/media.py`

#### `async def download_and_upload_image(bot, core_client: CoreClient, memory_id: str, file_id: str) -> str | None`

1. Download from Telegram: `tg_file = await bot.get_file(file_id)`, then `file_bytes = await tg_file.download_as_bytearray()`
2. Upload to Core: `local_path = await core_client.upload_image(memory_id, bytes(file_bytes))`
3. Return `local_path` on success, `None` on failure
4. Log exceptions but do not re-raise (caller handles this as non-fatal)

---

## Imports Required

From `shared`:
- `shared.schemas.MemoryCreate`
- `shared.enums.MediaType`
- `shared.redis_streams.STREAM_LLM_IMAGE_TAG, publish`

From `telegram_gw`:
- `telegram_gw.core_client.CoreClient, CoreUnavailableError`
- `telegram_gw.keyboards.memory_actions_keyboard`
- `telegram_gw.handlers.conversation` (for pending state delegation)
- `telegram_gw.media.download_and_upload_image`

---

## Acceptance Criteria

1. Sending a text message creates a confirmed memory in Core and shows [Task][Remind][Tag][Pin][Delete] buttons
2. Sending an image creates a pending memory with `media_file_id` stored, shows [Confirm Tags][Edit Tags][Task][Remind][Pin][Delete] buttons
3. Image bytes are downloaded from Telegram and uploaded to Core via the image upload endpoint
4. An `llm:image_tag` job is published to Redis after image capture
5. If Core is unreachable, user gets "I'm having trouble right now" message
6. If image download/upload fails, the bot still responds with buttons (non-fatal)
7. If Redis publish fails, the bot still responds with buttons (non-fatal)
8. Non-allowlisted users get "Sorry, I'm a private bot" message
9. If `pending_tag_memory_id` is in `user_data`, the next text message is routed to tag entry (not captured as a new memory)
10. Image captions are stored as the memory's `content` field
