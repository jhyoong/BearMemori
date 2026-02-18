# Phase 2 - Group 8: Redis Consumer (Outbound Notifications) and Docker

## Goal

Implement the background task that listens on the `notify:telegram` Redis stream and delivers outbound messages to users (reminders, LLM results, event confirmations, failure notifications). Also create the Dockerfile and update docker-compose.yml for the Telegram service.

**Depends on:** Groups 2 (Core client), 4 (bot entrypoint starts the consumer)
**Blocks:** None (can be built in parallel with Groups 5-7)

---

## Context

### Outbound Notification Flow

Several services need to send messages to users via Telegram:
- **Core scheduler** publishes reminder notifications when reminders fire
- **LLM Worker** publishes tag suggestions, intent results, follow-up questions, task match suggestions
- **Core scheduler** publishes event re-prompts for unanswered events

None of these services have direct access to the Telegram API. Instead, they publish messages to the `notify:telegram` Redis stream. The Telegram Gateway consumes this stream and delivers the messages.

### Redis Streams Consumed

| Stream | Consumer Group | Published By | Message Types |
|---|---|---|---|
| `notify:telegram` | `telegram-group` | Core scheduler, LLM Worker | reminder, llm_image_tag_result, llm_intent_result, llm_followup_result, llm_task_match_result, event_confirmation, event_reprompt, llm_failure |

### Redis Streams Published (by other groups, listed for reference)

| Stream | Published By (this service) | Purpose |
|---|---|---|
| `llm:image_tag` | Group 5 (message handler) | Image tagging requests |
| `llm:intent` | Future (Phase 3 integration) | Search intent classification |
| `llm:followup` | Future (Phase 3 integration) | Follow-up question generation |
| `llm:task_match` | Future (Phase 3 integration) | Task completion matching |

### Message Format

Each message on `notify:telegram` has this structure:
```json
{
    "user_id": 123456,
    "message_type": "reminder|llm_image_tag_result|llm_followup_result|...",
    "content": { ... }
}
```

The `content` field varies by `message_type` (see details below).

### Consumer Lifecycle

The consumer is started as a managed task via `application.create_task()` in `post_init` (Group 4). PTB manages the task lifecycle:
- Started after application initialization
- Cancelled automatically on shutdown (SIGTERM)
- Runs in the same event loop as the bot polling

---

## Files to Create

### `telegram/tg_gateway/consumer.py`

#### `async def run_notify_consumer(application: Application) -> None`

Main consumer loop:

1. Get Redis client from `application.bot_data["redis"]`
2. Get bot from `application.bot`
3. Create consumer group: `await create_consumer_group(redis_client, STREAM_NOTIFY_TELEGRAM, GROUP_TELEGRAM)`
   - Uses `shared.redis_streams.create_consumer_group` which handles "BUSYGROUP" errors (group already exists)
4. Consumer name: `"telegram-gw-1"` (hardcoded, single instance)
5. Loop:
   - `messages = await consume(redis_client, STREAM_NOTIFY_TELEGRAM, GROUP_TELEGRAM, consumer_name, count=10, block_ms=5000)`
   - For each `(msg_id, data)`:
     - Try: `await _dispatch_notification(bot, data)` then `await ack(redis_client, ..., msg_id)`
     - Except: log error, do NOT ack (message will be re-delivered on next XREADGROUP)
   - On `asyncio.CancelledError`: log shutdown, break
   - On unexpected exception: log error, `await asyncio.sleep(5)` (back off)

#### `async def _dispatch_notification(bot, data: dict) -> None`

Route by `data["message_type"]`:

**`"reminder"`** -- `content` contains:
- `memory_content: str` -- the memory text
- `fire_at: str` -- when the reminder was scheduled
- `reminder_id: str`
- `memory_id: str`

Action: Send text message: `"Reminder: {memory_content}"` with fire_at info.

**`"llm_image_tag_result"`** -- `content` contains:
- `memory_id: str`
- `tags: list[str]` -- suggested tags
- `description: str` -- optional LLM-generated description

Action: Send message with tag suggestions and `tag_suggestion_keyboard(memory_id)`:
```
Tag suggestions for your image:
Description: {description}
Suggested tags: {comma-separated tags}
[Confirm Tags] [Edit Tags]
```

