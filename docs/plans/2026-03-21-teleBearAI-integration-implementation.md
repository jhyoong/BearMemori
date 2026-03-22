# teleBearAI Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adapt BearMemori to be a drop-in replacement for teleBearAI's memory microservice.

**Architecture:** Replace BearMemori's current storage, model, and API layers to match teleBearAI's contract exactly. Add ChromaDB for vector search, a pending store for HITL, a triage subagent, and hybrid retrieval. Keep the existing classify/extract pipeline for BearMemori's own Telegram interface.

**Tech Stack:** Python 3.12, FastAPI, ChromaDB, sentence-transformers, SQLite, pydantic-settings, openai SDK

---

### Task 1: Update Dependencies

**Files:**
- Modify: `pyproject.toml:1-21`

**Step 1: Update pyproject.toml**

Replace `numpy>=2.2` with `chromadb` and `sentence-transformers`:

```toml
[project]
name = "bearmemori"
version = "0.4.0"
description = "Personal memory store with LLM processing"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "python-telegram-bot>=21",
    "openai>=1.60",
    "pydantic-settings>=2.7",
    "chromadb>=0.6",
    "sentence-transformers>=3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.25",
    "httpx>=0.28",
    "ruff>=0.9",
]
```

**Step 2: Install updated dependencies**

Run: `pip install -e ".[dev]"`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: swap numpy for chromadb and sentence-transformers"
```

---

### Task 2: Update Config

**Files:**
- Modify: `bearmemori/config.py:1-16`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Step 1: Write failing test**

Add tests for new config fields in `tests/test_config.py`:

```python
def test_new_settings_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    s = Settings()
    assert s.chroma_persist_dir == "chroma_data"
    assert s.embedding_model == "all-MiniLM-L6-v2"
    assert s.pending_ttl_seconds == 86400
    assert s.retrieval_top_k == 5
    assert s.upcoming_events_days == 7
    assert s.api_port == 8100
    assert s.llm_api_key == "not-needed"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_new_settings_defaults -v`
Expected: FAIL (attributes don't exist yet)

**Step 3: Update config.py**

Replace the entire `Settings` class in `bearmemori/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    telegram_bot_token: str
    telegram_allowed_user_id: int
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3"
    llm_api_key: str = "not-needed"
    embedding_model: str = "all-MiniLM-L6-v2"
    database_path: str = "bearmemori.db"
    chroma_persist_dir: str = "chroma_data"
    pending_ttl_seconds: int = 86400
    queue_max_size: int = 1000
    followup_timeout_hours: int = 24
    reminder_poll_interval_seconds: int = 60
    retrieval_top_k: int = 5
    upcoming_events_days: int = 7
    api_port: int = 8100
```

**Step 4: Update .env.example** to document all new settings.

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

**Step 6: Fix any broken existing config tests** that reference old defaults (e.g., `embedding_model` was `nomic-embed-text`).

**Step 7: Commit**

```bash
git add bearmemori/config.py .env.example tests/test_config.py
git commit -m "feat: add new config settings for ChromaDB, pending store, retrieval"
```

---

### Task 3: Update Memory Model and Schemas

**Files:**
- Modify: `bearmemori/storage/models.py:1-18`
- Modify: `bearmemori/api/schemas.py:1-50`
- Test: `tests/test_models.py` (new)

**Step 1: Write failing test**

Create `tests/test_models.py`:

```python
from bearmemori.storage.models import (
    MemoryCategory,
    EventFields,
    MemorySource,
    MemoryDraft,
    MemoryRecord,
    PendingMemory,
)


def test_memory_category_values():
    assert MemoryCategory.PROFILE == "profile"
    assert MemoryCategory.GENERAL == "general"
    assert MemoryCategory.EVENT == "event"
    assert MemoryCategory.LOCATION == "location"
    assert MemoryCategory.TASK == "task"
    assert MemoryCategory.REMINDER == "reminder"


def test_memory_draft_creation():
    draft = MemoryDraft(
        category=MemoryCategory.PROFILE,
        title="Likes coffee",
        content="User prefers black coffee in the morning",
        tags=["preference", "coffee"],
    )
    assert draft.title == "Likes coffee"
    assert draft.event_fields is None
    assert draft.source is None


def test_memory_record_from_draft():
    draft = MemoryDraft(
        category=MemoryCategory.EVENT,
        title="Dentist appointment",
        content="Dentist at 2pm on Friday",
        event_fields=EventFields(datetime="2026-03-25T14:00:00"),
        tags=["health"],
    )
    record = MemoryRecord.from_draft(draft, record_id="mem_abc123")
    assert record.id == "mem_abc123"
    assert record.category == MemoryCategory.EVENT
    assert record.title == "Dentist appointment"
    assert record.event_fields.datetime == "2026-03-25T14:00:00"
    assert record.event_fields.status == "pending"
    assert record.created_at is not None


