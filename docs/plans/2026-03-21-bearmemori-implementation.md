# BearMemori v0.3.0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a personal memory store with Telegram interface, LLM processing, priority queue, follow-up system, and REST API.

**Architecture:** Event-driven modular monolith. Single Python process with an async event bus connecting decoupled modules: interfaces (Telegram), core (queue, processor, follow-ups), LLM client, storage (SQLite+FTS5+embeddings), and REST API (FastAPI).

**Tech Stack:** Python 3.12+, uv, ruff, FastAPI, python-telegram-bot, openai SDK, SQLite+FTS5, Pydantic Settings, pytest+pytest-asyncio

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `ruff.toml`
- Create: `.gitignore`
- Create: `bearmemori/__init__.py`
- Create: `tests/__init__.py`
- Create: `.env.example`

**Step 1: Initialize uv project**

Run: `uv init --name bearmemori --python 3.12`

Then replace the generated `pyproject.toml` with:

```toml
[project]
name = "bearmemori"
version = "0.3.0"
description = "Personal memory store with LLM processing"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "python-telegram-bot>=21",
    "openai>=1.60",
    "pydantic-settings>=2.7",
    "numpy>=2.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.25",
    "httpx>=0.28",
    "ruff>=0.9",
]
```

**Step 2: Create ruff.toml**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

**Step 3: Create .gitignore**

```
__pycache__/
*.py[cod]
.env
*.db
*.sqlite
.venv/
dist/
*.egg-info/
.ruff_cache/
.pytest_cache/
```

**Step 4: Create .env.example**

```
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3
EMBEDDING_MODEL=nomic-embed-text
TELEGRAM_BOT_TOKEN=your-token-here
DATABASE_PATH=bearmemori.db
QUEUE_MAX_SIZE=1000
FOLLOWUP_TIMEOUT_HOURS=24
```

**Step 5: Create package init files**

Create empty `bearmemori/__init__.py` and `tests/__init__.py`.

**Step 6: Install dependencies**

Run: `uv sync --all-extras`

**Step 7: Verify setup**

Run: `uv run python -c "import bearmemori; print('ok')"`
Expected: `ok`

**Step 8: Commit**

```bash
git add pyproject.toml ruff.toml .gitignore .env.example bearmemori/__init__.py tests/__init__.py uv.lock
git commit -m "feat: scaffold project with uv, ruff, and dependencies"
```

---

### Task 2: Configuration

**Files:**
- Create: `bearmemori/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# tests/test_config.py
from bearmemori.config import Settings


def test_settings_loads_defaults():
    settings = Settings(
        telegram_bot_token="test-token",
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
    )
    assert settings.telegram_bot_token == "test-token"
    assert settings.database_path == "bearmemori.db"
    assert settings.queue_max_size == 1000
    assert settings.followup_timeout_hours == 24
    assert settings.embedding_model == "nomic-embed-text"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL - cannot import Settings

**Step 3: Write minimal implementation**

```python
# bearmemori/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    telegram_bot_token: str
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3"
    embedding_model: str = "nomic-embed-text"
    database_path: str = "bearmemori.db"
    queue_max_size: int = 1000
    followup_timeout_hours: int = 24
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/config.py tests/test_config.py
git commit -m "feat: add Pydantic Settings configuration"
```

---

### Task 3: Event Bus

**Files:**
- Create: `bearmemori/events/__init__.py`
- Create: `bearmemori/events/bus.py`
- Create: `bearmemori/events/types.py`
- Create: `tests/test_event_bus.py`

**Step 1: Write the failing tests**

```python
# tests/test_event_bus.py
import pytest
from bearmemori.events.bus import EventBus
from bearmemori.events.types import Event


class FakeEvent(Event):
    data: str


class AnotherEvent(Event):
    value: int


@pytest.mark.asyncio
async def test_emit_calls_registered_handler():
    bus = EventBus()
    received = []

    async def handler(event: FakeEvent):
        received.append(event.data)

    bus.on(FakeEvent, handler)
    await bus.emit(FakeEvent(data="hello"))

    assert received == ["hello"]


@pytest.mark.asyncio
async def test_emit_calls_multiple_handlers():
    bus = EventBus()
    results = []

    async def handler_a(event: FakeEvent):
        results.append("a")

    async def handler_b(event: FakeEvent):
        results.append("b")

    bus.on(FakeEvent, handler_a)
    bus.on(FakeEvent, handler_b)
    await bus.emit(FakeEvent(data="x"))

    assert sorted(results) == ["a", "b"]


@pytest.mark.asyncio
async def test_emit_does_not_call_unrelated_handlers():
    bus = EventBus()
    called = False

    async def handler(event: FakeEvent):
        nonlocal called
        called = True

    bus.on(FakeEvent, handler)
    await bus.emit(AnotherEvent(value=1))

    assert not called


@pytest.mark.asyncio
async def test_emit_with_no_handlers_does_nothing():
    bus = EventBus()
    await bus.emit(FakeEvent(data="no one listening"))
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_event_bus.py -v`
Expected: FAIL - cannot import

**Step 3: Write event types base**

```python
# bearmemori/events/__init__.py
from bearmemori.events.bus import EventBus
from bearmemori.events.types import Event

__all__ = ["Event", "EventBus"]
```

```python
# bearmemori/events/types.py
from pydantic import BaseModel


class Event(BaseModel):
    """Base class for all events."""
    pass
