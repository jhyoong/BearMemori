# Image Storage and Retrieval Design

## Problem

Images sent via Telegram are processed by the LLM but not persisted. The webapp has no image display. The Telegram bot cannot send images back in previews or on demand.

## Approach

File system storage with path reference in SQLite. Images saved to a configurable directory, served via FastAPI, displayed in webapp and Telegram.

## 1. Image Storage

- New config setting: `IMAGE_STORAGE_DIR`, default `data/images/` (in Docker: `/data/images/`)
- File naming: `<memory_id>.jpg`
- New nullable `image_path` column in SQLite `memories` table
- New `image_path: str | None = None` field on `MemoryRecord`
- Lives under the same `/data` Docker volume as SQLite and ChromaDB -- no extra mount needed

## 2. Image Flow

- **Intake (unchanged):** Telegram `_handle_photo` downloads bytes, emits `InputReceived` with `image_bytes`, `caption`, `file_path` in content dict
- **Pending stage:** Change `PendingMemory` to store raw `image_bytes` (instead of Telegram API file path) so bytes are available at confirm time
- **Confirm stage:** `ConfirmHandler.handle_confirmed()` saves image bytes to `IMAGE_STORAGE_DIR/<memory_id>.jpg`, sets `record.image_path`
- **Edit flow:** Carry image bytes forward when a pending memory is edited (already partially done)

## 3. Serving Images

- New FastAPI route: `GET /images/{filename}` serving files from `IMAGE_STORAGE_DIR` via `FileResponse`
- Webapp `memory_detail.html`: show `<img>` tag if `memory.image_path` exists, above the edit form
- Memory list page: no image display (keep it lightweight)
- REST API `GET /memory/{record_id}`: naturally includes `image_path` once field is on the model

## 4. Telegram Commands

- **Preview with image:** Update `handle_memory_pending()` to use `send_photo()` with inline keyboard when pending memory has image bytes
- **New `/recall <memory_id>` command:** Look up memory in DB, send photo if image exists, otherwise send text. Error message if ID not found.
- **Menu registration:** Call `set_my_commands()` during bot startup to register `/start` and `/recall`

## 5. Cleanup

- On memory deletion (API, webapp, bulk): delete image file from disk if `image_path` is set
- Applies to all delete paths: single delete, bulk delete
- Pending discard: no file cleanup needed since bytes are held in memory, garbage collected on removal

## Files to Modify

- `bearmemori/config.py` -- add `IMAGE_STORAGE_DIR` setting
- `bearmemori/storage/models.py` -- add `image_path` to `MemoryRecord`, change `PendingMemory.image_path` to `image_bytes`
- `bearmemori/storage/database.py` -- add `image_path` column, migration, read/write support
- `bearmemori/storage/pending_store.py` -- update to handle `image_bytes`
- `bearmemori/core/processor.py` -- pass `image_bytes` instead of `image_path` to pending store
- `bearmemori/core/confirm.py` -- save image to disk on confirm
- `bearmemori/interfaces/telegram.py` -- send photos in previews, add `/recall` command, register menu commands
- `bearmemori/api/routes.py` -- add image serving route, delete image on memory deletion
- `bearmemori/webapp/router.py` -- delete image on memory deletion
- `bearmemori/webapp/templates/memory_detail.html` -- show image if present
- `bearmemori/app.py` -- ensure image directory is created on startup
- `Dockerfile` -- add `IMAGE_STORAGE_DIR=/data/images` env var