def test_pending_memory_creation():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    pm = PendingMemory(
        pending_id="pend_abc123",
        draft=draft,
        ttl_seconds=3600,
    )
    assert pm.pending_id == "pend_abc123"
    assert pm.ttl_seconds == 3600
    assert pm.created_at is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL (imports don't exist)

**Step 3: Rewrite bearmemori/storage/models.py**

Replace with models matching teleBearAI's schemas, extended with our 6 categories:

```python
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    PROFILE = "profile"
    GENERAL = "general"
    EVENT = "event"
    LOCATION = "location"
    TASK = "task"
    REMINDER = "reminder"


class MemorySource(BaseModel):
    platform: str
    chat_id: str
    message_ids: list[str] = Field(default_factory=list)


class EventFields(BaseModel):
    datetime: str  # ISO 8601 string
    status: str = "pending"
    recurrence: str | None = None


class MemoryDraft(BaseModel):
    category: MemoryCategory
    title: str
    content: str
    event_fields: EventFields | None = None
    tags: list[str] = Field(default_factory=list)
    source: MemorySource | None = None


class MemoryRecord(BaseModel):
    id: str
    category: MemoryCategory
    title: str
    content: str
    created_at: datetime
    raw_input: str = ""
    event_fields: EventFields | None = None
    tags: list[str] = Field(default_factory=list)
    source: MemorySource | None = None
    metadata: dict = Field(default_factory=dict)

    @classmethod
    def from_draft(cls, draft: MemoryDraft, record_id: str) -> MemoryRecord:
        return cls(
            id=record_id,
            category=draft.category,
            title=draft.title,
            content=draft.content,
            created_at=datetime.now(timezone.utc),
            event_fields=draft.event_fields,
            tags=draft.tags,
            source=draft.source,
        )


class PendingMemory(BaseModel):
    pending_id: str
    draft: MemoryDraft
    ttl_seconds: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Step 4: Update bearmemori/api/schemas.py**

Replace entirely to match new models. These schemas are used for API request/response serialization:

```python
from pydantic import BaseModel, Field

from bearmemori.storage.models import MemoryCategory


class TriageRequest(BaseModel):
    conversation: list[dict] = Field(min_length=1)
    memory_hint: dict | None = None


class ConfirmRequest(BaseModel):
    pending_id: str


class SearchRequest(BaseModel):
    query: str
    category: str | None = None
    top_k: int = 5
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/storage/models.py bearmemori/api/schemas.py tests/test_models.py
git commit -m "feat: rewrite memory model with categories, event fields, and HITL types"
```

---

### Task 4: Rewrite SQLite Database Layer

**Files:**
- Modify: `bearmemori/storage/database.py:1-203`
- Test: `tests/test_storage.py` (rewrite)

**Step 1: Write failing tests**

Rewrite `tests/test_storage.py` for the new schema. Key tests to include:

```python
import pytest
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    MemoryRecord,
    MemoryCategory,
    EventFields,
    MemorySource,
)
from datetime import datetime, timezone, timedelta


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _make_record(**overrides) -> MemoryRecord:
    defaults = dict(
        id="mem_test1",
        category=MemoryCategory.PROFILE,
        title="Test memory",
        content="Test content",
        created_at=datetime.now(timezone.utc),
        tags=["test"],
    )
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def test_create_and_get(db):
    record = _make_record()
    db.create(record)
    result = db.get("mem_test1")
    assert result is not None
    assert result.id == "mem_test1"
    assert result.category == MemoryCategory.PROFILE
    assert result.title == "Test memory"


def test_get_nonexistent(db):
    assert db.get("nonexistent") is None


def test_delete(db):
    db.create(_make_record())
    assert db.delete("mem_test1") is True
    assert db.get("mem_test1") is None


def test_delete_nonexistent(db):
    assert db.delete("nonexistent") is False


def test_list_all(db):
    db.create(_make_record(id="mem_1"))
    db.create(_make_record(id="mem_2", category=MemoryCategory.GENERAL))
    result = db.list_all()
    assert len(result) == 2


def test_list_by_category(db):
    db.create(_make_record(id="mem_1", category=MemoryCategory.PROFILE))
    db.create(_make_record(id="mem_2", category=MemoryCategory.EVENT))
    result = db.list_by_category(MemoryCategory.PROFILE)
    assert len(result) == 1
    assert result[0].id == "mem_1"


def test_event_fields_roundtrip(db):
    record = _make_record(
        category=MemoryCategory.EVENT,
        event_fields=EventFields(
            datetime="2026-03-25T14:00:00",
            status="pending",
            recurrence="weekly",
        ),
    )
    db.create(record)
    result = db.get("mem_test1")
    assert result.event_fields is not None
    assert result.event_fields.datetime == "2026-03-25T14:00:00"
    assert result.event_fields.recurrence == "weekly"


def test_source_roundtrip(db):
    record = _make_record(
        source=MemorySource(platform="telegram", chat_id="123", message_ids=["msg1"]),
    )
    db.create(record)
    result = db.get("mem_test1")
    assert result.source is not None
    assert result.source.platform == "telegram"
    assert result.source.chat_id == "123"


def test_upcoming_events(db):
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=2)).isoformat()
    past = (now - timedelta(days=2)).isoformat()

    db.create(_make_record(
        id="mem_future",
        category=MemoryCategory.EVENT,
        event_fields=EventFields(datetime=future, status="pending"),
    ))
    db.create(_make_record(
        id="mem_past",
        category=MemoryCategory.EVENT,
        event_fields=EventFields(datetime=past, status="pending"),
    ))
    results = db.get_upcoming_events(days=7)
    assert len(results) == 1
    assert results[0].id == "mem_future"


def test_keyword_search(db):
    db.create(_make_record(id="mem_1", title="Coffee preference", content="Likes black coffee"))
    db.create(_make_record(id="mem_2", title="Tea preference", content="Likes green tea"))
    results = db.search_keyword("coffee")
    assert len(results) >= 1
    assert any(r.id == "mem_1" for r in results)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL

**Step 3: Rewrite bearmemori/storage/database.py**

Replace with new schema. Key changes:
- Remove `embedding` column, `memory_type`, `remind_at`, `recurring_minutes`
- Add `category`, `title`, `event_datetime`, `event_status`, `event_recurrence`
- Change `source` from plain string to JSON
- Add `updated_at` and `metadata` columns
- Add FTS5 on `content`, `tags`, and `title`
- Add `list_all()`, `list_by_category()`, `get_upcoming_events()` methods
- Remove `search_semantic()` (moved to ChromaDB)
- `delete()` returns `bool`

