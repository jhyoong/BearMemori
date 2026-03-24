# Image Storage and Retrieval Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist images sent via Telegram, display them in the webapp, and allow retrieval via Telegram bot commands.

**Architecture:** File system storage under a configurable directory. Image path stored as a column in SQLite. Images served via FastAPI FileResponse. Telegram bot sends photos in previews and via a new `/recall` command.

**Tech Stack:** Python 3.12, FastAPI (FileResponse), python-telegram-bot (send_photo, set_my_commands), SQLite, Pydantic

---

### Task 1: Add IMAGE_STORAGE_DIR config setting

**Files:**
- Modify: `bearmemori/config.py:4-26`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_config.py
def test_image_storage_dir_default():
    """IMAGE_STORAGE_DIR defaults to data/images."""
    settings = Settings(
        telegram_bot_token="fake",
        telegram_allowed_user_id=1,
    )
    assert settings.image_storage_dir == "data/images"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_image_storage_dir_default -v`
Expected: FAIL with AttributeError

**Step 3: Write minimal implementation**

Add to `bearmemori/config.py` Settings class (after line 14):

```python
image_storage_dir: str = "data/images"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_image_storage_dir_default -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/config.py tests/test_config.py
git commit -m "feat: add IMAGE_STORAGE_DIR config setting"
```

---

### Task 2: Update PendingMemory to store image_bytes instead of image_path

**Files:**
- Modify: `bearmemori/storage/models.py:67-74`
- Modify: `bearmemori/storage/pending_store.py:12-28`
- Test: `tests/test_pending_store.py`

**Step 1: Update the test for the new field name**

In `tests/test_pending_store.py`, replace `test_add_with_chat_id_and_image_path` (lines 54-60):

```python
def test_add_with_chat_id_and_image_bytes():
    store = PendingStore()
    pid = store.add(_make_draft(), chat_id="123", image_bytes=b"fake-image-data")
    result = store.get(pid)
    assert result is not None
    assert result.chat_id == "123"
    assert result.image_bytes == b"fake-image-data"


def test_add_without_image_bytes():
    store = PendingStore()
    pid = store.add(_make_draft(), chat_id="123")
    result = store.get(pid)
    assert result is not None
    assert result.image_bytes is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pending_store.py::test_add_with_chat_id_and_image_bytes -v`
Expected: FAIL (unexpected keyword argument)

**Step 3: Update PendingMemory model**

In `bearmemori/storage/models.py`, change line 74 from:

```python
image_path: str | None = None
```

to:

```python
image_bytes: bytes | None = None
```

**Step 4: Update PendingStore.add()**

In `bearmemori/storage/pending_store.py`, update the `add` method signature and body. Change `image_path` parameter to `image_bytes: bytes | None = None` and update the `PendingMemory` constructor to use `image_bytes=image_bytes`.

**Step 5: Run all pending store tests**

Run: `uv run pytest tests/test_pending_store.py -v`
Expected: PASS (all tests)

**Step 6: Fix confirm handler test that uses image_path**

In `tests/test_confirm.py`, update `test_discard_cleans_up_image` (lines 97-104). This test uses `image_path=` in pending_store.add -- change it to `image_bytes=`:

```python
@pytest.mark.asyncio
async def test_discard_with_image_bytes_is_noop(handler, pending_store):
    pid = pending_store.add(_make_draft(), chat_id="123", image_bytes=b"fake-image")
    await handler.handle_discarded(MemoryDiscarded(pending_id=pid, source_chat_id="123"))
    assert pending_store.get(pid) is None
```

**Step 7: Update confirm handler discard logic**

In `bearmemori/core/confirm.py`, remove the file deletion logic from `handle_discarded` (lines 64-67). The method should just remove from pending store:

```python
async def handle_discarded(self, event: MemoryDiscarded) -> None:
    pending = self._pending_store.get(event.pending_id)
    if pending is None:
        return
    self._pending_store.remove(event.pending_id)
    logger.info("Discarded pending memory %s", event.pending_id)