```

**Step 4: Write the event bus**

```python
# bearmemori/events/bus.py
import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from bearmemori.events.types import Event

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Callable]] = defaultdict(list)

    def on(self, event_type: type[Event], handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def emit(self, event: Event) -> None:
        handlers = self._handlers.get(type(event), [])
        tasks = [handler(event) for handler in handlers]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("Event handler error: %s", result)
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_event_bus.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add bearmemori/events/ tests/test_event_bus.py
git commit -m "feat: add async event bus with pub/sub"
```

---

### Task 4: Domain Events

**Files:**
- Create: `bearmemori/events/domain.py`
- Modify: `bearmemori/events/__init__.py`

**Step 1: Define all domain events**

```python
# bearmemori/events/domain.py
from datetime import datetime
from typing import Any

from bearmemori.events.types import Event


class InputReceived(Event):
    input_type: str  # "text", "image", "log"
    content: Any
    source_chat_id: str
    context: dict | None = None


class InputQueued(Event):
    priority: int
    input_type: str
    source_chat_id: str


class FollowUpRequired(Event):
    question: str
    source_chat_id: str
    context: dict


class MemoryStored(Event):
    memory_id: str
    content: str
    memory_type: str
    source_chat_id: str


class MemoryUpdated(Event):
    memory_id: str


class MemoryDeleted(Event):
    memory_id: str


class SendMessage(Event):
    chat_id: str
    text: str
```

**Step 2: Update __init__.py exports**

```python
# bearmemori/events/__init__.py
from bearmemori.events.bus import EventBus
from bearmemori.events.types import Event

__all__ = ["Event", "EventBus"]
```

**Step 3: Run existing tests**

Run: `uv run pytest -v`
Expected: all PASS

**Step 4: Commit**

```bash
git add bearmemori/events/
git commit -m "feat: define domain events"
```

---

### Task 5: Storage Layer - Schema and CRUD

**Files:**
- Create: `bearmemori/storage/__init__.py`
- Create: `bearmemori/storage/database.py`
- Create: `bearmemori/storage/models.py`
- Create: `tests/test_storage.py`

**Step 1: Write the data models**

```python
# bearmemori/storage/__init__.py
```

```python
# bearmemori/storage/models.py
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
```

**Step 2: Write the failing tests**

```python
# tests/test_storage.py
import pytest
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = MemoryDatabase(db_path)
    database.initialize()
    return database


def _make_memory(**overrides) -> Memory:
    defaults = {
        "id": "test-id-1",
        "content": "User prefers dark mode",
        "raw_input": "I like dark mode",
        "memory_type": "preference",
        "tags": ["ui", "preference"],
        "source": "telegram",
    }
    defaults.update(overrides)
    return Memory(**defaults)


def test_create_and_get_memory(db):
    memory = _make_memory()
    db.create(memory)
    result = db.get("test-id-1")
    assert result is not None
    assert result.content == "User prefers dark mode"
    assert result.tags == ["ui", "preference"]


def test_get_nonexistent_returns_none(db):
    assert db.get("nope") is None


def test_update_memory(db):
    memory = _make_memory()
    db.create(memory)
    memory.content = "User prefers light mode"
    memory.tags = ["ui", "preference", "updated"]
    db.update(memory)
    result = db.get("test-id-1")
    assert result.content == "User prefers light mode"
    assert "updated" in result.tags


def test_delete_memory(db):
    db.create(_make_memory())
    db.delete("test-id-1")
    assert db.get("test-id-1") is None


def test_list_memories(db):
    db.create(_make_memory(id="1", memory_type="preference"))
    db.create(_make_memory(id="2", memory_type="event"))
    db.create(_make_memory(id="3", memory_type="preference"))

    all_memories = db.list_memories()
    assert len(all_memories) == 3

    prefs = db.list_memories(memory_type="preference")
    assert len(prefs) == 2


def test_list_memories_by_tag(db):
    db.create(_make_memory(id="1", tags=["food", "preference"]))
    db.create(_make_memory(id="2", tags=["music"]))

    results = db.list_memories(tag="food")
    assert len(results) == 1
    assert results[0].id == "1"
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL - cannot import

**Step 4: Implement the database**

```python
# bearmemori/storage/database.py
import json
import sqlite3
from datetime import datetime

from bearmemori.storage.models import Memory


class MemoryDatabase:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                raw_input TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                embedding BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'unknown',
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(content, tags, content=memories, content_rowid=rowid)
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, tags)
                VALUES ('delete', old.rowid, old.content, old.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, tags)
                VALUES ('delete', old.rowid, old.content, old.tags);
                INSERT INTO memories_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END
        """)
        self._conn.commit()

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            content=row["content"],
            raw_input=row["raw_input"],
            memory_type=row["memory_type"],
            tags=json.loads(row["tags"]),
            embedding=row["embedding"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source=row["source"],
            metadata=json.loads(row["metadata"]),
        )

    def create(self, memory: Memory) -> None:
        self._conn.execute(
            """INSERT INTO memories (id, content, raw_input, memory_type, tags, embedding,
               created_at, updated_at, source, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )
        self._conn.commit()

    def get(self, memory_id: str) -> Memory | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def update(self, memory: Memory) -> None:
        memory.updated_at = datetime.now()
        self._conn.execute(
            """UPDATE memories SET content=?, raw_input=?, memory_type=?, tags=?,
               embedding=?, updated_at=?, source=?, metadata=?
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
                memory.id,
            ),
        )
        self._conn.commit()

    def delete(self, memory_id: str) -> None:
        self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()

    def list_memories(
        self,
        memory_type: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        query = "SELECT * FROM memories WHERE 1=1"
        params: list = []
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type)
        if tag:
            query += " AND json_each.value = ?"
            query = query.replace(
                "FROM memories",
                "FROM memories, json_each(memories.tags)",
            )
            params.append(tag)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_memory(row) for row in rows]
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add bearmemori/storage/ tests/test_storage.py
git commit -m "feat: add SQLite storage layer with FTS5 and CRUD"
```

---

### Task 6: Storage Layer - Search

**Files:**
- Modify: `bearmemori/storage/database.py`
- Modify: `tests/test_storage.py`

**Step 1: Write the failing tests**

Add to `tests/test_storage.py`:

```python
def test_keyword_search(db):
    db.create(_make_memory(id="1", content="User likes pizza for dinner"))
    db.create(_make_memory(id="2", content="User prefers dark mode in editors"))
    db.create(_make_memory(id="3", content="Meeting with John on Friday"))

    results = db.search_keyword("pizza")
    assert len(results) == 1
    assert results[0].id == "1"


def test_keyword_search_no_results(db):
    db.create(_make_memory(id="1", content="User likes pizza"))
    results = db.search_keyword("sushi")
    assert len(results) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py::test_keyword_search -v`
Expected: FAIL - no search_keyword method

**Step 3: Implement keyword search**

Add to `MemoryDatabase` class in `bearmemori/storage/database.py`:

```python
    def search_keyword(self, query: str, limit: int = 20) -> list[Memory]:
        rows = self._conn.execute(
            """SELECT memories.* FROM memories_fts
               JOIN memories ON memories.rowid = memories_fts.rowid
               WHERE memories_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_storage.py
git commit -m "feat: add FTS5 keyword search to storage layer"
```

---

### Task 7: Queue Manager

**Files:**
- Create: `bearmemori/core/__init__.py`
- Create: `bearmemori/core/queue.py`
- Create: `bearmemori/core/models.py`
- Create: `tests/test_queue.py`

**Step 1: Write the queue item model**

```python
# bearmemori/core/__init__.py
```

```python
# bearmemori/core/models.py
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueueItem(BaseModel):
    priority: int = 10
    input_type: str  # "text", "image", "log"
    content: Any
    context: dict | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    source_chat_id: str = ""

    def __lt__(self, other: "QueueItem") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at
```

**Step 2: Write the failing tests**

```python
# tests/test_queue.py
import pytest
from datetime import datetime, timedelta
from bearmemori.core.queue import QueueManager
from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputReceived, InputQueued


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def queue(bus):
    return QueueManager(bus, max_size=5)


@pytest.mark.asyncio
async def test_handle_input_queues_item(queue, bus):
    queued_events = []
    bus.on(InputQueued, lambda e: queued_events.append(e))

    event = InputReceived(input_type="text", content="hello", source_chat_id="123")
    await queue.handle_input(event)

    assert queue.size() == 1
    assert len(queued_events) == 1


@pytest.mark.asyncio
async def test_get_next_returns_highest_priority(queue):
    await queue.enqueue(QueueItem(priority=10, input_type="text", content="low", source_chat_id="1"))
    await queue.enqueue(QueueItem(priority=0, input_type="text", content="high", source_chat_id="2"))

    item = await queue.get_next()
    assert item.content == "high"


@pytest.mark.asyncio
async def test_queue_rejects_when_full(queue, bus):
    for i in range(5):
        await queue.enqueue(
            QueueItem(priority=10, input_type="text", content=f"item{i}", source_chat_id="1")
        )

    rejected = await queue.enqueue(
        QueueItem(priority=10, input_type="text", content="overflow", source_chat_id="1")
    )
    assert rejected is False


@pytest.mark.asyncio
async def test_queue_fifo_within_same_priority(queue):
    t1 = datetime.now()
    t2 = t1 + timedelta(seconds=1)
    await queue.enqueue(
        QueueItem(priority=10, input_type="text", content="first", source_chat_id="1", created_at=t1)
    )
    await queue.enqueue(
        QueueItem(priority=10, input_type="text", content="second", source_chat_id="1", created_at=t2)
    )

    item = await queue.get_next()
    assert item.content == "first"
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_queue.py -v`
Expected: FAIL - cannot import

**Step 4: Implement QueueManager**

```python
# bearmemori/core/queue.py
import asyncio
import heapq
import logging

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputQueued, InputReceived

logger = logging.getLogger(__name__)


class QueueManager:
    def __init__(self, bus: EventBus, max_size: int = 1000) -> None:
        self._bus = bus
        self._max_size = max_size
        self._heap: list[QueueItem] = []
        self._item_available = asyncio.Event()

    def size(self) -> int:
        return len(self._heap)

    async def enqueue(self, item: QueueItem) -> bool:
        if len(self._heap) >= self._max_size:
            logger.warning("Queue full, rejecting item from %s", item.source_chat_id)
            return False
        heapq.heappush(self._heap, item)
        self._item_available.set()
        return True

    async def get_next(self) -> QueueItem:
        while not self._heap:
            self._item_available.clear()
            await self._item_available.wait()
        return heapq.heappop(self._heap)

    async def handle_input(self, event: InputReceived) -> None:
        item = QueueItem(
            priority=0 if event.context else 10,
            input_type=event.input_type,
            content=event.content,
            context=event.context,
            source_chat_id=event.source_chat_id,
        )
        accepted = await self.enqueue(item)
        if accepted:
            await self._bus.emit(
                InputQueued(
                    priority=item.priority,
                    input_type=item.input_type,
                    source_chat_id=item.source_chat_id,
                )
            )
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_queue.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add bearmemori/core/ tests/test_queue.py
git commit -m "feat: add priority queue manager with event integration"
```

---

### Task 8: LLM Client

**Files:**
- Create: `bearmemori/llm/__init__.py`
- Create: `bearmemori/llm/client.py`
- Create: `tests/test_llm_client.py`

**Step 1: Write the failing tests**

```python
# tests/test_llm_client.py
import json
import pytest
from unittest.mock import AsyncMock, patch
from bearmemori.llm.client import LLMClient, ClassificationResult, ExtractionResult


@pytest.fixture
def client():
    return LLMClient(base_url="http://localhost:11434/v1", model="llama3", api_key="not-needed")


@pytest.mark.asyncio
async def test_classify_input_returns_store(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps({
            "action": "store",
            "memory_type": "preference",
            "confidence": 0.9,
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("I prefer dark mode")

    assert result.action == "store"
    assert result.memory_type == "preference"


@pytest.mark.asyncio
async def test_classify_input_returns_followup(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps({
            "action": "followup",
            "question": "What kind of dark mode?",
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("I changed something")

    assert result.action == "followup"
    assert result.question == "What kind of dark mode?"


@pytest.mark.asyncio
async def test_extract_memory(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps({
            "content": "User prefers dark mode in all applications",
            "memory_type": "preference",
            "tags": ["ui", "dark-mode", "preference"],
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_memory("I prefer dark mode", context=None)

    assert result.content == "User prefers dark mode in all applications"
    assert "dark-mode" in result.tags


@pytest.mark.asyncio
async def test_generate_followup(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content="Could you tell me more about what changed?"))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.generate_followup("something changed", context=None)

    assert "changed" in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: FAIL - cannot import

**Step 3: Implement LLM client**

```python
# bearmemori/llm/__init__.py
```

```python
# bearmemori/llm/client.py
import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ClassificationResult(BaseModel):
    action: str  # "store" or "followup"
    memory_type: str | None = None
    confidence: float | None = None
    question: str | None = None


class ExtractionResult(BaseModel):
    content: str
    memory_type: str
    tags: list[str]


CLASSIFY_SYSTEM_PROMPT = """You are a memory classification assistant. Given user input, decide whether to:
1. "store" - the input contains clear information worth remembering
2. "followup" - the input is unclear and needs more context

Respond with JSON only:
- For store: {"action": "store", "memory_type": "<type>", "confidence": <0-1>}
  Types: preference, event, fact, note, person, location, task
- For followup: {"action": "followup", "question": "<your clarifying question>"}"""

EXTRACT_SYSTEM_PROMPT = """You are a memory extraction assistant. Extract structured memory data from the user input.
If follow-up context is provided, use the full conversation to understand the memory.

Respond with JSON only:
{"content": "<clear summary of the memory>", "memory_type": "<type>", "tags": ["tag1", "tag2"]}
Types: preference, event, fact, note, person, location, task"""

FOLLOWUP_SYSTEM_PROMPT = """You are a helpful assistant gathering information for a personal memory store.
Ask a single, clear clarifying question to better understand what the user wants to remember.
Keep your question short and direct."""


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = "not-needed") -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def classify_input(self, text: str) -> ClassificationResult:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        data = json.loads(response.choices[0].message.content)
        return ClassificationResult(**data)

    async def extract_memory(self, text: str, context: dict | None) -> ExtractionResult:
        messages = [{"role": "system", "content": EXTRACT_SYSTEM_PROMPT}]
        if context and "messages" in context:
            messages.extend(context["messages"])
        messages.append({"role": "user", "content": text})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.1,
        )
        data = json.loads(response.choices[0].message.content)
        return ExtractionResult(**data)

    async def generate_followup(self, text: str, context: dict | None) -> str:
        messages = [{"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT}]
        if context and "messages" in context:
            messages.extend(context["messages"])
        messages.append({"role": "user", "content": text})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.7,
        )
        return response.choices[0].message.content

    async def get_embedding(self, text: str, model: str) -> list[float]:
        response = await self._client.embeddings.create(model=model, input=text)
        return response.data[0].embedding
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/llm/ tests/test_llm_client.py
git commit -m "feat: add LLM client with classify, extract, and followup"
```

---

### Task 9: Processor

**Files:**
- Create: `bearmemori/core/processor.py`
- Create: `tests/test_processor.py`

**Step 1: Write the failing tests**

```python
# tests/test_processor.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from bearmemori.core.processor import Processor
from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryStored
from bearmemori.llm.client import ClassificationResult, ExtractionResult


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def processor(bus, mock_llm, mock_db):
    return Processor(bus=bus, llm=mock_llm, db=mock_db, embedding_model="nomic-embed-text")


@pytest.mark.asyncio
async def test_process_item_stores_memory(processor, bus, mock_llm, mock_db):
    stored_events = []
    bus.on(MemoryStored, lambda e: stored_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", memory_type="preference", confidence=0.9
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="User likes dark mode", memory_type="preference", tags=["ui"]
    )
    mock_llm.get_embedding.return_value = [0.1, 0.2, 0.3]

    item = QueueItem(input_type="text", content="I like dark mode", source_chat_id="123")
    await processor.process_item(item)

    mock_db.create.assert_called_once()
    assert len(stored_events) == 1
    assert stored_events[0].source_chat_id == "123"


@pytest.mark.asyncio
async def test_process_item_requests_followup(processor, bus, mock_llm):
    followup_events = []
    bus.on(FollowUpRequired, lambda e: followup_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="followup", question="What changed?"
    )
    mock_llm.generate_followup.return_value = "Can you tell me more?"

    item = QueueItem(input_type="text", content="something changed", source_chat_id="123")
    await processor.process_item(item)

    assert len(followup_events) == 1
    assert followup_events[0].source_chat_id == "123"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_processor.py -v`
Expected: FAIL - cannot import Processor

**Step 3: Implement the Processor**

```python
# bearmemori/core/processor.py
import logging
import struct
import uuid

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryStored
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory

logger = logging.getLogger(__name__)


class Processor:
    def __init__(
        self,
        bus: EventBus,
        llm: LLMClient,
        db: MemoryDatabase,
        embedding_model: str,
    ) -> None:
        self._bus = bus
        self._llm = llm
        self._db = db
        self._embedding_model = embedding_model

    async def process_item(self, item: QueueItem) -> None:
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
        embedding = await self._llm.get_embedding(extraction.content, self._embedding_model)
        embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)

        memory = Memory(
            id=str(uuid.uuid4()),
            content=extraction.content,
            raw_input=text,
            memory_type=extraction.memory_type,
            tags=extraction.tags,
            embedding=embedding_bytes,
            source="telegram",
        )
        self._db.create(memory)

        await self._bus.emit(
            MemoryStored(
                memory_id=memory.id,
                content=memory.content,
                memory_type=memory.memory_type,
                source_chat_id=item.source_chat_id,
            )
        )
        logger.info("Stored memory %s: %s", memory.id, memory.content[:80])
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_processor.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/core/processor.py tests/test_processor.py
git commit -m "feat: add processor with LLM classification and memory storage"
```

---

### Task 10: Follow-Up Manager

**Files:**
- Create: `bearmemori/core/followup.py`
- Create: `tests/test_followup.py`

**Step 1: Write the failing tests**

```python
# tests/test_followup.py
import pytest
from bearmemori.core.followup import FollowUpManager
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, InputReceived, SendMessage


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def manager(bus):
    return FollowUpManager(bus)


