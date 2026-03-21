# Reminder System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a reminder system where reminders are time-tagged memories processed through the existing LLM pipeline, with a background scheduler that detects due reminders and emits events.

**Architecture:** Reminders are stored as memories with `remind_at` and `recurring_minutes` fields. A `ReminderScheduler` async background task polls for due reminders and emits `ReminderDue` events. New REST API endpoints expose active and due reminders for the external chatbot to poll.

**Tech Stack:** Python 3.12+, SQLite, asyncio, FastAPI, pytest + pytest-asyncio

---

### Task 1: Add reminder fields to Memory model

**Files:**
- Modify: `bearmemori/storage/models.py:1-17`
- Test: `tests/test_storage.py`

**Step 1: Write the failing test**

Add to `tests/test_storage.py`:

```python
def test_create_memory_with_reminder_fields(db):
    from datetime import datetime, timedelta

    remind_time = datetime.now() + timedelta(hours=1)
    memory = _make_memory(
        id="reminder-1",
        memory_type="reminder",
        remind_at=remind_time,
        recurring_minutes=480,
    )
    db.create(memory)
    result = db.get("reminder-1")
    assert result is not None
    assert result.remind_at == remind_time
    assert result.recurring_minutes == 480


def test_create_memory_without_reminder_fields(db):
    memory = _make_memory(id="normal-1")
    db.create(memory)
    result = db.get("normal-1")
    assert result is not None
    assert result.remind_at is None
    assert result.recurring_minutes is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py::test_create_memory_with_reminder_fields tests/test_storage.py::test_create_memory_without_reminder_fields -v`
Expected: FAIL -- `remind_at` field does not exist on Memory model

**Step 3: Write minimal implementation**

In `bearmemori/storage/models.py`, add two fields to the `Memory` class:

```python
from datetime import datetime

from pydantic import BaseModel, Field


class Memory(BaseModel):
    id: str
    content: str
    raw_input: str
    memory_type: str
    tags: list[str] = Field(default_factory=list)
    embedding: bytes | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    source: str = "unknown"
    metadata: dict = Field(default_factory=dict)
    remind_at: datetime | None = None
    recurring_minutes: int | None = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py::test_create_memory_with_reminder_fields tests/test_storage.py::test_create_memory_without_reminder_fields -v`
Expected: FAIL -- database schema doesn't have the columns yet (this is expected, Task 2 fixes it)

**Step 5: Commit**

```bash
git add bearmemori/storage/models.py tests/test_storage.py
git commit -m "feat: add remind_at and recurring_minutes fields to Memory model"
```

---

### Task 2: Add reminder columns to database schema

**Files:**
- Modify: `bearmemori/storage/database.py:16-58` (initialize method)
- Modify: `bearmemori/storage/database.py:60-72` (_row_to_memory method)
- Modify: `bearmemori/storage/database.py:74-92` (create method)
- Modify: `bearmemori/storage/database.py:100-118` (update method)
- Test: `tests/test_storage.py`

**Step 1: Update the `initialize` method's CREATE TABLE**

In `bearmemori/storage/database.py`, add two columns to the CREATE TABLE statement inside `initialize`:

```sql
remind_at TEXT,
recurring_minutes INTEGER
```

Add them after the `metadata` column, before the closing parenthesis.

**Step 2: Update `_row_to_memory`**

Add to the `_row_to_memory` method in `bearmemori/storage/database.py`:

```python
remind_at=datetime.fromisoformat(row["remind_at"]) if row["remind_at"] else None,
recurring_minutes=row["recurring_minutes"],
```

**Step 3: Update `create` method**

Add `remind_at` and `recurring_minutes` to the INSERT statement and parameter tuple:

```python
def create(self, memory: Memory) -> None:
    self._conn.execute(
        """INSERT INTO memories (id, content, raw_input, memory_type, tags, embedding,
           created_at, updated_at, source, metadata, remind_at, recurring_minutes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            memory.id,
            memory.content,
            memory.raw_input,
            memory.memory_type,
            json.dumps(memory.tags),
            memory.embedding,
            memory.created_at.isoformat(),
            memory.updated_at.isoformat(),
            memory.source,
            json.dumps(memory.metadata),
            memory.remind_at.isoformat() if memory.remind_at else None,
            memory.recurring_minutes,
        ),
    )
    self._conn.commit()
```