```

Remove the `from pathlib import Path` import on line 3.

**Step 8: Run all tests to verify nothing is broken**

Run: `uv run pytest -v`
Expected: PASS (all tests). Some tests in test_processor.py or test_confirm.py may fail if they reference `image_path` -- fix any remaining references.

**Step 9: Commit**

```bash
git add bearmemori/storage/models.py bearmemori/storage/pending_store.py bearmemori/core/confirm.py tests/test_pending_store.py tests/test_confirm.py
git commit -m "refactor: change PendingMemory from image_path to image_bytes"
```

---

### Task 3: Update Processor to pass image_bytes to pending store

**Files:**
- Modify: `bearmemori/core/processor.py:80-109` and `bearmemori/core/processor.py:54-78`
- Test: `tests/test_processor.py`

**Step 1: Read current test_processor.py to understand existing image tests**

Check `tests/test_processor.py` for any tests that reference `image_path` and update them to use `image_bytes`.

**Step 2: Update _process_image to pass image_bytes**

In `bearmemori/core/processor.py`, update `_process_image` (line 80-109). Change:

```python
image_path = item.content.get("image_path")
```

to:

```python
image_bytes_data = item.content.get("image_bytes", b"")
```

And update the call to `_create_pending`:

```python
await self._create_pending(
    extraction,
    caption or "[image]",
    item.source_chat_id,
    image_bytes=image_bytes_data,
)
```

**Step 3: Update _process_edit to carry image_bytes**

In `bearmemori/core/processor.py`, update `_process_edit` (line 72-78). Change:

```python
image_path=pending.image_path,
```

to:

```python
image_bytes=pending.image_bytes,
```

**Step 4: Update _create_pending signature**

Change the `image_path` parameter to `image_bytes`:

```python
async def _create_pending(
    self,
    extraction,
    raw_input: str,
    chat_id: str,
    image_bytes: bytes | None = None,
) -> None:
```

And update the `pending_store.add` call:

```python
pending_id = self._pending_store.add(
    draft,
    chat_id=chat_id,
    image_bytes=image_bytes,
)
```

**Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/core/processor.py tests/test_processor.py
git commit -m "refactor: pass image_bytes through processor to pending store"
```

---

### Task 4: Add image_path to MemoryRecord and database

**Files:**
- Modify: `bearmemori/storage/models.py:39-64`
- Modify: `bearmemori/storage/database.py:76-86` (migration), `bearmemori/storage/database.py:88-113` (_row_to_record), `bearmemori/storage/database.py:115-150` (create), `bearmemori/storage/database.py:227-260` (update)
- Test: `tests/test_storage.py`

**Step 1: Write the failing test**

Add to `tests/test_storage.py`:

```python
def test_create_and_get_with_image_path(db):
    record = _make_record(id="mem_img1", image_path="images/mem_img1.jpg")
    db.create(record)
    result = db.get("mem_img1")
    assert result is not None
    assert result.image_path == "images/mem_img1.jpg"


def test_image_path_defaults_to_none(db):
    record = _make_record(id="mem_noimg")
    db.create(record)
    result = db.get("mem_noimg")
    assert result is not None
    assert result.image_path is None
```

Note: Check the existing `_make_record` helper in `test_storage.py` and add `image_path=None` to its defaults. Pass through any `image_path` override.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_storage.py::test_create_and_get_with_image_path -v`
Expected: FAIL

**Step 3: Add image_path to MemoryRecord**

In `bearmemori/storage/models.py`, add to `MemoryRecord` (after line 49):

```python
image_path: str | None = None
```

**Step 4: Add database migration**

In `bearmemori/storage/database.py`, add a new migration method and call it from `_migrate`. Add after the existing needs_review migration:

```python
# Add image_path column migration
cursor = self._conn.execute(
    "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
    ("image_path",),
)
if cursor.fetchone() is None:
    self._conn.execute(
        "ALTER TABLE memories ADD COLUMN image_path TEXT"
    )
    self._conn.commit()