@pytest.mark.asyncio
async def test_followup_required_tracks_conversation(manager, bus):
    sent = []
    bus.on(SendMessage, lambda e: sent.append(e))

    event = FollowUpRequired(
        question="What changed?",
        source_chat_id="123",
        context={"messages": [{"role": "user", "content": "something"}]},
    )
    await manager.handle_followup_required(event)

    assert manager.has_active_followup("123")
    assert len(sent) == 1
    assert sent[0].text == "What changed?"


@pytest.mark.asyncio
async def test_check_followup_adds_context(manager):
    event = FollowUpRequired(
        question="What changed?",
        source_chat_id="123",
        context={"messages": [{"role": "user", "content": "something"}]},
    )
    await manager.handle_followup_required(event)

    input_event = InputReceived(input_type="text", content="the theme", source_chat_id="123")
    result = manager.check_followup(input_event)

    assert result is not None
    assert result.context is not None
    assert result.context["messages"][-1]["content"] == "something"
    assert not manager.has_active_followup("123")


@pytest.mark.asyncio
async def test_check_followup_returns_none_when_no_active(manager):
    input_event = InputReceived(input_type="text", content="hello", source_chat_id="456")
    result = manager.check_followup(input_event)
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_followup.py -v`
Expected: FAIL - cannot import

**Step 3: Implement FollowUpManager**

```python
# bearmemori/core/followup.py
import logging

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, InputReceived, SendMessage

