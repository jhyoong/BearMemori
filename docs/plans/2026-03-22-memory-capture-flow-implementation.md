# Memory Capture Flow Redesign - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace auto-store with a pending-then-confirm flow using Telegram inline keyboards, add LLM vision for captionless images, and auto-discard timed-out pending memories.

**Architecture:** The processor stops writing directly to the database. Instead it creates a `MemoryDraft`, adds it to the existing `PendingStore`, and emits a `MemoryPending` event. The Telegram adapter sends a preview with inline buttons (Save/Edit/Discard). On Save, the memory is committed to SQLite + ChromaDB. On timeout, it is discarded with a notification.

**Tech Stack:** python-telegram-bot (inline keyboards, CallbackQueryHandler), openai SDK (vision messages), existing EventBus, PendingStore, SQLite, ChromaDB.

---

### Task 1: Add new domain events (MemoryPending, MemoryConfirmed, MemoryDiscarded)

**Files:**
- Modify: `bearmemori/events/domain.py`
- Test: `tests/test_event_bus.py`

**Step 1: Write the failing test**

Add to `tests/test_event_bus.py`:

```python
@pytest.mark.asyncio
async def test_memory_pending_event():
    bus = EventBus()
    received = []
    bus.on(MemoryPending, lambda e: received.append(e))
    await bus.emit(MemoryPending(
        pending_id="pend_abc123",
        preview_data={"title": "Test", "category": "general", "content": "Test content", "tags": []},
        source_chat_id="123",
    ))
    assert len(received) == 1
    assert received[0].pending_id == "pend_abc123"


@pytest.mark.asyncio
async def test_memory_confirmed_event():
    bus = EventBus()
    received = []
    bus.on(MemoryConfirmed, lambda e: received.append(e))
    await bus.emit(MemoryConfirmed(pending_id="pend_abc123", source_chat_id="123"))
    assert len(received) == 1


@pytest.mark.asyncio
async def test_memory_discarded_event():
    bus = EventBus()
    received = []
    bus.on(MemoryDiscarded, lambda e: received.append(e))
    await bus.emit(MemoryDiscarded(pending_id="pend_abc123", source_chat_id="123"))
    assert len(received) == 1
```

Import the new events at the top of the test file:
```python
from bearmemori.events.domain import MemoryPending, MemoryConfirmed, MemoryDiscarded
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event_bus.py -v -k "memory_pending or memory_confirmed or memory_discarded"`
Expected: FAIL with `ImportError: cannot import name 'MemoryPending'`

**Step 3: Write minimal implementation**

Add to `bearmemori/events/domain.py`:

```python
class MemoryPending(Event):
    pending_id: str
    preview_data: dict
    source_chat_id: str


class MemoryConfirmed(Event):
    pending_id: str
    source_chat_id: str


class MemoryDiscarded(Event):
    pending_id: str
    source_chat_id: str
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_event_bus.py -v -k "memory_pending or memory_confirmed or memory_discarded"`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/events/domain.py tests/test_event_bus.py
git commit -m "feat: add MemoryPending, MemoryConfirmed, MemoryDiscarded events"
```

---

### Task 2: Extend PendingStore with chat_id, message_id, and image_path

**Files:**
- Modify: `bearmemori/storage/models.py` (PendingMemory model)
- Modify: `bearmemori/storage/pending_store.py`
- Test: `tests/test_pending_store.py`

**Step 1: Write the failing test**

Add to `tests/test_pending_store.py`:

```python
def test_add_with_chat_id_and_image_path():
    store = PendingStore()
    pid = store.add(_make_draft(), chat_id="123", image_path="/tmp/test.jpg")
    result = store.get(pid)
    assert result is not None
    assert result.chat_id == "123"
    assert result.image_path == "/tmp/test.jpg"


def test_add_stores_message_id():
    store = PendingStore()
    pid = store.add(_make_draft(), chat_id="123")
    result = store.get(pid)
    assert result.chat_id == "123"
    assert result.message_id is None

    store.set_message_id(pid, 42)
    result = store.get(pid)
    assert result.message_id == 42


def test_cleanup_returns_expired_ids():
    store = PendingStore(default_ttl=1)
    pid1 = store.add(_make_draft(), chat_id="123")
    pid2 = store.add(_make_draft(), chat_id="456")
    time.sleep(1.1)
    expired = store.cleanup_with_details()
    assert len(expired) == 2
    expired_ids = {e.pending_id for e in expired}
    assert pid1 in expired_ids
    assert pid2 in expired_ids
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pending_store.py -v -k "chat_id or message_id or cleanup_returns"`
Expected: FAIL with `TypeError` (unexpected keyword arguments)

**Step 3: Write minimal implementation**

In `bearmemori/storage/models.py`, update `PendingMemory`:

```python
class PendingMemory(BaseModel):
    pending_id: str
    draft: MemoryDraft
    ttl_seconds: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    chat_id: str = ""
    message_id: int | None = None
    image_path: str | None = None