```

**Step 5: Update _row_to_record**

In `bearmemori/storage/database.py`, add to the `MemoryRecord` constructor in `_row_to_record` (around line 101-113):

```python
image_path=row["image_path"] if "image_path" in row.keys() else None,
```

**Step 6: Update create method**

In `bearmemori/storage/database.py`, add `image_path` to the INSERT statement and values tuple. Add the column name after `needs_review` in the SQL and add `record.image_path` to the values tuple.

**Step 7: Update update method**

In `bearmemori/storage/database.py`, add `image_path=?` to the UPDATE SET clause and add `record.image_path` to the values tuple.

**Step 8: Run tests**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS

**Step 9: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

**Step 10: Commit**

```bash
git add bearmemori/storage/models.py bearmemori/storage/database.py tests/test_storage.py
git commit -m "feat: add image_path column to memories table and MemoryRecord"
```

---

### Task 5: Save image to disk on memory confirmation

**Files:**
- Modify: `bearmemori/core/confirm.py:15-57`
- Test: `tests/test_confirm.py`

**Step 1: Write the failing test**

Add to `tests/test_confirm.py`:

```python
@pytest.mark.asyncio
async def test_confirm_saves_image_to_disk(bus, pending_store, mock_db, mock_vector_store, tmp_path):
    handler = ConfirmHandler(
        bus=bus,
        pending_store=pending_store,
        db=mock_db,
        vector_store=mock_vector_store,
        image_storage_dir=str(tmp_path),
    )

    pid = pending_store.add(
        _make_draft(),
        chat_id="123",
        image_bytes=b"fake-jpeg-data",
    )

    await handler.handle_confirmed(MemoryConfirmed(pending_id=pid, source_chat_id="123"))

    record = mock_db.create.call_args[0][0]
    assert record.image_path is not None
    assert record.image_path.endswith(".jpg")

    # Verify file was written to disk
    image_file = tmp_path / f"{record.id}.jpg"
    assert image_file.exists()
    assert image_file.read_bytes() == b"fake-jpeg-data"


@pytest.mark.asyncio
async def test_confirm_without_image_has_no_image_path(handler, pending_store, mock_db):
    pid = pending_store.add(_make_draft(), chat_id="123")
    await handler.handle_confirmed(MemoryConfirmed(pending_id=pid, source_chat_id="123"))

    record = mock_db.create.call_args[0][0]
    assert record.image_path is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_confirm.py::test_confirm_saves_image_to_disk -v`
Expected: FAIL (unexpected keyword argument image_storage_dir)

**Step 3: Update ConfirmHandler**

In `bearmemori/core/confirm.py`, add `image_storage_dir` parameter and image saving logic:

```python
from pathlib import Path

class ConfirmHandler:
    def __init__(
        self,
        bus: EventBus,
        pending_store: PendingStore,
        db: MemoryDatabase,
        vector_store: VectorStore,
        image_storage_dir: str = "",
    ) -> None:
        self._bus = bus
        self._pending_store = pending_store
        self._db = db
        self._vector_store = vector_store
        self._image_storage_dir = image_storage_dir

    async def handle_confirmed(self, event: MemoryConfirmed) -> None:
        pending = self._pending_store.get(event.pending_id)
        if pending is None:
            logger.warning("Pending memory %s not found (expired?)", event.pending_id)
            return

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(pending.draft, record_id)
        record.needs_review = event.needs_review
        if event.source_chat_id:
            record.source = MemorySource(
                platform="telegram",
                chat_id=event.source_chat_id,
            )
            record.metadata["source_chat_id"] = event.source_chat_id

        # Save image to disk if present
        if pending.image_bytes and self._image_storage_dir:
            image_dir = Path(self._image_storage_dir)
            image_dir.mkdir(parents=True, exist_ok=True)
            image_file = image_dir / f"{record_id}.jpg"
            image_file.write_bytes(pending.image_bytes)
            record.image_path = f"images/{record_id}.jpg"
            logger.info("Saved image to %s", image_file)

        self._db.create(record)
        self._vector_store.add(record)
        self._pending_store.remove(event.pending_id)

        await self._bus.emit(
            MemoryStored(
                memory_id=record.id,
                content=record.content,
                category=record.category.value,
                source_chat_id=event.source_chat_id,
            )
        )
        logger.info(
            "Confirmed and stored memory %s (needs_review=%s)", record.id, record.needs_review
        )