**Step 4: Update `update` method**

Add `remind_at` and `recurring_minutes` to the UPDATE statement:

```python
def update(self, memory: Memory) -> None:
    memory.updated_at = datetime.now()
    self._conn.execute(
        """UPDATE memories SET content=?, raw_input=?, memory_type=?, tags=?,
           embedding=?, updated_at=?, source=?, metadata=?, remind_at=?, recurring_minutes=?
           WHERE id=?""",
        (
            memory.content,
            memory.raw_input,
            memory.memory_type,
            json.dumps(memory.tags),
            memory.embedding,
            memory.updated_at.isoformat(),
            memory.source,
            json.dumps(memory.metadata),
            memory.remind_at.isoformat() if memory.remind_at else None,
            memory.recurring_minutes,
            memory.id,
        ),
    )
    self._conn.commit()
```

**Step 5: Run all storage tests**

Run: `pytest tests/test_storage.py -v`
Expected: ALL PASS (including the two new tests from Task 1)

**Step 6: Commit**

```bash
git add bearmemori/storage/database.py
git commit -m "feat: add remind_at and recurring_minutes columns to database schema"
```

---

### Task 3: Add `get_due_reminders` method to database

**Files:**
- Modify: `bearmemori/storage/database.py` (add new method at end of class)
- Test: `tests/test_storage.py`

**Step 1: Write the failing test**

Add to `tests/test_storage.py`:

```python
def test_get_due_reminders(db):
    from datetime import datetime, timedelta

    past = datetime.now() - timedelta(hours=1)
    future = datetime.now() + timedelta(hours=1)

    db.create(_make_memory(id="due-1", memory_type="reminder", remind_at=past))
    db.create(_make_memory(id="not-due", memory_type="reminder", remind_at=future))
    db.create(_make_memory(id="normal", memory_type="preference"))

    results = db.get_due_reminders()
    assert len(results) == 1
    assert results[0].id == "due-1"


def test_get_due_reminders_empty(db):
    from datetime import datetime, timedelta

    future = datetime.now() + timedelta(hours=1)
    db.create(_make_memory(id="not-due", memory_type="reminder", remind_at=future))

    results = db.get_due_reminders()
    assert len(results) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py::test_get_due_reminders tests/test_storage.py::test_get_due_reminders_empty -v`
Expected: FAIL -- `get_due_reminders` does not exist

**Step 3: Write minimal implementation**

Add to `MemoryDatabase` class in `bearmemori/storage/database.py`:

```python
def get_due_reminders(self) -> list[Memory]:
    now = datetime.now().isoformat()
    rows = self._conn.execute(
        "SELECT * FROM memories WHERE remind_at IS NOT NULL AND remind_at <= ?",
        (now,),
    ).fetchall()
    return [self._row_to_memory(row) for row in rows]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py::test_get_due_reminders tests/test_storage.py::test_get_due_reminders_empty -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_storage.py
git commit -m "feat: add get_due_reminders query to storage layer"
```

---

### Task 4: Add `get_active_reminders` method to database

**Files:**
- Modify: `bearmemori/storage/database.py` (add new method at end of class)
- Test: `tests/test_storage.py`

**Step 1: Write the failing test**

Add to `tests/test_storage.py`:

```python
def test_get_active_reminders(db):
    from datetime import datetime, timedelta

    past = datetime.now() - timedelta(hours=1)
    future = datetime.now() + timedelta(hours=1)

    db.create(_make_memory(id="active-1", memory_type="reminder", remind_at=future))
    db.create(_make_memory(id="active-2", memory_type="reminder", remind_at=past))
    db.create(_make_memory(id="fired", memory_type="reminder"))  # remind_at is None = already fired
    db.create(_make_memory(id="normal", memory_type="preference"))

    results = db.get_active_reminders()
    assert len(results) == 2
    ids = {r.id for r in results}
    assert ids == {"active-1", "active-2"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py::test_get_active_reminders -v`
Expected: FAIL -- `get_active_reminders` does not exist

