# Sub-phase 3.4: Core API Integration + Docker Configuration

## Context

This is the final sub-phase of Phase 3. It addresses two gaps:

1. **Core API gap:** The `POST /llm_jobs` endpoint creates a job in the database but does NOT publish to Redis streams. Without this, the LLM Worker never receives jobs. This sub-phase adds the Redis publish step.

2. **Docker gap:** The `llm-worker` service in `docker-compose.yml` does not have the `image-data` volume mounted, so the worker cannot read image files for tagging.

**Prerequisites (all from sub-phases 3.1-3.3, already built):**
- Complete LLM Worker service: config, LLM client, Core API client, handlers, consumer, entrypoint
- All worker tests passing

**Files to reference (do not rebuild, just understand):**

`core/core_svc/routers/llm_jobs.py` -- The endpoint to modify. Current `create_llm_job()` flow:
1. Generate UUID
2. Serialize payload to JSON
3. INSERT into `llm_jobs` table with `status="queued"`
4. `db.commit()`
5. Log audit
6. Return `LLMJobResponse`

Missing step between 5 and 6: publish to the appropriate Redis stream.

`core/core_svc/main.py` -- Redis client is stored at `app.state.redis` during lifespan startup (line 37: `app.state.redis = await redis.asyncio.from_url(config.redis_url)`). The router needs to access this via `request.app.state.redis`.

`shared/shared_lib/redis_streams.py` -- `publish(redis_client, stream_name, data)` function. Stream constants: `STREAM_LLM_IMAGE_TAG`, `STREAM_LLM_INTENT`, `STREAM_LLM_FOLLOWUP`, `STREAM_LLM_TASK_MATCH`, `STREAM_LLM_EMAIL_EXTRACT`.

`shared/shared_lib/enums.py` -- `JobType` enum: `image_tag`, `intent_classify`, `followup`, `task_match`, `email_extract`.

`docker-compose.yml` -- Current `llm-worker` service config (no volumes).

`.env.example` -- Current LLM section uses Ollama-specific env vars that need updating.

**Existing test infrastructure:**
- `tests/conftest.py` -- `test_app` fixture provides `AsyncClient`, `mock_redis` provides `fakeredis`
- `tests/test_core/test_llm_jobs.py` -- 23 existing tests for the LLM jobs endpoints
- The `test_app` fixture does NOT currently inject `mock_redis` into `app.state.redis`. This needs to be addressed for the new test.

---

## Files to Modify

### 1. `core/core_svc/routers/llm_jobs.py`

Add Redis stream publishing after job creation.

**Changes to make:**

a) Add imports at the top of the file:

```python
from fastapi import Request

from shared_lib.redis_streams import (
    STREAM_LLM_EMAIL_EXTRACT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_TASK_MATCH,
    publish,
)
```

b) Add the job type to stream mapping (module-level constant):

```python
JOB_TYPE_TO_STREAM: dict[str, str] = {
    "image_tag": STREAM_LLM_IMAGE_TAG,
    "intent_classify": STREAM_LLM_INTENT,
    "followup": STREAM_LLM_FOLLOWUP,
    "task_match": STREAM_LLM_TASK_MATCH,
    "email_extract": STREAM_LLM_EMAIL_EXTRACT,
}
```

c) Modify the `create_llm_job` function signature to accept `Request`:

```python
@router.post("", response_model=LLMJobResponse, status_code=status.HTTP_201_CREATED)
async def create_llm_job(
    job: LLMJobCreate,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> LLMJobResponse:
```

d) Add Redis publish after the audit log, before the final SELECT:

```python
    # Log audit
    await log_audit(db, "llm_job", job_id, "created", actor)

    # Publish to Redis stream for LLM Worker to consume
    stream = JOB_TYPE_TO_STREAM.get(job.job_type)
    redis_client = getattr(request.app.state, "redis", None)
    if stream and redis_client:
        await publish(redis_client, stream, {
            "job_id": job_id,
            "job_type": job.job_type,
            "payload": job.payload,
            "user_id": job.user_id,
        })

    # Fetch and return the created job
    ...
```

The `getattr(..., None)` guard ensures tests without Redis don't crash. In tests using `mock_redis`, `app.state.redis` needs to be set (see test changes below).

---

