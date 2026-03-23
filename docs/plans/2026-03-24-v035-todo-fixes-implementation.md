# v0.3.5 TODO Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete four items for v0.3.5: changelog update, reminder pipeline debug/fix, Telegram button cleanup, and webapp event fields display.

**Architecture:** All changes are within existing modules. No new files except tests. Telegram callback handler gets button removal for the `review` action (the only one missing it). Webapp templates get conditional event_fields display. Router gets event_fields form handling.

**Tech Stack:** Python 3.12, python-telegram-bot, FastAPI, Jinja2, HTMX, SQLite, pytest

---

### Task 1: Update CHANGELOG.md for v0.3.4

**Files:**
- Modify: `CHANGELOG.md:8` (insert new section above v0.3.3)

**Step 1: Add v0.3.4 changelog entry**

Insert the following between line 7 and the existing `## [0.3.3]` entry:

```markdown
## [0.3.4] - 2026-03-23

### Added

- `llm_max_tokens` config setting to control token budget for LLM calls (default: 4096)

### Fixed

- Webapp root `/` now redirects to `/webapp/login` when webapp is enabled
- LLM response handling for reasoning models (e.g., Qwen3.5) that put JSON in `reasoning_content` instead of `content` -- added `_get_content()` helper in LLM client
- Triage LLM calls now respect `llm_max_tokens` to prevent reasoning models from exhausting token budget on thinking
```

Also add at the bottom with the other release links:
```markdown
[0.3.4]: https://github.com/jhyoong/BearMemori/releases/tag/v0.3.4
```

**Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add v0.3.4 changelog entry"
```

---

### Task 2: Add debug logging to reminder time pipeline

**Files:**
- Modify: `bearmemori/llm/client.py:149-163` (extract_memory)
- Modify: `bearmemori/core/processor.py:111-152` (_create_pending)

**Step 1: Add logging after LLM extraction in `llm/client.py`**

In `extract_memory()`, after line 162 (`data = extract_json(raw)`), add:

```python
logger.debug("Extracted data event_fields: %s", data.get("event_fields"))
```

**Step 2: Add logging in `processor.py` `_create_pending()`**

After line 119 (`if extraction.event_fields:`), add logging before and after:

```python
logger.debug(
    "Extraction event_fields (raw): %s (type: %s)",
    extraction.event_fields,
    type(extraction.event_fields).__name__,
)
```

After the `EventFields` construction (line 120), add:

```python
logger.debug("Constructed EventFields: %s", event_fields)
```

**Step 3: Commit**

```bash
git add bearmemori/llm/client.py bearmemori/core/processor.py
git commit -m "fix: add debug logging to reminder time pipeline"
```

---

### Task 3: Fix Telegram review callback -- remove inline buttons

**Files:**
- Modify: `bearmemori/interfaces/telegram.py:125-133`
- Test: `tests/test_telegram.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_callback_review_removes_buttons_and_updates_text(interface, bus):
    confirmed = []
    bus.on(MemoryConfirmed, lambda e: confirmed.append(e))

    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "review:pend_abc123"
    query.message = AsyncMock()
    query.message.text = "Memory Preview\n\nTitle: Test\nCategory: reminder\nContent: Test content"

    update = _make_update()
    update.callback_query = query

    await interface._handle_callback(update, MagicMock())

    assert len(confirmed) == 1
    assert confirmed[0].needs_review is True
    query.message.edit_text.assert_called_once()
    call_args = query.message.edit_text.call_args
    assert "Saved for review" in call_args[0][0]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_callback_review_removes_buttons_and_updates_text -v`
Expected: FAIL -- `edit_text` was not called

**Step 3: Fix the review callback in `telegram.py`**

Replace lines 125-133 (the `elif action == "review":` block) with:

```python
elif action == "review":
    await self._bus.emit(
        MemoryConfirmed(
            pending_id=pending_id,
            source_chat_id=chat_id,
            needs_review=True,
        )
    )
    await query.message.edit_text(query.message.text + "\n\nSaved for review.")
    await query.answer("Saved for review")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "fix: remove inline buttons after review callback"
