# Calendar System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a full calendar system with month/week views, RRULE recurrence, and per-occurrence management to the BearMemori webapp.

**Architecture:** New `recurrence.py` service module handles RRULE expansion and form helpers. Storage gains `get_events_in_range()`. The webapp adds three routes (`/webapp/calendar`, `/webapp/calendar/grid`, `/webapp/calendar/occurrence/toggle`) rendered with Jinja2 + HTMX. No new JS libraries; all interactivity via HTMX and minimal inline scripts.

**Tech Stack:** Python 3.12+, python-dateutil (RRULE), FastAPI, Jinja2, HTMX, Pico CSS, SQLite, uv

---

### Task 1: Add python-dateutil dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add the dependency**

In `pyproject.toml`, find the `dependencies` list and add `"python-dateutil>=2.9"`.

**Step 2: Sync**

```bash
uv sync
```
Expected: resolves and installs `python-dateutil`.

**Step 3: Verify import works**

```bash
uv run python -c "from dateutil import rrule; print('ok')"
```
Expected: prints `ok`.

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add python-dateutil dependency"
```

---

### Task 2: CalendarOccurrence model + non-recurring expand_occurrences

**Files:**
- Create: `bearmemori/core/recurrence.py`
- Create: `tests/core/test_recurrence.py`

**Step 1: Write the failing test**

Create `tests/core/test_recurrence.py`:

```python
from datetime import UTC, datetime

import pytest

from bearmemori.core.recurrence import CalendarOccurrence, expand_occurrences
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord


def _make_record(event_dt: str, recurrence: str | None = None, status: str = "pending") -> MemoryRecord:
    return MemoryRecord(
        id="mem_test001",
        category=MemoryCategory.EVENT,
        title="Test Event",
        content="Test content",
        created_at=datetime.now(UTC),
        event_fields=EventFields(datetime=event_dt, status=status, recurrence=recurrence),
    )


def test_expand_non_recurring_in_range():
    record = _make_record("2026-04-10T10:00:00+00:00")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert len(result) == 1
    assert result[0].memory_id == "mem_test001"
    assert result[0].status == "pending"
    assert result[0].is_recurring is False
    assert result[0].occurrence_dt == datetime(2026, 4, 10, 10, 0, 0, tzinfo=UTC)


def test_expand_non_recurring_out_of_range():
    record = _make_record("2026-05-10T10:00:00+00:00")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert result == []


def test_expand_no_event_fields():
    record = MemoryRecord(
        id="mem_test002",
        category=MemoryCategory.GENERAL,
        title="No event",
        content="content",
        created_at=datetime.now(UTC),
    )
    result = expand_occurrences(record, datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 30, tzinfo=UTC))
    assert result == []


def test_expand_non_recurring_done_status():
    record = _make_record("2026-04-10T10:00:00+00:00", status="done")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert len(result) == 1
    assert result[0].status == "done"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_recurrence.py -v
```
Expected: `ImportError` or `ModuleNotFoundError` -- `recurrence` does not exist yet.

**Step 3: Create `bearmemori/core/recurrence.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from bearmemori.storage.models import MemoryRecord


class CalendarOccurrence(BaseModel):
    memory_id: str
    title: str
    category: str
    occurrence_dt: datetime
    status: str  # "pending" or "done"
    is_recurring: bool


def expand_occurrences(
    record: "MemoryRecord",
    start: datetime,
    end: datetime,
) -> list[CalendarOccurrence]:
    if record.event_fields is None:
        return []

    if not record.event_fields.recurrence:
        occ_dt = datetime.fromisoformat(record.event_fields.datetime)
        if start <= occ_dt <= end:
            return [
                CalendarOccurrence(
                    memory_id=record.id,
                    title=record.title,
                    category=record.category.value,
                    occurrence_dt=occ_dt,
                    status=record.event_fields.status,
                    is_recurring=False,
                )
            ]
        return []

    return _expand_recurring(record, start, end)


def _expand_recurring(
    record: "MemoryRecord",
    start: datetime,
    end: datetime,
) -> list[CalendarOccurrence]:
    # Placeholder -- implemented in Task 3
    return []


def parse_rrule_to_form(rrule_str: str) -> dict:
    # Placeholder -- implemented in Task 4
    return {}


