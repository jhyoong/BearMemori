# Group 8: Tests

## Goal

Write pytest tests covering the database layer, all REST API endpoints, and the scheduler. At the end of this group, `pytest tests/` passes with full coverage of Core service functionality.

**Depends on:** All previous groups (1-7)
**Blocks:** Nothing

---

## Context

Tests use:
- `pytest` + `pytest-asyncio` for async test support
- `httpx.AsyncClient` for testing FastAPI endpoints (ASGI transport, no real HTTP server)
- A temporary SQLite database created fresh for each test session (or each test)
- `fakeredis` or a simple mock for Redis operations

All tests live in `tests/test_core/`. The `tests/conftest.py` provides shared fixtures.

---

## Steps

### Step 8.1: Test infrastructure

**Files to create:**
- `tests/__init__.py` (empty)
- `tests/conftest.py`
- `tests/test_core/__init__.py` (empty)

**Test dependencies** (add to a `pyproject.toml` at root or a `requirements-test.txt`):
- `pytest>=8.0`
- `pytest-asyncio>=0.23`
- `httpx>=0.27`
- `fakeredis[json]>=2.20`

**`tests/conftest.py` fixtures:**

#### `test_db` fixture (session or function scope)

```python
@pytest_asyncio.fixture
async def test_db(tmp_path):
    """Create a temporary SQLite database with migrations applied."""
    db_path = str(tmp_path / "test.db")
    db = await init_db(db_path)
    yield db
    await db.close()
```

#### `mock_redis` fixture

```python
@pytest_asyncio.fixture
async def mock_redis():
    """Create a fake Redis client for testing."""
    import fakeredis.aioredis
    redis_client = fakeredis.aioredis.FakeRedis()
    yield redis_client
    await redis_client.aclose()
```

#### `test_app` fixture

```python
@pytest_asyncio.fixture
async def test_app(test_db, mock_redis):
    """Create a FastAPI test client with test DB and mock Redis."""
    from core.core.main import app

    app.state.db = test_db
    app.state.redis = mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client
```

#### `test_user` fixture

```python
@pytest_asyncio.fixture
async def test_user(test_db):
    """Create a test user in the database."""
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (12345, "Test User", 1)
    )
    await test_db.commit()
    return 12345
```

---

### Step 8.2: Database tests

**File:** `tests/test_core/test_database.py`

**Tests:**

1. **`test_init_db_creates_tables`** -- Call `init_db()` on a fresh temp path. Verify all tables exist by querying `sqlite_master`.

2. **`test_init_db_sets_user_version`** -- After `init_db()`, `PRAGMA user_version` returns `1`.

3. **`test_init_db_idempotent`** -- Call `init_db()` twice on the same path. Second call should not fail and version should still be `1`.

4. **`test_wal_mode_enabled`** -- After `init_db()`, `PRAGMA journal_mode` returns `wal`.

5. **`test_foreign_keys_enabled`** -- After `init_db()`, `PRAGMA foreign_keys` returns `1`.

6. **`test_foreign_key_constraint`** -- Try to insert a memory with a non-existent `owner_user_id`. Should raise an IntegrityError.

---

### Step 8.3: Endpoint tests

#### `tests/test_core/test_memories.py`

**Tests:**

1. **`test_create_text_memory`** -- POST a text memory. Verify status is `confirmed`, `pending_expires_at` is None.

2. **`test_create_image_memory`** -- POST with `media_type=image`. Verify status is `pending`, `pending_expires_at` is approximately 7 days from now.

3. **`test_get_memory`** -- Create a memory, GET it by ID. Verify all fields match.

4. **`test_get_memory_not_found`** -- GET a non-existent ID. Verify 404 response.

5. **`test_get_memory_includes_tags`** -- Create a memory, add tags, GET it. Verify tags are in the response.

6. **`test_update_memory`** -- Create a memory, PATCH with `is_pinned=true`. Verify update.

7. **`test_delete_memory`** -- Create a memory, DELETE it. Verify 204. Verify GET returns 404.

8. **`test_delete_memory_removes_tags`** -- Create a memory with tags, delete it. Verify tags are also gone (cascade).

9. **`test_add_tags`** -- POST tags to a memory. Verify they appear on GET.

10. **`test_add_suggested_tags`** -- POST tags with `status=suggested`. Verify `suggested_at` is set.

11. **`test_remove_tag`** -- Add a tag, then DELETE it. Verify it no longer appears.

12. **`test_create_memory_audit_logged`** -- Create a memory. Query audit log. Verify an entry with action `created` exists.

#### `tests/test_core/test_tasks.py`

**Tests:**

1. **`test_create_task`** -- POST a task linked to a memory. Verify response.

2. **`test_list_tasks`** -- Create multiple tasks. GET all. Verify count.

3. **`test_list_tasks_filter_state`** -- Create NOT_DONE and DONE tasks. Filter by state. Verify correct subset.

4. **`test_mark_task_done`** -- PATCH with `state=DONE`. Verify `completed_at` is set.

5. **`test_recurring_task_creates_next`** -- Create a task with `recurrence_minutes=1440` and `due_at`. Mark it DONE. Verify a new NOT_DONE task exists with `due_at` = original + 1440 minutes.

