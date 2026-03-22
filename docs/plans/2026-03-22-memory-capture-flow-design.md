# Memory Capture Flow Redesign

## Problem

The current Telegram-to-memory flow stores memories automatically without user confirmation. Images without captions are not meaningfully processed. There is no feedback to the user about what was extracted and stored.

## Goals

- Quick, low-friction memory capture from Telegram
- Human-in-the-loop confirmation before storage (Save / Edit / Discard buttons)
- Proper image handling using LLM vision for captionless photos
- Auto-discard pending memories after a configurable timeout

## Approach: Pending Store with Inline Keyboards

### New Component: PendingStore

An in-memory store (dict keyed by `pending_id`) that holds extracted memories before they are committed.

Each entry contains:

- `pending_id`: Short unique ID used in inline button callback data
- `memory_record`: Full `MemoryRecord` as extracted by the LLM
- `chat_id`: Source Telegram chat for routing
- `message_id`: Bot's preview message ID (for editing after action)
- `created_at`: Timestamp for TTL expiration
- `image_path`: Optional path to downloaded image file

Pending entries do not survive restarts (consistent with the existing queue manager).

A background cleanup task runs every 5 minutes, discards entries older than the configurable timeout (default: 30 minutes), and notifies the user.

### Image Handling

**Image lifecycle:**

1. On receipt: Telegram bot downloads the photo to `data/images/{mem_id}.jpg`
2. During pending: Image stays on disk. LLM vision call uses the image to generate a description.
3. On confirm (Save): Image path stored in MemoryRecord's new `attachments` field (JSON array). Content field contains the LLM-generated description plus any user caption.
4. On discard: Image file deleted from disk.

**Attachments field format:**

```json
[{"type": "image", "path": "data/images/mem_abc123.jpg", "original_filename": "photo.jpg"}]
```

**LLM vision flow for captionless images:**

1. Image is base64-encoded and sent to the LLM using OpenAI vision message format
2. System prompt asks LLM to describe the image and suggest title, category, tags
3. Description becomes the memory content
4. Preview shown to user for confirmation

### Telegram Confirmation Flow

**Preview message sent to user:**

```
Memory Preview

Title: Dentist appointment next Tuesday
Category: reminder
Tags: health, dental
Content: Appointment with Dr. Smith on Tuesday April 15 at 10am

[Save]  [Edit]  [Discard]
```

**Button callback handling:**

- `save:{pending_id}` -- Moves MemoryRecord from pending store to SQLite + vector store. Edits preview message to show "Saved", removes buttons.
- `edit:{pending_id}` -- Bot replies "Send your corrections." Next message treated as edit input. LLM re-extracts using original input + corrections, shows new preview.
- `discard:{pending_id}` -- Deletes pending entry and image file. Edits preview message to show "Discarded", removes buttons.

Uses `python-telegram-bot`'s `CallbackQueryHandler` for inline button callbacks.

Edit flow reuses the follow-up manager pattern: stores pending_id as context so the next message is associated with the correct pending memory.

### New Events

- `MemoryPending(pending_id, preview_data, source_chat_id)` -- emitted after LLM extraction, before storage
- `MemoryConfirmed(pending_id, source_chat_id)` -- emitted when user taps Save
- `MemoryDiscarded(pending_id, source_chat_id)` -- emitted when user taps Discard or timeout

### Modified Processing Flow

```
User message --> Queue --> Processor
  |-- classify --> "followup" --> ask question (unchanged)
  |-- classify --> "store" --> extract memory
       |
  Create MemoryRecord --> PendingStore.add()
       |
  Emit MemoryPending --> Telegram sends preview + buttons
       |
  User taps Save --> Emit MemoryConfirmed
       |
  PendingStore.confirm() --> db.create() + vector_store.add()
       |
  Emit MemoryStored (existing event, unchanged)
```

The processor no longer calls `db.create()` directly. Storage happens only on `MemoryConfirmed`.

This also fixes the existing gap where `vector_store.add()` was never called during the storage flow.

### MemoryRecord Changes

- Add `attachments: list[dict]` field (default: empty list)
- Database schema: add `attachments` column (JSON, nullable)

### Edge Cases

1. **Multiple rapid messages**: Each gets its own pending entry and preview. User confirms each independently.
2. **Message during pending edit**: Treated as the edit response (user was prompted for corrections).
3. **LLM endpoint down**: Error caught in processing loop. Message stays in queue for retry.
4. **Image download fails**: Fall back to text-only processing (caption if available, or notify user).
5. **Timeout cleanup**: Background task every 5 minutes discards expired entries and notifies user.

### Unchanged Components

- REST API (queries committed memories only)
- Scheduler/reminders
- Database schema (only adding `attachments` column)