**Step 3: Write minimal implementation**

Add to `MemoryDatabase` class in `bearmemori/storage/database.py`:

```python
def get_active_reminders(self) -> list[Memory]:
    rows = self._conn.execute(
        "SELECT * FROM memories WHERE remind_at IS NOT NULL ORDER BY remind_at ASC"
    ).fetchall()
    return [self._row_to_memory(row) for row in rows]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py::test_get_active_reminders -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_storage.py
git commit -m "feat: add get_active_reminders query to storage layer"
```

---

### Task 5: Add `ReminderDue` event

**Files:**
- Modify: `bearmemori/events/domain.py`
- Test: `tests/test_event_bus.py`

**Step 1: Write the failing test**

Add to `tests/test_event_bus.py`:

```python
from bearmemori.events.domain import ReminderDue


@pytest.mark.asyncio
async def test_reminder_due_event():
    bus = EventBus()
    received = []
    bus.on(ReminderDue, lambda e: received.append(e))

    await bus.emit(ReminderDue(
        memory_id="rem-1",
        content="Take meds",
        source_chat_id="42",
        remind_at_iso="2026-03-21T10:00:00",
    ))

    assert len(received) == 1
    assert received[0].memory_id == "rem-1"
    assert received[0].content == "Take meds"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_bus.py::test_reminder_due_event -v`
Expected: FAIL -- cannot import `ReminderDue`

**Step 3: Write minimal implementation**

Add to `bearmemori/events/domain.py`:

```python
class ReminderDue(Event):
    memory_id: str
    content: str
    source_chat_id: str
    remind_at_iso: str
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_bus.py::test_reminder_due_event -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/events/domain.py tests/test_event_bus.py
git commit -m "feat: add ReminderDue event type"
```

---

### Task 6: Add ReminderScheduler

**Files:**
- Create: `bearmemori/core/scheduler.py`
- Test: `tests/test_scheduler.py`

**Step 1: Write the failing test**

Create `tests/test_scheduler.py`:

```python
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.models import Memory


def _make_reminder(**overrides) -> Memory:
    defaults = {
        "id": "rem-1",
        "content": "Take meds",
        "raw_input": "remind me to take meds",
        "memory_type": "reminder",
        "tags": ["health"],
        "source": "telegram",
        "remind_at": datetime.now() - timedelta(minutes=5),
        "recurring_minutes": None,
    }
    defaults.update(overrides)
    return Memory(**defaults)


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def scheduler(bus, mock_db):
    return ReminderScheduler(bus=bus, db=mock_db, poll_interval_seconds=60)


@pytest.mark.asyncio
async def test_check_fires_due_reminder(scheduler, bus, mock_db):
    reminder = _make_reminder(metadata={"source_chat_id": "42"})
    mock_db.get_due_reminders.return_value = [reminder]

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 1
    assert fired[0].memory_id == "rem-1"
    assert fired[0].content == "Take meds"
    assert fired[0].source_chat_id == "42"


@pytest.mark.asyncio
async def test_check_nulls_oneoff_reminder(scheduler, mock_db):
    reminder = _make_reminder(recurring_minutes=None, metadata={"source_chat_id": "42"})
    mock_db.get_due_reminders.return_value = [reminder]

    await scheduler.check_reminders()

    mock_db.update.assert_called_once()
    updated = mock_db.update.call_args[0][0]
    assert updated.remind_at is None


@pytest.mark.asyncio
async def test_check_advances_recurring_reminder(scheduler, mock_db):
    original_time = datetime.now() - timedelta(minutes=5)
    reminder = _make_reminder(
        remind_at=original_time,
        recurring_minutes=480,
        metadata={"source_chat_id": "42"},
    )
    mock_db.get_due_reminders.return_value = [reminder]

    await scheduler.check_reminders()

    mock_db.update.assert_called_once()
    updated = mock_db.update.call_args[0][0]
    expected_next = original_time + timedelta(minutes=480)
    assert updated.remind_at == expected_next
    assert updated.recurring_minutes == 480


@pytest.mark.asyncio
async def test_check_no_due_reminders(scheduler, bus, mock_db):
    mock_db.get_due_reminders.return_value = []

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 0
    mock_db.update.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL -- cannot import `ReminderScheduler`

**Step 3: Write minimal implementation**

Create `bearmemori/core/scheduler.py`:

```python
import asyncio
import logging
from datetime import timedelta

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.database import MemoryDatabase

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bus: EventBus, db: MemoryDatabase, poll_interval_seconds: int = 60) -> None:
        self._bus = bus
        self._db = db
        self._poll_interval = poll_interval_seconds

    async def check_reminders(self) -> None:
        due = self._db.get_due_reminders()
        for memory in due:
            source_chat_id = memory.metadata.get("source_chat_id", "")
            await self._bus.emit(
                ReminderDue(
                    memory_id=memory.id,
                    content=memory.content,
                    source_chat_id=source_chat_id,
                    remind_at_iso=memory.remind_at.isoformat(),
                )
            )

            if memory.recurring_minutes:
                memory.remind_at = memory.remind_at + timedelta(minutes=memory.recurring_minutes)
            else:
                memory.remind_at = None

            self._db.update(memory)
            logger.info("Fired reminder %s: %s", memory.id, memory.content[:80])

    async def run(self) -> None:
        logger.info("Reminder scheduler started (poll every %ds)", self._poll_interval)
        while True:
            try:
                await self.check_reminders()
            except Exception:
                logger.exception("Error checking reminders")
            await asyncio.sleep(self._poll_interval)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add bearmemori/core/scheduler.py tests/test_scheduler.py