def build_rrule_from_form(**kwargs) -> str:
    # Placeholder -- implemented in Task 4
    return ""
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/core/test_recurrence.py -v
```
Expected: all 4 tests PASS.

**Step 5: Commit**

```bash
git add bearmemori/core/recurrence.py tests/core/test_recurrence.py
git commit -m "feat: add CalendarOccurrence model and non-recurring expand_occurrences"
```

---

### Task 3: Recurring expand_occurrences

**Files:**
- Modify: `bearmemori/core/recurrence.py`
- Modify: `tests/core/test_recurrence.py`

**Step 1: Add failing tests**

Append to `tests/core/test_recurrence.py`:

```python
def test_expand_weekly_recurring_in_range():
    # Every Tuesday starting 2026-04-07
    record = _make_record("2026-04-07T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    # Tuesdays in April 2026: Apr 7, 14, 21, 28
    assert len(result) == 4
    assert all(occ.is_recurring for occ in result)
    assert all(occ.status == "pending" for occ in result)
    assert result[0].occurrence_dt.day == 7
    assert result[1].occurrence_dt.day == 14
    assert result[2].occurrence_dt.day == 21
    assert result[3].occurrence_dt.day == 28


def test_expand_recurring_with_completed_occurrences():
    record = _make_record("2026-04-07T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU")
    record.metadata["completed_occurrences"] = ["2026-04-07", "2026-04-14"]
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert len(result) == 4
    assert result[0].status == "done"
    assert result[1].status == "done"
    assert result[2].status == "pending"
    assert result[3].status == "pending"


def test_expand_recurring_invalid_rrule_returns_empty():
    record = _make_record("2026-04-07T10:00:00+00:00", recurrence="NOT_A_VALID_RRULE")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert result == []


def test_expand_recurring_no_occurrences_in_range():
    # Every year on Jan 1, range is April
    record = _make_record("2026-01-01T10:00:00+00:00", recurrence="FREQ=YEARLY")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert result == []
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/core/test_recurrence.py::test_expand_weekly_recurring_in_range -v
```
Expected: FAIL -- `_expand_recurring` returns empty list.

**Step 3: Implement `_expand_recurring`**

Replace the `_expand_recurring` placeholder in `bearmemori/core/recurrence.py`:

```python
def _expand_recurring(
    record: "MemoryRecord",
    start: datetime,
    end: datetime,
) -> list[CalendarOccurrence]:
    from dateutil import rrule as rrulelib

    completed = set(record.metadata.get("completed_occurrences", []))
    base_dt = datetime.fromisoformat(record.event_fields.datetime)

    try:
        rule = rrulelib.rrulestr(record.event_fields.recurrence, dtstart=base_dt)
    except Exception:
        return []

    occurrences = []
    for occ_dt in rule.between(start, end, inc=True):
        occ_date_str = occ_dt.date().isoformat()
        status = "done" if occ_date_str in completed else "pending"
        occurrences.append(
            CalendarOccurrence(
                memory_id=record.id,
                title=record.title,
                category=record.category.value,
                occurrence_dt=occ_dt,
                status=status,
                is_recurring=True,
            )
        )

    return occurrences
```

**Step 4: Run all recurrence tests**

```bash
uv run pytest tests/core/test_recurrence.py -v
```
Expected: all tests PASS.

**Step 5: Commit**

```bash
git add bearmemori/core/recurrence.py tests/core/test_recurrence.py
git commit -m "feat: implement recurring occurrence expansion with RRULE"
```

---

### Task 4: RRULE form helpers

**Files:**
- Modify: `bearmemori/core/recurrence.py`
- Modify: `tests/core/test_recurrence.py`

**Step 1: Add failing tests**

Append to `tests/core/test_recurrence.py`:

```python
from bearmemori.core.recurrence import build_rrule_from_form, parse_rrule_to_form


def test_parse_rrule_weekly_byday():
    result = parse_rrule_to_form("FREQ=WEEKLY;BYDAY=TU,TH;INTERVAL=2")
    assert result["freq"] == "weekly"
    assert result["interval"] == 2
    assert set(result["byday"]) == {"TU", "TH"}


def test_parse_rrule_monthly():
    result = parse_rrule_to_form("FREQ=MONTHLY;BYMONTHDAY=15")
    assert result["freq"] == "monthly"
    assert result["bymonthday"] == "15"


def test_parse_rrule_empty():
    result = parse_rrule_to_form("")
    assert result["freq"] == ""


def test_build_rrule_weekly():
    result = build_rrule_from_form(freq="weekly", interval=1, byday=["MO", "WE", "FR"])
    assert result == "FREQ=WEEKLY;BYDAY=MO,WE,FR"


def test_build_rrule_monthly_with_until():
    result = build_rrule_from_form(freq="monthly", interval=1, bymonthday="1", until="20261231T000000Z")
    assert result == "FREQ=MONTHLY;BYMONTHDAY=1;UNTIL=20261231T000000Z"


def test_build_rrule_empty_freq_returns_empty():
    result = build_rrule_from_form(freq="")
    assert result == ""


def test_rrule_round_trip():
    original = "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU"
    form = parse_rrule_to_form(original)
    rebuilt = build_rrule_from_form(
        freq=form["freq"],
        interval=form["interval"],
        byday=form["byday"],
    )
    assert rebuilt == original
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/core/test_recurrence.py -k "parse_rrule or build_rrule" -v
```
Expected: FAIL -- placeholders return empty dicts/strings.

**Step 3: Implement the helpers**

Replace both placeholder functions in `bearmemori/core/recurrence.py`:

```python
def parse_rrule_to_form(rrule_str: str) -> dict:
    """Parse an RRULE string into form field values."""
    if not rrule_str:
        return {
            "freq": "",
            "interval": 1,
            "byday": [],
            "bymonthday": "",
            "until": "",
            "count": "",
        }

    parts: dict[str, str] = {}
    for part in rrule_str.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k.upper()] = v

    return {
        "freq": parts.get("FREQ", "").lower(),
        "interval": int(parts.get("INTERVAL", 1)),
        "byday": parts.get("BYDAY", "").split(",") if parts.get("BYDAY") else [],
        "bymonthday": parts.get("BYMONTHDAY", ""),
        "until": parts.get("UNTIL", ""),
        "count": parts.get("COUNT", ""),
    }


def build_rrule_from_form(
    freq: str,
    interval: int = 1,
    byday: list[str] | None = None,
    bymonthday: str = "",
    until: str = "",
    count: str = "",
) -> str:
    """Build an RRULE string from form field values."""
    if not freq:
        return ""

    parts = [f"FREQ={freq.upper()}"]
    if interval and int(interval) > 1:
        parts.append(f"INTERVAL={int(interval)}")
    if byday:
        filtered = [d for d in byday if d]
        if filtered:
            parts.append(f"BYDAY={','.join(filtered)}")
    if bymonthday:
        parts.append(f"BYMONTHDAY={bymonthday}")
    if until:
        parts.append(f"UNTIL={until}")
    elif count:
        parts.append(f"COUNT={count}")

    return ";".join(parts)
```

**Step 4: Run all recurrence tests**

```bash
uv run pytest tests/core/test_recurrence.py -v
```
Expected: all tests PASS.

**Step 5: Commit**

```bash
git add bearmemori/core/recurrence.py tests/core/test_recurrence.py
git commit -m "feat: add RRULE form helpers parse_rrule_to_form and build_rrule_from_form"
```

---

### Task 5: Database -- get_events_in_range

**Files:**
- Modify: `bearmemori/storage/database.py`
- Create: `tests/storage/test_database_calendar.py`

**Step 1: Write failing test**

Create `tests/storage/test_database_calendar.py`:

```python
import tempfile
from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        d = MemoryDatabase(f.name)
        d.initialize()
        yield d


