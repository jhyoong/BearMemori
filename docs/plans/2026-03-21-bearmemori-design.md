# BearMemori Design Document

**Date**: 2026-03-21
**Version**: 0.3.0
**Status**: Approved

## Overview

BearMemori is a personal memory store. Users send text and images via Telegram. An LLM processes each input, decides how to store it, and can ask follow-up questions if clarity is needed. Memories are searchable via keyword (FTS5) and semantic (embeddings) search. A REST API exposes the memory store to other LLMs and tools.

## Constraints

- Single user, personal use only
- Locally hosted OpenAI-compatible LLM for processing
- Homelab deployment
- No voice input in MVP (text and images only)
- Sequential processing (one input at a time, LLM is the bottleneck)
- In-memory queue (no persistence between restarts, 2-week TTL)

## Architecture: Event-Driven Modular Monolith

Single Python process with an internal async event bus connecting decoupled modules.

### Module Structure

```
bearmemori/
  events/         # Event definitions and async pub/sub bus
  interfaces/     # Telegram adapter (emits/handles events)
  core/           # Queue manager, processor, follow-up manager
  llm/            # OpenAI-compatible client
  storage/        # SQLite + FTS5 + embedding store
  api/            # FastAPI REST API
```

### Event Bus

A lightweight async pub/sub built on `asyncio`. No external dependencies.

```python
class EventBus:
    async def emit(self, event: Event) -> None: ...
    def on(self, event_type: type[Event], handler: Callable) -> None: ...
```

Handlers register for specific event types. The bus dispatches events to all registered handlers.

### Event Flow

```
User sends message via Telegram
  -> Interface emits InputReceived
  -> QueueManager handles it, adds to priority queue
  -> QueueManager emits InputQueued
  -> Processor picks up next item, calls LLM
  -> LLM decides: store or follow-up?
    -> Store: Processor emits MemoryStored
    -> Follow-up: Processor emits FollowUpRequired
      -> FollowUpManager sends question via interface
      -> User responds -> InputReceived (priority 0) -> repeat
```

### Key Events

| Event | Emitted By | Handled By |
|-------|-----------|------------|
| InputReceived | Telegram interface | QueueManager |
| InputQueued | QueueManager | Processor |
| FollowUpRequired | Processor | FollowUpManager |
| MemoryStored | Processor | (logging, notifications) |
| MemoryUpdated | REST API | (logging) |
| MemoryDeleted | REST API | (logging) |

## Data Model

### Memory Record (SQLite)

| Field | Type | Description |
|-------|------|-------------|
| id | TEXT (UUID) | Primary key |
| content | TEXT | Processed memory content |
| raw_input | TEXT | Original user input |
| memory_type | TEXT | Category: preference, event, fact, note, etc. |
| tags | JSON | Searchable tags assigned by LLM |
| embedding | BLOB | Vector embedding for semantic search |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last modification timestamp |
| source | TEXT | Origin: telegram, api, etc. |
| metadata | JSON | Flexible extra data (image refs, etc.) |

### Queue Item (in-memory)

| Field | Type | Description |
|-------|------|-------------|
| priority | INT | Lower = higher priority. Follow-ups get 0. |
| input_type | ENUM | text, image, log |
| content | ANY | Raw input content |
| context | DICT | Follow-up conversation history if applicable |
| created_at | DATETIME | For FIFO ordering within same priority |
| source_chat_id | TEXT | To route responses back |

## Follow-Up System

- FollowUpManager tracks active follow-up conversations keyed by chat ID
- When InputReceived fires, QueueManager checks with FollowUpManager first:
  - **Active follow-up**: Input is tagged as a follow-up response, placed at priority 0 (front of queue), carrying full conversation context
  - **No follow-up**: Normal priority assignment and queuing
- Follow-ups continue until the LLM has enough information to store the memory
- **Timeout**: If no response within a configurable period (default 24 hours), the system stores what it has with a "needs-review" tag

## Search

- **Keyword search**: SQLite FTS5 full-text search on content and tags
- **Semantic search**: Cosine similarity on embeddings (local embedding model via OpenAI-compatible API)
- **Hybrid**: Results ranked by a combination of FTS5 score and cosine similarity

## Components

### LLM Client

Uses the `openai` Python SDK pointed at the local inference server. Methods:
- `classify_input(input)` -- determine memory type, decide if follow-up is needed
- `extract_memory(input, context)` -- extract structured memory data
- `generate_followup(input, context)` -- generate a follow-up question

Configurable base URL and model name via environment variables.

### Storage Layer

- SQLite with FTS5 for full-text search
- Embeddings stored as BLOBs
- Embedding model accessed via OpenAI-compatible API

### REST API (FastAPI)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /memories/search | Search memories (keyword, semantic, hybrid) |
| GET | /memories/{id} | Get a specific memory |
| GET | /memories | List with filtering (type, tags, date range) |
| POST | /memories | Manually create a memory |
| PUT | /memories/{id} | Edit a memory |
| DELETE | /memories/{id} | Delete a memory |

### Telegram Interface

- `python-telegram-bot` library (async)
- Handles text and photo messages
- Commands: `/search`, `/delete`, `/edit` for direct memory management

### Configuration

- Pydantic `Settings` model loading from `.env`
- Key settings: LLM base URL, model name, embedding model, Telegram bot token, SQLite path, queue max size, follow-up timeout

## Error Handling

- **LLM unavailable**: Items stay in queue, processor retries with exponential backoff, user notified via Telegram
- **Queue overflow**: Configurable max size, new inputs rejected with user notification
- **Queue item expiry**: Background task sweeps items older than 2 weeks, user notified
- **Follow-up timeout**: Store with "needs-review" tag after configurable timeout
- **Image handling**: Sent to LLM if vision-capable, otherwise stored as reference with caption

## Testing

- **Unit tests**: Each module in isolation (event bus, queue, storage, LLM client with mocked responses)
- **Integration tests**: Event flow end-to-end with test SQLite and mocked LLM
- **Framework**: pytest + pytest-asyncio
- **No E2E Telegram tests** in MVP -- manual testing via bot

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12+ |
| Web framework | FastAPI |
| Telegram | python-telegram-bot |
| Database | SQLite + FTS5 |
| LLM client | openai SDK |
| Embeddings | Local model via OpenAI-compatible API |
| Config | Pydantic Settings |
| Testing | pytest + pytest-asyncio |
| Linting | ruff |
| Package manager | uv |