**`"llm_intent_result"`** -- `content` contains:
- `query: str` -- original search query
- `intent: str` -- classified intent
- `results: list[dict]` -- search results if available

Action: If results available, format and send. If intent is "ambiguous", send clarification message.

**`"llm_followup_result"`** -- `content` contains:
- `question: str` -- the clarifying question from the LLM

Action: Send the question as a plain text message.

**`"llm_task_match_result"`** -- `content` contains:
- `task_id: str`
- `task_description: str`
- `memory_id: str`

Action: Send message with "Mark as done?" prompt and inline keyboard:
```
This looks related to your task: "{task_description}"
Mark as done?
[Yes, mark done] [No]
```
"Yes" button uses `TaskAction("mark_done", task_id)`.

**`"event_confirmation"`** -- `content` contains:
- `event_id: str`
- `description: str`
- `event_date: str`

Action: Send message:
```
I detected an event: "{description}" on {event_date}.
Add as event? [Yes] [No]
```
Note: Event confirmation callbacks will need their own callback data type. For now, send as text with instructions to reply. Full event callback support can be added when the event flow is integrated (Phase 3/4).

**`"event_reprompt"`** -- `content` contains:
- `description: str`
- `event_date: str`

Action: Send message: `"Reminder: I still need your confirmation on this event: \"{description}\" on {event_date}."`

**`"llm_failure"`** -- `content` contains:
- `job_type: str` -- e.g., "image_tag"
- `memory_id: str` (optional)

Action: Send message: `"I couldn't process your request ({job_type}). You can add tags or details manually."`

**Unknown message_type**: Log warning, skip.

---

### `telegram/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install shared package first (changes less frequently)
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/

# Install telegram package
COPY telegram/ /app/telegram/
RUN pip install --no-cache-dir -e /app/telegram/

CMD ["python", "-m", "tg_gateway.main"]
```

Notes:
- Uses `python:3.12-slim` base image
- Installs shared package as editable dependency first (Docker layer caching)
- `CMD` uses module execution (`-m`) so Python properly sets up the package paths

### Docker Compose Updates

Update the `telegram` service in `docker-compose.yml`:

```yaml
telegram:
  build:
    context: .
    dockerfile: telegram/Dockerfile
  depends_on:
    core:
      condition: service_healthy
    redis:
      condition: service_healthy
  env_file: .env
  restart: unless-stopped
```

Key points:
- Build context is the repo root (`.`) so the Dockerfile can COPY both `shared/` and `telegram/`
- `depends_on` with health checks ensures Core and Redis are ready before the bot starts
- No shared volumes needed -- images are uploaded to Core via REST API
- `restart: unless-stopped` for resilience

### Environment Variables

Add to `.env.example`:
```env
# Telegram Gateway
TELEGRAM_BOT_TOKEN=<your-bot-token>
ALLOWED_USER_IDS=123456,789012
CORE_API_URL=http://core:8000
```

---

## Imports Required

From `shared`:
- `shared.redis_streams.STREAM_NOTIFY_TELEGRAM, GROUP_TELEGRAM, create_consumer_group, consume, ack`

From `tg_gateway`:
- `tag_suggestion_keyboard` from `keyboards.py`
- `TaskAction, TagConfirm` from `callback_data.py`

---

## Acceptance Criteria

1. Consumer starts alongside the bot and logs "notify:telegram consumer started"
2. Publishing a `reminder` message to `notify:telegram` results in the user receiving a reminder text in Telegram
3. Publishing a `llm_image_tag_result` results in the user seeing tag suggestions with Confirm/Edit buttons
4. Publishing a `llm_followup_result` results in the user receiving a clarifying question
5. Publishing a `llm_task_match_result` results in a "Mark as done?" prompt with buttons
6. Publishing a `llm_failure` results in the user being told the processing failed
7. Messages that fail to process are NOT acknowledged (will be re-delivered)
8. If Redis is temporarily unreachable, the consumer backs off and reconnects
9. On bot shutdown (SIGTERM), the consumer exits cleanly (CancelledError handled)
10. Dockerfile builds successfully with all dependencies
11. `docker compose up telegram` starts the bot connected to Core and Redis
12. Bot logs show successful connection to Telegram, Core, and Redis