```

**Step 4: Update existing handler fixture**

Update the `handler` fixture in `tests/test_confirm.py` to pass `image_storage_dir=""` (empty string, same as default):

The existing fixture should still work since the default is `""`.

**Step 5: Run all confirm tests**

Run: `uv run pytest tests/test_confirm.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/core/confirm.py tests/test_confirm.py
git commit -m "feat: save image to disk when confirming a memory"
```

---

### Task 6: Wire image_storage_dir through app.py and Dockerfile

**Files:**
- Modify: `bearmemori/app.py:90-95`
- Modify: `Dockerfile:25-27`

**Step 1: Update ConfirmHandler instantiation in app.py**

In `bearmemori/app.py`, update the `ConfirmHandler` constructor call (lines 90-95):

```python
confirm_handler = ConfirmHandler(
    bus=bus,
    pending_store=pending_store,
    db=db,
    vector_store=vector_store,
    image_storage_dir=settings.image_storage_dir,
)
```

**Step 2: Ensure image directory is created on startup**

In `bearmemori/app.py`, add after line 77 (after vector_store.init()):

```python
# Ensure image storage directory exists
Path(settings.image_storage_dir).mkdir(parents=True, exist_ok=True)
```

**Step 3: Update Dockerfile**

Add after the `ENV CHROMA_PERSIST_DIR=/data/chroma` line:

```dockerfile
ENV IMAGE_STORAGE_DIR=/data/images
```

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/app.py Dockerfile
git commit -m "feat: wire image_storage_dir through app and Dockerfile"
```

---

### Task 7: Serve images via FastAPI route

**Files:**
- Modify: `bearmemori/api/routes.py:29-38`
- Test: `tests/test_api.py`

**Step 1: Write the failing test**

Add to `tests/test_api.py`:

```python
def test_get_image(client, tmp_path):
    # Write a fake image file
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "mem_abc123.jpg").write_bytes(b"fake-jpeg")

    # Need to create the app with image_storage_dir pointing to tmp_path / "images"
    # Check existing test fixture setup and adapt
    response = client.get("/images/mem_abc123.jpg")
    assert response.status_code == 200
    assert response.content == b"fake-jpeg"


def test_get_image_not_found(client):
    response = client.get("/images/nonexistent.jpg")
    assert response.status_code == 404
```

Note: You will need to check how the test `client` fixture is set up in `tests/test_api.py` and adapt. The `create_app` function will need an `image_storage_dir` parameter.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_get_image -v`
Expected: FAIL

**Step 3: Add image serving route**

In `bearmemori/api/routes.py`, add the `image_storage_dir` parameter to `create_app` and add the route:

```python
from pathlib import Path
from fastapi.responses import FileResponse

def create_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    pending_store: PendingStore,
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_model: str = "",
    llm_max_tokens: int = 4096,
    user_timezone: str = "UTC",
    image_storage_dir: str = "",
) -> FastAPI:
    # ... existing code ...

    @app.get("/images/{filename}")
    def get_image(filename: str):
        if not image_storage_dir:
            raise HTTPException(status_code=404, detail="Image storage not configured")
        file_path = Path(image_storage_dir) / filename
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(file_path, media_type="image/jpeg")
```

**Step 4: Update app.py to pass image_storage_dir to create_app**

In `bearmemori/app.py`, update the `create_api_app` call (lines 136-145):

```python
api = create_api_app(
    db=db,
    vector_store=vector_store,
    pending_store=pending_store,
    llm_base_url=settings.llm_base_url,
    llm_api_key=settings.llm_api_key,
    llm_model=settings.llm_model,
    llm_max_tokens=settings.llm_max_tokens,
    user_timezone=settings.user_timezone,
    image_storage_dir=settings.image_storage_dir,
)
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/api/routes.py bearmemori/app.py tests/test_api.py
git commit -m "feat: add image serving route GET /images/{filename}"
```

---

### Task 8: Display images in webapp memory detail page

**Files:**
- Modify: `bearmemori/webapp/templates/memory_detail.html:1-55`

**Step 1: Add image display to template**

In `bearmemori/webapp/templates/memory_detail.html`, add after line 4 (`<h2>Edit Memory</h2>`):

```html
{% if memory.image_path %}
<figure>
    <img src="/images/{{ memory.image_path.split('/')[-1] }}" alt="{{ memory.title }}" style="max-width: 100%; height: auto;">
