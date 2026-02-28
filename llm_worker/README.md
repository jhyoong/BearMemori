# LLM Worker

An async job processing service that consumes LLM tasks from Redis streams, processes them through specialized handlers calling the OpenAI API, and persists results back to the Core API. Publishes notifications to the Telegram stream when jobs complete or fail.

## Running

```bash
# Via Docker
docker-compose up --build

# Locally
cd llm_worker && pip install -e . && python -m worker.main
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:8080/v1` | OpenAI-compatible API base URL |
| `LLM_VISION_MODEL` | `llava` | Model for image analysis |
| `LLM_TEXT_MODEL` | `mistral` | Model for text tasks |
| `LLM_API_KEY` | `not-needed` | API key for LLM service |
| `LLM_MAX_RETRIES` | `5` | Max retries for invalid responses |
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |
| `CORE_API_URL` | `http://core:8000` | Core API base URL |
| `IMAGE_STORAGE_PATH` | `/data/images` | Path to stored images |

## Directory Structure

```
llm_worker/
├── pyproject.toml
├── Dockerfile
└── worker/
    ├── main.py                 # Entry point, wiring, signal handlers
    ├── config.py               # LLMWorkerSettings
    ├── consumer.py             # Main consumer loop, message dispatch
    ├── core_api_client.py      # HTTP client for Core API
    ├── llm_client.py           # OpenAI-compatible async client
    ├── retry.py                # RetryManager with two failure strategies
    ├── prompts.py              # All LLM prompt templates
    ├── utils.py                # JSON extraction from LLM responses
    └── handlers/
        ├── base.py             # Abstract BaseHandler
        ├── image_tag.py        # Image tagging via vision model
        ├── intent.py           # Intent classification
        ├── followup.py         # Follow-up question generation
        ├── task_match.py       # Task matching against open tasks
        └── email_extract.py    # Calendar event extraction from emails
```

## Handlers

Each handler inherits `BaseHandler` and implements `async handle(job_id, payload, user_id) -> dict | None`.

| Handler | Stream | Job Type | Description |
|---|---|---|---|
| `ImageTagHandler` | `llm:image_tag` | `image_tag` | Reads image from disk, sends to vision model, extracts description + tags, saves to Core |
| `IntentHandler` | `llm:intent` | `intent_classify` | Classifies user message intent (reminder, task, search, general_note, ambiguous) |
| `FollowupHandler` | `llm:followup` | `followup` | Generates clarifying follow-up question for ambiguous queries |
| `TaskMatchHandler` | `llm:task_match` | `task_match` | Matches new memory content against user's open tasks (confidence > 0.7) |
| `EmailExtractHandler` | `llm:email_extract` | `email_extract` | Extracts calendar events from email subject/body (confidence > 0.7) |

## Consumer Loop

1. Creates consumer groups for all 5 streams (idempotent)
2. Round-robins through streams, checking pending messages first, then new
3. Validates message age (skips messages older than 5 minutes)
4. Dispatches to appropriate handler
5. On success: updates job status, publishes notification to `notify:telegram`, acknowledges message
6. On failure: classifies failure type and applies retry strategy

## Retry Logic

Two distinct failure strategies:

### Invalid Response (parsing errors, missing fields)
- Max 5 attempts with exponential backoff (1s, 2s, 4s, 8s, 16s)
- After exhaustion: mark job as `failed`, publish `llm_failure` notification

### Unavailable (connection errors, timeouts, 5xx)
- Retries continuously for up to 14 days
- No backoff delay (retried on next consumer cycle)
- Pauses queue processing until service recovers
- After 14 days: mark as `failed`, publish `llm_expiry` notification

## Notifications

Successful results are published to `notify:telegram` with this structure:

```json
{
  "user_id": 123,
  "message_type": "llm_image_tag_result",
  "content": { ... }
}
```

Message types: `llm_image_tag_result`, `llm_intent_result`, `llm_followup_result`, `llm_task_match_result`, `event_confirmation`, `llm_failure`, `llm_expiry`.

## Dependencies

- `openai>=1.0.0`
- `aiohttp>=3.9.0`
- `redis[hiredis]>=5.0.0`
- `pydantic-settings>=2.0.0`
- `life-organiser-shared`