def _event_record(record_id: str, dt: str, recurrence: str | None = None, category=MemoryCategory.EVENT) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=category,
        title=f"Event {record_id}",
        content="content",
        created_at=datetime.now(UTC),
        event_fields=EventFields(datetime=dt, status="pending", recurrence=recurrence),
    )


def test_get_events_in_range_non_recurring(db):
    db.create(_event_record("mem_001", "2026-04-10T10:00:00+00:00"))
    db.create(_event_record("mem_002", "2026-05-10T10:00:00+00:00"))  # outside range

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_001" in ids
    assert "mem_002" not in ids


def test_get_events_in_range_includes_recurring_starting_before_range(db):
    # Recurring weekly starting in March -- should appear in April range
    db.create(_event_record("mem_003", "2026-03-03T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU"))

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_003" in ids


def test_get_events_in_range_excludes_done_recurring(db):
    r = _event_record("mem_004", "2026-03-03T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU")
    r.event_fields.status = "done"
    db.create(r)

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_004" not in ids


def test_get_events_in_range_only_event_task_reminder(db):
    db.create(_event_record("mem_005", "2026-04-10T10:00:00+00:00", category=MemoryCategory.GENERAL))

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_005" not in ids
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/storage/test_database_calendar.py -v
```
Expected: `AttributeError` -- `get_events_in_range` does not exist.

**Step 3: Add `get_events_in_range` to `MemoryDatabase`**

Add after `get_due_events` in `bearmemori/storage/database.py`:

```python
def get_events_in_range(self, start: datetime, end: datetime) -> list[MemoryRecord]:
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    rows = self._conn.execute(
        """SELECT * FROM memories
           WHERE category IN ('event', 'reminder', 'task')
             AND (
               (event_recurrence IS NULL
                AND event_datetime IS NOT NULL
                AND event_datetime >= ?
                AND event_datetime <= ?)
               OR
               (event_recurrence IS NOT NULL
                AND event_datetime <= ?
                AND (event_status IS NULL OR event_status = 'pending'))
             )
           ORDER BY event_datetime ASC""",
        (start_iso, end_iso, end_iso),
    ).fetchall()
    return [self._row_to_record(r) for r in rows]
```

**Step 4: Run tests**

```bash
uv run pytest tests/storage/test_database_calendar.py -v
```
Expected: all PASS.

**Step 5: Run full test suite to check for regressions**

```bash
uv run pytest -v
```
Expected: all existing tests still PASS.

**Step 6: Commit**

```bash
git add bearmemori/storage/database.py tests/storage/test_database_calendar.py
git commit -m "feat: add get_events_in_range to MemoryDatabase"
```

---

### Task 6: Scheduler -- recurring event handling

**Files:**
- Modify: `bearmemori/core/scheduler.py`
- Create: `tests/core/test_scheduler_recurring.py`

**Step 1: Write failing test**

Create `tests/core/test_scheduler_recurring.py`:

```python
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        d = MemoryDatabase(f.name)
        d.initialize()
        yield d


@pytest.fixture
def bus():
    b = MagicMock(spec=EventBus)
    b.emit = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_recurring_fires_due_occurrence_and_marks_completed(db, bus):
    # Weekly on Tuesday, base dt is last Tuesday (already due)
    past_tuesday = datetime(2026, 3, 31, 10, 0, 0, tzinfo=UTC)  # a Tuesday
    record = MemoryRecord(
        id="mem_rec001",
        category=MemoryCategory.REMINDER,
        title="Weekly standup",
        content="Do the standup",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime=past_tuesday.isoformat(),
            status="pending",
            recurrence="FREQ=WEEKLY;BYDAY=TU",
        ),
    )
    db.create(record)

    scheduler = ReminderScheduler(bus, db)
    await scheduler.check_reminders()

    bus.emit.assert_called_once()
    event = bus.emit.call_args[0][0]
    assert isinstance(event, ReminderDue)
    assert event.memory_id == "mem_rec001"

    # Record should have completed_occurrences set, status still pending
    updated = db.get("mem_rec001")
    assert updated.event_fields.status == "pending"
    assert "2026-03-31" in updated.metadata.get("completed_occurrences", [])


@pytest.mark.asyncio
async def test_recurring_does_not_refire_completed_occurrence(db, bus):
    past_tuesday = datetime(2026, 3, 31, 10, 0, 0, tzinfo=UTC)
    record = MemoryRecord(
        id="mem_rec002",
        category=MemoryCategory.REMINDER,
        title="Weekly standup",
        content="Do the standup",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime=past_tuesday.isoformat(),
            status="pending",
            recurrence="FREQ=WEEKLY;BYDAY=TU",
        ),
        metadata={"completed_occurrences": ["2026-03-31"]},
    )
    db.create(record)

    scheduler = ReminderScheduler(bus, db)
    await scheduler.check_reminders()

    bus.emit.assert_not_called()