### 2. `docker-compose.yml`

Add `image-data` volume to the `llm-worker` service so it can read image files.

**Current `llm-worker` section:**
```yaml
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
```

**Change to:**
```yaml
  llm-worker:
    build:
      context: .
      dockerfile: llm_worker/Dockerfile
    volumes:
      - image-data:/data/images
    depends_on:
      core:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env
```

---

### 3. `.env.example`

Update the LLM Worker section to use OpenAI-compatible env var names.

**Current:**
```env
# ============================
# LLM Worker
# ============================
OLLAMA_BASE_URL=http://<ollama-host>:11434
OLLAMA_VISION_MODEL=llava
OLLAMA_TEXT_MODEL=mistral
LLM_MAX_RETRIES=5
```

**Change to:**
```env
# ============================
# LLM Worker
# ============================
LLM_BASE_URL=http://<llm-server>:8080/v1
LLM_VISION_MODEL=llava
LLM_TEXT_MODEL=mistral
LLM_API_KEY=not-needed
LLM_MAX_RETRIES=5
```

---

### 4. `tests/conftest.py`

The `test_app` fixture needs to inject `mock_redis` into `app.state.redis` so the new Redis publish code in `create_llm_job` works in tests.

**Add after the dependency override line:**

```python
    app.dependency_overrides[get_db] = get_test_db

    # Inject mock Redis into app state for routers that use request.app.state.redis
    app.state.redis = mock_redis

    async with AsyncClient(...) as client:
        yield client

    app.dependency_overrides.clear()
    # Clean up app state
    if hasattr(app.state, "redis"):
        del app.state.redis
```

Note: The `test_app` fixture already receives `mock_redis` as a parameter, so no fixture signature change is needed.

---

## Test Files to Create/Modify

### 5. New test in `tests/test_core/test_llm_jobs.py`

Add a test verifying that creating a job publishes to the correct Redis stream.

```
Test case: test_create_llm_job_publishes_to_redis

Setup:
  - Use existing test_app and test_user fixtures
  - mock_redis is already injected into app.state.redis (from conftest change above)

Action:
  - POST /llm_jobs with job_type="image_tag", payload={"memory_id": "m-1", "image_path": "/data/images/test.jpg"}, user_id=12345

Assert:
  - Response status is 201
  - Read from Redis stream "llm:image_tag" to verify a message was published
  - The message data contains: job_id (matches response), job_type="image_tag", payload matches, user_id=12345

Additional test case: test_create_llm_job_publishes_intent_stream
  - Same as above but with job_type="intent_classify"
  - Verify message appears on "llm:intent" stream

Additional test case: test_create_llm_job_no_redis_no_crash
  - Delete app.state.redis before the call
  - POST /llm_jobs should still return 201 (job created in DB)
  - No crash even without Redis (graceful degradation)
```

**Reading from Redis streams in tests:**
```python
# After creating the job, read from the stream
result = await mock_redis.xread({"llm:image_tag": "0-0"}, count=1)
assert len(result) == 1
stream_name, messages = result[0]
msg_id, fields = messages[0]
data = json.loads(fields[b"data"])
assert data["job_id"] == response_json["id"]
assert data["job_type"] == "image_tag"
```

---

## Checkpoint

After this sub-phase is complete, verify:

1. `pytest tests/test_core/test_llm_jobs.py` -- all 23 existing tests still pass + new Redis publish tests pass
2. `pytest tests/test_core/` -- full core test suite passes (no regressions)
3. `pytest tests/test_llm_worker/` -- all worker tests still pass
4. `docker compose build` -- all images build successfully
5. `docker compose up` -- all services start, health checks pass
6. Manual smoke test:
   ```bash
   curl -X POST http://localhost:8000/llm_jobs \
     -H 'Content-Type: application/json' \
     -d '{"job_type": "intent_classify", "payload": {"query": "test"}, "user_id": 12345}'
   ```
   Check `docker compose logs llm-worker` -- should show the worker consuming the job and attempting to call the LLM.

---

## Code Conventions

- Async throughout: `async def`, `await`
- Type hints on all function signatures
- Max 100 char line length, double quotes, f-strings
- Logger per module: `logger = logging.getLogger(__name__)`
- Imports: stdlib, then third-party, then first-party, alphabetical within groups
