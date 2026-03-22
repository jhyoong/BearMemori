# Webapp Memory Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a lightweight HTMX webapp for managing memories, simplify Telegram to an input layer, and add a "Review Later" workflow.

**Architecture:** Extend the existing FastAPI app with Jinja2+HTMX pages served at `/webapp/`. Add `needs_review` boolean to the memories table. Tune the LLM classification prompt to bias toward saving. Add "Review Later" button to Telegram's pending preview.

**Tech Stack:** FastAPI, Jinja2, HTMX, Pico CSS (CDN), SQLite, ChromaDB, python-telegram-bot

---

### Task 1: Add `needs_review` field to MemoryRecord

**Files:**
- Modify: `bearmemori/storage/models.py:39-62` (MemoryRecord class)
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

In `tests/test_models.py`, add:

```python
def test_memory_record_needs_review_default():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    record = MemoryRecord.from_draft(draft, "mem_test123")
    assert record.needs_review is False


def test_memory_record_needs_review_set():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    record = MemoryRecord.from_draft(draft, "mem_test123")
    record.needs_review = True
    assert record.needs_review is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_memory_record_needs_review_default -v`
Expected: FAIL — `needs_review` attribute not found

**Step 3: Write minimal implementation**

In `bearmemori/storage/models.py`, add field to `MemoryRecord` (after `metadata` field, around line 49):

```python
needs_review: bool = False
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/models.py tests/test_models.py
git commit -m "feat: add needs_review field to MemoryRecord"
```

---

### Task 2: Add `needs_review` to database schema and CRUD

**Files:**
- Modify: `bearmemori/storage/database.py:22-38` (table creation), `:100-133` (create method), `:135-153` (get/list methods)
- Test: `tests/test_storage.py`

**Step 1: Write the failing tests**

In `tests/test_storage.py`, add:

```python
def test_create_memory_with_needs_review(db, sample_record):
    sample_record.needs_review = True
    db.create(sample_record)
    retrieved = db.get(sample_record.id)
    assert retrieved is not None
    assert retrieved.needs_review is True


def test_create_memory_default_needs_review(db, sample_record):
    db.create(sample_record)
    retrieved = db.get(sample_record.id)
    assert retrieved is not None
    assert retrieved.needs_review is False


def test_list_memories_filter_needs_review(db, sample_record):
    db.create(sample_record)

    review_record = sample_record.model_copy(
        update={"id": "mem_review123", "needs_review": True}
    )
    db.create(review_record)

    all_memories = db.list_all()
    assert len(all_memories) == 2

    review_only = db.list_all(needs_review=True)
    assert len(review_only) == 1
    assert review_only[0].id == "mem_review123"

    no_review = db.list_all(needs_review=False)
    assert len(no_review) == 1
    assert no_review[0].id == sample_record.id


def test_update_memory_needs_review(db, sample_record):
    db.create(sample_record)
    sample_record.needs_review = True
    db.update(sample_record)
    retrieved = db.get(sample_record.id)
    assert retrieved.needs_review is True


def test_delete_many(db, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    record3 = sample_record.model_copy(update={"id": "mem_third1234"})
    db.create(sample_record)
    db.create(record2)
    db.create(record3)
    deleted = db.delete_many([sample_record.id, record2.id])
    assert deleted == 2
    assert db.get(sample_record.id) is None
    assert db.get(record2.id) is None
    assert db.get(record3.id) is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py::test_create_memory_with_needs_review -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `bearmemori/storage/database.py`:

a) Add `needs_review` column to table creation SQL (around line 35, before the closing paren):
```sql
needs_review INTEGER NOT NULL DEFAULT 0
```

b) Add auto-migration in `__init__` (after table creation, before FTS setup). Add a `_migrate()` method:
```python
def _migrate(self) -> None:
    cursor = self._conn.execute("PRAGMA table_info(memories)")
    columns = {row[1] for row in cursor.fetchall()}
    if "needs_review" not in columns:
        self._conn.execute(
            "ALTER TABLE memories ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.commit()
```

Call `self._migrate()` right after the CREATE TABLE statement.

c) Update `create()` method to include `needs_review` in INSERT:
```python
# Add to column list: ..., metadata, needs_review)
# Add to VALUES: ..., ?, ?)
# Add to params tuple: ..., json.dumps(record.metadata), int(record.needs_review))
```

d) Update `_row_to_record()` to include `needs_review`:
```python
needs_review=bool(row["needs_review"]),
```

e) Update `update()` method to include `needs_review` in UPDATE SET clause.

f) Update `list_all()` to accept optional `needs_review` filter:
```python
def list_all(self, needs_review: bool | None = None) -> list[MemoryRecord]:
    if needs_review is not None:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE needs_review = ? ORDER BY created_at DESC",
            (int(needs_review),),
        ).fetchall()
    else:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC"
        ).fetchall()
    return [self._row_to_record(row) for row in rows]