@pytest.mark.asyncio
async def test_non_recurring_still_marks_done(db, bus):
    record = MemoryRecord(
        id="mem_single001",
        category=MemoryCategory.REMINDER,
        title="One-time reminder",
        content="Do the thing",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            status="pending",
        ),
    )
    db.create(record)

    scheduler = ReminderScheduler(bus, db)
    await scheduler.check_reminders()

    bus.emit.assert_called_once()
    updated = db.get("mem_single001")
    assert updated.event_fields.status == "done"
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/core/test_scheduler_recurring.py -v
```
Expected: `test_recurring_fires_due_occurrence_and_marks_completed` FAILS (currently marks status=done instead of adding to completed_occurrences), `test_non_recurring_still_marks_done` should PASS.

**Step 3: Refactor `scheduler.py`**

Replace the contents of `bearmemori/core/scheduler.py`:

```python
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from bearmemori.core.recurrence import expand_occurrences
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
        due = self._db.get_due_events()
        for record in due:
            if record.event_fields and record.event_fields.recurrence:
                await self._handle_recurring(record)
            else:
                await self._handle_single(record)

    async def _handle_single(self, record) -> None:
        source_chat_id = self._get_chat_id(record)
        remind_at_iso = record.event_fields.datetime if record.event_fields else ""
        await self._bus.emit(
            ReminderDue(
                memory_id=record.id,
                content=record.content,
                source_chat_id=source_chat_id,
                remind_at_iso=remind_at_iso,
            )
        )
        if record.event_fields:
            record.event_fields = EventFields(
                datetime=record.event_fields.datetime,
                status="done",
                recurrence=record.event_fields.recurrence,
            )
        self._db.update(record)
        logger.info("Fired single reminder %s: %s", record.id, record.content[:80])

    async def _handle_recurring(self, record) -> None:
        now = datetime.now(UTC)
        # Check the last 25 hours to find any occurrence that just became due
        window_start = now - timedelta(hours=25)
        occurrences = expand_occurrences(record, window_start, now)

        fired = False
        for occ in occurrences:
            if occ.status == "done":
                continue
            source_chat_id = self._get_chat_id(record)
            await self._bus.emit(
                ReminderDue(
                    memory_id=record.id,
                    content=record.content,
                    source_chat_id=source_chat_id,
                    remind_at_iso=occ.occurrence_dt.isoformat(),
                )
            )
            completed = list(record.metadata.get("completed_occurrences", []))
            occ_date_str = occ.occurrence_dt.date().isoformat()
            if occ_date_str not in completed:
                completed.append(occ_date_str)
            record.metadata["completed_occurrences"] = completed
            self._db.update(record)
            fired = True
            logger.info("Fired recurring reminder %s occurrence %s", record.id, occ_date_str)

        if not fired:
            logger.debug("Recurring reminder %s has no unfired due occurrences", record.id)

    def _get_chat_id(self, record) -> str:
        if record.source:
            return record.source.chat_id
        return record.metadata.get("source_chat_id", "")

    async def run(self) -> None:
        logger.info("Reminder scheduler started (poll every %ds)", self._poll_interval)
        while True:
            try:
                await self.check_reminders()
            except Exception:
                logger.exception("Error checking reminders")
            await asyncio.sleep(self._poll_interval)
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_scheduler_recurring.py -v
```
Expected: all 3 PASS.

**Step 5: Run full test suite**

```bash
uv run pytest -v
```
Expected: all tests PASS.

**Step 6: Commit**

```bash
git add bearmemori/core/scheduler.py tests/core/test_scheduler_recurring.py
git commit -m "feat: handle recurring reminders in scheduler with per-occurrence tracking"
```

---

### Task 7: API -- extend /memory/events/upcoming with start/end params

**Files:**
- Modify: `bearmemori/api/routes.py`
- Modify: `tests/api/test_routes.py` (or create if it doesn't exist)

**Step 1: Check if API tests exist**

```bash
ls tests/api/
```

If `test_routes.py` exists, append to it. If the directory doesn't exist, create `tests/api/__init__.py` and `tests/api/test_routes.py`.

**Step 2: Write failing test**

Add to the API test file:

```python
import tempfile
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore
from unittest.mock import MagicMock


@pytest.fixture
def test_client():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = MemoryDatabase(f.name)
        db.initialize()
        vs = MagicMock(spec=VectorStore)
        vs.search.return_value = []
        ps = PendingStore()
        app = create_app(db=db, vector_store=vs, pending_store=ps)
        yield TestClient(app), db