```python
import json
import sqlite3
from datetime import datetime, timezone, timedelta

from bearmemori.storage.models import (
    MemoryRecord,
    MemoryCategory,
    EventFields,
    MemorySource,
)


class MemoryDatabase:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                raw_input TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                source TEXT,
                event_datetime TEXT,
                event_status TEXT,
                event_recurrence TEXT,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category
            ON memories (category)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_event_datetime
            ON memories (event_datetime)
            WHERE event_datetime IS NOT NULL
        """)
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(title, content, tags, content=memories, content_rowid=rowid)
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, title, content, tags)
                VALUES (new.rowid, new.title, new.content, new.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, content, tags)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, content, tags)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags);
                INSERT INTO memories_fts(rowid, title, content, tags)
                VALUES (new.rowid, new.title, new.content, new.tags);
            END
        """)
        self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        event_fields = None
        if row["event_datetime"] is not None:
            event_fields = EventFields(
                datetime=row["event_datetime"],
                status=row["event_status"] or "pending",
                recurrence=row["event_recurrence"],
            )

        source = None
        if row["source"] is not None:
            source = MemorySource.model_validate_json(row["source"])

        return MemoryRecord(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            title=row["title"],
            content=row["content"],
            raw_input=row["raw_input"],
            created_at=datetime.fromisoformat(row["created_at"]),
            event_fields=event_fields,
            tags=json.loads(row["tags"]),
            source=source,
            metadata=json.loads(row["metadata"]),
        )

    def create(self, record: MemoryRecord) -> None:
        event_dt = None
        event_status = None
        event_recurrence = None
        if record.event_fields:
            event_dt = record.event_fields.datetime
            event_status = record.event_fields.status
            event_recurrence = record.event_fields.recurrence

        source_json = record.source.model_dump_json() if record.source else None
        now = datetime.now(timezone.utc).isoformat()

        self._conn.execute(
            """INSERT INTO memories
               (id, category, title, content, raw_input, created_at, updated_at,
                tags, source, event_datetime, event_status, event_recurrence, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.id,
                record.category.value,
                record.title,
                record.content,
                record.raw_input,
                record.created_at.isoformat(),
                now,
                json.dumps(record.tags),
                source_json,
                event_dt,
                event_status,
                event_recurrence,
                json.dumps(record.metadata),
            ),
        )
        self._conn.commit()

    def get(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (record_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def delete(self, record_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM memories WHERE id = ?", (record_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list_all(self) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_by_category(self, category: MemoryCategory) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC",
            (category.value,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def search_keyword(self, query: str, limit: int = 20) -> list[MemoryRecord]:
        rows = self._conn.execute(
            """SELECT memories.* FROM memories_fts
               JOIN memories ON memories.rowid = memories_fts.rowid
               WHERE memories_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_upcoming_events(self, days: int = 7) -> list[MemoryRecord]:
        now = datetime.now(timezone.utc).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT * FROM memories
               WHERE category IN ('event', 'reminder', 'task')
                 AND event_datetime IS NOT NULL
                 AND event_datetime >= ?
                 AND event_datetime <= ?
                 AND (event_status IS NULL OR event_status = 'pending')
               ORDER BY event_datetime ASC""",
            (now, future),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_storage.py
git commit -m "feat: rewrite database layer for new schema with categories and event fields"
```

---

### Task 5: Add VectorStore (ChromaDB)

**Files:**
- Create: `bearmemori/storage/vector_store.py`
- Test: `tests/test_vector_store.py` (new)

**Step 1: Write failing test**

Create `tests/test_vector_store.py`:

```python
import pytest
from bearmemori.storage.vector_store import VectorStore
from bearmemori.storage.models import MemoryRecord, MemoryCategory, EventFields
from datetime import datetime, timezone


@pytest.fixture
def store(tmp_path):
    vs = VectorStore(persist_dir=str(tmp_path / "chroma"))
    vs.init()
    return vs


def _make_record(**overrides) -> MemoryRecord:
    defaults = dict(
        id="mem_test1",
        category=MemoryCategory.PROFILE,
        title="Coffee preference",
        content="User likes black coffee",
        created_at=datetime.now(timezone.utc),
        tags=["coffee"],
    )
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def test_add_and_search(store):
    store.add(_make_record())
    results = store.search("coffee", top_k=5)
    assert len(results) >= 1
    assert results[0]["id"] == "mem_test1"


def test_search_with_category_filter(store):
    store.add(_make_record(id="mem_1", category=MemoryCategory.PROFILE))
    store.add(_make_record(id="mem_2", category=MemoryCategory.EVENT, title="Meeting", content="Team meeting"))
    results = store.search("meeting", top_k=5, category="event")
    assert all(r["metadata"]["category"] == "event" for r in results)


def test_delete(store):
    store.add(_make_record())
    store.delete("mem_test1")
    results = store.search("coffee", top_k=5)
    assert not any(r["id"] == "mem_test1" for r in results)


def test_event_metadata(store):
    record = _make_record(
        category=MemoryCategory.EVENT,
        event_fields=EventFields(datetime="2026-03-25T14:00:00"),
    )
    store.add(record)
    results = store.search("coffee", top_k=5)
    assert results[0]["metadata"]["event_datetime"] == "2026-03-25T14:00:00"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vector_store.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Create bearmemori/storage/vector_store.py**

```python
import chromadb
from chromadb.utils import embedding_functions

from bearmemori.storage.models import MemoryRecord


class VectorStore:
    def __init__(self, persist_dir: str | None = None, embedding_model: str = "all-MiniLM-L6-v2"):
        self._persist_dir = persist_dir
        self._embedding_model = embedding_model
        self._collection = None

    def init(self) -> None:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self._embedding_model
        )
        if self._persist_dir:
            client = chromadb.PersistentClient(path=self._persist_dir)
        else:
            client = chromadb.EphemeralClient()
        self._collection = client.get_or_create_collection(
            name="memories",
            embedding_function=ef,
        )

    def add(self, record: MemoryRecord) -> None:
        text = f"{record.title}: {record.content}"
        metadata = {
            "category": record.category.value,
            "created_at": record.created_at.isoformat(),
        }
        if record.event_fields:
            metadata["event_datetime"] = record.event_fields.datetime
        self._collection.upsert(
            ids=[record.id],
            documents=[text],
            metadatas=[metadata],
        )

    def delete(self, record_id: str) -> None:
        self._collection.delete(ids=[record_id])

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict]:
        where = None
        if category:
            where = {"category": category}

        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
        )

        items = []
        if results["ids"] and results["ids"][0]:
            for i, id_ in enumerate(results["ids"][0]):
                items.append({
                    "id": id_,
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                })
        return items
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_vector_store.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/vector_store.py tests/test_vector_store.py
git commit -m "feat: add ChromaDB vector store for semantic search"
```

---

### Task 6: Add PendingStore

**Files:**
- Create: `bearmemori/storage/pending_store.py`
- Test: `tests/test_pending_store.py` (new)

**Step 1: Write failing test**

Create `tests/test_pending_store.py`:

```python
import time
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.models import MemoryDraft, MemoryCategory