```

In `bearmemori/storage/pending_store.py`, update `add()` signature and add `set_message_id()` and `cleanup_with_details()`:

```python
def add(self, draft: MemoryDraft, ttl: int | None = None, chat_id: str = "", image_path: str | None = None) -> str:
    pending_id = f"pend_{uuid.uuid4().hex[:12]}"
    ttl_seconds = ttl if ttl is not None else self._default_ttl
    self._store[pending_id] = PendingMemory(
        pending_id=pending_id,
        draft=draft,
        ttl_seconds=ttl_seconds,
        chat_id=chat_id,
        image_path=image_path,
    )
    return pending_id

def set_message_id(self, pending_id: str, message_id: int) -> None:
    item = self._store.get(pending_id)
    if item is not None:
        item.message_id = message_id

def cleanup_with_details(self) -> list[PendingMemory]:
    expired = [item for item in self._store.values() if self._is_expired(item)]
    for item in expired:
        del self._store[item.pending_id]
    return expired
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pending_store.py -v`
Expected: PASS (all existing + new tests)

**Step 5: Commit**

```bash
git add bearmemori/storage/models.py bearmemori/storage/pending_store.py tests/test_pending_store.py
git commit -m "feat: extend PendingStore with chat_id, message_id, image_path"
```

---

### Task 3: Add LLM vision method for image description

**Files:**
- Modify: `bearmemori/llm/client.py`
- Test: `tests/test_llm_client.py`

**Step 1: Write the failing test**

Add to `tests/test_llm_client.py`:

```python
@pytest.mark.asyncio
async def test_describe_image(llm_client, mock_completions):
    mock_completions.create.return_value = _make_response(
        '{"content": "A sunset over the ocean", "category": "general", '
        '"title": "Ocean sunset", "tags": ["photo", "nature"]}'
    )

    result = await llm_client.describe_image(b"fake-image-bytes")

    assert isinstance(result, ExtractionResult)
    assert result.title == "Ocean sunset"
    assert result.content == "A sunset over the ocean"

    call_args = mock_completions.create.call_args
    messages = call_args.kwargs["messages"]
    # Should have system + user message with image_url content
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][0]["type"] == "image_url"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_client.py -v -k "describe_image"`
Expected: FAIL with `AttributeError: 'LLMClient' object has no attribute 'describe_image'`

**Step 3: Write minimal implementation**

Add a new system prompt and method to `bearmemori/llm/client.py`:

```python
import base64

