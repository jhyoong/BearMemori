# Queue Visibility and LLM Health Monitoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add queue visibility and LLM health monitoring via Core API admin endpoints, LLM worker health checks, and Telegram bot commands/feedback.

**Architecture:** Hybrid approach using DB queries for job status counts and Redis introspection for stream/consumer health. A background health check in the LLM worker pings the LLM endpoint and writes status to Redis. Telegram bot reads this for user feedback and admin commands.

**Tech Stack:** FastAPI (Core API), redis.asyncio (Redis introspection), aiohttp (health check HTTP), python-telegram-bot (commands), fakeredis (tests)

---

### Task 1: Core API — Queue Stats Endpoint

**Files:**
- Create: `core/core_svc/routers/admin.py`
- Modify: `core/core_svc/main.py:54-71` (register router)
- Test: `tests/test_core/test_admin.py`

**Step 1: Write the failing test**

Create `tests/test_core/test_admin.py`:

```python
"""Tests for the admin monitoring endpoints."""

import pytest


@pytest.mark.asyncio
async def test_queue_stats_empty(test_app, test_user):
    """Queue stats returns zeros when no jobs exist."""
    resp = await test_app.get("/admin/queue-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_pending"] == 0
    assert data["by_status"]["queued"] == 0
    assert data["by_status"]["processing"] == 0
    assert data["oldest_queued_age_seconds"] is None


@pytest.mark.asyncio
async def test_queue_stats_with_jobs(test_app, test_user):
    """Queue stats counts jobs by status and type."""
    # Create jobs via the API
    for _ in range(3):
        await test_app.post("/llm_jobs", json={
            "job_type": "intent_classify",
            "payload": {"message": "test"},
            "user_id": test_user,
        })
    await test_app.post("/llm_jobs", json={
        "job_type": "image_tag",
        "payload": {"memory_id": "m1", "image_path": "/tmp/x.jpg"},
        "user_id": test_user,
    })

    resp = await test_app.get("/admin/queue-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_pending"] == 4
    assert data["by_status"]["queued"] == 4
    assert data["by_type"]["intent_classify"]["queued"] == 3
    assert data["by_type"]["image_tag"]["queued"] == 1
    assert data["oldest_queued_age_seconds"] is not None


@pytest.mark.asyncio
async def test_queue_stats_user_filter(test_app, test_user):
    """Queue stats can filter by user_id."""
    await test_app.post("/llm_jobs", json={
        "job_type": "intent_classify",
        "payload": {"message": "test"},
        "user_id": test_user,
    })
    resp = await test_app.get(f"/admin/queue-stats?user_id={test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_pending"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_admin.py -v`
Expected: FAIL — 404 because endpoint does not exist yet.

**Step 3: Write the admin router**

Create `core/core_svc/routers/admin.py`:

```python
"""Admin monitoring endpoints for queue visibility."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/queue-stats")
async def queue_stats(request: Request, user_id: int | None = None):
    """Return job counts grouped by status and job_type."""
    db = request.app.state.db

    # Build WHERE clause
    where_parts = []
    params = []
    if user_id is not None:
        where_parts.append("user_id = ?")
        params.append(user_id)
    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    # Counts by status
    cursor = await db.execute(
        f"SELECT status, COUNT(*) as cnt FROM llm_jobs {where_clause} GROUP BY status",
        params,
    )
    rows = await cursor.fetchall()
    by_status = {"queued": 0, "processing": 0, "completed": 0, "failed": 0}
    for row in rows:
        by_status[row["status"]] = row["cnt"]

    # Counts by job_type (only pending statuses)
    pending_where = "status IN ('queued', 'processing')"
    if where_parts:
        pending_where = f"{pending_where} AND {' AND '.join(where_parts)}"
    cursor = await db.execute(
        f"SELECT job_type, status, COUNT(*) as cnt FROM llm_jobs WHERE {pending_where} GROUP BY job_type, status",
        params,
    )
    rows = await cursor.fetchall()
    by_type: dict[str, dict[str, int]] = {}
    for row in rows:
        jt = row["job_type"]
        if jt not in by_type:
            by_type[jt] = {"queued": 0, "processing": 0}
        by_type[jt][row["status"]] = row["cnt"]

    # Oldest queued job age
    oldest_where = "status = 'queued'"
    if where_parts:
        oldest_where = f"{oldest_where} AND {' AND '.join(where_parts)}"
    cursor = await db.execute(
        f"SELECT MIN(created_at) as oldest FROM llm_jobs WHERE {oldest_where}",
        params,
    )
    oldest_row = await cursor.fetchone()
    oldest_queued_age_seconds = None
    if oldest_row and oldest_row["oldest"]:
        oldest_dt = datetime.fromisoformat(oldest_row["oldest"]).replace(
            tzinfo=timezone.utc
        )
        oldest_queued_age_seconds = (
            datetime.now(timezone.utc) - oldest_dt
        ).total_seconds()

    total_pending = by_status["queued"] + by_status["processing"]

    return {
        "by_status": by_status,
        "by_type": by_type,
        "oldest_queued_age_seconds": oldest_queued_age_seconds,
        "total_pending": total_pending,
    }
```

