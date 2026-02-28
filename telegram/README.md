# Telegram Gateway

The primary user interface for BearMemori. A Telegram bot that receives text and photo messages, manages multi-step conversation flows, and displays interactive inline keyboards for user actions. Consumes notification streams from Redis to deliver LLM results and reminders back to users.

## Running

```bash
# Via Docker
docker-compose up --build

# Locally
cd telegram && pip install -e . && python -m tg_gateway.main
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token (required) |
| `ALLOWED_USER_IDS` | `""` | Comma-separated allowed Telegram user IDs (empty = allow all) |
| `CORE_API_URL` | `http://core:8000` | Core API base URL |
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |

## Directory Structure

```
telegram/
├── pyproject.toml
├── Dockerfile
└── tg_gateway/
    ├── main.py                 # App entry point, PTB application setup
    ├── config.py               # TelegramConfig settings
    ├── core_client.py          # HTTP client for Core API
    ├── consumer.py             # Redis stream consumer (notify:telegram)
    ├── gateway.py              # Abstract gateway base class
    ├── telegram_gateway.py     # Telegram gateway implementation
    ├── callback_data.py        # Callback data classes (frozen dataclasses)
    ├── keyboards.py            # Inline keyboard builders
    ├── media.py                # Image download/upload utilities
    ├── filters.py              # User authorization filter
    └── handlers/
        ├── command.py          # Bot commands (/help, /find, /tasks, /pinned, /cancel)
        ├── message.py          # Text and photo message handlers
        ├── callback.py         # Callback query dispatcher
        └── conversation.py     # Multi-step conversation state handlers
```

## Bot Commands

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/find <query>` | Search memories via FTS5 |
| `/tasks` | List open tasks |
| `/pinned` | Show pinned memories |
| `/cancel` | Clear all pending conversation states |

## Message Handling

### Text Messages

When a user sends text, the handler checks for pending conversation states in priority order:
1. Waiting for tags -> add tags to memory
2. Waiting for custom due date -> create task
3. Waiting for custom reminder time -> create reminder
4. Waiting for follow-up answer -> re-submit to LLM with context
5. Default -> queue for LLM intent classification

### Photo Messages

1. Download highest-resolution photo from Telegram
2. Create pending memory in Core API (7-day expiry)
3. Upload image to Core
4. Queue LLM image tagging job
5. Show memory actions keyboard

## Callback Actions

Interactive inline keyboards handle:
- **Memory actions:** set task, set reminder, add tags, toggle pin, delete
- **Due date selection:** today, tomorrow, next week, no date, custom
- **Reminder time selection:** 1 hour, tomorrow 9am, custom
- **Tag confirmation:** confirm all suggested, edit manually
- **Intent confirmation:** confirm reminder/task, edit time, mark as just a note
- **Task actions:** mark as done
- **Search results:** view details of a specific memory
- **Reschedule:** reschedule or dismiss stale reminders

## Redis Consumer

Listens on `notify:telegram` stream and handles these message types:
- `reminder` -- Fire reminder to user
- `event_reprompt` -- Re-prompt for event confirmation
- `llm_image_tag_result` -- Show suggested tags with confirm/edit keyboard
- `llm_intent_result` -- Route by intent (reminder, task, search, note, ambiguous)
- `llm_followup_result` -- Send follow-up question to user
- `llm_task_match_result` -- Suggest task match
- `event_confirmation` -- Show event detection for confirmation
- `llm_failure` -- Notify user of processing failure

## Dependencies

- `python-telegram-bot[ext]>=20.0,<23.0`
- `httpx>=0.27`
- `redis>=5.0`
- `aiofiles>=24.0`
- `life-organiser-shared`
