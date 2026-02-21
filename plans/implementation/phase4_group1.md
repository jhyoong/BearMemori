# Phase 4, Group 1: Config + Dependencies + Dockerfile

## Context

This is the first group of Phase 4 (Email Poller Service). The Email Poller periodically checks configured IMAP email accounts, fetches new unseen emails, filters out noise, deduplicates, and submits them to the core API as LLM jobs for event extraction.

**Current state of `email_poller/`:**
- `poller/__init__.py` -- empty
- `poller/main.py` -- stub that logs "not yet implemented" and sleeps forever
- `pyproject.toml` -- bare, no dependencies listed
- `Dockerfile` -- does NOT install `shared_lib`, does not follow the `llm_worker` pattern

**Key architectural insight:** The email poller does NOT publish to Redis directly. The core `POST /llm_jobs` endpoint (`core/core_svc/routers/llm_jobs.py:49-88`) already creates the DB row AND publishes to the appropriate Redis stream. The email poller only needs to call this HTTP endpoint. It uses Redis only for dedup (tracking processed Message-IDs).

**Dependencies from other services (DO NOT modify these, just use them):**
- `shared/shared_lib/schemas.py` -- `LLMJobCreate` schema: `job_type: JobType`, `payload: dict[str, Any]`, `user_id: int | None`
- `shared/shared_lib/enums.py` -- `JobType.email_extract`

**Pattern reference:** `llm_worker/worker/config.py` -- Pydantic settings class using `BaseSettings` with `SettingsConfigDict`.

---

## Files to Create

### 1. `email_poller/poller/config.py`

Pydantic settings class for the email poller, plus email account config parsing.

```python
"""Configuration settings for the Email Poller service."""

import json
import logging
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

IMAP_HOSTS = {
    "gmail": "imap.gmail.com",
    "outlook": "outlook.office365.com",
}


class EmailAccountConfig(BaseModel):
    """Configuration for a single email account to poll."""

    provider: str  # "gmail" or "outlook"
    email: str
    password: str
    user_id: int  # Telegram user ID (required for LLMJobCreate)
    folder: str = "INBOX"
    filter_senders: list[str] = []
    filter_subjects: list[str] = []


class EmailPollerSettings(BaseSettings):
    """Email Poller settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    redis_url: str = "redis://redis:6379"
    core_api_url: str = "http://core:8000"
    poll_interval_seconds: int = 300
    email_accounts: str = "[]"  # JSON string from env var
    imap_timeout_seconds: int = 30
    dedup_ttl_seconds: int = 604800  # 7 days


def parse_email_accounts(raw: str) -> list[EmailAccountConfig]:
    """Parse a JSON string into a list of EmailAccountConfig objects.

    Returns an empty list if the input is empty or invalid JSON.
    Skips individual accounts that fail validation, logging the error.
    """
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.error("Failed to parse EMAIL_ACCOUNTS JSON: %s", raw[:200])
        return []

    if not isinstance(items, list):
        logger.error("EMAIL_ACCOUNTS must be a JSON array, got: %s", type(items).__name__)
        return []

    accounts: list[EmailAccountConfig] = []
    for i, item in enumerate(items):
        try:
            account = EmailAccountConfig(**item)
            if account.provider not in IMAP_HOSTS:
                logger.error(
                    "Account %d: unknown provider %r (expected one of %s)",
                    i, account.provider, list(IMAP_HOSTS.keys()),
                )
                continue
            accounts.append(account)
        except Exception as exc:
            logger.error("Account %d: validation failed: %s", i, exc)
    return accounts


def load_email_poller_settings() -> EmailPollerSettings:
    """Load and return email poller settings."""
    return EmailPollerSettings()
```

---

## Files to Modify

### 2. `email_poller/pyproject.toml`

Replace the empty dependencies list with the required packages.

**Current content:**
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "life-organiser-email-poller"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["poller"]
```

**New content:**
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "life-organiser-email-poller"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "redis[hiredis]>=5.0.0",
    "pydantic-settings>=2.0.0",
    "aiohttp>=3.9.0",
]

[tool.hatch.build.targets.wheel]
packages = ["poller"]
```

### 3. `email_poller/Dockerfile`

Replace the current Dockerfile to mirror `llm_worker/Dockerfile` (installs shared/ first).

**Current content:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY email_poller/ /app/email_poller/
RUN pip install --no-cache-dir -e /app/email_poller/
CMD ["python", "-m", "poller.main"]
```

**New content (mirror `llm_worker/Dockerfile`):**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/
COPY email_poller/ /app/email_poller/
RUN pip install --no-cache-dir -e /app/email_poller/
CMD ["python", "-m", "poller.main"]
```

---

## Verification

```bash
# Build the Docker image (should succeed without errors)
docker build -f email_poller/Dockerfile -t email-poller-test .

# Run config tests (written in Group 5, but can test early)
pytest tests/test_email_poller/test_config.py -v
```