def _make_draft(**overrides) -> MemoryDraft:
    defaults = dict(
        category=MemoryCategory.PROFILE,
        title="Test",
        content="Test content",
    )
    defaults.update(overrides)
    return MemoryDraft(**defaults)


def test_add_and_get():
    store = PendingStore()
    pid = store.add(_make_draft())
    assert pid.startswith("pend_")
    result = store.get(pid)
    assert result is not None
    assert result.draft.title == "Test"


def test_remove():
    store = PendingStore()
    pid = store.add(_make_draft())
    assert store.remove(pid) is True
    assert store.get(pid) is None


def test_remove_nonexistent():
    store = PendingStore()
    assert store.remove("nonexistent") is False


def test_expiry():
    store = PendingStore(default_ttl=1)
    pid = store.add(_make_draft())
    time.sleep(1.1)
    assert store.get(pid) is None


def test_cleanup():
    store = PendingStore(default_ttl=1)
    store.add(_make_draft())
    store.add(_make_draft())
    time.sleep(1.1)
    removed = store.cleanup()
    assert removed == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pending_store.py -v`
Expected: FAIL

**Step 3: Create bearmemori/storage/pending_store.py**

```python
import uuid
from datetime import datetime, timezone

from bearmemori.storage.models import MemoryDraft, PendingMemory


class PendingStore:
    def __init__(self, default_ttl: int = 86400):
        self._store: dict[str, PendingMemory] = {}
        self._default_ttl = default_ttl

    def add(self, draft: MemoryDraft, ttl: int | None = None) -> str:
        pending_id = f"pend_{uuid.uuid4().hex[:12]}"
        ttl_seconds = ttl if ttl is not None else self._default_ttl
        self._store[pending_id] = PendingMemory(
            pending_id=pending_id,
            draft=draft,
            ttl_seconds=ttl_seconds,
        )
        return pending_id

    def get(self, pending_id: str) -> PendingMemory | None:
        item = self._store.get(pending_id)
        if item is None:
            return None
        if self._is_expired(item):
            del self._store[pending_id]
            return None
        return item

    def remove(self, pending_id: str) -> bool:
        if pending_id in self._store:
            del self._store[pending_id]
            return True
        return False

    def cleanup(self) -> int:
        expired = [
            pid for pid, item in self._store.items() if self._is_expired(item)
        ]
        for pid in expired:
            del self._store[pid]
        return len(expired)

    def _is_expired(self, item: PendingMemory) -> bool:
        now = datetime.now(timezone.utc)
        elapsed = (now - item.created_at).total_seconds()
        return elapsed >= item.ttl_seconds
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pending_store.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/pending_store.py tests/test_pending_store.py
git commit -m "feat: add PendingStore for HITL memory confirmation flow"
```

---

### Task 7: Add Triage Subagent

**Files:**
- Create: `bearmemori/core/triage.py`
- Modify: `bearmemori/llm/client.py` (add `run_triage` method)
- Test: `tests/test_triage.py` (new)

**Step 1: Write failing test**

Create `tests/test_triage.py`:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from bearmemori.core.triage import run_triage, TriageResult
from bearmemori.storage.models import MemoryCategory


@pytest.fixture
def mock_llm_response():
    def _make(data):
        mock = AsyncMock()
        mock.return_value.choices = [
            type("Choice", (), {"message": type("Msg", (), {"content": json.dumps(data)})()})()
        ]
        return mock
    return _make


@pytest.mark.asyncio
async def test_triage_should_save(mock_llm_response):
    response_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "event_fields": None,
    }
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps(response_data)}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "I love black coffee"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.PROFILE


@pytest.mark.asyncio
async def test_triage_should_not_save():
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps({"should_save": False})}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "Hello"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is False
    assert result.draft is None


@pytest.mark.asyncio
async def test_triage_malformed_response():
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": "not json"}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "test"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_triage.py -v`
Expected: FAIL

**Step 3: Create bearmemori/core/triage.py**

Model this closely on teleBearAI's `services/memory/app/subagents/triage.py`, but extended with 6 categories and parameterized LLM config:

```python
import json
import logging
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from bearmemori.storage.models import MemoryDraft, MemoryCategory, EventFields

logger = logging.getLogger(__name__)

TRIAGE_SYSTEM_PROMPT = """\
You are a memory triage agent. Given a conversation, decide if any information \
is worth saving as a long-term memory.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

Respond with valid JSON only. If the conversation contains memory-worthy information:
{
  "should_save": true,
  "category": "profile|general|event|location|task|reminder",
  "title": "Short descriptive title",
  "content": "The key information to remember",
  "tags": ["tag1", "tag2"],
  "event_fields": null or {"datetime": "ISO 8601", "status": "pending", "recurrence": null}
}

If nothing is worth saving:
{"should_save": false}

Be selective. Only save genuinely useful, specific information. Do not save:
- Greetings or small talk
- Questions without answers
- Temporary or trivial information
"""


@dataclass
class TriageResult:
    should_save: bool
    draft: MemoryDraft | None = None


async def _llm_call(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
) -> dict:
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    ) as client:
        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 512,
            },
        )
        response.raise_for_status()
        return response.json()


async def run_triage(
    conversation: list[dict],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    memory_hint: dict | None = None,
) -> TriageResult:
    hint_text = ""
    if memory_hint:
        hint_text = f"\n\nMemory hint from chatbot: {json.dumps(memory_hint)}"

    try:
        conv_text = "\n".join(
            f"{msg['role'].upper()}: {msg.get('content', '')}"
            for msg in conversation[-10:]
        )
    except (KeyError, AttributeError) as e:
        logger.warning("Malformed conversation item: %s", e)
        return TriageResult(should_save=False)

    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Conversation:\n{conv_text}{hint_text}"},
    ]

    try:
        response = await _llm_call(messages, llm_base_url, llm_api_key, llm_model)
        raw = response["choices"][0]["message"]["content"]
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Triage LLM returned unparseable output: %s", e)
        return TriageResult(should_save=False)
    except httpx.HTTPError as e:
        logger.error("Triage LLM call failed: %s", e)
        return TriageResult(should_save=False)

    if not data.get("should_save", False):
        return TriageResult(should_save=False)

    try:
        event_fields = None
        if data.get("event_fields"):
            event_fields = EventFields(**data["event_fields"])

        draft = MemoryDraft(
            category=MemoryCategory(data["category"]),
            title=data["title"],
            content=data["content"],
            tags=data.get("tags", []),
            event_fields=event_fields,
        )
        return TriageResult(should_save=True, draft=draft)
    except (ValueError, KeyError, ValidationError) as e:
        logger.warning("Triage produced invalid draft: %s", e)
        return TriageResult(should_save=False)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_triage.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/core/triage.py tests/test_triage.py
git commit -m "feat: add triage subagent for conversation-based memory proposals"
```