6. **`test_recurring_task_drift_prevention`** -- Create a recurring task with a `due_at` in the past. Mark DONE. Verify new `due_at` is based on the old `due_at`, not "now".

7. **`test_delete_task`** -- Create and delete. Verify gone.

#### `tests/test_core/test_reminders.py`

**Tests:**

1. **`test_create_reminder`** -- POST a reminder. Verify response.

2. **`test_list_reminders`** -- Create multiple. GET all. Verify sorted by `fire_at` ascending.

3. **`test_list_upcoming_only`** -- Create a fired and an unfired reminder. Filter `upcoming_only=true`. Verify only unfired returned.

4. **`test_update_reminder`** -- PATCH `fire_at`. Verify updated.

5. **`test_delete_reminder`** -- Create and delete. Verify gone.

#### `tests/test_core/test_events.py`

**Tests:**

1. **`test_create_event`** -- POST an event. Verify status is `pending` and `pending_since` is set.

2. **`test_confirm_event_creates_reminder`** -- Create an event with a `memory_id`. PATCH to `confirmed`. Verify a reminder was created and `reminder_id` is set on the event.

3. **`test_reject_event`** -- Create, reject. Verify status is `rejected`.

4. **`test_list_events_filter_status`** -- Create pending and confirmed events. Filter. Verify.

#### `tests/test_core/test_search.py`

**Tests:**

1. **`test_search_finds_memory`** -- Create a confirmed memory with content "buy butter". Search for "butter". Verify it appears in results.

2. **`test_search_ignores_pending`** -- Create a pending memory. Search for its content. Verify empty results.

3. **`test_search_pin_boost`** -- Create two confirmed memories with similar content. Pin one. Search. Verify pinned one appears first.

4. **`test_search_by_tag`** -- Create a memory with a tag "groceries". Search for "groceries". Verify it matches (tags are indexed in FTS5).

5. **`test_search_owner_filter`** -- Create memories for two users. Search with owner filter. Verify only that user's memories returned.

6. **`test_search_empty_query_returns_400`** -- Search with `q=""`. Verify 400.

#### `tests/test_core/test_settings.py`

**Tests:**

1. **`test_get_default_settings`** -- GET settings for a user with no settings row. Verify defaults returned.

2. **`test_update_settings`** -- PATCH timezone. Verify change persists.

3. **`test_get_settings_auto_creates_user`** -- GET settings for a non-existent user. Verify user row is created.

#### `tests/test_core/test_audit.py`

**Tests:**

1. **`test_audit_entries_created`** -- Perform a memory create. Query `GET /audit?entity_type=memory`. Verify entry exists.

2. **`test_audit_filter_by_entity_id`** -- Create two memories. Query audit for one specific entity_id. Verify only that one returned.

3. **`test_audit_detail_field`** -- Perform an update that logs detail. Verify the `detail` field is a parsed dict in the response.

---

### Step 8.4: Scheduler tests

**File:** `tests/test_core/test_scheduler.py`

These tests call the individual scheduler functions directly (not the main loop) to test each action in isolation.

**Tests:**

1. **`test_fire_due_reminder`** -- Insert a reminder with `fire_at` in the past, `fired=0`. Call `fire_due_reminders()`. Verify:
   - Reminder has `fired=1` in DB
   - A message was published to the `notify:telegram` stream in mock Redis

2. **`test_fire_recurring_reminder`** -- Insert a recurring reminder. Fire it. Verify:
   - Original is `fired=1`
   - A new reminder exists with `fire_at = old + recurrence` and `fired=0`

3. **`test_expire_pending_image`** -- Insert a pending memory with `pending_expires_at` in the past. Call `expire_pending_images()`. Verify:
   - Memory no longer in DB
   - Audit log has an "expired" entry

4. **`test_expire_suggested_tags`** -- Insert a suggested tag with `suggested_at` 8 days ago. Call `expire_suggested_tags()`. Verify:
   - Tag no longer in DB
   - Audit log has an "expired" entry

5. **`test_requeue_stale_event`** -- Insert a pending event with `pending_since` 25 hours ago. Call `requeue_stale_events()`. Verify:
   - `pending_since` is updated to approximately "now"
   - A message was published to `notify:telegram`
   - Audit log has a "requeued" entry

6. **`test_scheduler_error_isolation`** -- Mock one action to raise an exception. Run the scheduler tick. Verify other actions still execute.

---

## Running Tests

```bash
# From project root
pip install -e ./shared
pip install -e ./core
pip install pytest pytest-asyncio httpx fakeredis

pytest tests/ -v
```

Or via Docker:
```bash
docker compose exec core pytest /app/tests/ -v
```

---

## Acceptance Criteria

1. All test files exist and are discoverable by pytest
2. `pytest tests/` runs without errors
3. Database tests verify schema correctness and migration idempotency
4. Memory tests cover create (text + image), get, update, delete, tags, and audit
5. Task tests cover CRUD and recurring task auto-creation with drift prevention
6. Reminder tests cover CRUD and upcoming-only filter
7. Event tests cover create, confirm (with auto-reminder), and reject
8. Search tests verify FTS5 matching, pin boost, tag search, and owner filter
9. Settings tests verify defaults and updates
10. Audit tests verify entries are created and filterable
11. Scheduler tests verify all four actions and error isolation
