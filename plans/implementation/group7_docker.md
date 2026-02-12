# Group 7: Docker + Infrastructure

## Goal

Create the Docker Compose configuration, stub service packages for telegram/llm_worker/email_poller, .env.example, and utility scripts. At the end of this group, `docker compose up` starts all services.

**Depends on:** Group 2 (core Dockerfile)
**Blocks:** Nothing directly (can be done in parallel with later groups)

---

## Context

The full architecture has 5 services in Docker Compose: core, telegram, llm-worker, email, and redis. In Phase 1, only core and redis are functional. The other three are stub containers that stay alive but do nothing. This ensures the docker-compose.yml matches the target architecture from day one.

---

## Steps

### Step 7.1: Stub service packages

Create three minimal packages. Each follows the same pattern.

#### Telegram Gateway stub

**Files:**
- `telegram/pyproject.toml`
- `telegram/telegram_gw/__init__.py` (empty)
- `telegram/telegram_gw/main.py`
- `telegram/Dockerfile`

**`telegram/pyproject.toml`:**
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "life-organiser-telegram"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []
```

**`telegram/telegram_gw/main.py`:**
```python
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Telegram Gateway -- not yet implemented (Phase 2)")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
```

**`telegram/Dockerfile`:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY telegram/ /app/telegram/
RUN pip install --no-cache-dir -e /app/telegram/
CMD ["python", "-m", "telegram_gw.main"]
```

#### LLM Worker stub

**Files:**
- `llm_worker/pyproject.toml`
- `llm_worker/llm_worker/__init__.py` (empty)
- `llm_worker/llm_worker/main.py`
- `llm_worker/Dockerfile`

Same pattern as above. Log message: `"LLM Worker -- not yet implemented (Phase 3)"`

**Dockerfile CMD:** `["python", "-m", "llm_worker.main"]`

#### Email Poller stub

**Files:**
- `email_poller/pyproject.toml`
- `email_poller/email_poller/__init__.py` (empty)
- `email_poller/email_poller/main.py`
- `email_poller/Dockerfile`

Same pattern. Log message: `"Email Poller -- not yet implemented (Phase 4)"`

**Dockerfile CMD:** `["python", "-m", "email_poller.main"]`

---

### Step 7.2: docker-compose.yml

**File:** `docker-compose.yml` (project root)

```yaml
services:
  core:
    build:
      context: .
      dockerfile: core/Dockerfile
    volumes:
      - db-data:/data/db
      - image-data:/data/images
    ports:
      - "8000:8000"
    depends_on:
      redis:
        condition: service_healthy
    env_file: .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

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

  llm-worker:
    build:
      context: .
      dockerfile: llm_worker/Dockerfile
    depends_on:
      core:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env

  email:
    build:
      context: .
      dockerfile: email_poller/Dockerfile
    depends_on:
      core:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

volumes:
  db-data:
  image-data:
  redis-data:
```

**Notes:**
- Core Dockerfile `context` is `.` (project root) because it needs to COPY both `shared/` and `core/`
- Stub Dockerfiles `context` is also `.` for consistency, though they only need their own directory
- Health checks ensure services start in correct order
- `start_period` gives Core time to initialize the database before health checks begin

---

### Step 7.3: .env.example

**File:** `.env.example` (project root)

```env
# ============================
# Core Service
# ============================
CORE_HOST=0.0.0.0
CORE_PORT=8000
DATABASE_PATH=/data/db/life_organiser.db
IMAGE_STORAGE_PATH=/data/images

# S3 Backup (not configured in Phase 1)
# S3_BUCKET=life-organiser-backup
# S3_REGION=ap-southeast-1
# BACKUP_SCHEDULE_CRON=0 3 * * 0

# ============================
# Redis
# ============================
REDIS_URL=redis://redis:6379

# ============================
# Telegram Gateway
# ============================
TELEGRAM_BOT_TOKEN=<your-bot-token>
ALLOWED_USER_IDS=123456,789012
CORE_API_URL=http://core:8000

# ============================
# LLM Worker
# ============================
OLLAMA_BASE_URL=http://<ollama-host>:11434
OLLAMA_VISION_MODEL=llava
OLLAMA_TEXT_MODEL=mistral
LLM_MAX_RETRIES=5

# ============================
# Email Poller
# ============================
EMAIL_POLL_INTERVAL_SECONDS=300
GMAIL_IMAP_HOST=imap.gmail.com
OUTLOOK_IMAP_HOST=outlook.office365.com
# EMAIL_ACCOUNTS='[{"provider": "gmail", "email": "you@gmail.com", "password": "app-password"}]'
```

---

### Step 7.4: Utility scripts

**Directory:** `scripts/`

#### `scripts/init_db.py`

Standalone script to initialize or migrate the database outside Docker. Useful for local development.

```python
"""
Standalone database initialization script.
Usage: python scripts/init_db.py [--db-path PATH]
"""
import argparse
import asyncio
import sys
sys.path.insert(0, '.')

async def main(db_path: str):
    from core.core.database import init_db
    db = await init_db(db_path)
    print(f"Database initialized at {db_path}")
    await db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="./life_organiser.db")
    args = parser.parse_args()
    asyncio.run(main(args.db_path))
```

#### `scripts/backup_now.py`

Stub for triggering an immediate backup.

```python
"""Trigger an immediate backup. (Not implemented in Phase 1)"""
print("S3 backup is not configured in Phase 1.")
```

#### `scripts/restore.py`

Stub for restoring from backup.

```python
"""Restore from S3 backup. (Not implemented in Phase 1)"""
print("S3 restore is not configured in Phase 1.")
```

---

## Acceptance Criteria

1. `docker compose build` builds all 4 service images without errors
2. `docker compose up` starts all 5 services (core, telegram, llm-worker, email, redis)
3. Core health check passes: `curl http://localhost:8000/health` returns `{"status": "ok"}`
4. Redis is reachable: `docker compose exec redis redis-cli ping` returns `PONG`
5. Stub services log their "not yet implemented" message and stay alive
6. `.env.example` exists with all documented variables
7. `python scripts/init_db.py` creates a database file when run locally (with core package installed)