logger = logging.getLogger(__name__)


class FollowUpManager:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._active: dict[str, dict] = {}  # chat_id -> context

    def has_active_followup(self, chat_id: str) -> bool:
        return chat_id in self._active

    async def handle_followup_required(self, event: FollowUpRequired) -> None:
        self._active[event.source_chat_id] = event.context
        await self._bus.emit(SendMessage(chat_id=event.source_chat_id, text=event.question))
        logger.info("Follow-up requested for chat %s", event.source_chat_id)

    def check_followup(self, event: InputReceived) -> InputReceived | None:
        context = self._active.pop(event.source_chat_id, None)
        if context is None:
            return None
        return InputReceived(
            input_type=event.input_type,
            content=event.content,
            source_chat_id=event.source_chat_id,
            context=context,
        )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_followup.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/core/followup.py tests/test_followup.py
git commit -m "feat: add follow-up manager for conversation tracking"
```

---

### Task 11: REST API

**Files:**
- Create: `bearmemori/api/__init__.py`
- Create: `bearmemori/api/routes.py`
- Create: `bearmemori/api/schemas.py`
- Create: `tests/test_api.py`

**Step 1: Write the API schemas**

```python
# bearmemori/api/__init__.py
```

```python
# bearmemori/api/schemas.py
from datetime import datetime