---

### Task 8: Rewrite API Routes

**Files:**
- Modify: `bearmemori/api/routes.py:1-87`
- Test: `tests/test_api.py` (rewrite)

This is the largest task. The API must match teleBearAI's endpoint contract exactly.

**Step 1: Write failing tests**

Rewrite `tests/test_api.py`. Key tests to cover every endpoint:

```python
import json
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    MemoryRecord,
    MemoryCategory,
    MemoryDraft,
    EventFields,
)
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore
from datetime import datetime, timezone


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


@pytest.fixture
def vector_store(tmp_path):
    vs = VectorStore(persist_dir=str(tmp_path / "chroma"))
    vs.init()
    return vs


@pytest.fixture
def pending_store():
    return PendingStore()


@pytest.fixture
def client(db, vector_store, pending_store):
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="test",
        llm_model="test",
    )
    return TestClient(app)


def _seed_memory(db, vector_store, **overrides):
    defaults = dict(
        id="mem_test1",
        category=MemoryCategory.PROFILE,
        title="Coffee preference",
        content="User likes black coffee",
        created_at=datetime.now(timezone.utc),
        tags=["coffee"],
    )
    defaults.update(overrides)
    record = MemoryRecord(**defaults)
    db.create(record)
    vector_store.add(record)
    return record


# --- Health ---

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200


# --- List ---

def test_list_memories(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.get("/memory/list")
    assert r.status_code == 200
    assert len(r.json()["memories"]) == 1


def test_list_by_category(client, db, vector_store):
    _seed_memory(db, vector_store, id="mem_1", category=MemoryCategory.PROFILE)
    _seed_memory(db, vector_store, id="mem_2", category=MemoryCategory.EVENT)
    r = client.get("/memory/list?category=profile")
    assert len(r.json()["memories"]) == 1


# --- Get ---

def test_get_memory(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.get("/memory/mem_test1")
    assert r.status_code == 200
    assert r.json()["title"] == "Coffee preference"


def test_get_nonexistent(client):
    r = client.get("/memory/nonexistent")
    assert r.status_code == 404


# --- Delete ---

def test_delete_memory(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.delete("/memory/mem_test1")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


# --- Search ---

def test_search(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.post("/memory/search", json={"query": "coffee", "top_k": 5})
    assert r.status_code == 200
    assert "results" in r.json()


# --- Pending / Confirm / Dismiss ---

def test_pending_confirm_flow(client, pending_store):
    draft = {
        "category": "profile",
        "title": "Likes tea",
        "content": "User likes green tea",
        "tags": ["tea"],
    }
    # Create pending
    r = client.post("/memory/pending", json=draft)
    assert r.status_code == 200
    pending_id = r.json()["pending_id"]

    # Confirm
    r = client.post("/memory/confirm", json={"pending_id": pending_id})
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    # Verify it's in permanent storage
    record_id = r.json()["record_id"]
    r = client.get(f"/memory/{record_id}")
    assert r.status_code == 200


def test_dismiss_pending(client, pending_store):
    draft = {"category": "general", "title": "Test", "content": "Test"}
    r = client.post("/memory/pending", json=draft)
    pending_id = r.json()["pending_id"]

    r = client.delete(f"/memory/pending/{pending_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"


# --- Triage ---

def test_triage_endpoint(client):
    triage_response = {
        "should_save": True,
        "category": "profile",
        "title": "Coffee",
        "content": "Likes coffee",
        "tags": [],
        "event_fields": None,
    }
    with patch(
        "bearmemori.api.routes.run_triage",
    ) as mock_triage:
        from bearmemori.core.triage import TriageResult
        mock_triage.return_value = TriageResult(
            should_save=True,
            draft=MemoryDraft(
                category=MemoryCategory.PROFILE,
                title="Coffee",
                content="Likes coffee",
            ),
        )
        r = client.post(
            "/memory/triage",
            json={"conversation": [{"role": "user", "content": "I love coffee"}]},
        )
    assert r.status_code == 200
    assert r.json()["should_save"] is True
    assert "pending_id" in r.json()


# --- Retrieve ---

def test_retrieve(client, db, vector_store):
    _seed_memory(db, vector_store)
    r = client.get("/memory/retrieve?query_context=coffee")
    assert r.status_code == 200
    assert "context_block" in r.json()


# --- Upcoming Events ---

def test_upcoming_events(client, db, vector_store):
    from datetime import timedelta
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    _seed_memory(
        db, vector_store,
        id="mem_event",
        category=MemoryCategory.EVENT,
        title="Meeting",
        content="Team meeting",
        event_fields=EventFields(datetime=future, status="pending"),
    )
    r = client.get("/memory/events/upcoming")
    assert r.status_code == 200
    assert len(r.json()["events"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL

**Step 3: Rewrite bearmemori/api/routes.py**

```python
import uuid
import logging

from fastapi import FastAPI, HTTPException