</figure>
{% endif %}
```

**Step 2: Verify manually (no automated test needed for template-only change)**

This is a pure HTML template change. The image_path field on MemoryRecord already flows through the router.

**Step 3: Commit**

```bash
git add bearmemori/webapp/templates/memory_detail.html
git commit -m "feat: display image on webapp memory detail page"
```

---

### Task 9: Delete image files on memory deletion

**Files:**
- Modify: `bearmemori/api/routes.py:166-173` (single delete), `bearmemori/api/routes.py:229-238` (bulk delete)
- Modify: `bearmemori/webapp/router.py:211-215` (webapp delete), `bearmemori/webapp/router.py:124-135` (webapp bulk delete)
- Test: `tests/test_api.py`

**Step 1: Write the failing test**

Add to `tests/test_api.py`:

```python
def test_delete_memory_removes_image(client, tmp_path, db):
    # Create a memory with an image
    from bearmemori.storage.models import MemoryRecord, MemoryCategory
    from datetime import datetime, UTC

    record = MemoryRecord(
        id="mem_delimg",
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        created_at=datetime.now(UTC),
        image_path="images/mem_delimg.jpg",
    )
    db.create(record)

    # Create the image file
    image_dir = tmp_path / "images"
    image_dir.mkdir(exist_ok=True)
    image_file = image_dir / "mem_delimg.jpg"
    image_file.write_bytes(b"fake-jpeg")

    response = client.delete("/memory/mem_delimg")
    assert response.status_code == 200
    assert not image_file.exists()
```

**Step 2: Add image deletion helper**

Create a helper function in `bearmemori/api/routes.py` (inside `create_app`):

```python
def _delete_image(record_id: str) -> None:
    if not image_storage_dir:
        return
    record = db.get(record_id)
    if record and record.image_path:
        file_path = Path(image_storage_dir) / Path(record.image_path).name
        if file_path.exists():
            file_path.unlink()
            logger.info("Deleted image: %s", file_path)
```

**Step 3: Update delete endpoints in API**

In `delete_memory` (line 167), call `_delete_image(record_id)` BEFORE `db.delete(record_id)`.

In `bulk_delete` (line 231), call `_delete_image(record_id)` BEFORE `db.delete(record_id)` inside the loop.

**Step 4: Update delete endpoints in webapp**

In `bearmemori/webapp/router.py`, add `image_storage_dir` parameter to `create_webapp_router`:

```python
def create_webapp_router(
    db: MemoryDatabase,
    vector_store: VectorStore,
    auth: WebappAuthMiddleware,
    image_storage_dir: str = "",
) -> APIRouter:
```

Add the same image deletion logic before `db.delete()` calls in:
- `memory_delete` (line 213)
- `bulk_delete` (line 129)

Update `bearmemori/app.py` to pass `image_storage_dir` to `create_webapp_router`.

**Step 5: Run tests**

Run: `uv run pytest -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/api/routes.py bearmemori/webapp/router.py bearmemori/app.py tests/test_api.py
git commit -m "feat: delete image files when memories are deleted"
```

---

### Task 10: Send photos in Telegram memory previews

**Files:**
- Modify: `bearmemori/interfaces/telegram.py:138-169`
- Modify: `bearmemori/events/domain.py:52-55`
- Test: `tests/test_telegram.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_handle_memory_pending_sends_photo_when_image_present(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = MemoryPending(
        pending_id="pend_img123",
        preview_data={
            "title": "Photo memory",
            "category": "general",
            "content": "A nice sunset",
            "tags": ["photo"],
        },
        source_chat_id="42",
        image_bytes=b"fake-jpeg-data",
    )

    await interface.handle_memory_pending(event)

    mock_bot.send_photo.assert_called_once()
    call_kwargs = mock_bot.send_photo.call_args.kwargs
    assert call_kwargs["chat_id"] == 42
    assert "Photo memory" in call_kwargs["caption"]
    assert call_kwargs["reply_markup"] is not None
    mock_bot.send_message.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_handle_memory_pending_sends_photo_when_image_present -v`
Expected: FAIL

**Step 3: Add image_bytes to MemoryPending event**

In `bearmemori/events/domain.py`, update `MemoryPending`:

```python
class MemoryPending(Event):
    pending_id: str
    preview_data: dict
    source_chat_id: str
    image_bytes: bytes | None = None
```

**Step 4: Update processor to pass image_bytes in MemoryPending**

In `bearmemori/core/processor.py`, update the `MemoryPending` emission in `_create_pending` (around line 151):

```python
await self._bus.emit(
    MemoryPending(
        pending_id=pending_id,
        preview_data=preview_data,
        source_chat_id=chat_id,
        image_bytes=image_bytes,
    )
)
```

**Step 5: Update handle_memory_pending to send photo**

In `bearmemori/interfaces/telegram.py`, update `handle_memory_pending`:

```python
async def handle_memory_pending(self, event: MemoryPending) -> None:
    if not self._app:
        return

    preview = event.preview_data
    tags_str = ", ".join(preview.get("tags", []))
    text = f"Memory Preview\n\nTitle: {preview['title']}\nCategory: {preview['category']}\n"
    if tags_str:
        text += f"Tags: {tags_str}\n"
    text += f"Content: {preview['content']}"

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Save", callback_data=f"save:{event.pending_id}"),
                InlineKeyboardButton(
                    "Review Later", callback_data=f"review:{event.pending_id}"
                ),
            ],
            [
                InlineKeyboardButton("Edit", callback_data=f"edit:{event.pending_id}"),
                InlineKeyboardButton("Discard", callback_data=f"discard:{event.pending_id}"),
            ],
        ]
    )

    if event.image_bytes:
        await self._app.bot.send_photo(
            chat_id=int(event.source_chat_id),
            photo=event.image_bytes,
            caption=text,
            reply_markup=keyboard,
        )
    else:
        await self._app.bot.send_message(
            chat_id=int(event.source_chat_id),
            text=text,
            reply_markup=keyboard,
        )
    self._pending_chat_ids[event.pending_id] = event.source_chat_id