from pydantic import BaseModel


class MemoryResponse(BaseModel):
    id: str
    content: str
    raw_input: str
    memory_type: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    source: str
    metadata: dict


class MemoryCreate(BaseModel):
    content: str
    raw_input: str = ""
    memory_type: str
    tags: list[str] = []
    source: str = "api"
    metadata: dict = {}


class MemoryUpdate(BaseModel):
    content: str | None = None
    memory_type: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None


class SearchRequest(BaseModel):
    query: str
    mode: str = "keyword"  # "keyword", "semantic", "hybrid"
    limit: int = 20
```

**Step 2: Write the failing tests**

```python
# tests/test_api.py
import pytest
from fastapi.testclient import TestClient
from bearmemori.api.routes import create_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = MemoryDatabase(db_path)
    database.initialize()
    return database


@pytest.fixture
def client(db):
    app = create_app(db)
    return TestClient(app)


@pytest.fixture
def seeded_db(db):
    db.create(Memory(
        id="mem-1",
        content="User prefers dark mode",
        raw_input="I like dark mode",
        memory_type="preference",
        tags=["ui", "preference"],
        source="telegram",
    ))
    db.create(Memory(
        id="mem-2",
        content="Meeting with John on Friday",
        raw_input="meeting john friday",
        memory_type="event",
        tags=["meeting", "john"],
        source="telegram",
    ))
    return db