git commit -m "feat: add ReminderScheduler with polling and recurring support"
```

---

### Task 7: Update LLM prompts for reminder classification

**Files:**
- Modify: `bearmemori/llm/client.py:10-14` (ClassificationResult)
- Modify: `bearmemori/llm/client.py:17-20` (ExtractionResult)
- Modify: `bearmemori/llm/client.py:23-48` (system prompts)
- Test: `tests/test_llm_client.py`

**Step 1: Write the failing test**

Add to `tests/test_llm_client.py`. First read the file to check existing patterns, then add:

```python
@pytest.mark.asyncio
async def test_classify_reminder(llm_client, mock_completions):
    mock_completions.create.return_value = _make_response(
        '{"action": "store", "memory_type": "reminder", "confidence": 0.95}'
    )

    result = await llm_client.classify_input("remind me to take meds at 8pm")
    assert result.action == "store"
    assert result.memory_type == "reminder"


@pytest.mark.asyncio
async def test_extract_reminder(llm_client, mock_completions):
    mock_completions.create.return_value = _make_response(
        '{"content": "Take meds", "memory_type": "reminder", "tags": ["health"], '
        '"remind_at": "2026-03-21T20:00:00", "recurring_minutes": null}'
    )

    result = await llm_client.extract_memory("remind me to take meds at 8pm", None)
    assert result.memory_type == "reminder"
    assert result.remind_at == "2026-03-21T20:00:00"
    assert result.recurring_minutes is None


@pytest.mark.asyncio
async def test_extract_recurring_reminder(llm_client, mock_completions):
    mock_completions.create.return_value = _make_response(
        '{"content": "Take meds", "memory_type": "reminder", "tags": ["health"], '
        '"remind_at": "2026-03-21T20:00:00", "recurring_minutes": 480}'
    )

    result = await llm_client.extract_memory("remind me every 8 hours to take meds", None)
    assert result.recurring_minutes == 480
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_client.py::test_extract_reminder tests/test_llm_client.py::test_extract_recurring_reminder -v`
Expected: FAIL -- `remind_at` and `recurring_minutes` not on ExtractionResult

**Step 3: Write minimal implementation**

In `bearmemori/llm/client.py`:

Update `ExtractionResult`:

```python
class ExtractionResult(BaseModel):
    content: str
    memory_type: str
    tags: list[str]
    remind_at: str | None = None
    recurring_minutes: int | None = None