from bearmemori.api.schemas import TriageRequest, ConfirmRequest, SearchRequest
from bearmemori.core.triage import run_triage
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    MemoryCategory,
    MemoryDraft,
    MemoryRecord,
)
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


def create_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    pending_store: PendingStore,
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_model: str = "",
) -> FastAPI:
    app = FastAPI(title="BearMemori", version="0.4.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/memory/triage")
    async def triage_conversation(request: TriageRequest):
        result = await run_triage(
            request.conversation,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            memory_hint=request.memory_hint,
        )
        if not result.should_save or result.draft is None:
            return {"should_save": False}

        pending_id = pending_store.add(result.draft)
        logger.info("Triage proposed memory: %s", pending_id)
        return {
            "should_save": True,
            "pending_id": pending_id,
            "draft": result.draft.model_dump(mode="json"),
        }

    @app.post("/memory/pending")
    def create_pending(draft: MemoryDraft):
        pending_id = pending_store.add(draft)
        logger.info("Created pending memory: %s", pending_id)
        return {"pending_id": pending_id}

    @app.delete("/memory/pending/{pending_id}")
    def dismiss_pending(pending_id: str):
        removed = pending_store.remove(pending_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Pending memory not found")
        logger.info("Dismissed pending memory: %s", pending_id)
        return {"status": "dismissed"}

    @app.post("/memory/confirm")
    def confirm_pending(request: ConfirmRequest):
        pending = pending_store.get(request.pending_id)
        if pending is None:
            raise HTTPException(status_code=404, detail="Pending memory not found or expired")

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(pending.draft, record_id=record_id)

        db.create(record)
        vector_store.add(record)
        pending_store.remove(request.pending_id)

        logger.info("Confirmed memory: %s -> %s", request.pending_id, record_id)
        return {"record_id": record_id, "status": "confirmed"}

    @app.post("/memory/search")
    def search_memories(request: SearchRequest):
        results = vector_store.search(
            query=request.query,
            top_k=request.top_k,
            category=request.category,
        )
        return {"results": results}

    @app.get("/memory/retrieve")
    def retrieve_context(query_context: str, top_k: int = 5, event_days: int = 7):
        semantic_results = vector_store.search(query=query_context, top_k=top_k)
        upcoming_events = db.get_upcoming_events(days=event_days)

        lines = []
        if semantic_results:
            lines.append("## Relevant Memories")
            for r in semantic_results:
                lines.append(f"- {r['document']}")

        if upcoming_events:
            lines.append("\n## Upcoming Events")
            for e in upcoming_events:
                dt = e.event_fields.datetime if e.event_fields else "unknown"
                lines.append(f"- [{dt}] {e.title}: {e.content}")

        context_block = "\n".join(lines) if lines else ""

        items = semantic_results + [
            {"id": e.id, "document": f"{e.title}: {e.content}", "metadata": {"category": e.category.value}}
            for e in upcoming_events
        ]

        return {"context_block": context_block, "items": items}

    @app.get("/memory/events/upcoming")
    def get_upcoming_events(days: int = 7):
        events = db.get_upcoming_events(days=days)
        return {"events": [e.model_dump(mode="json") for e in events]}

    @app.get("/memory/list")
    def list_memories(category: str | None = None):
        if category is not None:
            try:
                cat = MemoryCategory(category)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {category}",
                )
            records = db.list_by_category(cat)
        else:
            records = db.list_all()
        return {"memories": [r.model_dump(mode="json") for r in records]}

    @app.get("/memory/{record_id}")
    def get_memory(record_id: str):
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return record.model_dump(mode="json")

    @app.delete("/memory/{record_id}")
    def delete_memory(record_id: str):
        deleted = db.delete(record_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found")
        vector_store.delete(record_id)
        logger.info("Deleted memory: %s", record_id)
        return {"status": "deleted"}

    return app
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/api/routes.py bearmemori/api/schemas.py tests/test_api.py
git commit -m "feat: rewrite API routes to match teleBearAI memory service contract"
```

---

### Task 9: Update Application Wiring and Entry Point

**Files:**
- Modify: `bearmemori/app.py:1-80`
- Modify: `bearmemori/__main__.py:1-67`
- Test: `tests/test_app.py` (update)

**Step 1: Write failing test**

Update `tests/test_app.py` to verify the new `Application` has `vector_store` and `pending_store` attributes:

```python
from unittest.mock import patch, MagicMock
from bearmemori.app import create_application
from bearmemori.config import Settings


def test_create_application_has_new_components(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))

    with patch("bearmemori.app.VectorStore") as MockVS:
        mock_vs = MagicMock()
        MockVS.return_value = mock_vs
        settings = Settings()
        app = create_application(settings)

    assert app.vector_store is not None
    assert app.pending_store is not None
    assert hasattr(app, "db")
    assert hasattr(app, "bus")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -v`
Expected: FAIL

**Step 3: Update bearmemori/app.py**

Add `VectorStore` and `PendingStore` to `Application` and `create_application`:

```python
import logging

from bearmemori.config import Settings
from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, InputReceived, ReminderDue, SendMessage
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
    processor = Processor(bus=bus, llm=llm, db=db, embedding_model=settings.embedding_model)
    followup_manager = FollowUpManager(bus)
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

    # Wire events
    bus.on(InputReceived, queue_manager.handle_input)
    bus.on(FollowUpRequired, followup_manager.handle_followup_required)
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
        telegram=telegram,
        settings=settings,
        scheduler=scheduler,
    )
```

**Step 4: Update bearmemori/__main__.py**

Update `create_api` call to pass new dependencies, and change port to `settings.api_port`:

```python
import asyncio
import logging

import uvicorn

from bearmemori.api.routes import create_app as create_api
from bearmemori.app import create_application
from bearmemori.config import Settings
from bearmemori.events.domain import InputReceived

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
            followup_event = InputReceived(
                input_type=item.input_type,
                content=item.content,
                source_chat_id=item.source_chat_id,
            )
            followup_input = application.followup_manager.check_followup(followup_event)
            if followup_input:
                item.context = followup_input.context

            await application.processor.process_item(item)
        except Exception:
            logger.exception("Error processing item from %s", item.source_chat_id)


