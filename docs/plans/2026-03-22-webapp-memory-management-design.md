# Webapp Memory Management - Design Document

Date: 2026-03-22

## Overview

Add a lightweight webapp for managing stored memories, simplify the Telegram interface to focus on input, and introduce a "Review Later" workflow for memories that need refinement.

## Goals

1. Webapp to browse, edit, create, and delete memories with bulk operations
2. Telegram becomes primarily an input layer — fewer LLM follow-ups, faster saves
3. "Review Later" status allows saving memories that need future refinement

## Architecture Decisions

- **Integrated webapp**: Served from the existing FastAPI app on `:8100/webapp/`
- **Frontend**: Plain HTML + Jinja2 templates + HTMX for interactivity
- **CSS**: Pico CSS (classless, ~10KB, CDN)
- **Auth**: Simple shared-secret via `WEBAPP_SECRET` env var, cookie-based session
- **Review Later**: Boolean `needs_review` column on existing `memories` table (not a separate table)
- **Follow-up reduction**: Prompt tuning only, keep follow-up mechanism intact

## Data Model Changes

### memories table

Add column:
```sql
ALTER TABLE memories ADD COLUMN needs_review BOOLEAN DEFAULT 0;
```

Auto-migrate at startup if column does not exist.

### MemoryRecord

Add field: `needs_review: bool = False`

## Event Changes

### MemoryConfirmed

Add optional field: `needs_review: bool = False`

When user taps "Review Later" in Telegram, emit `MemoryConfirmed` with `needs_review=True`. The `ConfirmHandler` passes this through to `MemoryDatabase.save()`.

## Telegram Changes

### Pending preview buttons

Current: `[Save] [Edit] [Discard]`
New: `[Save] [Review Later] [Edit] [Discard]`

- "Save" — commits with `needs_review=False` (unchanged)
- "Review Later" — commits with `needs_review=True`
- "Edit" / "Discard" — unchanged

### Callback data

New callback pattern: `review:{pending_id}`

### LLM Classification Prompt

Update system prompt to bias toward "store" over "followup":
- "Prefer to store the memory even if the input is vague or incomplete. Only request a follow-up if the input is truly unintelligible or you cannot determine any meaningful content to extract."
- No code changes to the follow-up flow itself

## API Changes

### New endpoints

| Method | Path | Description |
|--------|------|-------------|
| PUT | `/memory/{record_id}` | Update memory fields (title, content, category, tags, event_fields, needs_review) |
| POST | `/memory/create` | Create memory directly (bypass LLM extraction) |
| POST | `/memory/bulk/delete` | Delete multiple memories by ID list |
| POST | `/memory/bulk/update` | Bulk update category or clear review flag |

### Modified endpoints

| Method | Path | Change |
|--------|------|--------|
| GET | `/memory/list` | Add `needs_review` query parameter filter |

## Storage Changes

### MemoryDatabase

- `save()` — accept optional `needs_review` parameter
- `update(record_id, **fields)` — new method to update fields on existing memory
- `list_memories()` — accept optional `needs_review` filter
- `delete_many(record_ids)` — new method for bulk delete

### VectorStore

- `update(record_id, content, metadata)` — update document and re-embed if content changes
- `delete_many(record_ids)` — new method for bulk delete

## Webapp Module

### Structure

```
bearmemori/
  webapp/
    __init__.py
    router.py              # FastAPI router with HTML endpoints
    auth.py                # Shared-secret auth middleware
    templates/
      base.html            # Layout: nav, HTMX + Pico CSS CDN links
      memories.html        # Main list view with filters
      memory_detail.html   # Single memory edit form
      review_queue.html    # Filtered view of needs_review memories
      create.html          # New memory creation form
    static/
      style.css            # Minimal custom overrides
```

### Pages

1. **Memory List** (`/webapp/memories`)
   - Table/card list of all memories
   - Filters: category, tags, full-text search (existing FTS5), needs_review
   - Sort: created date, category
   - Bulk select checkboxes with actions: delete, change category, clear review flag
   - Per-row actions: edit, delete

2. **Memory Detail/Edit** (`/webapp/memories/{id}`)
   - Editable fields: title, content, category, tags, event_fields
   - Clear "needs review" flag
   - Delete button
   - HTMX partial swap for inline saves

3. **Create Memory** (`/webapp/memories/new`)
   - Form: category, title, content, tags
   - Saves directly to DB + vector store (no LLM)

4. **Review Queue** (`/webapp/review`)
   - Memory list pre-filtered to `needs_review=True`
   - Per-item actions: Approve (clear flag), Edit & Approve, Delete

### Auth

- `WEBAPP_SECRET` env var (required to enable webapp)
- Login page at `/webapp/login` — user enters secret
- Sets signed session cookie on success
- Middleware checks cookie on all `/webapp/` routes (except login)

### HTMX Patterns

- List filtering: `hx-get` with query params, swap table body
- Inline edit: `hx-put` on form, swap row/card
- Delete: `hx-delete` with `hx-confirm`, remove element
- Bulk actions: form wrapping checkboxes, `hx-post` to bulk endpoint

## Configuration

New settings in `config.py`:

- `WEBAPP_SECRET: str = ""` — shared secret for webapp auth (empty = webapp disabled)

## Wiring (app.py)

- Mount `webapp.router` on the FastAPI app
- Add auth middleware for `/webapp/` routes
- Configure Jinja2 template directory
