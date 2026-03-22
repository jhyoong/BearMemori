# BearMemori - teleBearAI Integration Design

## Goal

Adapt BearMemori to be a drop-in replacement for teleBearAI's memory microservice. The teleBearAI bot should only need to change its `MEMORY_SERVICE_URL` to point at BearMemori.

## Approach

Approach A: reshape BearMemori's API and internals to match teleBearAI's expected contract. Zero changes on the teleBearAI bot side.

---

## 1. Memory Model & Categories

### Categories (6)

| Category | Description |
|----------|-------------|
| `profile` | Stable user facts (preferences, identity, relationships) |
| `general` | Non-time-bound information (deals, recommendations, facts) |
| `event` | Time-bound commitments (appointments, deadlines) |
| `location` | Places, addresses, venues |
| `task` | Action items, to-dos |
| `reminder` | Triggered notifications with scheduling |

### Memory Model Fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | str (UUID) | Primary key |
| `category` | enum | One of the 6 categories |
| `title` | str | Short summary |
| `content` | str | Full detail |
| `raw_input` | str | Original user input |
| `tags` | list[str] | Searchable tags |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last modification |
| `source` | dict | `{platform, chat_id, message_ids}` |
| `event_fields` | dict or None | `{datetime, status, recurrence}` |
| `metadata` | dict | Arbitrary key-value data |

### Changes from current BearMemori

- `memory_type` (8 flat types) becomes `category` (6 categories)
- Add `title` field
- `source` changes from string to structured dict
- `remind_at` and `recurring_minutes` fold into `event_fields`
- `embedding` bytes removed from SQLite (lives in ChromaDB)

---

## 2. Storage Layer

### SQLite (relational)

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    event_datetime TEXT,
    event_status TEXT,
    event_recurrence TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE memories_fts USING fts5(content, tags, title, content=memories);
```

### ChromaDB (vector)

- Embedded client, persisted to disk at `chroma_persist_dir`
- Collection: `memories`
- Documents: `"{title}: {content}"`
- Metadata: `{category, created_at, event_datetime}`
- IDs: memory record ID
- Embedding model: configurable (default `all-MiniLM-L6-v2`)

### Pending Store (new, in-memory)

- `dict[pending_id -> PendingMemory]`
- PendingMemory: `{draft, ttl_seconds, created_at}`
- Default TTL: 24 hours
- Auto-expires on access
- Used for HITL confirmation flow

### Changes

- Remove `embedding` column from SQLite
- Add ChromaDB as vector backend
- Add PendingStore class
- FTS5 indexes `title` in addition to `content` and `tags`
- Remove numpy dependency

---

## 3. API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/memory/triage` | POST | Evaluate conversation, propose memory draft |
| `/memory/pending` | POST | Create pending memory directly |
| `/memory/pending/{pending_id}` | DELETE | Dismiss pending memory |
| `/memory/confirm` | POST | Confirm pending -> permanent storage |
| `/memory/search` | POST | Semantic search with optional category/top_k |
| `/memory/retrieve` | GET | Hybrid retrieval: semantic + upcoming events |
| `/memory/list` | GET | List memories, optional category filter |
| `/memory/events/upcoming` | GET | Upcoming events within day window |
| `/memory/{record_id}` | GET | Fetch single memory |
| `/memory/{record_id}` | DELETE | Delete a memory |
| `/health` | GET | Health check |

### Removed from current BearMemori API

- `PUT /memories/{id}` - teleBearAI doesn't use it
- `POST /memories` - Replaced by triage/confirm flow

### Classify/Extract pipeline

Kept internally for BearMemori's own Telegram interface. Not exposed as HTTP endpoint.

---

## 4. Triage Subagent & Processing Pipeline

### Triage (new, for teleBearAI)

```
POST /memory/triage
  { conversation: [{role, content}, ...], memory_hint?: {likely_category, confidence} }
    -> LLM evaluates conversation
    -> should_save=false: done
    -> should_save=true: create PendingMemory, return {should_save, pending_id, draft}
```

Triage system prompt defines the 6 categories, JSON response schema, and selectivity rules.

### Classify/Extract (kept, for direct input)

```
InputReceived -> classify_input() -> "store" or "followup"
  "followup" -> generate clarifying question
  "store" -> extract_memory() -> save
```

### LLM client changes

- Add `run_triage(conversation, memory_hint)` method
- Existing methods remain unchanged

---

## 5. Hybrid Retrieval

### GET /memory/retrieve

```
query_context (str)
  -> parallel:
    1. Semantic search via ChromaDB (top_k results)
    2. Upcoming events/reminders (next N days from SQLite)
  -> combine into formatted context block
  -> return { context: "..." }
```

### GET /memory/events/upcoming

- Queries memories where category is event/reminder/task and event_datetime is within next N days
- Default: 7 days, configurable via query param
- Returns list sorted by event_datetime

### POST /memory/search

- Semantic search via ChromaDB
- Optional filters: category, top_k
- Returns matching memories with distance scores

---

## 6. Configuration

| Setting | Default | Notes |
|---------|---------|-------|
| `telegram_bot_token` | required | Kept |
| `telegram_allowed_user_id` | required | Kept |
| `llm_base_url` | `http://localhost:11434/v1` | Kept |
| `llm_model` | `llama3` | Kept |
| `llm_api_key` | `""` | Kept |
| `database_path` | `bearmemori.db` | Kept |
| `chroma_persist_dir` | `chroma_data/` | New |
| `embedding_model` | `all-MiniLM-L6-v2` | Changed |
| `pending_ttl_seconds` | `86400` | New |
| `queue_max_size` | `1000` | Kept |
| `followup_timeout_hours` | `24` | Kept |
| `reminder_poll_interval_seconds` | `60` | Kept |
| `retrieval_top_k` | `5` | New |
| `upcoming_events_days` | `7` | New |
| `api_port` | `8100` | Changed |

### Dependency changes

| Remove | Add |
|--------|-----|
| `numpy` | `chromadb` |
| | `sentence-transformers` |