```

---

### Task 4: Add event_fields to webapp memory list

**Files:**
- Modify: `bearmemori/webapp/templates/partials/memory_table.html`

**Step 1: Write the failing test**

Add to `tests/test_webapp.py`:

```python
def test_memory_list_shows_event_datetime(authed_webapp_client, db):
    from bearmemori.storage.models import EventFields

    record = MemoryRecord(
        id="mem_reminder1",
        category=MemoryCategory.REMINDER,
        title="Take meds",
        content="Take meds every 8 hours",
        created_at=datetime.now(UTC),
        tags=["health"],
        event_fields=EventFields(
            datetime="2026-03-25T15:00:00",
            status="pending",
            recurrence="every 8 hours",
        ),
    )
    db.create(record)
    response = authed_webapp_client.get("/webapp/memories")
    assert response.status_code == 200
    assert "2026-03-25" in response.text
    assert "pending" in response.text.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_webapp.py::test_memory_list_shows_event_datetime -v`
Expected: FAIL -- datetime not in response text

**Step 3: Update memory_table.html to show event_fields**

In `bearmemori/webapp/templates/partials/memory_table.html`, update the title cell (line 17) to include event info below the title:

```html
<td>
    <a href="/webapp/memories/{{ memory.id }}">{{ memory.title }}</a>
    {% if memory.event_fields %}
    <br><small>Due: {{ memory.event_fields.datetime }} | <mark>{{ memory.event_fields.status }}</mark></small>
    {% endif %}
</td>
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_webapp.py::test_memory_list_shows_event_datetime -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/webapp/templates/partials/memory_table.html tests/test_webapp.py
git commit -m "feat: show event datetime and status in memory list"
```

---

### Task 5: Add editable event_fields to webapp memory detail

**Files:**
- Modify: `bearmemori/webapp/templates/memory_detail.html`
- Modify: `bearmemori/webapp/router.py:165-186` (memory_update)
- Test: `tests/test_webapp.py`

**Step 1: Write the failing test for displaying event_fields**

Add to `tests/test_webapp.py`:

```python
def test_memory_detail_shows_event_fields(authed_webapp_client, db):
    from bearmemori.storage.models import EventFields

    record = MemoryRecord(
        id="mem_reminder2",
        category=MemoryCategory.REMINDER,
        title="Dentist appointment",
        content="Dentist at 3pm",
        created_at=datetime.now(UTC),
        tags=["health"],
        event_fields=EventFields(
            datetime="2026-03-25T15:00:00",
            status="pending",
            recurrence=None,
        ),
    )
    db.create(record)
    response = authed_webapp_client.get("/webapp/memories/mem_reminder2")
    assert response.status_code == 200
    assert "2026-03-25T15:00" in response.text
    assert "pending" in response.text.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_webapp.py::test_memory_detail_shows_event_fields -v`
Expected: FAIL -- datetime not in response text

**Step 3: Add event_fields to memory_detail.html**

After the "Needs Review" checkbox (line 26) and before the button grid (line 28), add:

```html
<fieldset id="event-fields" {% if not memory.event_fields and memory.category not in ['event', 'task', 'reminder'] %}style="display:none"{% endif %}>
    <legend>Event / Reminder Fields</legend>

    <label for="event_datetime">Date & Time</label>
    <input type="datetime-local" id="event_datetime" name="event_datetime"
           value="{{ memory.event_fields.datetime[:16] if memory.event_fields else '' }}">

    <label for="event_status">Status</label>
    <select id="event_status" name="event_status">
        <option value="pending" {% if memory.event_fields and memory.event_fields.status == 'pending' %}selected{% endif %}>pending</option>
        <option value="done" {% if memory.event_fields and memory.event_fields.status == 'done' %}selected{% endif %}>done</option>
    </select>

    <label for="event_recurrence">Recurrence</label>
    <input type="text" id="event_recurrence" name="event_recurrence"
           value="{{ memory.event_fields.recurrence or '' if memory.event_fields else '' }}"
           placeholder="e.g., every 8 hours, daily, weekly">