async def main() -> None:
    settings = Settings()
    application = create_application(settings)

    api = create_api(
        db=application.db,
        vector_store=application.vector_store,
        pending_store=application.pending_store,
        llm_base_url=settings.llm_base_url,
        llm_api_key=settings.llm_api_key,
        llm_model=settings.llm_model,
    )

    telegram_app = application.telegram.build()

    # Start processing loop
    asyncio.create_task(processing_loop(application))
    asyncio.create_task(application.scheduler.run())

    # Start API server
    config = uvicorn.Config(api, host="0.0.0.0", port=settings.api_port, log_level="info")
    server = uvicorn.Server(config)

    # Run telegram and API concurrently
    async with telegram_app:
        await telegram_app.start()
        await telegram_app.updater.start_polling()
        logger.info("BearMemori is running on port %d", settings.api_port)

        await server.serve()

        await telegram_app.updater.stop()
        await telegram_app.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/app.py bearmemori/__main__.py tests/test_app.py
git commit -m "feat: wire VectorStore and PendingStore into application"
```

---

### Task 10: Update Processor for New Model

**Files:**
- Modify: `bearmemori/core/processor.py:1-79`
- Modify: `bearmemori/llm/client.py:1-139` (update prompts for new categories)
- Test: `tests/test_processor.py` (update)

The Processor and LLM client still power BearMemori's own Telegram interface (classify/extract pipeline). They need to use the new `MemoryRecord` model and categories.

**Step 1: Update LLM client prompts**

In `bearmemori/llm/client.py`, update `CLASSIFY_SYSTEM_PROMPT` to use the 6 categories:

```python
CLASSIFY_SYSTEM_PROMPT = (
    "You are a memory classification assistant. Given user input, decide whether to:\n"
    '1. "store" - the input contains clear information worth remembering\n'
    '2. "followup" - the input is unclear and needs more context\n'
    "\n"
    "Respond with JSON only:\n"
    '- For store: {"action": "store", "category": "<type>", "confidence": <0-1>}\n'
    "  Categories: profile, general, event, location, task, reminder\n"
    '- For followup: {"action": "followup", "question": "<your clarifying question>"}'
)
```

Update `ExtractionResult` and `EXTRACT_SYSTEM_PROMPT` similarly:

```python
class ExtractionResult(BaseModel):
    title: str
    content: str
    category: str
    tags: list[str]
    event_fields: dict | None = None
```

```python
EXTRACT_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Extract structured memory data from the user input.\n"
    "If follow-up context is provided, use the full conversation to understand the memory.\n"
    "\n"
    "Respond with JSON only:\n"
    '{"title": "<short descriptive title>", "content": "<clear summary>", '
    '"category": "<type>", "tags": ["tag1", "tag2"], '
    '"event_fields": null or {"datetime": "ISO 8601", "status": "pending", "recurrence": null}}\n'
    "Categories: profile, general, event, location, task, reminder"
)
```

Update `ClassificationResult` to use `category` instead of `memory_type`:

```python
class ClassificationResult(BaseModel):
    action: str
    category: str | None = None
    confidence: float | None = None
    question: str | None = None
```

**Step 2: Update Processor to build MemoryRecord**

In `bearmemori/core/processor.py`, update `process_item` to create `MemoryRecord` instead of `Memory`:

```python
import logging
import uuid
from datetime import datetime, timezone

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryStored
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryRecord, MemoryCategory, EventFields, MemorySource

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

        event_fields = None
        if extraction.event_fields:
            event_fields = EventFields(**extraction.event_fields)

        record = MemoryRecord(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            category=MemoryCategory(extraction.category),
            title=extraction.title,
            content=extraction.content,
            raw_input=text,
            created_at=datetime.now(timezone.utc),
            tags=extraction.tags,
            event_fields=event_fields,
            source=MemorySource(platform="telegram", chat_id=item.source_chat_id),
            metadata={"source_chat_id": item.source_chat_id},
        )
        self._db.create(record)

        await self._bus.emit(
            MemoryStored(
                memory_id=record.id,
                content=record.content,
                memory_type=record.category.value,
                source_chat_id=item.source_chat_id,
            )
        )
        logger.info("Stored memory %s: %s", record.id, record.content[:80])
```

Note: The Processor no longer calls `get_embedding` since embeddings are now handled by ChromaDB in the API layer. If you want the Telegram pipeline to also add to ChromaDB, inject `vector_store` into Processor. This can be done as a follow-up.

**Step 3: Update tests**

Update `tests/test_processor.py` and `tests/test_llm_client.py` to use `category` instead of `memory_type`, `title` instead of just `content`, and `ExtractionResult` with new fields.

**Step 4: Run all tests**

Run: `pytest tests/test_processor.py tests/test_llm_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/core/processor.py bearmemori/llm/client.py tests/test_processor.py tests/test_llm_client.py
git commit -m "feat: update processor and LLM client for new category model"
```

---

### Task 11: Update Scheduler for New Model

**Files:**
- Modify: `bearmemori/core/scheduler.py:1-47`
- Test: `tests/test_scheduler.py` (update)

The scheduler now works with `event_fields` instead of `remind_at` / `recurring_minutes`.

**Step 1: Update scheduler**

The scheduler should query upcoming events/reminders that are due and fire `ReminderDue` events. Update to work with the new `MemoryRecord` model:

```python
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bus: EventBus, db: MemoryDatabase, poll_interval_seconds: int = 60) -> None:
        self._bus = bus
        self._db = db
        self._poll_interval = poll_interval_seconds

    async def check_reminders(self) -> None:
        # Get events/reminders due now (past due, not future)
        due = self._db.get_upcoming_events(days=0)
        # Also get overdue items (event_datetime <= now)
        # We need a dedicated method for this - get_due_reminders queries
        # reminders where event_datetime <= now
        due = self._db.get_due_events()
        for record in due:
            source_chat_id = ""
            if record.source:
                source_chat_id = record.source.chat_id
            elif record.metadata.get("source_chat_id"):
                source_chat_id = record.metadata["source_chat_id"]

            await self._bus.emit(
                ReminderDue(
                    memory_id=record.id,
                    content=record.content,
                    source_chat_id=source_chat_id,
                    remind_at_iso=record.event_fields.datetime if record.event_fields else "",
                )
            )

            if record.event_fields and record.event_fields.recurrence:
                # Advance the datetime by recurrence interval
                # For now, mark as done. Recurrence parsing is a follow-up.
                record.event_fields = EventFields(
                    datetime=record.event_fields.datetime,
                    status="done",
                    recurrence=record.event_fields.recurrence,
                )
            else:
                if record.event_fields:
                    record.event_fields = EventFields(
                        datetime=record.event_fields.datetime,
                        status="done",
                    )

            # Need an update method - add to database if not present
            logger.info("Fired reminder %s: %s", record.id, record.content[:80])

    async def run(self) -> None:
        logger.info("Reminder scheduler started (poll every %ds)", self._poll_interval)
        while True:
            try:
                await self.check_reminders()
            except Exception:
                logger.exception("Error checking reminders")
            await asyncio.sleep(self._poll_interval)