**Step 4: Register router in main.py**

In `core/core_svc/main.py`, add alongside existing router imports/registrations:

```python
from core_svc.routers.admin import router as admin_router
# ...
app.include_router(admin_router)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_core/test_admin.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add core/core_svc/routers/admin.py core/core_svc/main.py tests/test_core/test_admin.py
git commit -m "feat: add /admin/queue-stats endpoint for job count monitoring"
```

---

### Task 2: Core API — Stream Health Endpoint

**Files:**
- Modify: `core/core_svc/routers/admin.py`
- Test: `tests/test_core/test_admin.py`

**Step 1: Write the failing test**

Append to `tests/test_core/test_admin.py`:

```python
@pytest.mark.asyncio
async def test_stream_health(test_app):
    """Stream health returns stream info from Redis."""
    resp = await test_app.get("/admin/stream-health")
    assert resp.status_code == 200
    data = resp.json()
    assert "streams" in data
    assert "consumer_group" in data
    # With fakeredis, streams may not exist yet — that's fine
    assert data["consumer_group"] == "llm-worker-group"


@pytest.mark.asyncio
async def test_stream_health_with_messages(test_app, test_user):
    """Stream health shows stream lengths after jobs are published."""
    # Create a job which publishes to Redis stream
    await test_app.post("/llm_jobs", json={
        "job_type": "intent_classify",
        "payload": {"message": "test"},
        "user_id": test_user,
    })
    resp = await test_app.get("/admin/stream-health")
    assert resp.status_code == 200
    data = resp.json()
    # The llm:intent stream should have at least 1 message
    intent_stream = data["streams"].get("llm:intent", {})
    assert intent_stream.get("length", 0) >= 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core/test_admin.py::test_stream_health -v`
Expected: FAIL — endpoint not found.

**Step 3: Add stream-health endpoint to admin router**

Append to `core/core_svc/routers/admin.py`:

```python
from shared_lib.redis_streams import (
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_TASK_MATCH,
    STREAM_LLM_EMAIL_EXTRACT,
    GROUP_LLM_WORKER,
)

ALL_LLM_STREAMS = [
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_TASK_MATCH,
    STREAM_LLM_EMAIL_EXTRACT,
]


@router.get("/stream-health")
async def stream_health(request: Request):
    """Return Redis stream lengths and consumer group info."""
    redis_client = request.app.state.redis
    streams = {}

    for stream_name in ALL_LLM_STREAMS:
        info = {"length": 0, "pending": 0, "last_delivery_age_seconds": None}
        try:
            length = await redis_client.xlen(stream_name)
            info["length"] = length
        except Exception:
            pass

        try:
            # XPENDING returns [total_pending, min_id, max_id, [[consumer, count]...]]
            pending_info = await redis_client.xpending(stream_name, GROUP_LLM_WORKER)
            if pending_info and pending_info["pending"]:
                info["pending"] = pending_info["pending"]
        except Exception:
            pass

        streams[stream_name] = info

    # Count active consumers
    consumers_active = 0
    try:
        groups = await redis_client.xinfo_groups(STREAM_LLM_INTENT)
        for group in groups:
            if group["name"] == GROUP_LLM_WORKER:
                consumers_active = group["consumers"]
                break
    except Exception:
        pass

    return {
        "streams": streams,
        "consumer_group": GROUP_LLM_WORKER,
        "consumers_active": consumers_active,
    }
```