```

Update `CLASSIFY_SYSTEM_PROMPT` -- add `reminder` to the types list:

```python
CLASSIFY_SYSTEM_PROMPT = (
    "You are a memory classification assistant. Given user input, decide whether to:\n"
    '1. "store" - the input contains clear information worth remembering\n'
    '2. "followup" - the input is unclear and needs more context\n'
    "\n"
    "Respond with JSON only:\n"
    '- For store: {"action": "store", "memory_type": "<type>", "confidence": <0-1>}\n'
    "  Types: preference, event, fact, note, person, location, task, reminder\n"
    '- For followup: {"action": "followup", "question": "<your clarifying question>"}'
)
```

Update `EXTRACT_SYSTEM_PROMPT` -- add reminder fields and instructions:

```python
EXTRACT_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Extract structured memory data from the user input.\n"
    "If follow-up context is provided, use the full conversation to understand the memory.\n"
    "\n"
    "Respond with JSON only:\n"
    '{"content": "<clear summary of the memory>", "memory_type": "<type>", '
    '"tags": ["tag1", "tag2"], "remind_at": "<ISO datetime or null>", '
    '"recurring_minutes": <minutes between recurrences or null>}\n'
    "Types: preference, event, fact, note, person, location, task, reminder\n"
    "\n"
    "For reminders:\n"
    "- Set remind_at to the ISO 8601 datetime when the reminder should fire\n"
    "- Set recurring_minutes if the user wants a repeating reminder (e.g., every 8 hours = 480)\n"
    "- For non-reminder types, set both remind_at and recurring_minutes to null"
)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_client.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add bearmemori/llm/client.py tests/test_llm_client.py
git commit -m "feat: update LLM prompts and models for reminder classification"
```

---

### Task 8: Update Processor to handle reminder fields

**Files:**
- Modify: `bearmemori/core/processor.py:48-71` (store branch of process_item)
- Test: `tests/test_processor.py`

**Step 1: Write the failing test**

Add to `tests/test_processor.py`:

```python
from datetime import datetime


@pytest.mark.asyncio
async def test_process_item_stores_reminder(processor, bus, mock_llm, mock_db):
    stored_events = []
    bus.on(MemoryStored, lambda e: stored_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", memory_type="reminder", confidence=0.95
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Take meds",
        memory_type="reminder",
        tags=["health"],
        remind_at="2026-03-21T20:00:00",
        recurring_minutes=480,
    )
    mock_llm.get_embedding.return_value = [0.1, 0.2, 0.3]

    item = QueueItem(input_type="text", content="remind me every 8 hours to take meds", source_chat_id="123")
    await processor.process_item(item)

    mock_db.create.assert_called_once()
    created_memory = mock_db.create.call_args[0][0]
    assert created_memory.memory_type == "reminder"
    assert created_memory.remind_at == datetime.fromisoformat("2026-03-21T20:00:00")
    assert created_memory.recurring_minutes == 480
    assert created_memory.metadata["source_chat_id"] == "123"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_processor.py::test_process_item_stores_reminder -v`
Expected: FAIL -- `remind_at` not set on the created Memory

**Step 3: Write minimal implementation**

In `bearmemori/core/processor.py`, update the store branch of `process_item` (after the extraction call). Replace the Memory creation block:

```python
from datetime import datetime

# ... in process_item, after extraction and embedding ...

remind_at = None
if extraction.remind_at:
    remind_at = datetime.fromisoformat(extraction.remind_at)

memory = Memory(
    id=str(uuid.uuid4()),
    content=extraction.content,
    raw_input=text,
    memory_type=extraction.memory_type,
    tags=extraction.tags,
    embedding=embedding_bytes,
    source="telegram",
    metadata={"source_chat_id": item.source_chat_id},
    remind_at=remind_at,
    recurring_minutes=extraction.recurring_minutes,
)
```

Add `from datetime import datetime` to the imports at the top of the file.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_processor.py -v`
Expected: ALL PASS

Note: The existing `test_process_item_stores_memory` test should still pass because `ExtractionResult` defaults `remind_at` and `recurring_minutes` to None.

**Step 5: Commit**

```bash
git add bearmemori/core/processor.py tests/test_processor.py
git commit -m "feat: update processor to store reminder fields from LLM extraction"
```

---

### Task 9: Add reminder API endpoints

**Files:**
- Modify: `bearmemori/api/schemas.py` (add ReminderResponse)
- Modify: `bearmemori/api/routes.py` (add two endpoints)
- Test: `tests/test_api.py`

