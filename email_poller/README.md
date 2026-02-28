# Email Poller

A service that will periodically check configured IMAP email accounts, fetch unseen emails, filter noise, deduplicate, and submit them to the Core API as LLM jobs for calendar event extraction.

**Status: Stub (Phase 4 scope -- not yet implemented)**

The current code is a placeholder that logs a message and sleeps indefinitely.

## Directory Structure

```
email_poller/
├── pyproject.toml
├── Dockerfile
└── poller/
    ├── __init__.py
    └── main.py         # Placeholder (infinite sleep loop)
```

## Planned Functionality

When implemented, this service will:

1. **Poll IMAP accounts** on a configurable interval (default 300s)
2. **Parse emails** using Python stdlib (`imaplib`, `email`)
3. **Filter noise** by sender/subject patterns (case-insensitive substring match)
4. **Deduplicate** using Redis SET keys per account (7-day TTL on Message-IDs)
5. **Submit to Core API** as `POST /llm_jobs` with `job_type=email_extract`
6. Core API auto-publishes to Redis stream, which the LLM worker picks up for event extraction

## Planned Environment Variables

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |
| `CORE_API_URL` | `http://core:8000` | Core API base URL |
| `POLL_INTERVAL_SECONDS` | `300` | Polling interval |
| `EMAIL_ACCOUNTS` | — | JSON array of account configs |
| `IMAP_TIMEOUT_SECONDS` | `30` | IMAP connection timeout |
| `DEDUP_TTL_SECONDS` | `604800` | Dedup key TTL (7 days) |

## Planned Account Config

```json
{
  "provider": "gmail",
  "email": "user@domain.com",
  "password": "app-password",
  "user_id": 12345,
  "folder": "INBOX",
  "filter_senders": ["noreply@example.com"],
  "filter_subjects": ["newsletter"]
}
```

## Planned Dependencies

- `redis[hiredis]>=5.0.0`
- `pydantic-settings>=2.0.0`
- `aiohttp>=3.9.0`
- `life-organiser-shared`