def test_upcoming_events_with_start_end_returns_occurrences(test_client):
    client, db = test_client
    # Create a weekly recurring event
    record = MemoryRecord(
        id="mem_api001",
        category=MemoryCategory.EVENT,
        title="Weekly meeting",
        content="Team sync",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime="2026-04-07T10:00:00+00:00",
            status="pending",
            recurrence="FREQ=WEEKLY;BYDAY=TU",
        ),
    )
    db.create(record)

    response = client.get(
        "/memory/events/upcoming",
        params={"start": "2026-04-01T00:00:00+00:00", "end": "2026-04-30T23:59:59+00:00"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "occurrences" in data
    assert len(data["occurrences"]) == 4  # 4 Tuesdays in April 2026


def test_upcoming_events_without_start_end_no_occurrences_field(test_client):
    client, db = test_client
    response = client.get("/memory/events/upcoming", params={"days": 7})
    assert response.status_code == 200
    data = response.json()
    assert "occurrences" not in data
    assert "events" in data
```

**Step 3: Run to verify they fail**

```bash
uv run pytest tests/api/ -k "start_end" -v
```
Expected: FAIL -- `occurrences` key missing from response.

**Step 4: Update the route in `bearmemori/api/routes.py`**

Replace the `get_upcoming_events` route:

```python
@app.get("/memory/events/upcoming")
def get_upcoming_events(days: int = 7, start: str | None = None, end: str | None = None):
    from bearmemori.core.recurrence import expand_occurrences

    if start and end:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start or end datetime format")
        records = db.get_events_in_range(start_dt, end_dt)
        occurrences = []
        for r in records:
            occurrences.extend(expand_occurrences(r, start_dt, end_dt))
        return {
            "events": [e.model_dump(mode="json") for e in records],
            "occurrences": [o.model_dump(mode="json") for o in occurrences],
        }

    events = db.get_upcoming_events(days=days)
    return {"events": [e.model_dump(mode="json") for e in events]}
```

**Step 5: Run tests**

```bash
uv run pytest tests/api/ -v
```
Expected: all PASS.

**Step 6: Run full test suite**

```bash
uv run pytest -v
```
Expected: all PASS.

**Step 7: Commit**

```bash
git add bearmemori/api/routes.py tests/api/
git commit -m "feat: extend /memory/events/upcoming with start/end params and occurrence expansion"
```

---

### Task 8: Webapp -- calendar routes

**Files:**
- Modify: `bearmemori/webapp/router.py`

**Step 1: Add helper function and three new routes**

In `bearmemori/webapp/router.py`, add the following imports at the top of the file:

```python
import calendar as cal_module
from collections import defaultdict
```

Then add the following helper and routes inside `create_webapp_router`, after the existing routes and before `return r`:

```python
def _build_calendar_context(view: str, year: int, month: int, week_start_str: str | None):
    from bearmemori.core.recurrence import expand_occurrences

    today = datetime.now(UTC).date()

    if view == "week":
        from datetime import date, timedelta
        if week_start_str:
            ws = date.fromisoformat(week_start_str)
        else:
            ws = today - timedelta(days=today.weekday())
        we = ws + timedelta(days=6)
        start_dt = datetime(ws.year, ws.month, ws.day, tzinfo=UTC)
        end_dt = datetime(we.year, we.month, we.day, 23, 59, 59, tzinfo=UTC)

        prev_ws = (ws - timedelta(days=7)).isoformat()
        next_ws = (ws + timedelta(days=7)).isoformat()

        records = db.get_events_in_range(start_dt, end_dt)
        all_occs = []
        for rec in records:
            all_occs.extend(expand_occurrences(rec, start_dt, end_dt))

        by_date = defaultdict(list)
        for occ in all_occs:
            local_iso = utc_to_local_iso(occ.occurrence_dt.isoformat(), user_timezone)
            occ_date = datetime.fromisoformat(local_iso).date().isoformat()
            by_date[occ_date].append({
                "memory_id": occ.memory_id,
                "title": occ.title,
                "category": occ.category,
                "time": datetime.fromisoformat(local_iso).strftime("%H:%M"),
                "status": occ.status,
                "is_recurring": occ.is_recurring,
                "occurrence_date": occ.occurrence_dt.date().isoformat(),
            })

        days = []
        for i in range(7):
            from datetime import timedelta as td
            d = ws + td(days=i)
            days.append({
                "date": d.isoformat(),
                "label": d.strftime("%a %-d"),
                "occurrences": by_date.get(d.isoformat(), []),
            })

        return {
            "view": "week",
            "week_start": ws.isoformat(),
            "days": days,
            "prev_url": f"/webapp/calendar/grid?view=week&week_start={prev_ws}",
            "next_url": f"/webapp/calendar/grid?view=week&week_start={next_ws}",
            "today": today.isoformat(),
        }

    else:  # month view
        from datetime import date
        y = year or today.year
        m = month or today.month
        first_day = date(y, m, 1)
        last_day = date(y, m, cal_module.monthrange(y, m)[1])
        start_dt = datetime(y, m, 1, tzinfo=UTC)
        end_dt = datetime(last_day.year, last_day.month, last_day.day, 23, 59, 59, tzinfo=UTC)

        if m == 1:
            prev_url = f"/webapp/calendar/grid?view=month&year={y - 1}&month=12"
        else:
            prev_url = f"/webapp/calendar/grid?view=month&year={y}&month={m - 1}"
        if m == 12:
            next_url = f"/webapp/calendar/grid?view=month&year={y + 1}&month=1"
        else:
            next_url = f"/webapp/calendar/grid?view=month&year={y}&month={m + 1}"

        records = db.get_events_in_range(start_dt, end_dt)
        all_occs = []
        for rec in records:
            all_occs.extend(expand_occurrences(rec, start_dt, end_dt))

        by_date = defaultdict(list)
        for occ in all_occs:
            local_iso = utc_to_local_iso(occ.occurrence_dt.isoformat(), user_timezone)
            occ_date = datetime.fromisoformat(local_iso).date().isoformat()
            by_date[occ_date].append({
                "memory_id": occ.memory_id,
                "title": occ.title,
                "category": occ.category,
                "time": datetime.fromisoformat(local_iso).strftime("%H:%M"),
                "status": occ.status,
                "is_recurring": occ.is_recurring,
                "occurrence_date": occ.occurrence_dt.date().isoformat(),
            })

        # Build weeks grid: list of weeks, each a list of 7 day dicts
        weeks = []
        cal = cal_module.monthcalendar(y, m)
        for week in cal:
            week_days = []
            for day_num in week:
                if day_num == 0:
                    week_days.append(None)
                else:
                    d = date(y, m, day_num)
                    week_days.append({
                        "date": d.isoformat(),
                        "day": day_num,
                        "in_month": True,
                        "occurrences": by_date.get(d.isoformat(), []),
                    })
            weeks.append(week_days)

        return {
            "view": "month",
            "year": y,
            "month": m,
            "month_name": first_day.strftime("%B %Y"),
            "weeks": weeks,
            "prev_url": prev_url,
            "next_url": next_url,
            "today": today.isoformat(),
        }

@r.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request,
    view: str = "month",
    year: int = 0,
    month: int = 0,
    week_start: str | None = None,
):
    today = datetime.now(UTC)
    ctx = _build_calendar_context(
        view,
        year or today.year,
        month or today.month,
        week_start,
    )
    ctx["current_view_url"] = f"/webapp/calendar/grid?view={view}&year={ctx.get('year', '')}&month={ctx.get('month', '')}"
    return templates.TemplateResponse(request, "calendar.html", ctx)


@r.get("/calendar/grid", response_class=HTMLResponse)
async def calendar_grid(
    request: Request,
    view: str = "month",
    year: int = 0,
    month: int = 0,
    week_start: str | None = None,
):
    today = datetime.now(UTC)
    ctx = _build_calendar_context(
        view,
        year or today.year,
        month or today.month,
        week_start,
    )
    return templates.TemplateResponse(request, "partials/calendar_grid.html", ctx)


@r.post("/calendar/occurrence/toggle", response_class=HTMLResponse)
async def toggle_occurrence(
    request: Request,
    memory_id: str = Form(...),
    occurrence_date: str = Form(...),
    view: str = Form("month"),
    year: int = Form(0),
    month: int = Form(0),
    week_start: str = Form(""),
):
    record = db.get(memory_id)
    if record:
        completed = list(record.metadata.get("completed_occurrences", []))
        if occurrence_date in completed:
            completed.remove(occurrence_date)
        else:
            completed.append(occurrence_date)
        record.metadata["completed_occurrences"] = completed
        db.update(record)

    today = datetime.now(UTC)
    ctx = _build_calendar_context(
        view,
        year or today.year,
        month or today.month,
        week_start or None,
    )
    return templates.TemplateResponse(request, "partials/calendar_grid.html", ctx)
```

**Step 2: Manually verify the app starts without errors**

```bash
uv run python -c "
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.vector_store import VectorStore
from bearmemori.webapp.router import create_webapp_router
from bearmemori.webapp.auth import WebappAuthMiddleware
from unittest.mock import MagicMock
import tempfile, os
f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
db = MemoryDatabase(f.name)
db.initialize()
vs = MagicMock(spec=VectorStore)
auth = WebappAuthMiddleware('test')
r = create_webapp_router(db=db, vector_store=vs, auth=auth)
print('Routes:', [str(route.path) for route in r.routes])
os.unlink(f.name)
"
```
Expected: prints route paths including `/webapp/calendar`, `/webapp/calendar/grid`, `/webapp/calendar/occurrence/toggle`.

**Step 3: Commit**

```bash
git add bearmemori/webapp/router.py
git commit -m "feat: add calendar routes to webapp router"
```

---

### Task 9: Templates -- calendar.html and month view grid

**Files:**
- Create: `bearmemori/webapp/templates/calendar.html`
- Create: `bearmemori/webapp/templates/partials/calendar_grid.html`
- Modify: `bearmemori/webapp/templates/base.html`

**Step 1: Add Calendar link to `base.html`**

In `bearmemori/webapp/templates/base.html`, find the nav `<ul>` with links and add:

```html
<li><a href="/webapp/calendar">Calendar</a></li>
```

Place it after the `Memories` link.

**Step 2: Create `calendar.html`**

```html
{% extends "base.html" %}
{% block title %}Calendar - BearMemori{% endblock %}
{% block content %}
<h2>Calendar</h2>

<div style="display:flex; gap:1rem; align-items:center; margin-bottom:1rem;">
    <div role="group">
        <a href="/webapp/calendar?view=month" role="button" {% if view == 'month' %}class="contrast"{% else %}class="secondary"{% endif %}>Month</a>
        <a href="/webapp/calendar?view=week" role="button" {% if view == 'week' %}class="contrast"{% else %}class="secondary"{% endif %}>Week</a>
    </div>
</div>

<div id="calendar-grid">
    {% include "partials/calendar_grid.html" %}
</div>
{% endblock %}
```

**Step 3: Create `partials/calendar_grid.html`**

```html
{% if view == "month" %}
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
    <a href="#" hx-get="{{ prev_url }}" hx-target="#calendar-grid" hx-swap="innerHTML" role="button" class="secondary">&#8249; Prev</a>
    <strong>{{ month_name }}</strong>
    <a href="#" hx-get="{{ next_url }}" hx-target="#calendar-grid" hx-swap="innerHTML" role="button" class="secondary">Next &#8250;</a>
</div>

<table style="width:100%; table-layout:fixed; border-collapse:collapse;">
    <thead>
        <tr>
            {% for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] %}
            <th style="text-align:center; padding:0.25rem; border:1px solid var(--pico-muted-border-color);">{{ day_name }}</th>
            {% endfor %}
        </tr>
    </thead>
    <tbody>
        {% for week in weeks %}
        <tr>
            {% for day in week %}
            {% if day is none %}
            <td style="border:1px solid var(--pico-muted-border-color); height:6rem; vertical-align:top; padding:0.25rem;"></td>
            {% else %}
            <td style="border:1px solid var(--pico-muted-border-color); height:6rem; vertical-align:top; padding:0.25rem; {% if day.date == today %}background: var(--pico-primary-background);{% endif %}">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <small><strong>{{ day.day }}</strong></small>
                    <a href="/webapp/memories/new?event_datetime={{ day.date }}T00:00&return=calendar" style="font-size:0.7rem; text-decoration:none;">+</a>
                </div>
                {% for occ in day.occurrences %}
                <form hx-post="/webapp/calendar/occurrence/toggle" hx-target="#calendar-grid" hx-swap="innerHTML" style="margin:0; padding:0;">
                    <input type="hidden" name="memory_id" value="{{ occ.memory_id }}">
                    <input type="hidden" name="occurrence_date" value="{{ occ.occurrence_date }}">
                    <input type="hidden" name="view" value="month">
                    <input type="hidden" name="year" value="{{ year }}">
                    <input type="hidden" name="month" value="{{ month }}">
                    <button type="submit" style="
                        display:block; width:100%; text-align:left; padding:0.1rem 0.25rem;
                        margin-bottom:0.1rem; font-size:0.7rem; border-radius:3px; cursor:pointer;
                        border:none;
                        background: {% if occ.category == 'reminder' %}var(--pico-color-amber-500){% elif occ.category == 'task' %}var(--pico-color-blue-500){% else %}var(--pico-color-green-500){% endif %};
                        opacity: {% if occ.status == 'done' %}0.5{% else %}1{% endif %};
                        text-decoration: {% if occ.status == 'done' %}line-through{% else %}none{% endif %};
                        color: #fff;
                    " title="{{ occ.time }} - {{ occ.title }}">
                        {{ occ.time }} {{ occ.title|truncate(20, true) }}
                    </button>
                </form>
                {% endfor %}
            </td>
            {% endif %}
            {% endfor %}
        </tr>
        {% endfor %}
    </tbody>
