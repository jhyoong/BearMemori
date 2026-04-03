# Calendar System Design

**Date:** 2026-04-01
**Status:** Approved

## Overview

Add a full calendar system to BearMemori. The calendar shows memories of category `event`, `reminder`, and `task` that have an `event_datetime` set. It supports month and week views, inline occurrence management, and full iCalendar RRULE recurrence. The webapp is the primary interface; the REST API is extended minimally for backwards compatibility.

## Current State

- `MemoryRecord` has `event_fields: EventFields | None` containing `datetime` (ISO 8601 string), `status` (`pending`/`done`), and `recurrence` (free-text string, currently unused).
- `MemoryDatabase` has `get_upcoming_events(days)` and `get_due_events()`.
- `GET /memory/events/upcoming` returns raw memory records for the next N days.
- `ReminderScheduler` polls every 60s, fires `ReminderDue`, and marks the whole record as `done`.
- The webapp has no calendar view -- only a flat memory list.

## What Changes

### 1. Data Model

No schema migrations required. Two behavioral changes to existing fields:

**`event_recurrence`** -- stores RRULE strings (e.g., `FREQ=WEEKLY;BYDAY=TU;INTERVAL=2`) instead of free text. Existing free-text values that fail RRULE parsing are treated as non-recurring.

**`metadata["completed_occurrences"]`** -- new key written into the existing `metadata` JSON column. Stores a list of ISO date strings for recurring occurrences that have been marked done. Only written for recurring events. Example:
```json
{"completed_occurrences": ["2026-01-15", "2026-01-22"]}
```

**`event_status` behavior** -- for recurring events, stays `"pending"` while the series is active; individual occurrences are tracked via `completed_occurrences`. Set to `"done"` only when all occurrences are exhausted (RRULE has an end date/count and it has passed). Non-recurring events keep existing `pending`/`done` behavior.

### 2. New Dependency

Add `python-dateutil` to `pyproject.toml` for RRULE parsing and occurrence expansion.

### 3. New Service Module: `bearmemori/core/recurrence.py`

Responsibilities:
- **Occurrence expansion**: `expand_occurrences(record, start, end) -> list[CalendarOccurrence]`
  - Non-recurring: returns one `CalendarOccurrence` if `event_datetime` is in range.
  - Recurring: uses `dateutil.rrule` to generate all dates in range, checks `metadata["completed_occurrences"]` for status per occurrence.
- **RRULE form helpers**: `parse_rrule_to_form(rrule_str) -> dict` and `build_rrule_from_form(**kwargs) -> str` for converting between RRULE strings and structured form fields.

`CalendarOccurrence` model:
```python
class CalendarOccurrence(BaseModel):
    memory_id: str
    title: str
    category: str
    occurrence_dt: datetime
    status: str          # "pending" or "done"
    is_recurring: bool
```

### 4. Storage Changes

One new method on `MemoryDatabase`:

**`get_events_in_range(start, end) -> list[MemoryRecord]`** -- returns memories where:
- `category IN ('event', 'reminder', 'task')` AND
- Either: `event_datetime` is in `[start, end]` (non-recurring), OR `event_recurrence IS NOT NULL AND event_datetime <= end` (recurring series that may have occurrences in range).

Returns raw `MemoryRecord` objects; the recurrence module handles expansion.

### 5. API Changes

**`GET /memory/events/upcoming`** -- two new optional query params: `start: str | None` and `end: str | None` (ISO datetime). When provided, uses `get_events_in_range()` and runs occurrence expansion. Response gains a new optional field:

```json
{
  "events": [...],
  "occurrences": [
    {
      "memory_id": "...",
      "title": "...",
      "category": "...",
      "occurrence_dt": "2026-04-08T10:00:00+00:00",
      "status": "pending",
      "is_recurring": true
    }
  ]
}
```

Existing callers using only `days=N` see no change (`occurrences` field is absent).

### 6. Scheduler Changes

**`get_due_events()`** -- updated to also return recurring events where `event_recurrence IS NOT NULL AND event_datetime <= now AND event_status = 'pending'`. The scheduler then uses `recurrence.py` to determine which specific occurrence is due.

**`check_reminders()`** -- two code paths:

- **Non-recurring**: existing behavior unchanged -- fire `ReminderDue`, set `event_status = "done"`.
- **Recurring**: fire `ReminderDue` with the specific occurrence date, add that date to `metadata["completed_occurrences"]`, call `db.update(record)`, leave `event_status = "pending"`. If the RRULE is exhausted (all occurrences complete), set `event_status = "done"`.

### 7. Webapp Routes

Three new routes in `webapp/router.py`:

**`GET /webapp/calendar`** -- main calendar page. Params: `view` (`month`|`week`, default `month`), `year`, `month`, `week_start` (ISO date). Computes date range, fetches and expands events, renders `calendar.html`.

**`GET /webapp/calendar/grid`** -- HTMX partial. Same params. Returns only `partials/calendar_grid.html` for view switching and prev/next navigation.

**`POST /webapp/calendar/occurrence/toggle`** -- accepts `memory_id` and `occurrence_date`. Loads record, toggles the date in `metadata["completed_occurrences"]`, saves, returns updated calendar grid partial.

**Create from calendar**: day-click links to `/webapp/memories/new?event_datetime=YYYY-MM-DDTHH:MM`. The create form pre-fills `event_datetime` from query param. After save, redirects to `/webapp/calendar`.

**Edit from calendar**: event pill links to existing `/webapp/memories/{record_id}` detail page.

### 8. Templates

**New:**
- `calendar.html` -- extends `base.html`. Contains view switcher (month/week toggle), prev/next nav (HTMX swaps `#calendar-grid`), and the grid container.
- `partials/calendar_grid.html` -- the calendar grid. Month view: 7-column CSS grid, one cell per day, event pills per cell. Week view: 7 columns with time-slot rows, events positioned at their time. Event pills show category, title, and a checkmark toggle button posting to `/webapp/calendar/occurrence/toggle`.

**Modified:**
- `memory_detail.html` -- replace the `event_recurrence` text input with a structured RRULE builder (frequency dropdown, interval, day-of-week checkboxes, day-of-month selector, end condition). A hidden input holds the assembled RRULE string for form submission.
- `create.html` -- same RRULE builder added; `event_datetime` input pre-filled from query param.
- `base.html` -- add "Calendar" link to the nav bar.

**Unchanged:** `memories.html`, `review_queue.html`, `partials/memory_table.html`.

## File Change Summary

| File | Change |
|------|--------|
| `pyproject.toml` | Add `python-dateutil` dependency |
| `bearmemori/core/recurrence.py` | New -- occurrence expansion + RRULE helpers |
| `bearmemori/storage/database.py` | Add `get_events_in_range()`, update `get_due_events()` |
| `bearmemori/api/routes.py` | Extend `/memory/events/upcoming` with `start`/`end` params |
| `bearmemori/core/scheduler.py` | Handle recurring events separately in `check_reminders()` |
| `bearmemori/webapp/router.py` | Add calendar routes + occurrence toggle |
| `bearmemori/webapp/templates/base.html` | Add Calendar nav link |
| `bearmemori/webapp/templates/calendar.html` | New |
| `bearmemori/webapp/templates/partials/calendar_grid.html` | New |
| `bearmemori/webapp/templates/memory_detail.html` | Replace recurrence text input with RRULE builder |
| `bearmemori/webapp/templates/create.html` | Add RRULE builder, pre-fill event_datetime |
| `tests/` | Tests for recurrence module, updated scheduler tests, API tests |