```

g) Add `delete_many()` method:
```python
def delete_many(self, record_ids: list[str]) -> int:
    if not record_ids:
        return 0
    placeholders = ",".join("?" for _ in record_ids)
    cursor = self._conn.execute(
        f"DELETE FROM memories WHERE id IN ({placeholders})", record_ids
    )
    self._conn.commit()
    return cursor.rowcount
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_storage.py
git commit -m "feat: add needs_review column to database with migration"
```

---

### Task 3: Add vector store bulk delete and update

**Files:**
- Modify: `bearmemori/storage/vector_store.py:26-41`
- Test: `tests/test_vector_store.py`

**Step 1: Write the failing tests**

In `tests/test_vector_store.py`, add:

```python
def test_update_document(vector_store, sample_record):
    vector_store.add(sample_record)
    sample_record.content = "Updated content here"
    sample_record.title = "Updated Title"
    vector_store.update(sample_record)
    results = vector_store.search("Updated content", top_k=1)
    assert len(results) == 1
    assert results[0]["id"] == sample_record.id


def test_delete_many(vector_store, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    vector_store.add(sample_record)
    vector_store.add(record2)
    vector_store.delete_many([sample_record.id, record2.id])
    results = vector_store.search(sample_record.content, top_k=5)
    assert len(results) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vector_store.py::test_update_document -v`
Expected: FAIL — `update` method not found

**Step 3: Write minimal implementation**

In `bearmemori/storage/vector_store.py`, add after the `delete()` method:

```python
def update(self, record: MemoryRecord) -> None:
    self.add(record)  # ChromaDB upsert handles update

def delete_many(self, record_ids: list[str]) -> None:
    if record_ids:
        self._collection.delete(ids=record_ids)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vector_store.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/storage/vector_store.py tests/test_vector_store.py
git commit -m "feat: add update and delete_many to vector store"
```

---

### Task 4: Extend MemoryConfirmed event with `needs_review`

**Files:**
- Modify: `bearmemori/events/domain.py:58-60`
- Test: `tests/test_event_bus.py`

**Step 1: Write the failing test**

In `tests/test_event_bus.py`, add:

```python
def test_memory_confirmed_needs_review_default():
    event = MemoryConfirmed(pending_id="pend_test", source_chat_id="123")
    assert event.needs_review is False


def test_memory_confirmed_needs_review_set():
    event = MemoryConfirmed(
        pending_id="pend_test", source_chat_id="123", needs_review=True
    )
    assert event.needs_review is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event_bus.py::test_memory_confirmed_needs_review_default -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `bearmemori/events/domain.py`, update `MemoryConfirmed` (line 58-60):

```python
class MemoryConfirmed(Event):
    pending_id: str
    source_chat_id: str
    needs_review: bool = False
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_event_bus.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/events/domain.py tests/test_event_bus.py
git commit -m "feat: add needs_review field to MemoryConfirmed event"
```

---

### Task 5: Update ConfirmHandler to pass `needs_review` through

**Files:**
- Modify: `bearmemori/core/confirm.py:28-48`
- Test: `tests/test_confirm.py`

**Step 1: Write the failing test**

In `tests/test_confirm.py`, add:

```python
@pytest.mark.asyncio
async def test_confirm_with_needs_review(bus, pending_store, db, vector_store):
    handler = ConfirmHandler(bus, pending_store, db, vector_store)
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL, title="Test", content="Test content"
    )
    pending_id = pending_store.add(draft, chat_id="123")

    event = MemoryConfirmed(
        pending_id=pending_id, source_chat_id="123", needs_review=True
    )
    await handler.handle_confirmed(event)

    # Find the stored record
    records = db.list_all(needs_review=True)
    assert len(records) == 1
    assert records[0].needs_review is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_confirm.py::test_confirm_with_needs_review -v`
Expected: FAIL — record saved with `needs_review=False`

**Step 3: Write minimal implementation**

In `bearmemori/core/confirm.py`, update `handle_confirmed()`:

```python
async def handle_confirmed(self, event: MemoryConfirmed) -> None:
    pending = self._pending_store.get(event.pending_id)
    if pending is None:
        logger.warning("Pending memory %s not found (expired?)", event.pending_id)
        return

    record_id = f"mem_{uuid.uuid4().hex[:12]}"
    record = MemoryRecord.from_draft(pending.draft, record_id)
    record.needs_review = event.needs_review
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
    logger.info("Confirmed and stored memory %s (needs_review=%s)", record.id, record.needs_review)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_confirm.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/core/confirm.py tests/test_confirm.py
git commit -m "feat: pass needs_review through confirm handler"
```

---

### Task 6: Add "Review Later" button to Telegram

**Files:**
- Modify: `bearmemori/interfaces/telegram.py:128-157` (handle_memory_pending), `:104-126` (_handle_callback)
- Test: `tests/test_telegram.py`

**Step 1: Write the failing test**

In `tests/test_telegram.py`, add a test for the review callback:

```python
@pytest.mark.asyncio
async def test_review_callback_emits_confirmed_with_needs_review(
    telegram_interface, bus, pending_store
):
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL, title="Test", content="Test content"
    )
    pending_id = pending_store.add(draft, chat_id="123")
    telegram_interface._pending_chat_ids[pending_id] = "123"

    events_emitted = []
    bus.on(MemoryConfirmed, lambda e: events_emitted.append(e))

    # Simulate callback with "review:{pending_id}"
    # The exact mock setup depends on existing test patterns in test_telegram.py
    # Check how existing save/discard callbacks are tested and follow the same pattern
    callback_data = f"review:{pending_id}"
    # ... follow existing test pattern for callback simulation
    # Assert that MemoryConfirmed was emitted with needs_review=True
```

Note: Check `tests/test_telegram.py` for the existing callback test pattern and replicate it. The key assertion is that `MemoryConfirmed` is emitted with `needs_review=True`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_review_callback_emits_confirmed_with_needs_review -v`
Expected: FAIL

**Step 3: Write minimal implementation**

a) In `handle_memory_pending()`, add the "Review Later" button to the keyboard (around line 139-150):

```python
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
            InlineKeyboardButton(
                "Discard", callback_data=f"discard:{event.pending_id}"
            ),
        ],
    ]
)
```

b) In `_handle_callback()`, add handling for "review" action (in the if/elif chain):

```python
elif action == "review":
    await self._bus.emit(
        MemoryConfirmed(
            pending_id=pending_id,
            source_chat_id=str(query.message.chat_id),
            needs_review=True,
        )
    )
    await query.answer("Saved for review")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: add Review Later button to Telegram pending preview"