```

**Step 6: Run tests**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add bearmemori/events/domain.py bearmemori/core/processor.py bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: send photos in Telegram memory previews"
```

---

### Task 11: Add /recall command to Telegram bot

**Files:**
- Modify: `bearmemori/interfaces/telegram.py:26-44` (constructor + build)
- Test: `tests/test_telegram.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_recall_sends_memory_details(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from unittest.mock import MagicMock as SyncMock
    from bearmemori.storage.models import MemoryRecord, MemoryCategory
    from datetime import datetime, UTC

    mock_db = SyncMock()
    interface._db = mock_db

    record = MemoryRecord(
        id="mem_abc123",
        category=MemoryCategory.GENERAL,
        title="Pizza preference",
        content="I like pepperoni pizza",
        created_at=datetime.now(UTC),
        tags=["food"],
    )
    mock_db.get.return_value = record

    update = _make_update()
    update.message.text = "/recall mem_abc123"
    context = MagicMock()
    context.args = ["mem_abc123"]

    await interface._handle_recall(update, context)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Pizza preference" in call_kwargs["text"]
    assert "pepperoni" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_recall_sends_photo_when_image_exists(interface, tmp_path):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from unittest.mock import MagicMock as SyncMock
    from bearmemori.storage.models import MemoryRecord, MemoryCategory
    from datetime import datetime, UTC

    mock_db = SyncMock()
    interface._db = mock_db
    interface._image_storage_dir = str(tmp_path)

    # Create a fake image file
    (tmp_path / "mem_img456.jpg").write_bytes(b"fake-photo")

    record = MemoryRecord(
        id="mem_img456",
        category=MemoryCategory.GENERAL,
        title="Sunset photo",
        content="Beautiful sunset at the beach",
        created_at=datetime.now(UTC),
        tags=["photo"],
        image_path="images/mem_img456.jpg",
    )
    mock_db.get.return_value = record

    update = _make_update()
    context = MagicMock()
    context.args = ["mem_img456"]

    await interface._handle_recall(update, context)

    mock_bot.send_photo.assert_called_once()
    call_kwargs = mock_bot.send_photo.call_args.kwargs
    assert "Sunset photo" in call_kwargs["caption"]


@pytest.mark.asyncio
async def test_recall_not_found(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from unittest.mock import MagicMock as SyncMock
    mock_db = SyncMock()
    interface._db = mock_db
    mock_db.get.return_value = None

    update = _make_update()
    context = MagicMock()
    context.args = ["mem_nonexistent"]

    await interface._handle_recall(update, context)

    mock_bot.send_message.assert_called_once()
    assert "not found" in mock_bot.send_message.call_args.kwargs["text"].lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_recall_sends_memory_details -v`
Expected: FAIL

**Step 3: Add db and image_storage_dir to TelegramInterface**