</fieldset>
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_webapp.py::test_memory_detail_shows_event_fields -v`
Expected: PASS

**Step 5: Write the failing test for updating event_fields**

Add to `tests/test_webapp.py`:

```python
def test_memory_update_saves_event_fields(authed_webapp_client, db):
    from bearmemori.storage.models import EventFields

    record = MemoryRecord(
        id="mem_reminder3",
        category=MemoryCategory.REMINDER,
        title="Take meds",
        content="Take meds",
        created_at=datetime.now(UTC),
        tags=["health"],
    )
    db.create(record)
    response = authed_webapp_client.post(
        "/webapp/memories/mem_reminder3",
        data={
            "title": "Take meds",
            "category": "reminder",
            "content": "Take meds every 8 hours",
            "tags": "health",
            "event_datetime": "2026-03-25T15:00",
            "event_status": "pending",
            "event_recurrence": "every 8 hours",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    updated = db.get("mem_reminder3")
    assert updated.event_fields is not None
    assert updated.event_fields.datetime == "2026-03-25T15:00"
    assert updated.event_fields.status == "pending"
    assert updated.event_fields.recurrence == "every 8 hours"


def test_memory_update_clears_event_fields_when_empty(authed_webapp_client, db):
    from bearmemori.storage.models import EventFields

    record = MemoryRecord(
        id="mem_reminder4",
        category=MemoryCategory.REMINDER,
        title="Take meds",
        content="Take meds",
        created_at=datetime.now(UTC),
        tags=["health"],
        event_fields=EventFields(
            datetime="2026-03-25T15:00:00",
            status="pending",
            recurrence=None,
        ),
    )
    db.create(record)
    response = authed_webapp_client.post(
        "/webapp/memories/mem_reminder4",
        data={
            "title": "Take meds",
            "category": "general",
            "content": "Take meds",
            "tags": "health",
            "event_datetime": "",
            "event_status": "pending",
            "event_recurrence": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    updated = db.get("mem_reminder4")
    assert updated.event_fields is None
```

**Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/test_webapp.py::test_memory_update_saves_event_fields tests/test_webapp.py::test_memory_update_clears_event_fields_when_empty -v`
Expected: FAIL -- event_fields not being read from form

**Step 7: Update router.py memory_update to handle event_fields**

In `bearmemori/webapp/router.py`, modify the `memory_update` function signature (lines 166-174) to add the new form parameters:

```python
@r.post("/memories/{record_id}")
async def memory_update(
    request: Request,
    record_id: str,
    title: str = Form(...),
    category: str = Form(...),
    content: str = Form(...),
    tags: str = Form(""),
    needs_review: bool = Form(False),
    event_datetime: str = Form(""),
    event_status: str = Form("pending"),
    event_recurrence: str = Form(""),
):
```

Then after `record.needs_review = needs_review` (line 183), add:

```python
if event_datetime:
    record.event_fields = EventFields(
        datetime=event_datetime,
        status=event_status,
        recurrence=event_recurrence if event_recurrence else None,
    )
else:
    record.event_fields = None
```

Also add the import at the top of the file (line 10):

```python
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord
```

(Add `EventFields` to the existing import.)

**Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_webapp.py -v`
Expected: All tests PASS

**Step 9: Commit**

```bash
git add bearmemori/webapp/templates/memory_detail.html bearmemori/webapp/router.py tests/test_webapp.py
git commit -m "feat: add editable event_fields to webapp memory detail"
```

---

### Task 6: Run full test suite and verify

**Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 2: Run linter**

Run: `uv run ruff check .`
Expected: No errors

**Step 3: Run formatter**

Run: `uv run ruff format --check .`
Expected: No formatting issues (or run `uv run ruff format .` to fix)