DESCRIBE_IMAGE_SYSTEM_PROMPT = (
    "/no_think\n"
    "You are a memory extraction assistant. Describe the image and extract structured memory data.\n"
    "\n"
    "You MUST respond with a single valid JSON object and nothing else.\n"
    '{"content": "<description of what the image shows>", "category": "<category>", '
    '"title": "<short descriptive title>", "tags": ["tag1", "tag2"], '
    '"event_fields": null}\n'
    "Categories: profile, general, event, location, task, reminder"
)
```

Add method to `LLMClient`:

```python
async def describe_image(self, image_bytes: bytes, caption: str | None = None) -> ExtractionResult:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    user_content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]
    if caption:
        user_content.append({"type": "text", "text": caption})

    response = await self._client.chat.completions.create(
        model=self._model,
        messages=[
            {"role": "system", "content": DESCRIBE_IMAGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
    )
    raw = response.choices[0].message.content
    logger.debug("Describe image raw output: %s", raw)
    data = extract_json(raw)
    return ExtractionResult(**data)
```

Add `import base64` to the top of the file.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_llm_client.py -v -k "describe_image"`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/llm/client.py tests/test_llm_client.py
git commit -m "feat: add LLM vision describe_image method"
```

---

### Task 4: Modify processor to emit MemoryPending instead of storing directly

**Files:**
- Modify: `bearmemori/core/processor.py`
- Modify: `tests/test_processor.py`

**Step 1: Write the failing test**

Replace the existing `test_process_item_stores_memory` test and add a new one in `tests/test_processor.py`:

```python
@pytest.fixture
def mock_pending_store():
    store = MagicMock()
    store.add.return_value = "pend_abc123"
    return store


@pytest.fixture
def processor(bus, mock_llm, mock_db, mock_pending_store):
    return Processor(bus=bus, llm=mock_llm, db=mock_db, pending_store=mock_pending_store)


@pytest.mark.asyncio
async def test_process_item_creates_pending_memory(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", category="profile", confidence=0.9
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="User likes dark mode",
        category="profile",
        title="Dark mode preference",
        tags=["ui"],
    )

    item = QueueItem(input_type="text", content="I like dark mode", source_chat_id="123")
    await processor.process_item(item)

    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1
    assert pending_events[0].pending_id == "pend_abc123"
    assert pending_events[0].source_chat_id == "123"
    assert pending_events[0].preview_data["title"] == "Dark mode preference"
```

Also add a test for image processing:

```python
@pytest.mark.asyncio
async def test_process_image_without_caption(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    mock_llm.describe_image.return_value = ExtractionResult(
        content="A sunset over the ocean",
        category="general",
        title="Ocean sunset",
        tags=["photo", "nature"],
    )

    item = QueueItem(
        input_type="image",
        content={"image_bytes": b"fake-image", "caption": "", "image_path": "/tmp/test.jpg"},
        source_chat_id="123",
    )
    await processor.process_item(item)

    mock_llm.describe_image.assert_called_once_with(b"fake-image", caption="")
    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1


@pytest.mark.asyncio
async def test_process_image_with_caption(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", category="general", confidence=0.9
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Photo of new apartment kitchen",
        category="general",
        title="New apartment kitchen",
        tags=["home"],
    )

    item = QueueItem(
        input_type="image",
        content={"image_bytes": b"fake-image", "caption": "My new kitchen", "image_path": "/tmp/test.jpg"},
        source_chat_id="123",
    )
    await processor.process_item(item)

    # With caption, uses normal classify + extract flow (not describe_image)
    mock_llm.classify_input.assert_called_once_with("My new kitchen")
    mock_pending_store.add.assert_called_once()
```

Import `MemoryPending` at the top of test file:
```python
from bearmemori.events.domain import FollowUpRequired, MemoryPending, MemoryStored
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_processor.py -v -k "pending_memory or image"`
Expected: FAIL (Processor constructor doesn't accept pending_store)

**Step 3: Write minimal implementation**

Update `bearmemori/core/processor.py`:

```python
import logging
import uuid
from datetime import UTC, datetime

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryPending
from bearmemori.llm.client import LLMClient
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft, MemorySource
from bearmemori.storage.pending_store import PendingStore

logger = logging.getLogger(__name__)


class Processor:
    def __init__(
        self,
        bus: EventBus,
        llm: LLMClient,
        db,  # kept for confirm handler
        pending_store: PendingStore,
    ) -> None:
        self._bus = bus
        self._llm = llm
        self._db = db
        self._pending_store = pending_store

    async def process_item(self, item: QueueItem) -> None:
        if item.input_type == "image":
            await self._process_image(item)
            return

        text = item.content if isinstance(item.content, str) else str(item.content)
        classification = await self._llm.classify_input(text)

        if classification.action == "followup":
            question = await self._llm.generate_followup(text, item.context)
            context = item.context or {"messages": []}
            context["messages"].append({"role": "user", "content": text})
            context["messages"].append({"role": "assistant", "content": question})
            await self._bus.emit(
                FollowUpRequired(
                    question=question,
                    source_chat_id=item.source_chat_id,
                    context=context,
                )
            )
            return

        extraction = await self._llm.extract_memory(text, item.context)
        await self._create_pending(extraction, text, item.source_chat_id)

    async def _process_image(self, item: QueueItem) -> None:
        image_bytes = item.content.get("image_bytes", b"")
        caption = item.content.get("caption", "")
        image_path = item.content.get("image_path")

        if caption:
            classification = await self._llm.classify_input(caption)
            if classification.action == "followup":
                question = await self._llm.generate_followup(caption, item.context)
                context = item.context or {"messages": []}
                context["messages"].append({"role": "user", "content": caption})
                context["messages"].append({"role": "assistant", "content": question})
                await self._bus.emit(
                    FollowUpRequired(
                        question=question,
                        source_chat_id=item.source_chat_id,
                        context=context,
                    )
                )
                return
            extraction = await self._llm.extract_memory(caption, item.context)
        else:
            extraction = await self._llm.describe_image(image_bytes, caption=caption)

        await self._create_pending(
            extraction, caption or "[image]", item.source_chat_id, image_path=image_path,
        )

    async def _create_pending(
        self, extraction, raw_input: str, chat_id: str, image_path: str | None = None,
    ) -> None:
        event_fields = None
        if extraction.event_fields:
            event_fields = EventFields(**extraction.event_fields)

        draft = MemoryDraft(
            category=MemoryCategory(extraction.category),
            title=extraction.title,
            content=extraction.content,
            event_fields=event_fields,
            tags=extraction.tags,
            source=MemorySource(platform="telegram", chat_id=chat_id),
        )

        pending_id = self._pending_store.add(
            draft, chat_id=chat_id, image_path=image_path,
        )

        preview_data = {
            "title": extraction.title,
            "category": extraction.category,
            "content": extraction.content,
            "tags": extraction.tags,
            "event_fields": extraction.event_fields,
        }

        await self._bus.emit(
            MemoryPending(
                pending_id=pending_id,
                preview_data=preview_data,
                source_chat_id=chat_id,
            )
        )
        logger.info("Pending memory %s: %s", pending_id, extraction.content[:80])
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_processor.py -v`
Expected: PASS (update existing tests that use the old constructor signature to include `mock_pending_store`)

Note: The existing `test_process_item_stores_reminder` test needs to be updated to check for `MemoryPending` instead of `MemoryStored`, and `mock_db.create` assertion should be removed since the processor no longer calls `db.create` directly. Update the fixture to include `mock_pending_store`.

**Step 5: Commit**

```bash
git add bearmemori/core/processor.py tests/test_processor.py
git commit -m "feat: processor emits MemoryPending instead of storing directly"
```

---

### Task 5: Add confirm handler to commit pending memories to storage

**Files:**
- Create: `bearmemori/core/confirm.py`
- Test: `tests/test_confirm.py`

**Step 1: Write the failing test**

Create `tests/test_confirm.py`:

```python
import uuid
from unittest.mock import MagicMock

import pytest

from bearmemori.core.confirm import ConfirmHandler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryStored
from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def pending_store():
    return PendingStore()


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_vector_store():
    return MagicMock()


@pytest.fixture
def handler(bus, pending_store, mock_db, mock_vector_store):
    return ConfirmHandler(
        bus=bus, pending_store=pending_store, db=mock_db, vector_store=mock_vector_store,
    )


def _make_draft(**overrides):
    defaults = dict(category=MemoryCategory.GENERAL, title="Test", content="Test content")
    defaults.update(overrides)
    return MemoryDraft(**defaults)


@pytest.mark.asyncio
async def test_confirm_stores_memory(handler, bus, pending_store, mock_db, mock_vector_store):
    stored_events = []
    bus.on(MemoryStored, lambda e: stored_events.append(e))

    pid = pending_store.add(_make_draft(), chat_id="123")

    await handler.handle_confirmed(MemoryConfirmed(pending_id=pid, source_chat_id="123"))

    mock_db.create.assert_called_once()
    record = mock_db.create.call_args[0][0]
    assert record.title == "Test"
    assert record.category == MemoryCategory.GENERAL

    mock_vector_store.add.assert_called_once_with(record)

    assert pending_store.get(pid) is None
    assert len(stored_events) == 1


@pytest.mark.asyncio
async def test_confirm_nonexistent_is_noop(handler, mock_db):
    await handler.handle_confirmed(MemoryConfirmed(pending_id="pend_nonexistent", source_chat_id="123"))
    mock_db.create.assert_not_called()


@pytest.mark.asyncio
async def test_discard_removes_pending(handler, bus, pending_store):
    pid = pending_store.add(_make_draft(), chat_id="123")
    await handler.handle_discarded(MemoryDiscarded(pending_id=pid, source_chat_id="123"))
    assert pending_store.get(pid) is None


@pytest.mark.asyncio
async def test_discard_cleans_up_image(handler, pending_store, tmp_path):
    img = tmp_path / "test.jpg"
    img.write_bytes(b"fake")
    pid = pending_store.add(_make_draft(), chat_id="123", image_path=str(img))

    await handler.handle_discarded(MemoryDiscarded(pending_id=pid, source_chat_id="123"))

    assert not img.exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_confirm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bearmemori.core.confirm'`

**Step 3: Write minimal implementation**

Create `bearmemori/core/confirm.py`:

```python
import logging
import uuid
from pathlib import Path

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryStored
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryRecord
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class ConfirmHandler:
    def __init__(
        self,
        bus: EventBus,
        pending_store: PendingStore,
        db: MemoryDatabase,
        vector_store: VectorStore,
    ) -> None:
        self._bus = bus
        self._pending_store = pending_store
        self._db = db
        self._vector_store = vector_store

    async def handle_confirmed(self, event: MemoryConfirmed) -> None:
        pending = self._pending_store.get(event.pending_id)
        if pending is None:
            logger.warning("Pending memory %s not found (expired?)", event.pending_id)
            return

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(pending.draft, record_id)
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
        logger.info("Confirmed and stored memory %s", record.id)

    async def handle_discarded(self, event: MemoryDiscarded) -> None:
        pending = self._pending_store.get(event.pending_id)
        if pending is None:
            return

        if pending.image_path:
            path = Path(pending.image_path)
            if path.exists():
                path.unlink()
                logger.info("Deleted image %s", pending.image_path)

        self._pending_store.remove(event.pending_id)
        logger.info("Discarded pending memory %s", event.pending_id)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_confirm.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/core/confirm.py tests/test_confirm.py
git commit -m "feat: add ConfirmHandler for committing/discarding pending memories"
```

---

### Task 6: Add Telegram inline keyboard preview and callback handling

**Files:**
- Modify: `bearmemori/interfaces/telegram.py`
- Modify: `tests/test_telegram.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
from bearmemori.events.domain import InputReceived, MemoryConfirmed, MemoryDiscarded, MemoryPending, ReminderDue, SendMessage


@pytest.mark.asyncio
async def test_handle_memory_pending_sends_preview(interface, bus):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot
    mock_bot.send_message.return_value = MagicMock(message_id=99)

    event = MemoryPending(
        pending_id="pend_abc123",
        preview_data={
            "title": "Dentist appointment",
            "category": "reminder",
            "content": "Dentist on Tuesday",
            "tags": ["health"],
        },
        source_chat_id="42",
    )

    await interface.handle_memory_pending(event)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 42
    assert "Dentist appointment" in call_kwargs["text"]
    assert call_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_callback_save_emits_confirmed(interface, bus):
    confirmed = []
    bus.on(MemoryConfirmed, lambda e: confirmed.append(e))

    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "save:pend_abc123"
    query.message = MagicMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_user.id = ALLOWED_USER_ID

    await interface._handle_callback(update, MagicMock())

    assert len(confirmed) == 1
    assert confirmed[0].pending_id == "pend_abc123"
    query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_callback_discard_emits_discarded(interface, bus):
    discarded = []
    bus.on(MemoryDiscarded, lambda e: discarded.append(e))

    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "discard:pend_abc123"
    query.message = MagicMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_user.id = ALLOWED_USER_ID

    await interface._handle_callback(update, MagicMock())

    assert len(discarded) == 1
    assert discarded[0].pending_id == "pend_abc123"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py -v -k "preview or callback"`
Expected: FAIL with `AttributeError: 'TelegramInterface' object has no attribute 'handle_memory_pending'`

**Step 3: Write minimal implementation**

Update `bearmemori/interfaces/telegram.py`:

```python
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputReceived, MemoryConfirmed, MemoryDiscarded, MemoryPending, ReminderDue, SendMessage

logger = logging.getLogger(__name__)


class TelegramInterface:
    def __init__(self, bus: EventBus, token: str, allowed_user_id: int) -> None:
        self._bus = bus
        self._token = token
        self._allowed_user_id = allowed_user_id
        self._app: Application | None = None
        self._pending_chat_ids: dict[str, str] = {}  # pending_id -> chat_id
        self._edit_pending: dict[str, str] = {}  # chat_id -> pending_id

    def _is_authorized(self, update: Update) -> bool:
        return update.effective_user.id == self._allowed_user_id

    def build(self) -> Application:
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self._app.add_handler(CommandHandler("start", self._handle_start))
        return self._app

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            logger.warning("Unauthorized text message from user %s", update.effective_user.id)
            return

        chat_id = str(update.effective_chat.id)
        text = update.message.text

        # Check if this is an edit response for a pending memory
        if chat_id in self._edit_pending:
            pending_id = self._edit_pending.pop(chat_id)
            await self._bus.emit(
                InputReceived(
                    input_type="text",
                    content=text,
                    source_chat_id=chat_id,
                    context={"edit_pending_id": pending_id},
                )
            )
            return

        logger.info("Received text from %s: %s", chat_id, text[:80])
        await self._bus.emit(InputReceived(input_type="text", content=text, source_chat_id=chat_id))

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            logger.warning("Unauthorized photo message from user %s", update.effective_user.id)
            return

        chat_id = str(update.effective_chat.id)
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        caption = update.message.caption or ""

        logger.info("Received photo from %s", chat_id)

        await self._bus.emit(
            InputReceived(
                input_type="image",
                content={
                    "image_bytes": bytes(file_bytes),
                    "caption": caption,
                    "file_path": file.file_path,
                },
                source_chat_id=chat_id,
            )
        )

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            logger.warning("Unauthorized /start command from user %s", update.effective_user.id)
            return

        await update.message.reply_text(
            "Welcome to BearMemori. Send me text or images and I will remember them for you."
        )

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        query = update.callback_query
        data = query.data
        action, pending_id = data.split(":", 1)
        chat_id = self._pending_chat_ids.get(pending_id, str(update.effective_chat.id))

        if action == "save":
            await self._bus.emit(MemoryConfirmed(pending_id=pending_id, source_chat_id=chat_id))
            await query.message.edit_text(query.message.text + "\n\nSaved.")
            await query.answer("Saved")
        elif action == "edit":
            self._edit_pending[chat_id] = pending_id
            await query.message.edit_text(query.message.text + "\n\nSend your corrections.")
            await query.answer()
        elif action == "discard":
            await self._bus.emit(MemoryDiscarded(pending_id=pending_id, source_chat_id=chat_id))
            await query.message.edit_text(query.message.text + "\n\nDiscarded.")
            await query.answer("Discarded")

        self._pending_chat_ids.pop(pending_id, None)

    async def handle_memory_pending(self, event: MemoryPending) -> None:
        if not self._app:
            return

        preview = event.preview_data
        tags_str = ", ".join(preview.get("tags", []))
        text = (
            f"Memory Preview\n\n"
            f"Title: {preview['title']}\n"
            f"Category: {preview['category']}\n"
        )
        if tags_str:
            text += f"Tags: {tags_str}\n"
        text += f"Content: {preview['content']}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Save", callback_data=f"save:{event.pending_id}"),
                InlineKeyboardButton("Edit", callback_data=f"edit:{event.pending_id}"),
                InlineKeyboardButton("Discard", callback_data=f"discard:{event.pending_id}"),
            ]
        ])

        msg = await self._app.bot.send_message(
            chat_id=int(event.source_chat_id),
            text=text,
            reply_markup=keyboard,
        )
        self._pending_chat_ids[event.pending_id] = event.source_chat_id

    async def handle_send_message(self, event: SendMessage) -> None:
        if self._app:
            await self._app.bot.send_message(chat_id=int(event.chat_id), text=event.text)

    async def handle_reminder_due(self, event: ReminderDue) -> None:
        if self._app:
            await self._app.bot.send_message(
                chat_id=int(event.source_chat_id),
                text=f"Reminder: {event.content}",
            )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: add inline keyboard preview and callback handling for memory confirmation"
```

---

### Task 7: Add pending memory timeout cleanup task

**Files:**
- Create: `bearmemori/core/cleanup.py`
- Test: `tests/test_cleanup.py`

**Step 1: Write the failing test**

Create `tests/test_cleanup.py`:

```python
import time
from unittest.mock import AsyncMock

import pytest

from bearmemori.core.cleanup import PendingCleanupTask
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryDiscarded, SendMessage
from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def pending_store():
    return PendingStore(default_ttl=1)


@pytest.fixture
def cleanup(bus, pending_store):
    return PendingCleanupTask(bus=bus, pending_store=pending_store)


def _make_draft():
    return MemoryDraft(category=MemoryCategory.GENERAL, title="Test", content="Test content")


@pytest.mark.asyncio
async def test_cleanup_discards_expired_and_notifies(cleanup, bus, pending_store):
    discarded_events = []
    send_events = []
    bus.on(MemoryDiscarded, lambda e: discarded_events.append(e))
    bus.on(SendMessage, lambda e: send_events.append(e))

    pending_store.add(_make_draft(), chat_id="123")
    pending_store.add(_make_draft(), chat_id="456")
    time.sleep(1.1)

    await cleanup.run_once()

    assert len(discarded_events) == 2
    assert len(send_events) == 2
    chat_ids = {e.chat_id for e in send_events}
    assert "123" in chat_ids
    assert "456" in chat_ids


@pytest.mark.asyncio
async def test_cleanup_skips_non_expired(cleanup, pending_store):
    pending_store.add(_make_draft(), chat_id="123")
    # Don't sleep - should not be expired
    count = await cleanup.run_once()
    assert count == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cleanup.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `bearmemori/core/cleanup.py`:

```python
import asyncio
import logging
from pathlib import Path

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryDiscarded, SendMessage
from bearmemori.storage.pending_store import PendingStore

logger = logging.getLogger(__name__)


class PendingCleanupTask:
    def __init__(
        self,
        bus: EventBus,
        pending_store: PendingStore,
        interval_seconds: int = 300,
    ) -> None:
        self._bus = bus
        self._pending_store = pending_store
        self._interval = interval_seconds

    async def run_once(self) -> int:
        expired = self._pending_store.cleanup_with_details()
        for item in expired:
            if item.image_path:
                path = Path(item.image_path)
                if path.exists():
                    path.unlink()
            await self._bus.emit(
                MemoryDiscarded(pending_id=item.pending_id, source_chat_id=item.chat_id)
            )
            await self._bus.emit(
                SendMessage(chat_id=item.chat_id, text="Memory discarded (timed out).")
            )
        if expired:
            logger.info("Cleaned up %d expired pending memories", len(expired))
        return len(expired)

    async def run(self) -> None:
        logger.info("Pending cleanup task started (interval=%ds)", self._interval)
        while True:
            await asyncio.sleep(self._interval)
            await self.run_once()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cleanup.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/core/cleanup.py tests/test_cleanup.py
git commit -m "feat: add PendingCleanupTask for auto-discarding expired pending memories"
```

---

### Task 8: Wire everything together in app.py and __main__.py

**Files:**
- Modify: `bearmemori/app.py`
- Modify: `bearmemori/__main__.py`
- Modify: `tests/test_app.py`

**Step 1: Read existing test_app.py**

Check `tests/test_app.py` for existing patterns before writing new tests.

**Step 2: Write the failing test**

Add to `tests/test_app.py`:

```python
def test_event_wiring_includes_pending_events(application):
    """MemoryPending, MemoryConfirmed, MemoryDiscarded should have handlers registered."""
    from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryPending

    bus = application.bus
    assert len(bus._handlers[MemoryPending]) > 0, "MemoryPending has no handlers"
    assert len(bus._handlers[MemoryConfirmed]) > 0, "MemoryConfirmed has no handlers"
    assert len(bus._handlers[MemoryDiscarded]) > 0, "MemoryDiscarded has no handlers"
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py -v -k "pending_events"`
Expected: FAIL (no handlers registered for new events)

**Step 4: Write minimal implementation**

Update `bearmemori/app.py`:

```python
import logging

from bearmemori.config import Settings
from bearmemori.core.cleanup import PendingCleanupTask
from bearmemori.core.confirm import ConfirmHandler
from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import (
    FollowUpRequired,
    InputReceived,
    MemoryConfirmed,
    MemoryDiscarded,
    MemoryPending,
    ReminderDue,
    SendMessage,
)
from bearmemori.interfaces.telegram import TelegramInterface
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Application:
    def __init__(
        self,
        bus: EventBus,
        db: MemoryDatabase,
        vector_store: VectorStore,
        pending_store: PendingStore,
        queue_manager: QueueManager,
        processor: Processor,
        followup_manager: FollowUpManager,
        confirm_handler: ConfirmHandler,
        cleanup_task: PendingCleanupTask,
        telegram: TelegramInterface,
        settings: Settings,
        scheduler: ReminderScheduler,
    ) -> None:
        self.bus = bus
        self.db = db
        self.vector_store = vector_store
        self.pending_store = pending_store
        self.queue_manager = queue_manager
        self.processor = processor
        self.followup_manager = followup_manager
        self.confirm_handler = confirm_handler
        self.cleanup_task = cleanup_task
        self.telegram = telegram
        self.settings = settings
        self.scheduler = scheduler


def create_application(settings: Settings) -> Application:
    bus = EventBus()

    db = MemoryDatabase(settings.database_path)
    db.initialize()

    vector_store = VectorStore(
        persist_dir=settings.chroma_persist_dir,
        embedding_model=settings.embedding_model,
    )
    vector_store.init()

    pending_store = PendingStore(default_ttl=settings.pending_ttl_seconds)

    llm = LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )

    queue_manager = QueueManager(bus, max_size=settings.queue_max_size)
    processor = Processor(bus=bus, llm=llm, db=db, pending_store=pending_store)
    followup_manager = FollowUpManager(bus)
    confirm_handler = ConfirmHandler(
        bus=bus, pending_store=pending_store, db=db, vector_store=vector_store,
    )
    cleanup_task = PendingCleanupTask(bus=bus, pending_store=pending_store)
    telegram = TelegramInterface(
        bus=bus,
        token=settings.telegram_bot_token,
        allowed_user_id=settings.telegram_allowed_user_id,
    )
    scheduler = ReminderScheduler(
        bus=bus,
        db=db,
        poll_interval_seconds=settings.reminder_poll_interval_seconds,
    )

    bus.on(InputReceived, queue_manager.handle_input)
    bus.on(FollowUpRequired, followup_manager.handle_followup_required)
    bus.on(MemoryPending, telegram.handle_memory_pending)
    bus.on(MemoryConfirmed, confirm_handler.handle_confirmed)
    bus.on(MemoryDiscarded, confirm_handler.handle_discarded)
    bus.on(SendMessage, telegram.handle_send_message)
    bus.on(ReminderDue, telegram.handle_reminder_due)

    return Application(
        bus=bus,
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        queue_manager=queue_manager,
        processor=processor,
        followup_manager=followup_manager,
        confirm_handler=confirm_handler,
        cleanup_task=cleanup_task,
        telegram=telegram,
        settings=settings,
        scheduler=scheduler,
    )
```

Update `bearmemori/__main__.py` to start the cleanup task:

```python
asyncio.create_task(processing_loop(application))
asyncio.create_task(application.scheduler.run())
asyncio.create_task(application.cleanup_task.run())
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_app.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/app.py bearmemori/__main__.py tests/test_app.py
git commit -m "feat: wire MemoryPending/Confirmed/Discarded events and cleanup task"
```

---

### Task 9: Handle edit flow in processor (re-extract with corrections)

**Files:**
- Modify: `bearmemori/core/processor.py`
- Modify: `tests/test_processor.py`

**Step 1: Write the failing test**

Add to `tests/test_processor.py`:

```python
@pytest.mark.asyncio
async def test_process_edit_re_extracts_memory(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    # Set up the original pending memory
    original_draft = MagicMock()
    original_pending = MagicMock()
    original_pending.draft = original_draft
    original_pending.chat_id = "123"
    original_pending.image_path = None
    mock_pending_store.get.return_value = original_pending
    mock_pending_store.add.return_value = "pend_new123"

    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Dentist appointment on Wednesday",
        category="reminder",
        title="Dentist on Wednesday",
        tags=["health"],
        event_fields={"datetime": "2026-04-16T10:00:00", "status": "pending", "recurrence": None},
    )

    item = QueueItem(
        input_type="text",
        content="Actually it's Wednesday not Tuesday",
        source_chat_id="123",
        context={"edit_pending_id": "pend_abc123"},
    )
    await processor.process_item(item)

    # Old pending should be removed
    mock_pending_store.remove.assert_called_with("pend_abc123")
    # New pending should be created
    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1
    assert pending_events[0].preview_data["title"] == "Dentist on Wednesday"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_processor.py -v -k "edit_re_extracts"`
Expected: FAIL (processor doesn't handle edit context)

**Step 3: Write minimal implementation**

Add to the top of `Processor.process_item()` in `bearmemori/core/processor.py`:

```python
async def process_item(self, item: QueueItem) -> None:
    # Handle edit corrections for a pending memory
    if item.context and "edit_pending_id" in item.context:
        await self._process_edit(item)
        return

    # ... rest of existing code
```

Add the `_process_edit` method:

```python
async def _process_edit(self, item: QueueItem) -> None:
    pending_id = item.context["edit_pending_id"]
    pending = self._pending_store.get(pending_id)
    if pending is None:
        logger.warning("Edit target %s not found (expired?)", pending_id)
        return

    text = item.content if isinstance(item.content, str) else str(item.content)
    original_content = pending.draft.content

    context = {"messages": [
        {"role": "user", "content": original_content},
        {"role": "user", "content": text},
    ]}
    extraction = await self._llm.extract_memory(text, context)

    self._pending_store.remove(pending_id)
    await self._create_pending(
        extraction, text, item.source_chat_id, image_path=pending.image_path,
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_processor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/core/processor.py tests/test_processor.py
git commit -m "feat: handle edit flow in processor, re-extract with corrections"
```

---

### Task 10: Run full test suite and fix any breakage

**Files:**
- Potentially modify: any files with broken tests

**Step 1: Run the full test suite**

Run: `uv run pytest -v`

**Step 2: Fix any failures**

Common expected issues:
- `test_app.py`: `create_application` signature changed (now includes `confirm_handler`, `cleanup_task`)
- `test_processor.py`: existing tests need `mock_pending_store` fixture
- `test_integration.py`: may need updates for new flow
- Import paths for moved/renamed items

Fix each failure by updating the test to match the new code.

**Step 3: Run lint**

Run: `uv run ruff check .`

Fix any lint issues.

**Step 4: Run full suite again**

Run: `uv run pytest -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "fix: update all tests for new pending memory confirmation flow"
```

---

### Task 11: Update config with new settings

**Files:**
- Modify: `bearmemori/config.py`

**Step 1: Review needed settings**

The `pending_ttl_seconds` already exists (default 86400 = 24h). Per the design, the default should be 1800 (30 minutes). Also add `cleanup_interval_seconds`.

**Step 2: Update config**

In `bearmemori/config.py`, change:

```python
pending_ttl_seconds: int = 1800  # 30 minutes
cleanup_interval_seconds: int = 300  # 5 minutes
```

**Step 3: Wire cleanup interval in app.py**

Update the `PendingCleanupTask` instantiation:

```python
cleanup_task = PendingCleanupTask(
    bus=bus, pending_store=pending_store, interval_seconds=settings.cleanup_interval_seconds,
)
```

**Step 4: Run tests**

Run: `uv run pytest -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/config.py bearmemori/app.py
git commit -m "chore: update pending TTL default to 30min, add cleanup interval setting"
```
