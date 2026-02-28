# Assistant Service

A conversational AI assistant that uses OpenAI tool-calling to help users interact with their BearMemori data. Runs as a separate Telegram bot with its own token. Manages multi-turn conversations with token-aware history, builds contextual briefings, and sends daily digest messages.

## Running

```bash
# Via Docker
docker-compose up --build

# Locally
cd assistant && pip install -e . && python -m assistant_svc.main
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ASSISTANT_TELEGRAM_BOT_TOKEN` | `""` | Telegram bot token (required, separate from gateway bot) |
| `ASSISTANT_ALLOWED_USER_IDS` | `""` | Comma-separated allowed Telegram user IDs |
| `OPENAI_API_KEY` | `not-needed` | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI API base URL |
| `OPENAI_MODEL` | `gpt-4o` | LLM model to use |
| `CORE_API_URL` | `http://core:8000` | Core API base URL |
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |
| `CONTEXT_WINDOW_TOKENS` | `128000` | Context window size |
| `BRIEFING_BUDGET_TOKENS` | `5000` | Max tokens for briefing |
| `RESPONSE_RESERVE_TOKENS` | `4000` | Reserved tokens for response |
| `DIGEST_DEFAULT_HOUR` | `8` | Hour (user timezone) to send daily digest |

## Directory Structure

```
assistant/
├── pyproject.toml
└── assistant_svc/
    ├── main.py             # Entry point, component wiring, signal handlers
    ├── config.py           # AssistantConfig settings
    ├── agent.py            # Core agent loop with OpenAI tool-calling
    ├── briefing.py         # Builds pre-loaded context (tasks, reminders, summary)
    ├── context.py          # Chat history management with token counting
    ├── digest.py           # Daily morning briefing scheduler
    ├── core_client.py      # HTTP client for Core API
    ├── interfaces/
    │   ├── base.py         # Abstract BaseInterface
    │   └── telegram.py     # Telegram bot implementation
    └── tools/
        ├── __init__.py     # ToolRegistry class
        ├── memories.py     # search_memories, get_memory
        ├── tasks.py        # list_tasks, create_task
        ├── reminders.py    # list_reminders, create_reminder
        └── events.py       # list_events
```

## Agent Loop

1. Load chat history from Redis
2. Build system prompt with briefing (upcoming tasks, reminders, session summary)
3. Check token budget; summarize history if over 70% threshold
4. Call OpenAI with tool definitions
5. If OpenAI returns tool calls, execute each one and loop back (max 10 iterations)
6. When OpenAI returns text, save updated history and reply to user

The agent injects `owner_user_id` into every tool call automatically. This field is not exposed in the OpenAI tool schemas.

## Available Tools

| Tool | Type | Description |
|---|---|---|
| `search_memories` | Read | Full-text search across memories (up to 10 results) |
| `get_memory` | Read | Fetch full details of a memory by ID |
| `list_tasks` | Read | List tasks with optional state filter (NOT_DONE/DONE) |
| `create_task` | Write | Create a task linked to a memory |
| `list_reminders` | Read | List reminders (upcoming only by default) |
| `create_reminder` | Write | Create a reminder linked to a memory |
| `list_events` | Read | List events with optional status filter |

Write tools (create_task, create_reminder) include a schema note instructing the agent to confirm with the user before calling.

## Context Management

- **Chat history:** Stored in Redis at `assistant:chat:{user_id}` (24h TTL)
- **Session summaries:** Stored at `assistant:summary:{user_id}` (7-day TTL)
- **Token counting:** Uses `tiktoken` encoder for GPT-4o
- **Summarization:** Triggered when chat history exceeds 70% of available budget. Replaces the oldest half of messages with an LLM-generated summary.

## Daily Digest

The `DigestScheduler` runs in the background:
- Checks every 15 minutes
- Respects user timezone from Core API settings
- Sends once per day per user (deduplicated via Redis key `assistant:digest_sent:{user_id}:{date}` with 48h TTL)
- Briefing includes upcoming tasks, unfired reminders, and previous session summary

## Dependencies

- `openai>=1.0.0`
- `httpx>=0.27`
- `redis[hiredis]>=5.0.0`
- `pydantic-settings>=2.0.0`
- `tiktoken>=0.7.0`
- `python-telegram-bot[ext]>=20.0,<23.0`
- `life-organiser-shared`
