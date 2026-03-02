# Queue Visibility and LLM Health Monitoring Design

**Date:** 2026-03-01
**Status:** Approved

## Problem

BearMemori relies on a local LLM inference server which can be unavailable or unstable. When it is, there is no visibility into the queue state, job processing status, or LLM health. Users see "Processing..." but get no updates. The admin has no way to inspect queue depth or system health without querying the database and Redis directly.

## Approach: Hybrid (DB + Redis)

Use the existing `llm_jobs` database table for authoritative job status reporting, and Redis stream introspection (`XLEN`, `XPENDING`, `XINFO`) for worker/consumer health. Add a lightweight LLM health check in the worker that writes state to Redis.

No changes to core processing logic. The one-at-a-time conversation flow, job creation, Redis stream publishing, and retry mechanisms all stay exactly as they are.

## Components

### 1. Core API Monitoring Endpoints

New router: `core/core_svc/routers/admin.py`

**`GET /admin/queue-stats`**

Returns job counts grouped by status and job_type, plus the age of the oldest queued job.

```json
{
  "by_status": {"queued": 5, "processing": 1, "completed": 142, "failed": 3},
  "by_type": {
    "intent": {"queued": 3, "processing": 1},
    "image_tag": {"queued": 2, "processing": 0}
  },
  "oldest_queued_age_seconds": 45,
  "total_pending": 6
}
```

Queries `llm_jobs` table using existing indexes on `status` and `job_type`.

**`GET /admin/stream-health`**

Introspects Redis streams and consumer groups.

```json
{
  "streams": {
    "llm:intent": {"length": 12, "pending": 2, "last_delivery_age_seconds": 5},
    "llm:image_tag": {"length": 3, "pending": 0, "last_delivery_age_seconds": null}
  },
  "consumer_group": "llm-worker-group",
  "consumers_active": 1
}
```

Uses `XLEN`, `XINFO GROUPS`, and `XPENDING` Redis commands.

**`GET /admin/llm-health`**

Returns last-known LLM endpoint health status from Redis key `llm:health_status`.

```json
{
  "status": "healthy",
  "last_check": "2026-03-01T10:30:00Z",
  "last_success": "2026-03-01T10:30:00Z",
  "last_failure": "2026-03-01T09:15:00Z",
  "consecutive_failures": 0
}
```

No authentication on these endpoints (same pattern as existing Core API — internal network only).

### 2. LLM Health Check (Worker Side)

New module: `llm_worker/worker/health_check.py`

Background async task running inside the LLM worker process alongside the consumer loop.

- Every 60 seconds, sends a lightweight HTTP GET to the LLM server's base URL or `/v1/models` endpoint.
- Success: HTTP 2xx response within 5 second timeout.
- Failure: connection refused, timeout, or non-2xx status.
- Writes result to Redis key `llm:health_status` (JSON with status, timestamps, consecutive failure count).
- Redis key TTL: 300 seconds. If worker dies, key expires and admin endpoint reports `unknown`.
- Does NOT send completion requests — just checks endpoint reachability to avoid overloading the inference server.

Integration with `llm_worker/worker/main.py`:
- Starts as `asyncio.create_task()` alongside `run_consumer()`.
- Graceful shutdown cancels both tasks.

On health state transitions (healthy -> unhealthy or vice versa), publishes `llm_health_change` notification to `notify:telegram` stream. Tracks previous state in memory to avoid repeat notifications.

### 3. Telegram Admin Commands

**`/queue` command (admin-only)**

Fetches from the three Core API admin endpoints and formats a summary:

```
Queue Status
------------
Queued: 5 | Processing: 1 | Failed: 3

By type:
  intent: 3 queued, 1 processing
  image_tag: 2 queued, 0 processing

Oldest queued job: 45s ago

LLM: healthy (last check 30s ago)

Worker: active (1 consumer, 2 pending in streams)
```

Access controlled by existing admin/allowed user ID settings in the Telegram gateway.

**`/status` command (any user)**

Shows the requesting user's own pending jobs and LLM health:

```
Your messages
-------------
Pending: 2 (1 processing, 1 queued)

LLM: healthy
```

### 4. User-Facing Submission Feedback

Changes to existing Telegram message handlers for more informative responses.

**When LLM is healthy:**
- First message (nothing queued): "Processing your message..."
- Subsequent messages (queue > 0): "Added to queue (2 messages ahead)"

**When LLM is unhealthy:**
- "Message saved. The system is currently catching up — it will be processed automatically once available."

Health check reads `llm:health_status` Redis key directly (no API call).

**Proactive notifications on health state changes:**
- Unhealthy: "System is catching up — your messages will be processed once the LLM is back" (sent to users with queued jobs)
- Healthy (recovery): "System is back online — processing your queued messages" (sent to those same users)

### 5. Error Handling and Edge Cases

**Worker crashes/restarts:** Health key expires after 5 min (TTL). Treated as `unknown` (same as unhealthy for user-facing messages). Unacked stream messages redelivered on restart (existing behavior).

**Redis unavailable:** Admin endpoints return 503. Health check logs error and retries next iteration. Telegram commands show "Unable to fetch queue status".

**Large job table:** Queue stats only counts `status IN ('queued', 'processing')` — small subset covered by existing index. No new indexes needed.

**Health state flapping:** Notifications only fire on actual transitions. If LLM flaps rapidly, users see each transition (reflects real state).

## Testing

- Admin endpoints: unit tests with mock DB and mock Redis
- Health check: unit tests with mocked HTTP responses
- Telegram commands: unit tests following existing handler test patterns
- Integration: health check + admin endpoint together with fakeredis
