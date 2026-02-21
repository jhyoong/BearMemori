# Phase 4, Group 4: Poll Loop + Main Entrypoint

## Context

This group implements the main polling loop and the service entrypoint. This is the final group that wires everything together.

**Dependencies from previous groups:**
- Group 1: `EmailPollerSettings`, `parse_email_accounts`, `EmailAccountConfig`
- Group 2: `fetch_unseen_emails` (async IMAP fetch)
- Group 3: `should_skip`, `is_duplicate`, `mark_seen`, `CoreClient`

**Pattern reference:** `llm_worker/worker/main.py` -- async entrypoint with signal handling, Redis client, aiohttp session, and graceful shutdown via `asyncio.Event`.

**Current state of `email_poller/poller/main.py`:**
```python
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Email Poller -- not yet implemented (Phase 4)")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Files to Create

### 1. `email_poller/poller/poller.py`

The main polling loop. Iterates accounts, fetches emails, filters, deduplicates, and submits to core.

```python
"""Email polling loop."""

import asyncio
import logging

import redis.asyncio as aioredis

from poller.config import EmailPollerSettings, parse_email_accounts
from poller.core_client import CoreClient
from poller.dedup import is_duplicate, mark_seen
from poller.filters import should_skip
from poller.imap_client import fetch_unseen_emails

logger = logging.getLogger(__name__)


async def run_poller(
    config: EmailPollerSettings,
    redis_client: aioredis.Redis,
    core_client: CoreClient,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the email polling loop until shutdown_event is set."""
    accounts = parse_email_accounts(config.email_accounts)
    if not accounts:
        logger.warning("No valid email accounts configured, poller will idle")

    logger.info("Starting Email Poller with %d account(s)", len(accounts))

    while not shutdown_event.is_set():
        for account in accounts:
            if shutdown_event.is_set():
                break
            await _poll_account(config, redis_client, core_client, account)

        # Sleep until next poll or shutdown
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=config.poll_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass  # Normal: timeout means it's time to poll again


async def _poll_account(
    config: EmailPollerSettings,
    redis_client: aioredis.Redis,
    core_client: CoreClient,
    account,
) -> None:
    """Poll a single email account for new emails."""
    try:
        emails = await fetch_unseen_emails(account, config.imap_timeout_seconds)
    except Exception:
        logger.exception("IMAP error for account %s", account.email)
        return

    logger.info("Fetched %d unseen email(s) from %s", len(emails), account.email)

    for email_data in emails:
        try:
            if should_skip(email_data, account):
                continue

            message_id = email_data["message_id"]
            if await is_duplicate(redis_client, account.email, message_id):
                logger.debug("Skipping duplicate: %s", message_id)
                continue

            await core_client.create_llm_job(
                job_type="email_extract",
                payload={
                    "subject": email_data.get("subject", ""),
                    "body": email_data.get("body", ""),
                },
                user_id=account.user_id,
            )

            await mark_seen(
                redis_client, account.email, message_id, config.dedup_ttl_seconds
            )
            logger.info("Submitted email %s for extraction", message_id)
        except Exception:
            logger.exception(
                "Error processing email %s from %s",
                email_data.get("message_id", "unknown"),
                account.email,
            )
```

**Key design decisions:**
- `parse_email_accounts()` is called once at startup, not every loop iteration
- IMAP errors on one account are caught and logged; other accounts continue
- Individual email processing errors are caught per-email so one bad email does not skip the rest
- `mark_seen()` is called AFTER `create_llm_job()` succeeds -- if the API call fails, the email will be retried next poll
- Sleep uses `asyncio.wait_for(shutdown_event.wait(), timeout=...)` for responsive shutdown instead of `asyncio.sleep()`

---

## Files to Modify

### 2. `email_poller/poller/main.py`

Replace the stub entirely. Follow the `llm_worker/worker/main.py` pattern.

```python
"""Email Poller main entrypoint."""

import asyncio
import logging
import signal

import aiohttp
import redis.asyncio as aioredis

from poller.config import load_email_poller_settings
from poller.core_client import CoreClient
from poller.poller import run_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Main entrypoint for the Email Poller service."""
    config = load_email_poller_settings()
    logger.info("Starting Email Poller")

    redis_client = aioredis.from_url(config.redis_url)
    session = aiohttp.ClientSession()
    core_client = CoreClient(config.core_api_url, session)

    shutdown_event = asyncio.Event()

    def handle_signal(signum):
        logger.info("Received signal %s, initiating shutdown...", signum)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    try:
        await run_poller(config, redis_client, core_client, shutdown_event)
    except asyncio.CancelledError:
        logger.info("Email Poller cancelled")
    finally:
        logger.info("Cleaning up Email Poller resources...")
        await session.close()
        await redis_client.close()
        logger.info("Email Poller shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Verification

```bash
# Run poller tests
pytest tests/test_email_poller/test_poller.py -v

# Manual integration test with Docker
docker-compose up --build redis core email
# With EMAIL_ACCOUNTS=[] : verify logs "Starting Email Poller" and "No valid email accounts configured"
# With a fake account: verify logs connection attempt and recoverable IMAP error
```