```

Note: The scheduler needs a `get_due_events()` method on the database that returns records where `event_datetime <= now` and `event_status = 'pending'`. Add this to `MemoryDatabase`:

```python
def get_due_events(self) -> list[MemoryRecord]:
    now = datetime.now(timezone.utc).isoformat()
    rows = self._conn.execute(
        """SELECT * FROM memories
           WHERE category IN ('event', 'reminder', 'task')
             AND event_datetime IS NOT NULL
             AND event_datetime <= ?
             AND (event_status IS NULL OR event_status = 'pending')
           ORDER BY event_datetime ASC""",
        (now,),
    ).fetchall()
    return [self._row_to_record(r) for r in rows]
```

Also add an `update()` method to `MemoryDatabase` for updating event status after firing.

**Step 2: Update tests**

Update `tests/test_scheduler.py` to use the new model.

**Step 3: Run tests**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add bearmemori/core/scheduler.py bearmemori/storage/database.py tests/test_scheduler.py
git commit -m "feat: update scheduler for event_fields model"
```

---

### Task 12: Update Domain Events

**Files:**
- Modify: `bearmemori/events/domain.py:1-49`

**Step 1: Update MemoryStored event**

Change `memory_type` to `category` in `MemoryStored`:

```python
class MemoryStored(Event):
    memory_id: str
    content: str
    category: str  # was memory_type
    source_chat_id: str
```

**Step 2: Update any references**

Search for `memory_type` in event handlers and update to `category`.

**Step 3: Run full test suite**

Run: `pytest -v`
Expected: PASS

**Step 4: Commit**

```bash
git add bearmemori/events/domain.py
git commit -m "refactor: rename memory_type to category in domain events"
```

---

### Task 13: Update Telegram Interface

**Files:**
- Modify: `bearmemori/interfaces/telegram.py`
- Test: `tests/test_telegram.py` (update)

Update the Telegram interface to work with the new `MemoryRecord` model and `category` instead of `memory_type`.

**Step 1: Update handler references**

Any references to `memory_type` in Telegram response formatting should use `category`. Update `handle_reminder_due` if it references old fields.

**Step 2: Update tests**

Update `tests/test_telegram.py` to use new field names.

**Step 3: Run tests**

Run: `pytest tests/test_telegram.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "refactor: update Telegram interface for new model"
```

---

### Task 14: Full Integration Test

**Files:**
- Modify: `tests/test_integration.py` (rewrite)

**Step 1: Write integration tests**

Test the full triage -> pending -> confirm -> retrieve flow:

```python
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore
from bearmemori.core.triage import TriageResult


@pytest.fixture
def full_stack(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()
    vs = VectorStore(persist_dir=str(tmp_path / "chroma"))
    vs.init()
    ps = PendingStore()
    app = create_app(db=db, vector_store=vs, pending_store=ps,
                     llm_base_url="http://test", llm_api_key="test", llm_model="test")
    return TestClient(app), db, vs, ps


def test_triage_confirm_retrieve_flow(full_stack):
    client, db, vs, ps = full_stack

    # 1. Triage proposes a memory
    draft = MemoryDraft(
        category=MemoryCategory.PROFILE,
        title="Coffee preference",
        content="User likes black coffee",
        tags=["coffee"],
    )
    with patch("bearmemori.api.routes.run_triage") as mock:
        mock.return_value = TriageResult(should_save=True, draft=draft)
        r = client.post("/memory/triage", json={
            "conversation": [{"role": "user", "content": "I love black coffee"}],
        })
    assert r.json()["should_save"] is True
    pending_id = r.json()["pending_id"]

    # 2. Confirm the pending memory
    r = client.post("/memory/confirm", json={"pending_id": pending_id})
    assert r.json()["status"] == "confirmed"
    record_id = r.json()["record_id"]

    # 3. Retrieve context
    r = client.get("/memory/retrieve", params={"query_context": "coffee"})
    assert "coffee" in r.json()["context_block"].lower()

    # 4. Search
    r = client.post("/memory/search", json={"query": "coffee"})
    assert len(r.json()["results"]) >= 1

    # 5. Get by ID
    r = client.get(f"/memory/{record_id}")
    assert r.json()["title"] == "Coffee preference"

    # 6. List
    r = client.get("/memory/list")
    assert len(r.json()["memories"]) == 1

    # 7. Delete
    r = client.delete(f"/memory/{record_id}")
    assert r.json()["status"] == "deleted"
    r = client.get(f"/memory/{record_id}")
    assert r.status_code == 404
```

**Step 2: Run integration tests**

Run: `pytest tests/test_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end integration test for teleBearAI API contract"
```

---

### Task 15: Final Verification

**Step 1: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS

**Step 2: Verify API contract**

Start the service and manually verify endpoints match teleBearAI's expectations using curl or httpie. Compare response shapes against teleBearAI's `memory_client.py` calls.

**Step 3: Final commit and version bump**

```bash
git add -A
git commit -m "chore: v0.4.0 - teleBearAI integration complete"
```