**Step 1: Write the failing tests**

Add to `tests/test_api.py`:

```python
from datetime import datetime, timedelta


@pytest.fixture
def seeded_reminders(db):
    future = datetime.now() + timedelta(hours=2)
    past = datetime.now() - timedelta(minutes=10)

    db.create(Memory(
        id="rem-1",
        content="Take meds",
        raw_input="remind me to take meds",
        memory_type="reminder",
        tags=["health"],
        source="telegram",
        remind_at=future,
        recurring_minutes=480,
    ))
    db.create(Memory(
        id="rem-2",
        content="Call dentist",
        raw_input="remind me to call dentist",
        memory_type="reminder",
        tags=["health"],
        source="telegram",
        remind_at=past,
    ))
    db.create(Memory(
        id="mem-normal",
        content="Likes dark mode",
        raw_input="I like dark mode",
        memory_type="preference",
        tags=["ui"],
        source="telegram",
    ))
    return db


def test_list_active_reminders(client, seeded_reminders):
    response = client.get("/reminders")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    ids = {r["id"] for r in data}
    assert ids == {"rem-1", "rem-2"}


def test_list_due_reminders(client, seeded_reminders):
    response = client.get("/reminders/due")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "rem-2"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py::test_list_active_reminders tests/test_api.py::test_list_due_reminders -v`
Expected: FAIL -- 404 on `/reminders`

**Step 3: Write minimal implementation**

Add to `bearmemori/api/schemas.py`:

```python
class ReminderResponse(BaseModel):
    id: str
    content: str
    memory_type: str
    tags: list[str]
    remind_at: datetime | None
    recurring_minutes: int | None
    created_at: datetime
    source: str
    metadata: dict
```

Add to `bearmemori/api/routes.py` inside `create_app`, before the `return app` line:

```python
from bearmemori.api.schemas import ReminderResponse

@app.get("/reminders", response_model=list[ReminderResponse])
def list_active_reminders():
    return db.get_active_reminders()

@app.get("/reminders/due", response_model=list[ReminderResponse])
def list_due_reminders():
    return db.get_due_reminders()
```

Add the `ReminderResponse` import at the top of the file alongside the other schema imports.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add bearmemori/api/schemas.py bearmemori/api/routes.py tests/test_api.py
git commit -m "feat: add /reminders and /reminders/due API endpoints"
```

---

### Task 10: Add config setting for poll interval

**Files:**
- Modify: `bearmemori/config.py:4-14`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_reminder_poll_interval_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    settings = Settings()
    assert settings.reminder_poll_interval_seconds == 60
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_reminder_poll_interval_default -v`
Expected: FAIL -- `reminder_poll_interval_seconds` not on Settings

**Step 3: Write minimal implementation**

Add to `Settings` class in `bearmemori/config.py`:

```python
reminder_poll_interval_seconds: int = 60
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add bearmemori/config.py tests/test_config.py
git commit -m "feat: add reminder_poll_interval_seconds config setting"
```

---

### Task 11: Wire ReminderScheduler into Application

**Files:**
- Modify: `bearmemori/app.py` (add scheduler to Application and create_application)
- Modify: `bearmemori/__main__.py` (start scheduler background task)
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
def test_application_has_scheduler(app):
    assert hasattr(app, "scheduler")
    assert app.scheduler is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py::test_application_has_scheduler -v`
Expected: FAIL -- `scheduler` attribute does not exist

**Step 3: Update Application class**

In `bearmemori/app.py`, add the scheduler:

```python
from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.domain import FollowUpRequired, InputReceived, ReminderDue, SendMessage
```

Add `scheduler: ReminderScheduler` to the `Application.__init__` parameters and `self.scheduler = scheduler`.

In `create_application`, after creating the other components:

```python
scheduler = ReminderScheduler(
    bus=bus,
    db=db,
    poll_interval_seconds=settings.reminder_poll_interval_seconds,
)
```

Wire the `ReminderDue` event to the Telegram interface for fallback delivery:

```python
bus.on(ReminderDue, telegram.handle_reminder_due)
```

Pass `scheduler` to `Application(...)`.

**Step 4: Update `__main__.py`**

In `bearmemori/__main__.py`, after the processing loop task, add:

```python
asyncio.create_task(application.scheduler.run())
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: PASS (may need to update fixtures -- check existing test_app.py patterns first)