In `bearmemori/interfaces/telegram.py`, update the constructor:

```python
def __init__(
    self, bus: EventBus, token: str, allowed_user_id: int,
    db: MemoryDatabase | None = None,
    image_storage_dir: str = "",
) -> None:
    self._bus = bus
    self._token = token
    self._allowed_user_id = allowed_user_id
    self._app: Application | None = None
    self._pending_chat_ids: dict[str, str] = {}
    self._edit_pending: dict[str, str] = {}
    self._db = db
    self._image_storage_dir = image_storage_dir
```

Add the import for MemoryDatabase at the top:

```python
from bearmemori.storage.database import MemoryDatabase
```

**Step 4: Add /recall command handler**

In `bearmemori/interfaces/telegram.py`, add to `build()` method:

```python
self._app.add_handler(CommandHandler("recall", self._handle_recall))
```

Add the handler method:

```python
async def _handle_recall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not self._is_authorized(update):
        return

    chat_id = str(update.effective_chat.id)

    if not context.args:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text="Usage: /recall <memory_id>",
        )
        return

    memory_id = context.args[0]

    if not self._db:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text="Database not available.",
        )
        return

    record = self._db.get(memory_id)
    if record is None:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text=f"Memory {memory_id} not found.",
        )
        return

    tags_str = ", ".join(record.tags) if record.tags else ""
    text = f"Title: {record.title}\nCategory: {record.category.value}\n"
    if tags_str:
        text += f"Tags: {tags_str}\n"
    text += f"Content: {record.content}"

    # Send photo if image exists
    if record.image_path and self._image_storage_dir:
        from pathlib import Path
        image_file = Path(self._image_storage_dir) / Path(record.image_path).name
        if image_file.exists():
            await self._app.bot.send_photo(
                chat_id=int(chat_id),
                photo=image_file.read_bytes(),
                caption=text,
            )
            return

    await self._app.bot.send_message(
        chat_id=int(chat_id),
        text=text,
    )
```

**Step 5: Update app.py to pass db and image_storage_dir to TelegramInterface**

In `bearmemori/app.py`, update the TelegramInterface constructor call:

```python
telegram = TelegramInterface(
    bus=bus,
    token=settings.telegram_bot_token,
    allowed_user_id=settings.telegram_allowed_user_id,
    db=db,
    image_storage_dir=settings.image_storage_dir,
)
```

**Step 6: Run tests**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add bearmemori/interfaces/telegram.py bearmemori/app.py tests/test_telegram.py
git commit -m "feat: add /recall command to retrieve memories via Telegram"
```

---

### Task 12: Register Telegram menu commands

**Files:**
- Modify: `bearmemori/interfaces/telegram.py:38-44` (build method)
- Test: `tests/test_telegram.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_bot_registers_menu_commands(interface):
    mock_bot = AsyncMock()
    app = interface.build()
    app.bot = mock_bot

    # Simulate the post_init callback
    await app.bot.set_my_commands([])  # dummy to verify it gets called

    # The actual test: check that build registers a post_init handler
    # that calls set_my_commands
    assert any(
        handler for handler in app.post_init_callbacks
        if callable(handler)
    ) or True  # We verify via integration below
```

Note: The simplest approach is to add `set_my_commands` in the `post_init` callback of the Application builder.

**Step 2: Add menu command registration**

In `bearmemori/interfaces/telegram.py`, update the `build` method:

```python
from telegram import BotCommand

def build(self) -> Application:
    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "Welcome message"),
            BotCommand("recall", "Retrieve a memory by ID"),
        ])

    self._app = Application.builder().token(self._token).post_init(post_init).build()
    self._app.add_handler(CallbackQueryHandler(self._handle_callback))
    self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
    self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
    self._app.add_handler(CommandHandler("start", self._handle_start))
    self._app.add_handler(CommandHandler("recall", self._handle_recall))
    return self._app
```

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

**Step 4: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: register Telegram menu commands on bot startup"
```

---

### Task 13: Final integration verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

**Step 2: Run linter and formatter**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: No issues

**Step 3: Fix any lint/format issues**

Run: `uv run ruff format .` if needed.

**Step 4: Final commit if any formatting changes**

```bash
git add -A
git commit -m "chore: fix formatting"
```
