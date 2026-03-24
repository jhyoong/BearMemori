# v0.3.5 TODO Fixes Design

## Overview

Four items to address for the v0.3.5 release: changelog update, reminder time pipeline fix, Telegram inline button cleanup, and webapp event fields display.

## 1. Changelog Update for v0.3.4

Add a v0.3.4 entry to `CHANGELOG.md` documenting:
- Fixed webapp root `/` redirect to login page when webapp is enabled
- Fixed LLM response handling for reasoning models (Qwen3.5 etc.) -- added `_get_content()` helper that checks `reasoning_content` when `content` is empty
- Added `llm_max_tokens` config setting to control token budget for LLM calls
- Applied max_tokens to triage LLM calls

## 2. Debug and Fix Reminder Time Info Pipeline

**Problem:** `event_fields` (datetime, status, recurrence) may not be properly set or stored for reminder-type memories. The exact breakpoint is unknown.

**Approach:** Add debug logging at three key points:
1. After LLM response parsing in `llm/client.py` (`extract_memory`) -- log raw `event_fields`
2. After extraction result is built in `core/processor.py` -- log `ExtractionResult.event_fields`
3. Before database insert in `storage/database.py` -- log `MemoryRecord.event_fields`

Trace a real reminder through the system. Fix whatever root cause is found.

**Likely candidates:**
- LLM JSON response parser not mapping `event_fields` correctly
- `MemoryRecord` construction missing `event_fields` assignment
- Triage step overwriting or not passing through `event_fields`

**Testing:** Add/update tests verifying reminder extraction populates `event_fields` through to database.

## 3. Remove Inline Buttons After Telegram Callback

**Problem:** Inline buttons persist after the user taps one.

**Changes to `interfaces/telegram.py` `_handle_callback()`:**
- After processing each action, call `query.edit_message_reply_markup(reply_markup=None)` to remove buttons
- Append a status line to the original message using `query.edit_message_text()`:
  - Save: `"-- Saved"`
  - Discard: `"-- Discarded"`
  - Review Later: `"-- Saved for review"`
  - Edit: `"-- Editing..."`
- For Edit, remove buttons immediately; the existing edit flow continues as-is

## 4. Webapp Time Fields for Reminders

**Problem:** `memory_detail.html` does not display `event_fields` for reminder/event/task types.

### Memory list template
- For memories with `event_fields`, show datetime as a subtitle (e.g., "Due: 2026-03-25 15:00")
- Show status badge (pending/done)

### Memory detail template (`memory_detail.html`)
- Conditional section for event/task/reminder categories with three editable fields:
  - **Datetime**: `datetime-local` input, pre-filled from `event_fields.datetime`
  - **Status**: Dropdown select with "pending" and "done"
  - **Recurrence**: Text input (nullable)

### Webapp router (`webapp/router.py`)
- Update `memory_update()` to read three new form fields and reconstruct `EventFields` on save
- Only process when category is event/task/reminder
- Pass `event_fields` data to template context in `memory_detail()`

### No changes to
- API layer, storage layer, or data models (fields already exist in schema)