Note: `telegram.handle_reminder_due` does not exist yet -- that's Task 12. This task may need Task 12 done first, or the wiring can be deferred. Wire the event handler in Task 12 instead if needed.

**Step 6: Commit**

```bash
git add bearmemori/app.py bearmemori/__main__.py tests/test_app.py
git commit -m "feat: wire ReminderScheduler into application and processing loop"
```

---

### Task 12: Add Telegram reminder delivery handler

**Files:**
- Modify: `bearmemori/interfaces/telegram.py` (add handle_reminder_due method)
- Test: `tests/test_telegram.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
from bearmemori.events.domain import ReminderDue


@pytest.mark.asyncio
async def test_handle_reminder_due(telegram, mock_bot):
    event = ReminderDue(
        memory_id="rem-1",
        content="Take meds",
        source_chat_id="42",
        remind_at_iso="2026-03-21T20:00:00",
    )
    await telegram.handle_reminder_due(event)

    mock_bot.send_message.assert_called_once()
    call_args = mock_bot.send_message.call_args
    assert call_args.kwargs["chat_id"] == "42"
    assert "Take meds" in call_args.kwargs["text"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram.py::test_handle_reminder_due -v`
Expected: FAIL -- `handle_reminder_due` does not exist

**Step 3: Write minimal implementation**

Add to the `TelegramInterface` class in `bearmemori/interfaces/telegram.py`:

```python
from bearmemori.events.domain import ReminderDue

async def handle_reminder_due(self, event: ReminderDue) -> None:
    if self._bot:
        await self._bot.send_message(
            chat_id=event.source_chat_id,
            text=f"Reminder: {event.content}",
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: add Telegram handler for reminder delivery"
```

---

### Task 13: Add integration test for reminder flow

**Files:**
- Modify: `tests/test_integration.py` (add reminder flow test)

**Step 1: Write the integration test**

Add to `tests/test_integration.py`:

```python
from datetime import datetime, timedelta

from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.domain import ReminderDue


@pytest.mark.asyncio
async def test_reminder_store_and_fire_flow(wired_system, mock_llm, db):
    bus = wired_system["bus"]
    queue = wired_system["queue"]
    processor = wired_system["processor"]

    remind_time = datetime.now() - timedelta(minutes=1)  # already due

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", memory_type="reminder", confidence=0.95
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Take meds",
        memory_type="reminder",
        tags=["health"],
        remind_at=remind_time.isoformat(),
        recurring_minutes=None,
    )
    mock_llm.get_embedding.return_value = [0.1, 0.2, 0.3]

    # Send input through the pipeline
    await bus.emit(
        InputReceived(input_type="text", content="remind me to take meds", source_chat_id="42")
    )
    item = await queue.get_next()
    await processor.process_item(item)

    # Verify reminder stored
    memories = db.list_memories(memory_type="reminder")
    assert len(memories) == 1
    assert memories[0].remind_at is not None

    # Fire the scheduler
    scheduler = ReminderScheduler(bus=bus, db=db, poll_interval_seconds=60)

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 1
    assert fired[0].content == "Take meds"

    # One-off reminder should now have remind_at = None
    updated = db.get(memories[0].id)
    assert updated.remind_at is None
```

**Step 2: Run the integration test**

Run: `pytest tests/test_integration.py::test_reminder_store_and_fire_flow -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: add integration test for reminder store and fire flow"
```

---

### Task 14: Update .env.example

**Files:**
- Modify: `.env.example`

**Step 1: Add the new config option**

Add to `.env.example`:

```
REMINDER_POLL_INTERVAL_SECONDS=60
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add REMINDER_POLL_INTERVAL_SECONDS to .env.example"
```

---

### Task 15: Run full test suite

**Step 1: Run all tests**

Run: `pytest -v`
Expected: ALL PASS

**Step 2: Run linter**

Run: `ruff check .`
Expected: No errors

If any failures, fix them before proceeding.