</table>

{% else %}
{# Week view #}
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
    <a href="#" hx-get="{{ prev_url }}" hx-target="#calendar-grid" hx-swap="innerHTML" role="button" class="secondary">&#8249; Prev</a>
    <strong>Week of {{ days[0].date }}</strong>
    <a href="#" hx-get="{{ next_url }}" hx-target="#calendar-grid" hx-swap="innerHTML" role="button" class="secondary">Next &#8250;</a>
</div>

<div style="display:grid; grid-template-columns: repeat(7, 1fr); gap:0.5rem;">
    {% for day in days %}
    <div>
        <div style="text-align:center; padding:0.25rem; border-bottom:1px solid var(--pico-muted-border-color); {% if day.date == today %}font-weight:bold; color:var(--pico-primary);{% endif %}">
            {{ day.label }}<br>
            <a href="/webapp/memories/new?event_datetime={{ day.date }}T00:00&return=calendar" style="font-size:0.7rem; text-decoration:none;">+</a>
        </div>
        {% for occ in day.occurrences %}
        <form hx-post="/webapp/calendar/occurrence/toggle" hx-target="#calendar-grid" hx-swap="innerHTML" style="margin:0.25rem 0; padding:0;">
            <input type="hidden" name="memory_id" value="{{ occ.memory_id }}">
            <input type="hidden" name="occurrence_date" value="{{ occ.occurrence_date }}">
            <input type="hidden" name="view" value="week">
            <input type="hidden" name="week_start" value="{{ week_start }}">
            <button type="submit" style="
                display:block; width:100%; text-align:left; padding:0.25rem 0.4rem;
                font-size:0.75rem; border-radius:4px; cursor:pointer; border:none;
                background: {% if occ.category == 'reminder' %}var(--pico-color-amber-500){% elif occ.category == 'task' %}var(--pico-color-blue-500){% else %}var(--pico-color-green-500){% endif %};
                opacity: {% if occ.status == 'done' %}0.5{% else %}1{% endif %};
                text-decoration: {% if occ.status == 'done' %}line-through{% else %}none{% endif %};
                color: #fff;
            " title="{{ occ.time }} - {{ occ.title }}">
                <small>{{ occ.time }}</small><br>{{ occ.title|truncate(25, true) }}
            </button>
        </form>
        {% endfor %}
    </div>
    {% endfor %}
</div>
{% endif %}
```

**Step 4: Manually test in browser**

Start the app and navigate to `/webapp/calendar`. Verify:
- Month grid renders with day numbers
- Week view renders 7 columns
- Month/Week toggle buttons switch views via HTMX
- Prev/Next buttons navigate without full page reload

```bash
uv run python -m bearmemori
```

**Step 5: Commit**

```bash
git add bearmemori/webapp/templates/base.html bearmemori/webapp/templates/calendar.html bearmemori/webapp/templates/partials/calendar_grid.html
git commit -m "feat: add calendar templates (month and week views)"
```

---

### Task 10: Templates -- RRULE builder and memory_detail.html update

**Files:**
- Create: `bearmemori/webapp/templates/partials/rrule_builder.html`
- Modify: `bearmemori/webapp/templates/memory_detail.html`
- Modify: `bearmemori/webapp/templates/create.html`
- Modify: `bearmemori/webapp/router.py`

**Step 1: Read current `memory_detail.html` and `create.html`**

Read both files to understand the existing form structure before editing.

**Step 2: Create `partials/rrule_builder.html`**

This partial expects a `rrule_form` dict (from `parse_rrule_to_form`) and a `field_prefix` string.

```html
{# Expects: rrule_form dict, event_datetime_value string #}
<fieldset>
    <legend>Schedule</legend>

    <label>Date &amp; Time
        <input type="datetime-local" name="event_datetime" id="event_datetime"
               value="{{ event_datetime_value or '' }}">
    </label>

    <label>Recurrence
        <select name="rrule_freq" id="rrule_freq" onchange="toggleRruleFields()">
            <option value="">None</option>
            <option value="daily"   {% if rrule_form.freq == 'daily'   %}selected{% endif %}>Daily</option>
            <option value="weekly"  {% if rrule_form.freq == 'weekly'  %}selected{% endif %}>Weekly</option>
            <option value="monthly" {% if rrule_form.freq == 'monthly' %}selected{% endif %}>Monthly</option>
            <option value="yearly"  {% if rrule_form.freq == 'yearly'  %}selected{% endif %}>Yearly</option>
        </select>
    </label>

    <div id="rrule_interval_row">
        <label>Interval (every N)
            <input type="number" name="rrule_interval" min="1" value="{{ rrule_form.interval or 1 }}">
        </label>
    </div>

    <div id="rrule_byday_row" style="display:none;">
        <label>Days of week</label>
        <div style="display:flex; gap:1rem; flex-wrap:wrap;">
            {% for code, label in [('MO','Mon'),('TU','Tue'),('WE','Wed'),('TH','Thu'),('FR','Fri'),('SA','Sat'),('SU','Sun')] %}
            <label style="display:inline-flex; align-items:center; gap:0.25rem;">
                <input type="checkbox" name="rrule_byday" value="{{ code }}"
                       {% if code in (rrule_form.byday or []) %}checked{% endif %}>
                {{ label }}
            </label>
            {% endfor %}
        </div>
    </div>

    <div id="rrule_bymonthday_row" style="display:none;">
        <label>Day of month
            <input type="number" name="rrule_bymonthday" min="1" max="31"
                   value="{{ rrule_form.bymonthday or '' }}">
        </label>
    </div>

    <div id="rrule_end_row" style="display:none;">
        <label>End date (optional)
            <input type="date" name="rrule_until" value="{{ rrule_form.until[:8] if rrule_form.until else '' }}">
        </label>
    </div>

    <input type="hidden" name="event_status" value="{{ event_status or 'pending' }}">
</fieldset>

<script>
function toggleRruleFields() {
    var freq = document.getElementById('rrule_freq').value;
    document.getElementById('rrule_interval_row').style.display = freq ? '' : 'none';
    document.getElementById('rrule_byday_row').style.display = freq === 'weekly' ? '' : 'none';
    document.getElementById('rrule_bymonthday_row').style.display = freq === 'monthly' ? '' : 'none';
    document.getElementById('rrule_end_row').style.display = freq ? '' : 'none';
}
toggleRruleFields();
</script>
```

**Step 3: Update webapp router to pass rrule_form to templates**

In `bearmemori/webapp/router.py`, update the `memory_detail` GET route to parse the RRULE:

```python
@r.get("/memories/{record_id}", response_class=HTMLResponse)
async def memory_detail(request: Request, record_id: str):
    from bearmemori.core.recurrence import parse_rrule_to_form
    record = db.get(record_id)
    if not record:
        return RedirectResponse(url="/webapp/memories", status_code=302)
    rrule_form = parse_rrule_to_form(
        record.event_fields.recurrence if record.event_fields else ""
    )
    event_dt_value = ""
    if record.event_fields:
        event_dt_value = _format_event_dt_input(record.event_fields.datetime)
    return templates.TemplateResponse(
        request,
        "memory_detail.html",
        {
            "memory": record,
            "categories": CATEGORIES,
            "rrule_form": rrule_form,
            "event_datetime_value": event_dt_value,
            "event_status": record.event_fields.status if record.event_fields else "pending",
        },
    )
```

Update the `memory_update` POST route to build RRULE from form fields instead of reading raw `event_recurrence`. Replace the recurrence-related form params:

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
    importance: int = Form(5),
    event_datetime: str = Form(""),
    event_status: str = Form("pending"),
    rrule_freq: str = Form(""),
    rrule_interval: int = Form(1),
    rrule_byday: list[str] = Form(default=[]),
    rrule_bymonthday: str = Form(""),
    rrule_until: str = Form(""),
):
    from bearmemori.core.recurrence import build_rrule_from_form
    record = db.get(record_id)
    if not record:
        return RedirectResponse(url="/webapp/memories", status_code=302)

    until_rrule = f"{rrule_until.replace('-', '')}T000000Z" if rrule_until else ""
    recurrence = build_rrule_from_form(
        freq=rrule_freq,
        interval=rrule_interval,
        byday=rrule_byday,
        bymonthday=rrule_bymonthday,
        until=until_rrule,
    )

    record.title = title
    record.category = MemoryCategory(category)
    record.content = content
    record.tags = [t.strip() for t in tags.split(",") if t.strip()]
    record.needs_review = needs_review
    record.importance = max(1, min(10, importance))
    if event_datetime:
        record.event_fields = EventFields(
            datetime=event_datetime,
            status=event_status if event_status in ("pending", "done") else "pending",
            recurrence=recurrence if recurrence else None,
        )
    else:
        record.event_fields = None
    db.update(record)
    vector_store.update(record)

    return_to = request.query_params.get("return", "")
    if return_to == "calendar":
        return RedirectResponse(url="/webapp/calendar", status_code=302)
    return RedirectResponse(url=f"/webapp/memories/{record_id}", status_code=302)
```

Update the `create_memory_page` GET route to pass rrule_form and pre-fill event_datetime:

```python
@r.get("/memories/new", response_class=HTMLResponse)
async def create_memory_page(request: Request):
    from bearmemori.core.recurrence import parse_rrule_to_form
    event_dt = request.query_params.get("event_datetime", "")
    return templates.TemplateResponse(
        request,
        "create.html",
        {
            "categories": CATEGORIES,
            "rrule_form": parse_rrule_to_form(""),
            "event_datetime_value": event_dt,
            "event_status": "pending",
        },
    )
```

Update the `create_memory_submit` POST to handle RRULE fields:

```python
@r.post("/memories/new")
async def create_memory_submit(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    content: str = Form(...),
    tags: str = Form(""),
    importance: int = Form(5),
    event_datetime: str = Form(""),
    event_status: str = Form("pending"),
    rrule_freq: str = Form(""),
    rrule_interval: int = Form(1),
    rrule_byday: list[str] = Form(default=[]),
    rrule_bymonthday: str = Form(""),
    rrule_until: str = Form(""),
):
    from bearmemori.core.recurrence import build_rrule_from_form
    until_rrule = f"{rrule_until.replace('-', '')}T000000Z" if rrule_until else ""
    recurrence = build_rrule_from_form(
        freq=rrule_freq,
        interval=rrule_interval,
        byday=rrule_byday,
        bymonthday=rrule_bymonthday,
        until=until_rrule,
    )
    record_id = f"mem_{uuid.uuid4().hex[:12]}"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    record = MemoryRecord(
        id=record_id,
        category=MemoryCategory(category),
        title=title,
        content=content,
        created_at=datetime.now(UTC),
        tags=tag_list,
        importance=max(1, min(10, importance)),
    )
    if event_datetime:
        record.event_fields = EventFields(
            datetime=event_datetime,
            status="pending",
            recurrence=recurrence if recurrence else None,
        )
    db.create(record)
    vector_store.add(record)

    return_to = request.query_params.get("return", "")
    if return_to == "calendar":
        return RedirectResponse(url="/webapp/calendar", status_code=302)
    return RedirectResponse(url="/webapp/memories", status_code=302)
```

**Step 4: Update `memory_detail.html` to include the RRULE builder partial**

In `memory_detail.html`, find the section that renders `event_datetime` and `event_recurrence` inputs and replace them with:

```html
{% include "partials/rrule_builder.html" %}
```

Remove any existing `event_datetime`, `event_status`, and `event_recurrence` individual input fields from the form.

**Step 5: Update `create.html` similarly**

Replace the event-related fields with:

```html
{% include "partials/rrule_builder.html" %}
```

**Step 6: Manual test**

Start the app, go to `/webapp/memories/new`, verify the schedule fieldset renders with frequency dropdown. Create an event with weekly recurrence and check it appears in the calendar.

```bash
uv run python -m bearmemori
```

**Step 7: Run full test suite**

```bash
uv run pytest -v
```
Expected: all tests PASS.

**Step 8: Commit**

```bash
git add bearmemori/webapp/router.py \
        bearmemori/webapp/templates/partials/rrule_builder.html \
        bearmemori/webapp/templates/memory_detail.html \
        bearmemori/webapp/templates/create.html
git commit -m "feat: add RRULE builder to memory forms, wire calendar return redirect"
```

---

### Task 11: Final verification and lint

**Step 1: Run linter**

```bash
uv run ruff check .
```
Fix any issues found, then:
```bash
uv run ruff format .
```

**Step 2: Run full test suite**

```bash
uv run pytest -v
```
Expected: all tests PASS.

**Step 3: Commit any lint fixes**

```bash
git add -u
git commit -m "chore: fix lint warnings"
```
(Only commit if there are changes.)
