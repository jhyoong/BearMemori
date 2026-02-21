# Phase 4, Group 3: Filtering + Dedup + Core API Client

## Context

This group implements three small, focused modules:
1. **Filters** -- skip emails matching sender/subject patterns configured per account
2. **Dedup** -- Redis-based tracking of already-processed Message-IDs to avoid re-submitting emails
3. **Core API client** -- HTTP client for submitting LLM jobs to the core service

**Dependencies from previous groups:**
- Group 1: `EmailAccountConfig` (has `filter_senders`, `filter_subjects`, `email`)
- Group 1: `EmailPollerSettings` (has `dedup_ttl_seconds`)

**Key architectural insight:** The email poller submits emails as LLM jobs by calling `POST /llm_jobs` on the core API. The core endpoint (`core/core_svc/routers/llm_jobs.py:49-88`) creates the DB row AND publishes to the Redis stream. The `LLMJobCreate` schema (`shared/shared_lib/schemas.py:236-239`) expects: `job_type: JobType`, `payload: dict[str, Any]`, `user_id: int | None`.

**Pattern reference:** `llm_worker/worker/core_api_client.py` -- async HTTP client using `aiohttp.ClientSession`.

---

## Files to Create

### 1. `email_poller/poller/filters.py`

Simple sender/subject filtering based on account config.

```python
"""Email filtering based on account configuration."""

import logging

from poller.config import EmailAccountConfig

logger = logging.getLogger(__name__)


def should_skip(email_data: dict, account: EmailAccountConfig) -> bool:
    """Check if an email should be skipped based on account filters.

    Returns True if the email matches any filter_senders or filter_subjects
    pattern (case-insensitive substring match).
    """
    sender = (email_data.get("sender") or "").lower()
    subject = (email_data.get("subject") or "").lower()

    for pattern in account.filter_senders:
        if pattern.lower() in sender:
            logger.debug("Skipping email from %s (matches sender filter %r)", sender, pattern)
            return True

    for pattern in account.filter_subjects:
        if pattern.lower() in subject:
            logger.debug("Skipping email with subject matching filter %r", pattern)
            return True

    return False
```

### 2. `email_poller/poller/dedup.py`

Redis-based deduplication using a SET per email account.

```python
"""Redis-based email deduplication."""

import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


def dedup_key(account_email: str) -> str:
    """Return the Redis key for tracking seen Message-IDs for an account."""
    return f"email_poller:seen:{account_email}"


async def is_duplicate(
    redis_client: aioredis.Redis,
    account_email: str,
    message_id: str,
) -> bool:
    """Check if a Message-ID has already been processed for this account."""
    return await redis_client.sismember(dedup_key(account_email), message_id)


async def mark_seen(
    redis_client: aioredis.Redis,
    account_email: str,
    message_id: str,
    ttl_seconds: int,
) -> None:
    """Mark a Message-ID as seen for this account.

    Sets/refreshes the TTL on the set so old entries expire automatically.
    """
    key = dedup_key(account_email)
    await redis_client.sadd(key, message_id)
    await redis_client.expire(key, ttl_seconds)
```

### 3. `email_poller/poller/core_client.py`

HTTP client for calling the core API's `POST /llm_jobs` endpoint.

```python
"""HTTP client for submitting LLM jobs to the Core API."""

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class CoreClientError(Exception):
    """Raised when a Core API call fails."""


class CoreClient:
    """Async HTTP client for submitting email extraction jobs."""

    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        self._base_url = base_url.rstrip("/")
        self._session = session

    async def create_llm_job(
        self,
        job_type: str,
        payload: dict[str, Any],
        user_id: int,
    ) -> dict[str, Any]:
        """Create an LLM job via POST /llm_jobs.

        The core API creates the DB row and publishes to the Redis stream.
        """
        url = f"{self._base_url}/llm_jobs"
        body = {
            "job_type": job_type,
            "payload": payload,
            "user_id": user_id,
        }
        async with self._session.post(url, json=body) as resp:
            if resp.status != 201:
                text = await resp.text()
                raise CoreClientError(
                    f"POST {url} returned {resp.status}: {text}"
                )
            return await resp.json()
```

---

## Verification

```bash
pytest tests/test_email_poller/test_filters.py -v
pytest tests/test_email_poller/test_dedup.py -v
pytest tests/test_email_poller/test_core_client.py -v
```
