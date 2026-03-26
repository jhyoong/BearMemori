# Design: Memory Importance Field & Telegram Menu Commands

Date: 2026-03-26

## Overview

Two features from the TODO list:
1. **Memory importance field** -- A 1-10 integer score on each memory, assigned by the LLM during extraction and overridable by the user. Directly impacts system prompt context construction.
2. **Telegram menu commands** -- Add `/search`, `/list`, and `/help` commands to the Telegram bot menu via `set_bot_commands`.

---

## Feature 1: Memory Importance Field

### Data Model

- Add `importance` INTEGER column to `memories` table, default 5, range 1-10.
- Add index `idx_memories_importance` for sorting/filtering.
- Migration: `ALTER TABLE memories ADD COLUMN importance INTEGER NOT NULL DEFAULT 5`.
- Add `importance: int = 5` to `MemoryRecord`.
- Add `importance: int` to `ExtractionResult`.
- Add `importance: int | None` to `MemoryDraft` and `PendingMemory` for user override.
- Include `importance` in API memory list/search/detail responses.
- Allow `importance` as a filter parameter on the list endpoint.

### LLM Extraction

- Update the extraction prompt in `llm/client.py` to instruct the LLM to assign an `importance` score (1-10).
- Scoring guidelines in the prompt:
  - 1-3: Trivial/ephemeral info (casual observations, low-value notes)
  - 4-6: Useful but not critical (general facts, routine tasks)
  - 7-9: Important (key personal info, significant events, recurring tasks)
  - 10: Critical (health info, credentials, life events)
- Add `importance` to the expected JSON output schema.
- Extract and clamp to 1-10. Default to 5 if LLM omits it.

### User Override & Confirmation Flow

- Show LLM-assigned importance in the Telegram pending memory preview.
- Add inline keyboard buttons to adjust importance before confirming: "Importance: 7 [+] [-]".
- When user taps +/-, update the pending memory's importance and refresh the preview.
- In `core/confirm.py`, pass importance from `PendingMemory` to `MemoryRecord` via `from_draft()`. Use user-overridden value if set, otherwise LLM's value.
- Display and allow editing importance in the webapp memory detail/list views.

### System Prompt Context Construction

- When constructing LLM system prompt context, retrieve relevant memories via vector search as usual.
- Sort results by combined score: `relevance_weight * similarity + importance_weight * (importance / 10)`.
- Always include memories with importance >= 8 (high threshold) if they have any relevance.
- Fill remaining context budget by combined score, highest first.
- Skip memories with importance <= 2 (low threshold) unless highly relevant.
- Config: `IMPORTANCE_HIGH_THRESHOLD` (default 8), `IMPORTANCE_LOW_THRESHOLD` (default 2).
- Start with equal weighting (0.5/0.5) for relevance and importance; tune later.
- Design is static-for-now but field supports future dynamic scoring without schema changes.

---

## Feature 2: Telegram Menu Commands

### New Commands

**`/help`:**
- Static handler returning a formatted message listing all commands with descriptions.
- No event emission needed.

**`/search <query>`:**
- Extract query text after `/search`.
- Call vector search via storage layer (same path as API's `POST /memory/search`).
- Return top 5 results formatted with title, category, importance, and truncated content preview.
- If no query provided, reply with usage hint.

**`/list [category]`:**
- Optionally parse a category filter.
- Call database list via storage layer (same path as API's `GET /memory/list`).
- Return first 10 results formatted with title, category, and importance.
- If invalid category provided, reply with valid category options.

### Bot Menu Registration

Update `set_bot_commands` in the `build()` method to register all 5 commands:
- `start` -- Welcome message
- `recall` -- Retrieve a memory by ID
- `search` -- Search memories
- `list` -- List memories
- `help` -- Show available commands

---

## Testing

### Importance Field Tests

- Unit: LLM extraction returns importance, parser clamps to 1-10.
- Unit: Default importance of 5 when LLM omits it.
- Unit: User override flows through to stored record.
- Integration: Context builder respects importance weighting.

### Telegram Command Tests

- Unit: `/search` with query returns formatted results.
- Unit: `/search` without query returns usage hint.
- Unit: `/list` with and without category filter.
- Unit: `/help` returns command listing.
- Unit: `set_bot_commands` registers all 5 commands.

### Error Handling

- Invalid importance values from LLM clamped to 1-10.
- Empty search results return "no memories found" message.
- Invalid category on `/list` returns valid options.

---

## Files Affected

- `bearmemori/storage/models.py` -- MemoryRecord, ExtractionResult, MemoryDraft, PendingMemory
- `bearmemori/storage/database.py` -- Schema migration, importance column, index
- `bearmemori/llm/client.py` -- Extraction prompt, response parsing
- `bearmemori/core/confirm.py` -- Pass importance through confirmation flow
- `bearmemori/core/processor.py` -- Context construction with importance weighting
- `bearmemori/interfaces/telegram.py` -- New commands, importance override buttons, set_bot_commands
- `bearmemori/api/routes.py` -- Importance in responses and as filter
- `bearmemori/api/schemas.py` -- Importance in API schemas
- `bearmemori/config.py` -- Importance threshold settings
- `bearmemori/webapp/` -- Display importance in views
- `tests/` -- New test cases
