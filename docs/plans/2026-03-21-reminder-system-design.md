# Reminder System Design Document

**Date**: 2026-03-21
**Status**: Approved

## Overview

A reminder system within BearMemori where reminders are time-tagged memories that flow through the existing LLM classification pipeline. Reminders are stored as a memory type with time-trigger fields. A background scheduler detects due reminders and emits events. The chatbot (external project) handles delivery and proactive surfacing.

## Data Model Changes

Two new nullable fields on the existing Memory record:

| Field | Type | Description |
|-------|------|-------------|
| remind_at | DATETIME (nullable) | When the reminder should fire. Null for non-reminder memories. |
| recurring_minutes | INTEGER (nullable) | If set, reminder repeats at this interval. Null for one-off reminders. |

A memory with `memory_type = "reminder"` and a non-null `remind_at` is an active reminder. When a recurring reminder fires, `remind_at` is advanced by `recurring_minutes` minutes. A one-off reminder gets `remind_at` set to null after firing.

No separate reminders table -- reminders are memories.

## LLM Classification Changes

The existing LLM classification pipeline handles reminder creation:

- `"reminder"` is added as a recognized memory type
- When classified as a reminder, `extract_memory` also extracts:
  - `remind_at` -- the target datetime
  - `recurring_minutes` -- if the user indicated recurrence (e.g., "every 8 hours" = 480)
- If the LLM cannot determine a clear time, the existing follow-up system asks for clarification

No new LLM methods. The existing classify/extract/followup pipeline handles it. LLM prompt templates are updated to be aware of the reminder type and its fields.

## Reminder Scheduler

A new `ReminderScheduler` component in `bearmemori/core/`:

- Runs as a background `asyncio` task alongside the existing processing loop
- Polls the storage layer on a configurable interval for memories where `remind_at <= now` and `remind_at IS NOT NULL`
- For each due reminder:
  - Emits a `ReminderDue` event on the event bus
  - If `recurring_minutes` is set: advances `remind_at` by that interval
  - If `recurring_minutes` is null: sets `remind_at` to null (one-off, completed)

No external scheduler dependency -- just an async loop inside the existing process.

## REST API

### New Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /reminders | List active reminders (where `remind_at` is not null) |
| GET | /reminders/due | Get reminders due now or within a configurable lookahead window |

Creation, update, and deletion of reminders go through the existing `/memories` CRUD endpoints.

### New Event

| Event | Emitted By | Handled By |
|-------|-----------|------------|
| ReminderDue | ReminderScheduler | REST API notification / Telegram interface |

## Delivery Flow

### Chatbot (primary)

The chatbot polls `/reminders/due` on its own schedule and delivers reminders to the user. BearMemori stays stateless about delivery -- it flags what's due, the chatbot decides when and how to present it. This also enables proactive surfacing of upcoming time-sensitive memories.

### BearMemori Telegram bot (fallback)

When a reminder was set via BearMemori's Telegram interface, the `ReminderDue` event handler sends a notification directly to the user via `source_chat_id`, in case the chatbot isn't running.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| REMINDER_POLL_INTERVAL_SECONDS | 60 | How often the scheduler checks for due reminders |

## Testing

- **Unit tests**: ReminderScheduler in isolation with mocked storage and event bus -- verify it emits `ReminderDue` for due items, advances recurring reminders, and nulls one-off reminders
- **Unit tests**: LLM classification of reminder inputs with mocked LLM responses -- verify `remind_at` and `recurring_minutes` extraction
- **Integration tests**: Full event flow from `InputReceived` through LLM classification to reminder storage, then scheduler firing and `ReminderDue` emission
- **API tests**: `/reminders` and `/reminders/due` endpoints return correct filtered results

Frameworks: pytest + pytest-asyncio, mocked LLM responses.

## What Changes

- `ReminderScheduler` in `bearmemori/core/`
- `ReminderDue` event in `bearmemori/events/`
- `/reminders` and `/reminders/due` API endpoints
- Two new nullable columns on the Memory table
- Updated LLM prompt templates
- One new config setting

## What Doesn't Change

- Event bus architecture
- LLM client interface
- Storage layer structure (just two new nullable columns)
- Follow-up system
- Existing CRUD and search endpoints