Note: `xpending` and `xinfo_groups` may not be fully supported in fakeredis. If tests fail due to fakeredis limitations, mock the Redis calls in those specific tests. Check fakeredis compatibility first before adding mocks.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_admin.py -v`
Expected: PASS (or adjust for fakeredis limitations)

**Step 5: Commit**

```bash
git add core/core_svc/routers/admin.py tests/test_core/test_admin.py
git commit -m "feat: add /admin/stream-health endpoint for Redis stream introspection"
```

---

### Task 3: Core API — LLM Health Endpoint

**Files:**
- Modify: `core/core_svc/routers/admin.py`
- Test: `tests/test_core/test_admin.py`

**Step 1: Write the failing test**

Append to `tests/test_core/test_admin.py`:

```python
@pytest.mark.asyncio
async def test_llm_health_no_data(test_app):
    """LLM health returns unknown when no health data exists in Redis."""
    resp = await test_app.get("/admin/llm-health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unknown"


@pytest.mark.asyncio
async def test_llm_health_with_data(test_app, mock_redis):
    """LLM health returns stored health data from Redis."""
    import json as json_mod
    health_data = {
        "status": "healthy",
        "last_check": "2026-03-01T10:30:00Z",
        "last_success": "2026-03-01T10:30:00Z",
        "last_failure": None,
        "consecutive_failures": 0,
    }
    await mock_redis.set("llm:health_status", json_mod.dumps(health_data))

    resp = await test_app.get("/admin/llm-health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["consecutive_failures"] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core/test_admin.py::test_llm_health_no_data -v`
Expected: FAIL

**Step 3: Add llm-health endpoint**

Append to `core/core_svc/routers/admin.py`:

```python
LLM_HEALTH_KEY = "llm:health_status"


@router.get("/llm-health")
async def llm_health(request: Request):
    """Return last-known LLM endpoint health status from Redis."""
    redis_client = request.app.state.redis
    try:
        raw = await redis_client.get(LLM_HEALTH_KEY)
        if raw is None:
            return {
                "status": "unknown",
                "last_check": None,
                "last_success": None,
                "last_failure": None,
                "consecutive_failures": 0,
            }
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to read LLM health from Redis")
        return {
            "status": "unknown",
            "last_check": None,
            "last_success": None,
            "last_failure": None,
            "consecutive_failures": 0,
        }
```

**Step 4: Run tests**

Run: `pytest tests/test_core/test_admin.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add core/core_svc/routers/admin.py tests/test_core/test_admin.py
git commit -m "feat: add /admin/llm-health endpoint reading health status from Redis"
```

---

### Task 4: LLM Worker — Health Check Background Task

**Files:**
- Create: `llm_worker/worker/health_check.py`
- Modify: `llm_worker/worker/main.py:29-84`
- Test: `tests/test_llm_worker/test_health_check.py`

**Step 1: Write the failing test**

Create `tests/test_llm_worker/test_health_check.py`:

```python
"""Tests for the LLM health check background task."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import fakeredis.aioredis

from worker.health_check import run_health_check, check_llm_health, LLM_HEALTH_KEY


@pytest.fixture
def mock_redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.mark.asyncio
async def test_check_health_success(mock_redis):
    """Successful health check writes healthy status to Redis."""
    mock_response = MagicMock()
    mock_response.status = 200

    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await check_llm_health(
            llm_base_url="http://localhost:8080/v1",
            redis_client=mock_redis,
            previous_status="unknown",
        )

    assert result == "healthy"
    raw = await mock_redis.get(LLM_HEALTH_KEY)
    data = json.loads(raw)
    assert data["status"] == "healthy"
    assert data["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_check_health_failure(mock_redis):
    """Failed health check writes unhealthy status to Redis."""
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = ConnectionError("refused")

        result = await check_llm_health(
            llm_base_url="http://localhost:8080/v1",
            redis_client=mock_redis,
            previous_status="healthy",
        )

    assert result == "unhealthy"
    raw = await mock_redis.get(LLM_HEALTH_KEY)
    data = json.loads(raw)
    assert data["status"] == "unhealthy"
    assert data["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_check_health_consecutive_failures(mock_redis):
    """Consecutive failures increment the counter."""
    # Seed existing state
    await mock_redis.set(LLM_HEALTH_KEY, json.dumps({
        "status": "unhealthy",
        "consecutive_failures": 2,
        "last_check": "2026-03-01T10:00:00Z",
        "last_success": "2026-03-01T09:00:00Z",
        "last_failure": "2026-03-01T10:00:00Z",
    }))

    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = ConnectionError("refused")

        result = await check_llm_health(
            llm_base_url="http://localhost:8080/v1",
            redis_client=mock_redis,
            previous_status="unhealthy",
        )

    assert result == "unhealthy"
    raw = await mock_redis.get(LLM_HEALTH_KEY)
    data = json.loads(raw)
    assert data["consecutive_failures"] == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_worker/test_health_check.py -v`
Expected: FAIL — module not found.

**Step 3: Implement the health check module**

Create `llm_worker/worker/health_check.py`:

```python
"""LLM endpoint health check background task."""

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

LLM_HEALTH_KEY = "llm:health_status"
HEALTH_CHECK_INTERVAL = 60  # seconds
HEALTH_CHECK_TIMEOUT = 5  # seconds
HEALTH_KEY_TTL = 300  # seconds


async def check_llm_health(
    llm_base_url: str,
    redis_client,
    previous_status: str,
) -> str:
    """Ping the LLM endpoint and write health status to Redis.

    Args:
        llm_base_url: The LLM API base URL (e.g. "http://localhost:8080/v1").
        redis_client: Redis client for writing health status.
        previous_status: The previous health status ("healthy", "unhealthy", "unknown").

    Returns:
        The new health status string.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Read existing state for consecutive_failures counter
    existing = {"consecutive_failures": 0, "last_success": None, "last_failure": None}
    try:
        raw = await redis_client.get(LLM_HEALTH_KEY)
        if raw:
            existing = json.loads(raw)
    except Exception:
        pass

    # Strip /v1 suffix if present, then check /v1/models
    base = llm_base_url.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/models"
    else:
        url = f"{base}/v1/models"

    try:
        timeout = aiohttp.ClientTimeout(total=HEALTH_CHECK_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status < 400:
                    status = "healthy"
                else:
                    status = "unhealthy"
    except (ConnectionError, OSError, asyncio.TimeoutError, aiohttp.ClientError):
        status = "unhealthy"

    # Build health data
    if status == "healthy":
        health_data = {
            "status": "healthy",
            "last_check": now,
            "last_success": now,
            "last_failure": existing.get("last_failure"),
            "consecutive_failures": 0,
        }
    else:
        health_data = {
            "status": "unhealthy",
            "last_check": now,
            "last_success": existing.get("last_success"),
            "last_failure": now,
            "consecutive_failures": existing.get("consecutive_failures", 0) + 1,
        }

    # Write to Redis with TTL
    try:
        await redis_client.set(
            LLM_HEALTH_KEY, json.dumps(health_data), ex=HEALTH_KEY_TTL
        )
    except Exception:
        logger.exception("Failed to write health status to Redis")

    return status


async def run_health_check(
    llm_base_url: str,
    redis_client,
    publish_fn=None,
):
    """Run the health check loop.

    Args:
        llm_base_url: The LLM API base URL.
        redis_client: Redis client.
        publish_fn: Optional async callable(status_change: str, previous: str) for
                     publishing health change notifications. Called only on transitions.
    """
    previous_status = "unknown"

    while True:
        try:
            new_status = await check_llm_health(
                llm_base_url=llm_base_url,
                redis_client=redis_client,
                previous_status=previous_status,
            )

            # Publish notification on state transition
            if (
                publish_fn
                and previous_status != "unknown"
                and new_status != previous_status
            ):
                await publish_fn(new_status, previous_status)

            previous_status = new_status

        except asyncio.CancelledError:
            logger.info("Health check loop cancelled")
            break
        except Exception:
            logger.exception("Error in health check loop")

        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
```

**Step 4: Run tests**

Run: `pytest tests/test_llm_worker/test_health_check.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add llm_worker/worker/health_check.py tests/test_llm_worker/test_health_check.py
git commit -m "feat: add LLM health check module with Redis status writing"
```

---

### Task 5: LLM Worker — Integrate Health Check into main.py

**Files:**
- Modify: `llm_worker/worker/main.py`

**Step 1: Modify main.py to start health check alongside consumer**

In `llm_worker/worker/main.py`, add the health check import and start it as a concurrent task:

```python
# Add import at top:
from worker.health_check import run_health_check

# Add notification publisher helper:
from shared_lib.redis_streams import publish, STREAM_NOTIFY_TELEGRAM


async def _publish_health_change(redis_client, new_status, previous_status):
    """Publish health state change notification to Telegram stream."""
    message_type = "llm_health_change"
    await publish(redis_client, STREAM_NOTIFY_TELEGRAM, {
        "user_id": 0,  # broadcast — Telegram consumer handles routing
        "message_type": message_type,
        "content": {
            "new_status": new_status,
            "previous_status": previous_status,
        },
    })
```

In the `main()` function, replace the single `run_consumer()` call with `asyncio.gather()`:

```python
    try:
        consumer_task = asyncio.create_task(run_consumer(
            redis_client=redis_client,
            handlers=handlers,
            core_api=core_api,
            retry_tracker=retry_tracker,
            config=config,
        ))
        health_task = asyncio.create_task(run_health_check(
            llm_base_url=config.llm_base_url,
            redis_client=redis_client,
            publish_fn=lambda new, prev: _publish_health_change(redis_client, new, prev),
        ))
        await asyncio.gather(consumer_task, health_task)
    except asyncio.CancelledError:
        logger.info("LLM Worker cancelled")
    finally:
        # Cancel tasks on shutdown
        for task in [consumer_task, health_task]:
            if not task.done():
                task.cancel()
        # ... existing cleanup
```

**Step 2: Run existing tests to verify nothing breaks**

Run: `pytest tests/test_llm_worker/ -v`
Expected: PASS (existing tests should not be affected)

**Step 3: Commit**

```bash
git add llm_worker/worker/main.py
git commit -m "feat: integrate health check loop into LLM worker main entrypoint"
```

---

### Task 6: Telegram Bot — /queue Admin Command

**Files:**
- Modify: `telegram/tg_gateway/handlers/command.py`
- Modify: `telegram/tg_gateway/main.py` (register handler)
- Test: `tests/test_telegram/test_commands.py` (create if not exists)

**Step 1: Write the failing test**

Create `tests/test_telegram/test_commands.py` (or append if exists):

```python
"""Tests for Telegram bot command handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_queue_command():
    """The /queue command fetches admin stats and sends formatted message."""
    from tg_gateway.handlers.command import queue_command

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    mock_core_client = AsyncMock()
    context.bot_data = {"core_client": mock_core_client, "config": MagicMock()}
    context.bot_data["config"].allowed_ids_set = {12345}

    # Mock the three admin endpoint calls
    mock_core_client.get_queue_stats = AsyncMock(return_value={
        "by_status": {"queued": 5, "processing": 1, "completed": 100, "failed": 2},
        "by_type": {"intent_classify": {"queued": 3, "processing": 1}},
        "oldest_queued_age_seconds": 45,
        "total_pending": 6,
    })
    mock_core_client.get_stream_health = AsyncMock(return_value={
        "streams": {},
        "consumer_group": "llm-worker-group",
        "consumers_active": 1,
    })
    mock_core_client.get_llm_health = AsyncMock(return_value={
        "status": "healthy",
        "last_check": "2026-03-01T10:30:00Z",
        "consecutive_failures": 0,
    })

    await queue_command(update, context)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "Queued: 5" in text
    assert "Processing: 1" in text
    assert "healthy" in text.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram/test_commands.py::test_queue_command -v`
Expected: FAIL — `queue_command` not found.

**Step 3: Add queue_command to command.py**

Append to `telegram/tg_gateway/handlers/command.py`:

```python
async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show queue status (admin only).

    Args:
        update: The Telegram update.
        context: The context with bot_data containing core_client and config.
    """
    user = update.effective_user
    config = context.bot_data.get("config")
    if config and config.allowed_ids_set and user.id not in config.allowed_ids_set:
        await update.message.reply_text("Not authorized.")
        return

    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    try:
        stats = await core_client.get_queue_stats()
        stream = await core_client.get_stream_health()
        health = await core_client.get_llm_health()
    except Exception:
        logger.exception("Failed to fetch queue status")
        await update.message.reply_text("Unable to fetch queue status.")
        return

    by_status = stats.get("by_status", {})
    by_type = stats.get("by_type", {})
    oldest = stats.get("oldest_queued_age_seconds")

    lines = [
        "Queue Status",
        "------------",
        f"Queued: {by_status.get('queued', 0)} | Processing: {by_status.get('processing', 0)} | Failed: {by_status.get('failed', 0)}",
        "",
    ]

    if by_type:
        lines.append("By type:")
        for jt, counts in by_type.items():
            lines.append(f"  {jt}: {counts.get('queued', 0)} queued, {counts.get('processing', 0)} processing")
        lines.append("")

    if oldest is not None:
        lines.append(f"Oldest queued job: {int(oldest)}s ago")
        lines.append("")

    llm_status = health.get("status", "unknown")
    last_check = health.get("last_check", "never")
    lines.append(f"LLM: {llm_status} (last check: {last_check})")

    consumers = stream.get("consumers_active", 0)
    total_pending_streams = sum(
        s.get("pending", 0) for s in stream.get("streams", {}).values()
    )
    lines.append(f"Worker: {'active' if consumers > 0 else 'inactive'} ({consumers} consumer, {total_pending_streams} pending in streams)")

    await update.message.reply_text("\n".join(lines))
```

**Step 4: Add CoreClient methods for admin endpoints**

Append to `telegram/tg_gateway/core_client.py`:

```python
    async def get_queue_stats(self, user_id: int | None = None) -> dict:
        """Fetch queue stats from admin endpoint."""
        params = {}
        if user_id is not None:
            params["user_id"] = user_id
        resp = await self._client.get("/admin/queue-stats", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_stream_health(self) -> dict:
        """Fetch stream health from admin endpoint."""
        resp = await self._client.get("/admin/stream-health")
        resp.raise_for_status()
        return resp.json()

    async def get_llm_health(self) -> dict:
        """Fetch LLM health from admin endpoint."""
        resp = await self._client.get("/admin/llm-health")
        resp.raise_for_status()
        return resp.json()
```

**Step 5: Register the command in main.py**

In `telegram/tg_gateway/main.py`, add to the command_handlers list and imports:

```python
from tg_gateway.handlers.command import (
    help_command,
    find_command,
    tasks_command,
    pinned_command,
    cancel_command,
    queue_command,  # add this
)

# In the command_handlers list, add:
CommandHandler("queue", queue_command, filters=allowed_filter),
```

Also add to the bot menu commands list in `post_init`:

```python
BotCommand("queue", "Show queue status (admin)"),
```

**Step 6: Run tests**

Run: `pytest tests/test_telegram/test_commands.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add telegram/tg_gateway/handlers/command.py telegram/tg_gateway/core_client.py telegram/tg_gateway/main.py tests/test_telegram/test_commands.py
git commit -m "feat: add /queue admin command for queue visibility in Telegram"
```

---

### Task 7: Telegram Bot — /status User Command

**Files:**
- Modify: `telegram/tg_gateway/handlers/command.py`
- Modify: `telegram/tg_gateway/main.py` (register handler)
- Test: `tests/test_telegram/test_commands.py`

**Step 1: Write the failing test**

Append to `tests/test_telegram/test_commands.py`:

```python
@pytest.mark.asyncio
async def test_status_command():
    """The /status command shows user's own pending jobs and LLM health."""
    from tg_gateway.handlers.command import status_command

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    mock_core_client = AsyncMock()
    context.bot_data = {"core_client": mock_core_client}

    mock_core_client.get_queue_stats = AsyncMock(return_value={
        "by_status": {"queued": 1, "processing": 1, "completed": 10, "failed": 0},
        "total_pending": 2,
    })
    mock_core_client.get_llm_health = AsyncMock(return_value={
        "status": "healthy",
    })

    await status_command(update, context)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "Pending: 2" in text
    assert "healthy" in text.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram/test_commands.py::test_status_command -v`
Expected: FAIL

**Step 3: Add status_command**

Append to `telegram/tg_gateway/handlers/command.py`:

```python
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's own pending messages and LLM health.

    Args:
        update: The Telegram update.
        context: The context with bot_data containing core_client.
    """
    user = update.effective_user
    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    try:
        stats = await core_client.get_queue_stats(user_id=user.id)
        health = await core_client.get_llm_health()
    except Exception:
        logger.exception("Failed to fetch status for user %s", user.id)
        await update.message.reply_text("Unable to fetch status.")
        return

    by_status = stats.get("by_status", {})
    total = stats.get("total_pending", 0)
    queued = by_status.get("queued", 0)
    processing = by_status.get("processing", 0)

    llm_status = health.get("status", "unknown")

    lines = [
        "Your messages",
        "-------------",
        f"Pending: {total} ({processing} processing, {queued} queued)",
        "",
        f"LLM: {llm_status}",
    ]

    await update.message.reply_text("\n".join(lines))
```

**Step 4: Register in main.py**

Add to imports and command_handlers list in `telegram/tg_gateway/main.py`:

```python
from tg_gateway.handlers.command import (
    ...,
    status_command,
)

# Add to command_handlers:
CommandHandler("status", status_command, filters=allowed_filter),

# Add to bot menu commands:
BotCommand("status", "Show your pending messages"),
```

**Step 5: Run tests**

Run: `pytest tests/test_telegram/test_commands.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add telegram/tg_gateway/handlers/command.py telegram/tg_gateway/main.py tests/test_telegram/test_commands.py
git commit -m "feat: add /status command for user queue visibility"
```

---

### Task 8: Telegram Bot — Improved Submission Feedback

**Files:**
- Modify: `telegram/tg_gateway/handlers/message.py`
- Test: `tests/test_telegram/test_message_feedback.py`

**Step 1: Write the failing test**

Create `tests/test_telegram/test_message_feedback.py`:

```python
"""Tests for improved submission feedback in message handlers."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis


@pytest.fixture
def mock_redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.mark.asyncio
async def test_text_message_healthy_first_message(mock_redis):
    """When LLM is healthy and no queue, shows 'Processing your message...'"""
    from tg_gateway.handlers.message import _get_submission_feedback

    # Set healthy status
    await mock_redis.set("llm:health_status", json.dumps({"status": "healthy"}))
    result = await _get_submission_feedback(mock_redis, queue_count=0)
    assert result == "Processing your message..."


@pytest.mark.asyncio
async def test_text_message_healthy_queued(mock_redis):
    """When LLM is healthy and queue > 0, shows queue position."""
    await mock_redis.set("llm:health_status", json.dumps({"status": "healthy"}))
    result = await _get_submission_feedback(mock_redis, queue_count=2)
    assert "2 messages ahead" in result


@pytest.mark.asyncio
async def test_text_message_unhealthy(mock_redis):
    """When LLM is unhealthy, shows catching up message."""
    await mock_redis.set("llm:health_status", json.dumps({"status": "unhealthy"}))
    result = await _get_submission_feedback(mock_redis, queue_count=0)
    assert "catching up" in result.lower()


@pytest.mark.asyncio
async def test_text_message_unknown_status(mock_redis):
    """When no health data exists, treats as unhealthy."""
    # No health key set
    result = await _get_submission_feedback(mock_redis, queue_count=0)
    assert "catching up" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram/test_message_feedback.py -v`
Expected: FAIL — function not found.

**Step 3: Add the feedback helper and update message handlers**

Add to `telegram/tg_gateway/handlers/message.py`:

```python
import json as json_mod

LLM_HEALTH_KEY = "llm:health_status"


async def _get_submission_feedback(redis_client, queue_count: int) -> str:
    """Get appropriate feedback message based on LLM health and queue state.

    Args:
        redis_client: Redis client to read health status.
        queue_count: Number of messages ahead in queue for this user.

    Returns:
        Feedback message string to show the user.
    """
    # Read LLM health from Redis
    status = "unknown"
    try:
        raw = await redis_client.get(LLM_HEALTH_KEY)
        if raw:
            data = json_mod.loads(raw)
            status = data.get("status", "unknown")
    except Exception:
        pass

    if status not in ("healthy",):
        return (
            "Message saved. The system is currently catching up "
            "-- it will be processed automatically once available."
        )

    if queue_count == 0:
        return "Processing your message..."
    else:
        return f"Added to queue ({queue_count} messages ahead)"
```

Then update the `handle_text` function (or equivalent `text_message_handler`) to use this helper instead of the existing static messages. Replace:

```python
    queue_count = get_queue_count(context)
    if queue_count == 0:
        await msg.reply_text("Processing...")
    else:
        await msg.reply_text("Added to queue")
```

With:

```python
    queue_count = get_queue_count(context)
    redis_client = context.bot_data.get("redis")
    feedback = await _get_submission_feedback(redis_client, queue_count)
    await msg.reply_text(feedback)
```

**Step 4: Run tests**

Run: `pytest tests/test_telegram/test_message_feedback.py -v`
Expected: PASS

**Step 5: Run existing tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add telegram/tg_gateway/handlers/message.py tests/test_telegram/test_message_feedback.py
git commit -m "feat: improve submission feedback based on LLM health and queue state"
```

---

### Task 9: Telegram Bot — Health Change Notifications

**Files:**
- Modify: `telegram/tg_gateway/consumer.py`
- Test: `tests/test_telegram/test_consumer_health.py`

**Step 1: Write the failing test**

Create `tests/test_telegram/test_consumer_health.py`:

```python
"""Tests for health change notification dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_dispatch_health_change_unhealthy():
    """Health change to unhealthy sends catching-up message."""
    from tg_gateway.consumer import _dispatch_notification

    application = MagicMock()
    application.bot = AsyncMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {
        "config": MagicMock(allowed_ids_set={12345, 67890}),
    }

    data = {
        "user_id": 0,
        "message_type": "llm_health_change",
        "content": {
            "new_status": "unhealthy",
            "previous_status": "healthy",
        },
    }

    await _dispatch_notification(application, data)

    # Should send to all allowed users
    assert application.bot.send_message.call_count == 2
    text = application.bot.send_message.call_args_list[0][1]["text"]
    assert "catching up" in text.lower()


@pytest.mark.asyncio
async def test_dispatch_health_change_healthy():
    """Health change to healthy sends recovery message."""
    from tg_gateway.consumer import _dispatch_notification

    application = MagicMock()
    application.bot = AsyncMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {
        "config": MagicMock(allowed_ids_set={12345}),
    }

    data = {
        "user_id": 0,
        "message_type": "llm_health_change",
        "content": {
            "new_status": "healthy",
            "previous_status": "unhealthy",
        },
    }

    await _dispatch_notification(application, data)

    assert application.bot.send_message.call_count == 1
    text = application.bot.send_message.call_args_list[0][1]["text"]
    assert "back online" in text.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram/test_consumer_health.py -v`
Expected: FAIL — llm_health_change not handled in dispatch.

**Step 3: Add health change handler to consumer dispatch**

In `telegram/tg_gateway/consumer.py`, add a new `elif` branch in `_dispatch_notification`:

```python
    elif message_type == "llm_health_change":
        new_status = content.get("new_status", "unknown")
        previous_status = content.get("previous_status", "unknown")

        config = application.bot_data.get("config")
        allowed_ids = config.allowed_ids_set if config else set()

        if new_status == "unhealthy":
            text = (
                "System is catching up -- your messages will be "
                "processed once the LLM is back."
            )
        elif new_status == "healthy":
            text = (
                "System is back online -- processing your queued messages."
            )
        else:
            return

        for uid in allowed_ids:
            try:
                await bot.send_message(chat_id=uid, text=text)
            except Exception:
                logger.warning("Failed to send health change to user %s", uid)
```

**Step 4: Run tests**

Run: `pytest tests/test_telegram/test_consumer_health.py -v`
Expected: PASS

**Step 5: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add telegram/tg_gateway/consumer.py tests/test_telegram/test_consumer_health.py
git commit -m "feat: handle llm_health_change notifications in Telegram consumer"
```

---

### Task 10: Final Integration Verification

**Files:**
- No new files — run full test suite and verify everything works together.

**Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS.

**Step 2: Run linter**

Run: `ruff check .`
Expected: No errors.

**Step 3: Verify imports and module structure**

Run: `python -c "from core_svc.routers.admin import router; print('admin router OK')"` (from core/ dir)
Run: `python -c "from worker.health_check import run_health_check; print('health check OK')"` (from llm_worker/ dir)

**Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address linting and integration issues from queue visibility feature"
```

---

## Summary of New/Modified Files

**New files:**
- `core/core_svc/routers/admin.py` — 3 admin endpoints
- `llm_worker/worker/health_check.py` — health check background task
- `tests/test_core/test_admin.py` — admin endpoint tests
- `tests/test_llm_worker/test_health_check.py` — health check tests
- `tests/test_telegram/test_commands.py` — Telegram command tests
- `tests/test_telegram/test_message_feedback.py` — submission feedback tests
- `tests/test_telegram/test_consumer_health.py` — health change notification tests

**Modified files:**
- `core/core_svc/main.py` — register admin router
- `llm_worker/worker/main.py` — start health check task
- `telegram/tg_gateway/handlers/command.py` — add /queue and /status commands
- `telegram/tg_gateway/handlers/message.py` — improved submission feedback
- `telegram/tg_gateway/core_client.py` — add admin API client methods
- `telegram/tg_gateway/main.py` — register new commands
- `telegram/tg_gateway/consumer.py` — handle llm_health_change notifications