```

---

### Task 7: Tune LLM classification prompt

**Files:**
- Modify: `bearmemori/llm/client.py:27-37` (CLASSIFY_SYSTEM_PROMPT)
- Test: `tests/test_llm_client.py`

**Step 1: Write the test**

This is a prompt change, not a logic change. Add a simple test that verifies the prompt text contains the bias instruction:

```python
def test_classify_prompt_biases_toward_store():
    from bearmemori.llm.client import CLASSIFY_SYSTEM_PROMPT

    assert "prefer" in CLASSIFY_SYSTEM_PROMPT.lower()
    assert "store" in CLASSIFY_SYSTEM_PROMPT.lower()
    assert "unintelligible" in CLASSIFY_SYSTEM_PROMPT.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_client.py::test_classify_prompt_biases_toward_store -v`
Expected: FAIL — "prefer" not in current prompt

**Step 3: Write minimal implementation**

Update `CLASSIFY_SYSTEM_PROMPT` in `bearmemori/llm/client.py`:

```python
CLASSIFY_SYSTEM_PROMPT = (
    "/no_think\n"
    "You are a memory classification assistant. Given user input, decide whether to:\n"
    '1. "store" - the input contains information worth remembering\n'
    '2. "followup" - the input is unclear and needs more context\n'
    "\n"
    "IMPORTANT: Prefer to store the memory even if the input is vague or incomplete. "
    "Extract what you can and save it. Only request a follow-up if the input is truly "
    "unintelligible or you cannot determine any meaningful content to extract.\n"
    "\n"
    "You MUST respond with a single valid JSON object and nothing else.\n"
    '- For store: {"action": "store", "category": "<category>", "confidence": <0-1>}\n'
    "  Categories: profile, general, event, location, task, reminder\n"
    '- For followup: {"action": "followup", "question": "<your clarifying question>"}'
)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/llm/client.py tests/test_llm_client.py
git commit -m "feat: tune classification prompt to bias toward storing"
```

---

### Task 8: Add new API endpoints (update, create, bulk)

**Files:**
- Modify: `bearmemori/api/routes.py`
- Modify: `bearmemori/api/schemas.py`
- Test: `tests/test_api.py`

**Step 1: Write the failing tests**

In `tests/test_api.py`, add tests for new endpoints. Check the existing test file for how the test client and fixtures are set up, then add:

```python
async def test_update_memory(client, db, sample_record):
    db.create(sample_record)
    response = await client.put(
        f"/memory/{sample_record.id}",
        json={"title": "Updated Title", "needs_review": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"

    retrieved = db.get(sample_record.id)
    assert retrieved.title == "Updated Title"
    assert retrieved.needs_review is True


async def test_create_memory_direct(client):
    response = await client.post(
        "/memory/create",
        json={
            "category": "general",
            "title": "Direct Memory",
            "content": "Created from webapp",
            "tags": ["test"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "record_id" in data
    assert data["status"] == "created"


async def test_bulk_delete(client, db, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    db.create(sample_record)
    db.create(record2)
    response = await client.post(
        "/memory/bulk/delete",
        json={"record_ids": [sample_record.id, record2.id]},
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 2


async def test_bulk_update(client, db, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    db.create(sample_record)
    db.create(record2)
    response = await client.post(
        "/memory/bulk/update",
        json={
            "record_ids": [sample_record.id, record2.id],
            "updates": {"needs_review": False},
        },
    )
    assert response.status_code == 200


async def test_list_memories_needs_review_filter(client, db, sample_record):
    db.create(sample_record)
    review_record = sample_record.model_copy(
        update={"id": "mem_review123", "needs_review": True}
    )
    db.create(review_record)

    response = await client.get("/memory/list?needs_review=true")
    assert response.status_code == 200
    data = response.json()
    assert len(data["memories"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py::test_update_memory -v`
Expected: FAIL — 404 or 405

**Step 3: Write minimal implementation**

a) Add new schemas to `bearmemori/api/schemas.py`:

```python
class UpdateMemoryRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    needs_review: bool | None = None


class CreateMemoryRequest(BaseModel):
    category: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class BulkDeleteRequest(BaseModel):
    record_ids: list[str]


class BulkUpdateRequest(BaseModel):
    record_ids: list[str]
    updates: dict
```

b) Add new routes to `bearmemori/api/routes.py`:

```python
@router.put("/memory/{record_id}")
async def update_memory(record_id: str, req: UpdateMemoryRequest):
    record = db.get(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Memory not found")
    if req.title is not None:
        record.title = req.title
    if req.content is not None:
        record.content = req.content
    if req.category is not None:
        record.category = MemoryCategory(req.category)
    if req.tags is not None:
        record.tags = req.tags
    if req.needs_review is not None:
        record.needs_review = req.needs_review
    db.update(record)
    vector_store.update(record)
    return {"status": "updated", "record_id": record_id}


@router.post("/memory/create")
async def create_memory_direct(req: CreateMemoryRequest):
    record_id = f"mem_{uuid.uuid4().hex[:12]}"
    record = MemoryRecord(
        id=record_id,
        category=MemoryCategory(req.category),
        title=req.title,
        content=req.content,
        created_at=datetime.now(UTC),
        tags=req.tags,
    )
    db.create(record)
    vector_store.add(record)
    return {"status": "created", "record_id": record_id}


@router.post("/memory/bulk/delete")
async def bulk_delete(req: BulkDeleteRequest):
    deleted = db.delete_many(req.record_ids)
    vector_store.delete_many(req.record_ids)
    return {"deleted": deleted}


@router.post("/memory/bulk/update")
async def bulk_update(req: BulkUpdateRequest):
    updated = 0
    for record_id in req.record_ids:
        record = db.get(record_id)
        if record:
            for key, value in req.updates.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            db.update(record)
            updated += 1
    return {"updated": updated}
```

c) Update `list_memories` route to accept `needs_review` query param:

```python
@router.get("/memory/list")
async def list_memories(
    category: str | None = None,
    needs_review: bool | None = None,
):
    if category:
        memories = db.list_by_category(MemoryCategory(category))
    else:
        memories = db.list_all(needs_review=needs_review)
    return {"memories": [m.model_dump() for m in memories]}
```

Note: Add `import uuid` and `from datetime import datetime, UTC` at top of routes.py if not already imported.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/api/routes.py bearmemori/api/schemas.py tests/test_api.py
git commit -m "feat: add update, create, bulk API endpoints"
```

---

### Task 9: Add `WEBAPP_SECRET` config setting

**Files:**
- Modify: `bearmemori/config.py:4-22`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

In `tests/test_config.py`, add:

```python
def test_webapp_secret_default():
    # Check existing test patterns for how Settings is instantiated in tests
    settings = Settings(
        telegram_bot_token="test",
        telegram_allowed_user_id=123,
    )
    assert settings.webapp_secret == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_webapp_secret_default -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `bearmemori/config.py`, add to Settings class:

```python
webapp_secret: str = ""
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/config.py tests/test_config.py
git commit -m "feat: add webapp_secret config setting"
```

---

### Task 10: Create webapp auth module

**Files:**
- Create: `bearmemori/webapp/__init__.py`
- Create: `bearmemori/webapp/auth.py`
- Test: `tests/test_webapp_auth.py`

**Step 1: Write the failing tests**

Create `tests/test_webapp_auth.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearmemori.webapp.auth import create_auth_middleware, verify_session


def test_login_page_accessible_without_auth():
    """Login page should be accessible without a session."""
    app = FastAPI()
    # Setup minimal app with auth middleware
    # GET /webapp/login should return 200


def test_protected_route_redirects_without_auth():
    """Protected webapp routes should redirect to login without session."""
    app = FastAPI()
    # GET /webapp/memories without session should redirect to /webapp/login


def test_login_with_correct_secret():
    """POST /webapp/login with correct secret should set session cookie."""
    # POST /webapp/login with secret=correct should set cookie and redirect


def test_login_with_wrong_secret():
    """POST /webapp/login with wrong secret should show error."""
    # POST /webapp/login with secret=wrong should return login page with error
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_webapp_auth.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

Create `bearmemori/webapp/__init__.py`:
```python
```

Create `bearmemori/webapp/auth.py`:

```python
import hashlib
import hmac
import secrets

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware


class WebappAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str):
        super().__init__(app)
        self._secret = secret
        self._token = hashlib.sha256(secret.encode()).hexdigest()

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/webapp"):
            return await call_next(request)

        # Allow login page and static files
        if request.url.path in ("/webapp/login",) or request.url.path.startswith(
            "/webapp/static"
        ):
            return await call_next(request)

        # Check session cookie
        session_token = request.cookies.get("webapp_session")
        if not session_token or not hmac.compare_digest(session_token, self._token):
            return RedirectResponse(url="/webapp/login", status_code=302)

        return await call_next(request)

    def create_session_cookie(self, response: Response) -> Response:
        response.set_cookie(
            key="webapp_session",
            value=self._token,
            httponly=True,
            samesite="strict",
            max_age=60 * 60 * 24 * 30,  # 30 days
        )
        return response

    def verify_secret(self, provided: str) -> bool:
        return hmac.compare_digest(
            hashlib.sha256(provided.encode()).hexdigest(), self._token
        )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_webapp_auth.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/webapp/__init__.py bearmemori/webapp/auth.py tests/test_webapp_auth.py
git commit -m "feat: add webapp auth middleware with shared secret"
```

---

### Task 11: Create webapp templates

**Files:**
- Create: `bearmemori/webapp/templates/base.html`
- Create: `bearmemori/webapp/templates/login.html`
- Create: `bearmemori/webapp/templates/memories.html`
- Create: `bearmemori/webapp/templates/memory_detail.html`
- Create: `bearmemori/webapp/templates/create.html`
- Create: `bearmemori/webapp/templates/review_queue.html`
- Create: `bearmemori/webapp/templates/partials/memory_table.html`
- Create: `bearmemori/webapp/static/style.css`

No tests for this task — templates are tested via integration in Task 12.

**Step 1: Create base template**

`bearmemori/webapp/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}BearMemori{% endblock %}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <link rel="stylesheet" href="/webapp/static/style.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</head>
<body>
    <nav class="container">
        <ul>
            <li><strong>BearMemori</strong></li>
        </ul>
        <ul>
            <li><a href="/webapp/memories">Memories</a></li>
            <li><a href="/webapp/review">Review Queue</a></li>
            <li><a href="/webapp/memories/new">New Memory</a></li>
        </ul>
    </nav>
    <main class="container">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

**Step 2: Create login template**

`bearmemori/webapp/templates/login.html`:
```html
{% extends "base.html" %}
{% block title %}Login - BearMemori{% endblock %}
{% block content %}
<article>
    <h2>Login</h2>
    {% if error %}
    <p role="alert">{{ error }}</p>
    {% endif %}
    <form method="post" action="/webapp/login">
        <label for="secret">Secret</label>
        <input type="password" id="secret" name="secret" required>
        <button type="submit">Login</button>
    </form>
</article>
{% endblock %}
```

**Step 3: Create memories list template**

`bearmemori/webapp/templates/memories.html`:
```html
{% extends "base.html" %}
{% block title %}Memories - BearMemori{% endblock %}
{% block content %}
<h2>Memories</h2>

<form hx-get="/webapp/memories" hx-target="#memory-table" hx-swap="innerHTML" hx-push-url="true">
    <div class="grid">
        <input type="search" name="q" placeholder="Search..." value="{{ q or '' }}">
        <select name="category">
            <option value="">All Categories</option>
            {% for cat in categories %}
            <option value="{{ cat }}" {% if category == cat %}selected{% endif %}>{{ cat }}</option>
            {% endfor %}
        </select>
        <button type="submit">Filter</button>
    </div>
</form>

<form id="bulk-form">
    <div id="bulk-actions" style="margin-bottom: 1rem;">
        <button type="button" hx-post="/webapp/memories/bulk/delete" hx-include="#bulk-form" hx-confirm="Delete selected memories?" hx-target="#memory-table" hx-swap="innerHTML" class="secondary">Delete Selected</button>
        <button type="button" hx-post="/webapp/memories/bulk/clear-review" hx-include="#bulk-form" hx-target="#memory-table" hx-swap="innerHTML" class="contrast">Clear Review Flag</button>
    </div>

    <div id="memory-table">
        {% include "partials/memory_table.html" %}
    </div>
</form>
{% endblock %}
```

**Step 4: Create memory table partial**

`bearmemori/webapp/templates/partials/memory_table.html`:
```html
<table>
    <thead>
        <tr>
            <th><input type="checkbox" id="select-all" onclick="document.querySelectorAll('.mem-check').forEach(c => c.checked = this.checked)"></th>
            <th>Title</th>
            <th>Category</th>
            <th>Tags</th>
            <th>Review</th>
            <th>Created</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for memory in memories %}
        <tr id="row-{{ memory.id }}">
            <td><input type="checkbox" class="mem-check" name="record_ids" value="{{ memory.id }}"></td>
            <td><a href="/webapp/memories/{{ memory.id }}">{{ memory.title }}</a></td>
            <td>{{ memory.category }}</td>
            <td>{{ memory.tags | join(', ') }}</td>
            <td>{% if memory.needs_review %}Needs Review{% endif %}</td>
            <td>{{ memory.created_at[:10] }}</td>
            <td>
                <a href="/webapp/memories/{{ memory.id }}">Edit</a>
                <a href="#" hx-delete="/webapp/memories/{{ memory.id }}" hx-confirm="Delete this memory?" hx-target="#row-{{ memory.id }}" hx-swap="outerHTML">Delete</a>
            </td>
        </tr>
        {% endfor %}
        {% if not memories %}
        <tr><td colspan="7">No memories found.</td></tr>
        {% endif %}
    </tbody>
</table>
```

**Step 5: Create memory detail template**

`bearmemori/webapp/templates/memory_detail.html`:
```html
{% extends "base.html" %}
{% block title %}{{ memory.title }} - BearMemori{% endblock %}
{% block content %}
<h2>Edit Memory</h2>

<form method="post" action="/webapp/memories/{{ memory.id }}">
    <label for="title">Title</label>
    <input type="text" id="title" name="title" value="{{ memory.title }}" required>

    <label for="category">Category</label>
    <select id="category" name="category">
        {% for cat in categories %}
        <option value="{{ cat }}" {% if memory.category == cat %}selected{% endif %}>{{ cat }}</option>
        {% endfor %}
    </select>

    <label for="content">Content</label>
    <textarea id="content" name="content" rows="6" required>{{ memory.content }}</textarea>

    <label for="tags">Tags (comma-separated)</label>
    <input type="text" id="tags" name="tags" value="{{ memory.tags | join(', ') }}">

    <label>
        <input type="checkbox" name="needs_review" {% if memory.needs_review %}checked{% endif %}>
        Needs Review
    </label>

    <div class="grid">
        <button type="submit">Save Changes</button>
        <button type="button" class="secondary" hx-delete="/webapp/memories/{{ memory.id }}" hx-confirm="Delete this memory permanently?">Delete</button>
    </div>
</form>

<p><a href="/webapp/memories">Back to list</a></p>
{% endblock %}
```

**Step 6: Create new memory template**

`bearmemori/webapp/templates/create.html`:
```html
{% extends "base.html" %}
{% block title %}New Memory - BearMemori{% endblock %}
{% block content %}
<h2>Create Memory</h2>

<form method="post" action="/webapp/memories/new">
    <label for="title">Title</label>
    <input type="text" id="title" name="title" required>

    <label for="category">Category</label>
    <select id="category" name="category">
        {% for cat in categories %}
        <option value="{{ cat }}">{{ cat }}</option>
        {% endfor %}
    </select>

    <label for="content">Content</label>
    <textarea id="content" name="content" rows="6" required></textarea>

    <label for="tags">Tags (comma-separated)</label>
    <input type="text" id="tags" name="tags">

    <button type="submit">Create Memory</button>
</form>

<p><a href="/webapp/memories">Back to list</a></p>
{% endblock %}
```

**Step 7: Create review queue template**

`bearmemori/webapp/templates/review_queue.html`:
```html
{% extends "base.html" %}
{% block title %}Review Queue - BearMemori{% endblock %}
{% block content %}
<h2>Review Queue</h2>
<p>{{ memories | length }} memories need review.</p>

<form id="bulk-form">
    <div style="margin-bottom: 1rem;">
        <button type="button" hx-post="/webapp/review/bulk/approve" hx-include="#bulk-form" hx-target="#review-table" hx-swap="innerHTML" class="contrast">Approve Selected</button>
        <button type="button" hx-post="/webapp/memories/bulk/delete" hx-include="#bulk-form" hx-confirm="Delete selected?" hx-target="#review-table" hx-swap="innerHTML" class="secondary">Delete Selected</button>
    </div>

    <div id="review-table">
        {% include "partials/memory_table.html" %}
    </div>
</form>
{% endblock %}
```

**Step 8: Create minimal CSS overrides**

`bearmemori/webapp/static/style.css`:
```css
/* Minimal overrides for BearMemori webapp */
table td a { margin-right: 0.5rem; }
#bulk-actions button { margin-right: 0.5rem; }
[role="alert"] { color: var(--pico-del-color); }
```

**Step 9: Commit**

```bash
git add bearmemori/webapp/templates/ bearmemori/webapp/static/
git commit -m "feat: add webapp Jinja2 templates and static CSS"
```

---

### Task 12: Create webapp router

**Files:**
- Create: `bearmemori/webapp/router.py`
- Test: `tests/test_webapp.py`

**Step 1: Write the failing tests**

Create `tests/test_webapp.py`:

```python
import pytest
from fastapi.testclient import TestClient


def test_login_page_returns_200(webapp_client):
    response = webapp_client.get("/webapp/login")
    assert response.status_code == 200


def test_memories_redirects_without_auth(webapp_client):
    response = webapp_client.get("/webapp/memories", follow_redirects=False)
    assert response.status_code == 302
    assert "/webapp/login" in response.headers["location"]


def test_login_with_correct_secret(webapp_client):
    response = webapp_client.post(
        "/webapp/login",
        data={"secret": "test-secret"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "webapp_session" in response.cookies


def test_memories_page_with_auth(authed_webapp_client):
    response = authed_webapp_client.get("/webapp/memories")
    assert response.status_code == 200
    assert "Memories" in response.text


def test_create_memory_page(authed_webapp_client):
    response = authed_webapp_client.get("/webapp/memories/new")
    assert response.status_code == 200


def test_review_queue_page(authed_webapp_client):
    response = authed_webapp_client.get("/webapp/review")
    assert response.status_code == 200
```

Note: You will need to create fixtures `webapp_client` and `authed_webapp_client` in `tests/conftest.py` that set up a test FastAPI app with the webapp router, database, vector store, and auth middleware. Follow the patterns already used in `tests/test_api.py` for fixture setup.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_webapp.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

Create `bearmemori/webapp/router.py`:

```python
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore
from bearmemori.webapp.auth import WebappAuthMiddleware

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

CATEGORIES = [c.value for c in MemoryCategory]

router = APIRouter(prefix="/webapp")


def create_webapp_router(
    db: MemoryDatabase,
    vector_store: VectorStore,
    auth: WebappAuthMiddleware,
) -> APIRouter:
    r = APIRouter(prefix="/webapp")

    @r.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @r.post("/login")
    async def login_submit(request: Request, secret: str = Form(...)):
        if auth.verify_secret(secret):
            response = RedirectResponse(url="/webapp/memories", status_code=302)
            return auth.create_session_cookie(response)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid secret"}, status_code=401
        )

    @r.get("/memories", response_class=HTMLResponse)
    async def memories_list(
        request: Request,
        q: str | None = None,
        category: str | None = None,
    ):
        if category:
            memories = db.list_by_category(MemoryCategory(category))
        else:
            memories = db.list_all()

        if q:
            search_results = db.search_keyword(q, limit=100)
            search_ids = {m.id for m in search_results}
            memories = [m for m in memories if m.id in search_ids]

        # Check if HTMX request (partial swap)
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                request,
                "partials/memory_table.html",
                {"memories": memories},
            )

        return templates.TemplateResponse(
            request,
            "memories.html",
            {
                "memories": memories,
                "categories": CATEGORIES,
                "q": q,
                "category": category,
            },
        )

    @r.get("/memories/new", response_class=HTMLResponse)
    async def create_memory_page(request: Request):
        return templates.TemplateResponse(
            request, "create.html", {"categories": CATEGORIES}
        )

    @r.post("/memories/new")
    async def create_memory_submit(
        request: Request,
        title: str = Form(...),
        category: str = Form(...),
        content: str = Form(...),
        tags: str = Form(""),
    ):
        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        record = MemoryRecord(
            id=record_id,
            category=MemoryCategory(category),
            title=title,
            content=content,
            created_at=datetime.now(UTC),
            tags=tag_list,
        )
        db.create(record)
        vector_store.add(record)
        return RedirectResponse(url="/webapp/memories", status_code=302)

    @r.get("/memories/{record_id}", response_class=HTMLResponse)
    async def memory_detail(request: Request, record_id: str):
        record = db.get(record_id)
        if not record:
            return RedirectResponse(url="/webapp/memories", status_code=302)
        return templates.TemplateResponse(
            request,
            "memory_detail.html",
            {"memory": record, "categories": CATEGORIES},
        )

    @r.post("/memories/{record_id}")
    async def memory_update(
        request: Request,
        record_id: str,
        title: str = Form(...),
        category: str = Form(...),
        content: str = Form(...),
        tags: str = Form(""),
        needs_review: bool = Form(False),
    ):
        record = db.get(record_id)
        if not record:
            return RedirectResponse(url="/webapp/memories", status_code=302)

        record.title = title
        record.category = MemoryCategory(category)
        record.content = content
        record.tags = [t.strip() for t in tags.split(",") if t.strip()]
        record.needs_review = needs_review
        db.update(record)
        vector_store.update(record)
        return RedirectResponse(
            url=f"/webapp/memories/{record_id}", status_code=302
        )

    @r.delete("/memories/{record_id}")
    async def memory_delete(record_id: str):
        db.delete(record_id)
        vector_store.delete(record_id)
        return ""  # HTMX removes the element

    @r.get("/review", response_class=HTMLResponse)
    async def review_queue(request: Request):
        memories = db.list_all(needs_review=True)
        return templates.TemplateResponse(
            request,
            "review_queue.html",
            {"memories": memories, "categories": CATEGORIES},
        )

    @r.post("/memories/bulk/delete")
    async def bulk_delete(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        if record_ids:
            db.delete_many(record_ids)
            vector_store.delete_many(record_ids)
        # Return updated table
        memories = db.list_all()
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    @r.post("/memories/bulk/clear-review")
    async def bulk_clear_review(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        for rid in record_ids:
            record = db.get(rid)
            if record:
                record.needs_review = False
                db.update(record)
        memories = db.list_all()
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    @r.post("/review/bulk/approve")
    async def bulk_approve(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        for rid in record_ids:
            record = db.get(rid)
            if record:
                record.needs_review = False
                db.update(record)
        memories = db.list_all(needs_review=True)
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    return r
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_webapp.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/webapp/router.py tests/test_webapp.py tests/conftest.py
git commit -m "feat: add webapp router with all CRUD and bulk operations"
```

---

### Task 13: Wire webapp into application

**Files:**
- Modify: `bearmemori/app.py:59-125`
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

In `tests/test_app.py`, add:

```python
@pytest.mark.asyncio
async def test_webapp_mounted_when_secret_configured(monkeypatch):
    monkeypatch.setenv("WEBAPP_SECRET", "test-secret")
    # Create application and check that /webapp routes are registered
    # Follow existing test patterns in test_app.py
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py::test_webapp_mounted_when_secret_configured -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `bearmemori/app.py`, in the `create_application()` function, after the FastAPI app is created and API routes are mounted, add:

```python
# Mount webapp if secret is configured
if settings.webapp_secret:
    from bearmemori.webapp.auth import WebappAuthMiddleware
    from bearmemori.webapp.router import create_webapp_router

    from starlette.staticfiles import StaticFiles
    from pathlib import Path

    webapp_auth = WebappAuthMiddleware(api, settings.webapp_secret)
    webapp_router = create_webapp_router(db, vector_store, webapp_auth)
    api.include_router(webapp_router)
    api.add_middleware(WebappAuthMiddleware, secret=settings.webapp_secret)

    static_dir = Path(__file__).parent / "webapp" / "static"
    api.mount("/webapp/static", StaticFiles(directory=str(static_dir)), name="webapp-static")
```

Note: Check how the FastAPI `api` instance is created in `app.py` and where routes are added. The webapp router should be included after the existing API router. The `WebappAuthMiddleware` needs to be added as Starlette middleware on the app.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/app.py tests/test_app.py
git commit -m "feat: wire webapp into application with conditional mounting"
```

---

### Task 14: Add `jinja2` and `python-multipart` dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Check current dependencies**

Run: `uv run python -c "import jinja2; print(jinja2.__version__)"` to check if jinja2 is already available (FastAPI may pull it in).

Run: `uv run python -c "import multipart; print('ok')"` to check python-multipart (needed for Form() parameters).

**Step 2: Add missing dependencies**

Run: `uv add jinja2 python-multipart` (only add what's missing).

**Step 3: Verify**

Run: `uv run python -c "from fastapi.templating import Jinja2Templates; print('ok')"`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add jinja2 and python-multipart dependencies"
```

---

### Task 15: Run full test suite and fix issues

**Step 1: Run all tests**

Run: `uv run pytest -v`

**Step 2: Fix any failures**

Address any test failures from existing tests that may be affected by the new `needs_review` column or other changes.

**Step 3: Run linter**

Run: `uv run ruff check .`
Run: `uv run ruff format .`

**Step 4: Fix any lint issues**

**Step 5: Commit**

```bash
git add -A
git commit -m "fix: resolve test and lint issues"
```

---

### Task 16: End-to-end verification

**Step 1: Verify the app starts**

Run: `uv run python -m bearmemori` (briefly, then Ctrl+C). Check for startup errors.

**Step 2: Verify webapp serves**

Set `WEBAPP_SECRET=test` in `.env`, start the app, and verify:
- `GET /webapp/login` returns the login page
- `POST /webapp/login` with correct secret sets a cookie
- `GET /webapp/memories` shows the memory list
- `GET /webapp/memories/new` shows the create form
- `GET /webapp/review` shows the review queue

**Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: end-to-end verification fixes"
```