def test_get_memory(client, seeded_db):
    response = client.get("/memories/mem-1")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "User prefers dark mode"


def test_get_memory_not_found(client):
    response = client.get("/memories/nope")
    assert response.status_code == 404


def test_list_memories(client, seeded_db):
    response = client.get("/memories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_list_memories_filter_by_type(client, seeded_db):
    response = client.get("/memories?memory_type=preference")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["memory_type"] == "preference"


def test_create_memory(client):
    response = client.post("/memories", json={
        "content": "Likes coffee",
        "memory_type": "preference",
        "tags": ["food"],
    })
    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Likes coffee"
    assert data["id"]  # should have an auto-generated ID


def test_update_memory(client, seeded_db):
    response = client.put("/memories/mem-1", json={
        "content": "User prefers light mode",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "User prefers light mode"


def test_delete_memory(client, seeded_db):
    response = client.delete("/memories/mem-1")
    assert response.status_code == 204
    assert client.get("/memories/mem-1").status_code == 404


def test_search_keyword(client, seeded_db):
    response = client.post("/memories/search", json={
        "query": "dark mode",
        "mode": "keyword",
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL - cannot import

**Step 4: Implement the API routes**

```python
# bearmemori/api/routes.py
import uuid

from fastapi import FastAPI, HTTPException

from bearmemori.api.schemas import MemoryCreate, MemoryResponse, MemoryUpdate, SearchRequest
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory


def create_app(db: MemoryDatabase) -> FastAPI:
    app = FastAPI(title="BearMemori", version="0.3.0")

    @app.get("/memories", response_model=list[MemoryResponse])
    def list_memories(
        memory_type: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        return db.list_memories(memory_type=memory_type, tag=tag, limit=limit, offset=offset)

    @app.get("/memories/{memory_id}", response_model=MemoryResponse)
    def get_memory(memory_id: str):
        memory = db.get(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        return memory

    @app.post("/memories", response_model=MemoryResponse, status_code=201)
    def create_memory(body: MemoryCreate):
        memory = Memory(
            id=str(uuid.uuid4()),
            content=body.content,
            raw_input=body.raw_input or body.content,
            memory_type=body.memory_type,
            tags=body.tags,
            source=body.source,
            metadata=body.metadata,
        )
        db.create(memory)
        return memory

    @app.put("/memories/{memory_id}", response_model=MemoryResponse)
    def update_memory(memory_id: str, body: MemoryUpdate):
        memory = db.get(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        if body.content is not None:
            memory.content = body.content
        if body.memory_type is not None:
            memory.memory_type = body.memory_type
        if body.tags is not None:
            memory.tags = body.tags
        if body.metadata is not None:
            memory.metadata = body.metadata
        db.update(memory)
        return memory

    @app.delete("/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: str):
        memory = db.get(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        db.delete(memory_id)

    @app.post("/memories/search", response_model=list[MemoryResponse])
    def search_memories(body: SearchRequest):
        if body.mode == "keyword":
            return db.search_keyword(body.query, limit=body.limit)
        # semantic and hybrid search added in Task 13
        return db.search_keyword(body.query, limit=body.limit)

    return app
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add bearmemori/api/ tests/test_api.py
git commit -m "feat: add REST API with CRUD and keyword search endpoints"
```

---

### Task 12: Telegram Interface

**Files:**
- Create: `bearmemori/interfaces/__init__.py`
- Create: `bearmemori/interfaces/telegram.py`
- Create: `tests/test_telegram.py`

**Step 1: Write the failing tests**

```python
# tests/test_telegram.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bearmemori.interfaces.telegram import TelegramInterface
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputReceived, SendMessage


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def interface(bus):
    return TelegramInterface(bus=bus, token="fake-token")


@pytest.mark.asyncio
async def test_handle_text_emits_input_received(interface, bus):
    received = []
    bus.on(InputReceived, lambda e: received.append(e))

    update = MagicMock()
    update.effective_chat.id = 12345
    update.message.text = "I like pizza"
    context = MagicMock()

    await interface._handle_text(update, context)

    assert len(received) == 1
    assert received[0].content == "I like pizza"
    assert received[0].input_type == "text"
    assert received[0].source_chat_id == "12345"


@pytest.mark.asyncio
async def test_handle_send_message(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = SendMessage(chat_id="12345", text="Hello back")
    await interface.handle_send_message(event)

    mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello back")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: FAIL - cannot import

**Step 3: Implement TelegramInterface**

```python
# bearmemori/interfaces/__init__.py
```

```python
# bearmemori/interfaces/telegram.py
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputReceived, SendMessage

logger = logging.getLogger(__name__)


class TelegramInterface:
    def __init__(self, bus: EventBus, token: str) -> None:
        self._bus = bus
        self._token = token
        self._app: Application | None = None

    def build(self) -> Application:
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self._app.add_handler(CommandHandler("start", self._handle_start))
        return self._app

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        text = update.message.text
        logger.info("Received text from %s: %s", chat_id, text[:80])

        await self._bus.emit(
            InputReceived(input_type="text", content=text, source_chat_id=chat_id)
        )

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        photo = update.message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        caption = update.message.caption or ""

        logger.info("Received photo from %s", chat_id)

        await self._bus.emit(
            InputReceived(
                input_type="image",
                content={"file_path": file.file_path, "caption": caption},
                source_chat_id=chat_id,
            )
        )

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Welcome to BearMemori. Send me text or images and I will remember them for you."
        )

    async def handle_send_message(self, event: SendMessage) -> None:
        if self._app:
            await self._app.bot.send_message(chat_id=int(event.chat_id), text=event.text)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/interfaces/ tests/test_telegram.py
git commit -m "feat: add Telegram interface with text and photo handling"
```

---

### Task 13: Semantic Search

**Files:**
- Modify: `bearmemori/storage/database.py`
- Modify: `tests/test_storage.py`

**Step 1: Write the failing tests**

Add to `tests/test_storage.py`:

```python
import struct
import numpy as np


def _make_embedding(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def test_search_semantic(db):
    emb1 = _make_embedding([1.0, 0.0, 0.0])
    emb2 = _make_embedding([0.0, 1.0, 0.0])
    emb3 = _make_embedding([0.9, 0.1, 0.0])

    db.create(_make_memory(id="1", content="pizza", embedding=emb1))
    db.create(_make_memory(id="2", content="music", embedding=emb2))
    db.create(_make_memory(id="3", content="pasta", embedding=emb3))

    query_emb = _make_embedding([1.0, 0.0, 0.0])
    results = db.search_semantic(query_emb, limit=2)

    assert len(results) == 2
    assert results[0].id == "1"  # exact match first
    assert results[1].id == "3"  # close second
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_storage.py::test_search_semantic -v`
Expected: FAIL - no search_semantic method

**Step 3: Implement semantic search**

Add to `MemoryDatabase` class in `bearmemori/storage/database.py`:

```python
import struct
import numpy as np

    def search_semantic(self, query_embedding: bytes, limit: int = 20) -> list[Memory]:
        rows = self._conn.execute("SELECT * FROM memories WHERE embedding IS NOT NULL").fetchall()
        if not rows:
            return []

        query_vec = np.array(struct.unpack(f"{len(query_embedding) // 4}f", query_embedding))
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        scored = []
        for row in rows:
            emb = row["embedding"]
            vec = np.array(struct.unpack(f"{len(emb) // 4}f", emb))
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            similarity = np.dot(query_vec, vec) / (query_norm * norm)
            scored.append((similarity, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._row_to_memory(row) for _, row in scored[:limit]]
```

Also add the `import struct` and `import numpy as np` to the top of `database.py`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_storage.py
git commit -m "feat: add semantic search with cosine similarity"
```

---

### Task 14: Wire Up the Application

**Files:**
- Create: `bearmemori/app.py`
- Create: `tests/test_app.py`

**Step 1: Write the failing test**

```python
# tests/test_app.py
import pytest
from bearmemori.app import create_application
from bearmemori.config import Settings


@pytest.fixture
def settings():
    return Settings(
        telegram_bot_token="fake-token",
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
        database_path=":memory:",
    )


def test_create_application(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    app = create_application(settings)
    assert app.bus is not None
    assert app.db is not None
    assert app.processor is not None
    assert app.queue_manager is not None
    assert app.followup_manager is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py -v`
Expected: FAIL - cannot import

**Step 3: Implement application wiring**

```python
# bearmemori/app.py
import asyncio
import logging

from bearmemori.config import Settings
from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, InputReceived, SendMessage
from bearmemori.interfaces.telegram import TelegramInterface
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase

logger = logging.getLogger(__name__)


class Application:
    def __init__(
        self,
        bus: EventBus,
        db: MemoryDatabase,
        queue_manager: QueueManager,
        processor: Processor,
        followup_manager: FollowUpManager,
        telegram: TelegramInterface,
        settings: Settings,
    ) -> None:
        self.bus = bus
        self.db = db
        self.queue_manager = queue_manager
        self.processor = processor
        self.followup_manager = followup_manager
        self.telegram = telegram
        self.settings = settings


def create_application(settings: Settings) -> Application:
    bus = EventBus()

    db = MemoryDatabase(settings.database_path)
    db.initialize()

    llm = LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    queue_manager = QueueManager(bus, max_size=settings.queue_max_size)
    processor = Processor(bus=bus, llm=llm, db=db, embedding_model=settings.embedding_model)
    followup_manager = FollowUpManager(bus)
    telegram = TelegramInterface(bus=bus, token=settings.telegram_bot_token)

    # Wire events
    bus.on(InputReceived, queue_manager.handle_input)
    bus.on(FollowUpRequired, followup_manager.handle_followup_required)
    bus.on(SendMessage, telegram.handle_send_message)

    return Application(
        bus=bus,
        db=db,
        queue_manager=queue_manager,
        processor=processor,
        followup_manager=followup_manager,
        telegram=telegram,
        settings=settings,
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/app.py tests/test_app.py
git commit -m "feat: wire up application with event bus connections"
```

---

### Task 15: Main Entry Point and Processing Loop

**Files:**
- Create: `bearmemori/__main__.py`

**Step 1: Implement the entry point**

```python
# bearmemori/__main__.py
import asyncio
import logging
import uvicorn

from bearmemori.api.routes import create_app as create_api
from bearmemori.app import create_application
from bearmemori.config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def processing_loop(application) -> None:
    logger.info("Processing loop started")
    while True:
        item = await application.queue_manager.get_next()
        try:
            # Check if this is a follow-up response
            followup_input = application.followup_manager.check_followup(
                type("FakeEvent", (), {
                    "source_chat_id": item.source_chat_id,
                    "input_type": item.input_type,
                    "content": item.content,
                })()
            )
            if followup_input:
                item.context = followup_input.context

            await application.processor.process_item(item)
        except Exception:
            logger.exception("Error processing item from %s", item.source_chat_id)


async def main() -> None:
    settings = Settings()
    application = create_application(settings)

    api = create_api(application.db)

    telegram_app = application.telegram.build()

    # Start processing loop
    asyncio.create_task(processing_loop(application))

    # Start API server
    config = uvicorn.Config(api, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    # Run telegram and API concurrently
    async with telegram_app:
        await telegram_app.start()
        await telegram_app.updater.start_polling()
        logger.info("BearMemori is running")

        await server.serve()

        await telegram_app.updater.stop()
        await telegram_app.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Verify the module runs (syntax check only, no real connections)**

Run: `uv run python -c "from bearmemori.__main__ import main; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add bearmemori/__main__.py
git commit -m "feat: add main entry point with processing loop"
```

---

### Task 16: Integration Test - Full Event Flow

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_integration.py
import json
import pytest
from unittest.mock import AsyncMock
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import (
    FollowUpRequired,
    InputReceived,
    MemoryStored,
    SendMessage,
)
from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
from bearmemori.llm.client import ClassificationResult, ExtractionResult
from bearmemori.storage.database import MemoryDatabase


@pytest.fixture
def db(tmp_path):
    database = MemoryDatabase(str(tmp_path / "test.db"))
    database.initialize()
    return database


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def wired_system(db, mock_llm):
    bus = EventBus()
    queue = QueueManager(bus, max_size=100)
    processor = Processor(bus=bus, llm=mock_llm, db=db, embedding_model="test")
    followup = FollowUpManager(bus)

    bus.on(InputReceived, queue.handle_input)
    bus.on(FollowUpRequired, followup.handle_followup_required)

    return {"bus": bus, "queue": queue, "processor": processor, "followup": followup}


@pytest.mark.asyncio
async def test_full_store_flow(wired_system, mock_llm, db):
    bus = wired_system["bus"]
    queue = wired_system["queue"]
    processor = wired_system["processor"]

    stored = []
    bus.on(MemoryStored, lambda e: stored.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", memory_type="preference", confidence=0.95
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="User likes dark mode", memory_type="preference", tags=["ui"]
    )
    mock_llm.get_embedding.return_value = [0.1, 0.2, 0.3]

    # Simulate input
    await bus.emit(InputReceived(input_type="text", content="I like dark mode", source_chat_id="42"))

    # Process the queued item
    item = await queue.get_next()
    await processor.process_item(item)

    assert len(stored) == 1
    assert stored[0].content == "User likes dark mode"

    # Verify it's in the database
    memories = db.list_memories()
    assert len(memories) == 1
    assert memories[0].content == "User likes dark mode"


@pytest.mark.asyncio
async def test_followup_flow(wired_system, mock_llm, db):
    bus = wired_system["bus"]
    queue = wired_system["queue"]
    processor = wired_system["processor"]
    followup = wired_system["followup"]

    sent = []
    bus.on(SendMessage, lambda e: sent.append(e))

    # First input: LLM needs clarification
    mock_llm.classify_input.return_value = ClassificationResult(
        action="followup", question="What changed?"
    )
    mock_llm.generate_followup.return_value = "Can you be more specific about what changed?"

    await bus.emit(InputReceived(input_type="text", content="something changed", source_chat_id="42"))
    item = await queue.get_next()
    await processor.process_item(item)

    assert len(sent) == 1
    assert followup.has_active_followup("42")

    # Second input: follow-up response
    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", memory_type="fact", confidence=0.9
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Theme changed to dark mode", memory_type="fact", tags=["ui"]
    )
    mock_llm.get_embedding.return_value = [0.1, 0.2]

    # Simulate follow-up input
    followup_event = InputReceived(
        input_type="text", content="the theme changed to dark mode", source_chat_id="42"
    )
    checked = followup.check_followup(followup_event)
    assert checked is not None
    assert checked.context is not None

    await bus.emit(checked)
    item = await queue.get_next()
    await processor.process_item(item)

    memories = db.list_memories()
    assert len(memories) == 1
```

**Step 2: Run integration tests**

Run: `uv run pytest tests/test_integration.py -v`
Expected: all PASS

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

**Step 4: Run linter**

Run: `uv run ruff check .`
Expected: no errors (fix any that appear)

**Step 5: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: add integration tests for full event flow"
```

---

### Task 17: Final Cleanup

**Step 1: Run full test suite and linter**

Run: `uv run pytest -v && uv run ruff check .`
Expected: all PASS, no lint errors

**Step 2: Fix any issues found**

**Step 3: Final commit if needed**
