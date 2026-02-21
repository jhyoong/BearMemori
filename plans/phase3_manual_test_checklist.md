# Phase 3: LLM Worker -- Manual Testing Checklist

This checklist is for manual testing after all Phase 3 sub-phases (3.1-3.4) are implemented. It covers every functional area introduced or modified in Phase 3.

---

## Prerequisites and Environment Setup

### 1. Prepare the `.env` file

Copy `.env.example` to `.env` and set the LLM Worker section to use the OpenAI API.

You need an OpenAI API key with access to the models below. Get one at https://platform.openai.com/api-keys.

Set in `.env`:

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_VISION_MODEL=gpt-4o-mini
LLM_TEXT_MODEL=gpt-4o-mini
LLM_API_KEY=sk-your-openai-api-key-here
LLM_MAX_RETRIES=5
```

Notes:
- `gpt-4o-mini` supports both text and vision (image) inputs and is cost-effective for testing.
- You can substitute `gpt-4o` for higher quality results if needed.
- The worker uses the OpenAI Python SDK, so any OpenAI-compatible endpoint works (e.g., Azure OpenAI, OpenRouter), but this checklist assumes the standard OpenAI API.

### 2. Build and start the full stack

```bash
docker compose build
docker compose up -d
```

### 3. Verify all services are healthy

```bash
docker compose ps
```

Expected: All 5 services (`core`, `telegram`, `llm-worker`, `email`, `redis`) should be running. `core` should show `healthy`.

```bash
curl http://localhost:8000/health
```

Expected: `200 OK` response.

### 4. Check LLM Worker logs show startup

```bash
docker compose logs llm-worker
```

Expected output should contain:
- `LLM Worker starting (base_url=...)` -- confirms config loaded
- `LLM Worker consumer started, listening on 5 streams` -- confirms consumer loop running

If you see `LLM Worker -- not yet implemented (Phase 3)` instead, Phase 3 code was not deployed.

### 5. Create a test user (if one does not already exist)

```bash
curl -s http://localhost:8000/settings -X POST \
  -H 'Content-Type: application/json' \
  -d '{"telegram_user_id": 12345, "timezone": "UTC"}'
```

Note the user's `telegram_user_id` (12345 in this example). Use this for all `user_id` fields below.

### 6. Prepare a test image

Place a JPEG image on the Docker `image-data` volume. From the host:

```bash
# Find the volume mount path
docker compose exec core ls /data/images/

# Copy a test image into the volume
docker compose cp /path/to/your/test-image.jpg core:/data/images/test-image.jpg

# Verify it's accessible from the llm-worker container
docker compose exec llm-worker ls /data/images/test-image.jpg
```

---

## Test Group A: Docker and Build Verification

### A1. Dockerfile builds successfully

```bash
docker compose build llm-worker
```

- [ ] Build completes without errors
- [ ] `shared/` is installed before `llm_worker/` (check build log for `pip install -e /app/shared/` before `pip install -e /app/llm_worker/`)
- [ ] `openai`, `aiohttp`, `redis`, `pydantic-settings` appear in installed packages

### A2. Volume mount is present

```bash
docker compose config | grep -A5 "llm-worker"
```

- [ ] `image-data:/data/images` appears in the llm-worker volumes section

### A3. LLM Worker container starts and stays running

```bash
docker compose up -d llm-worker
docker compose ps llm-worker
```

- [ ] Status is `running` (not restarting or exited)
- [ ] No Python import errors in `docker compose logs llm-worker`

### A4. `.env.example` has updated LLM variable names

```bash
cat .env.example | grep -A5 "LLM Worker"
```

- [ ] Uses `LLM_BASE_URL`
- [ ] Uses `LLM_VISION_MODEL`
- [ ] Uses `LLM_TEXT_MODEL`
- [ ] Has `LLM_API_KEY`

---

## Test Group B: Redis Stream Publishing (Core API -> Redis)

These tests verify that creating an LLM job via the Core API publishes a message to the correct Redis stream.

### B1. Create an `image_tag` job and verify Redis publish

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "image_tag",
    "payload": {"memory_id": "mem-test-1", "image_path": "/data/images/test-image.jpg"},
    "user_id": 12345
  }' | python3 -m json.tool
```

- [ ] Response status is `201`
- [ ] Response contains `"status": "queued"`
- [ ] Response contains a UUID `id` field
- [ ] Note the `id` value: ____________

Verify Redis received the message:

```bash
docker compose exec redis redis-cli XLEN llm:image_tag
```

- [ ] Count is >= 1

### B2. Create an `intent_classify` job

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "intent_classify",
    "payload": {"query": "where did I put my passport"},
    "user_id": 12345
  }' | python3 -m json.tool
```

- [ ] Response status is `201`
- [ ] Note the `id`: ____________

```bash
docker compose exec redis redis-cli XLEN llm:intent
```

- [ ] Count is >= 1

### B3. Create a `followup` job

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "followup",
    "payload": {"message": "recipe", "context": "User has saved several cooking notes"},
    "user_id": 12345
  }' | python3 -m json.tool
```

- [ ] Response status is `201`

### B4. Create a `task_match` job

First, create a task so the worker has something to match against:

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "Buy groceries from the supermarket",
    "owner_user_id": 12345
  }' | python3 -m json.tool
```

Note the task `id`: ____________

Then create the task_match job:

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "task_match",
    "payload": {"memory_id": "mem-test-2", "memory_content": "Just got back from the supermarket with all the groceries", "user_id": 12345},
    "user_id": 12345
  }' | python3 -m json.tool
```

- [ ] Response status is `201`

### B5. Create an `email_extract` job

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "email_extract",
    "payload": {"subject": "Team Standup Reminder", "body": "Hi team, our standup meeting is scheduled for March 5, 2026 at 9:00 AM in Conference Room B. Please be on time.", "user_id": 12345},
    "user_id": 12345
  }' | python3 -m json.tool
```

- [ ] Response status is `201`

### B6. Verify graceful degradation without Redis

This tests that if Redis is temporarily unavailable, the Core API still creates the job in the database without crashing.

```bash
# Stop Redis temporarily
docker compose stop redis

# Create a job (should still return 201, just no Redis publish)
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "intent_classify",
    "payload": {"query": "test without redis"},
    "user_id": 12345
  }' | python3 -m json.tool

# Restart Redis
docker compose start redis
```

- [ ] POST still returns `201` (job saved to DB)
- [ ] Core service did not crash (check `docker compose logs core`)

---

## Test Group C: LLM Worker Job Processing

These tests verify that the LLM Worker picks up jobs from Redis, calls the LLM, and processes them correctly. After each job is created in Group B, the worker should have already started processing. Check the worker logs for each.

### C1. Image Tag processing

```bash
docker compose logs llm-worker 2>&1 | grep -i "image_tag\|tagged memory"
```

- [ ] Log shows `Processing job <job_id> (type: image_tag)`
- [ ] Log shows `Tagged memory mem-test-1 with N tags: [...]`
- [ ] No Python traceback (no errors)

Verify job status was updated to `completed`:

```bash
curl -s http://localhost:8000/llm_jobs/<job_id_from_B1> | python3 -m json.tool
```

- [ ] `"status": "completed"`
- [ ] `"result"` contains `"tags"` (a list of strings) and `"description"` (a string)
- [ ] `"updated_at"` is different from `"created_at"`

Verify tags were persisted to the memory via Core API:

```bash
# If you have a memory with id mem-test-1, check its tags:
curl -s http://localhost:8000/memories/mem-test-1 | python3 -m json.tool
```

- [ ] Memory has suggested tags attached (or the `add_tags` endpoint was called -- check worker logs)

### C2. Intent Classification processing

```bash
docker compose logs llm-worker 2>&1 | grep -i "intent\|classified"
```

- [ ] Log shows `Processing job <job_id> (type: intent_classify)`
- [ ] Log shows `Classified query '...' as intent: <intent_type>`
- [ ] Intent is one of: `memory_search`, `task_lookup`, `reminder_check`, `event_search`, `ambiguous`

Verify job completion:

```bash
curl -s http://localhost:8000/llm_jobs/<job_id_from_B2> | python3 -m json.tool
```

- [ ] `"status": "completed"`
- [ ] `"result"` contains `"query"`, `"intent"`, `"results"`

### C3. Followup Question processing

```bash
docker compose logs llm-worker 2>&1 | grep -i "followup\|Generated followup"
```

- [ ] Log shows `Processing job <job_id> (type: followup)`
- [ ] Log shows `Generated followup question: ...`

Verify job completion:

```bash
curl -s http://localhost:8000/llm_jobs?job_type=followup | python3 -m json.tool
```

- [ ] Latest followup job has `"status": "completed"`
- [ ] `"result"` contains `"question"` with a non-empty string

### C4. Task Match processing

```bash
docker compose logs llm-worker 2>&1 | grep -i "task_match\|matched memory\|No confident"
```

- [ ] Log shows `Processing job <job_id> (type: task_match)`
- [ ] Log shows either:
  - `Matched memory mem-test-2 to task <task_id> (confidence: X.XX)` if LLM found a match, OR
  - `No confident task match for memory mem-test-2` if confidence was too low

Verify job completion:

```bash
curl -s http://localhost:8000/llm_jobs?job_type=task_match | python3 -m json.tool
```

- [ ] Latest task_match job has `"status": "completed"`
- [ ] If matched: `"result"` contains `"task_id"`, `"task_description"`, `"memory_id"`
- [ ] If not matched: `"result"` is `null`

### C5. Email Extract processing

```bash
docker compose logs llm-worker 2>&1 | grep -i "email_extract\|Extracted.*events\|No high-confidence"
```

- [ ] Log shows `Processing job <job_id> (type: email_extract)`
- [ ] Log shows either:
  - `Extracted N events from email 'Team Standup Reminder'`, OR
  - `No high-confidence events in email 'Team Standup Reminder'`

Verify job completion:

```bash
curl -s http://localhost:8000/llm_jobs?job_type=email_extract | python3 -m json.tool
```

- [ ] Latest email_extract job has `"status": "completed"`
- [ ] If events found: `"result"` contains `"description"` and `"event_date"`

If a high-confidence event was extracted, verify it was created in Core:

```bash
curl -s "http://localhost:8000/events?owner_user_id=12345" | python3 -m json.tool
```

- [ ] Event exists with `"source_type": "email"` and description matching the meeting

### C6. Task Match with no open tasks

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "task_match",
    "payload": {"memory_id": "mem-test-3", "memory_content": "random note about nothing", "user_id": 99999},
    "user_id": 99999
  }' | python3 -m json.tool
```

```bash
docker compose logs --since=30s llm-worker
```

- [ ] Log shows `No open tasks for user 99999, skipping match`
- [ ] Job completes (status = `completed`) with `result = null`
- [ ] LLM was NOT called (no `complete` log for this job)

---

## Test Group D: Notification Publishing (Worker -> notify:telegram)

After each successful job, the worker should publish a notification to the `notify:telegram` Redis stream for the Telegram consumer to pick up.

### D1. Check notification stream has messages

```bash
docker compose exec redis redis-cli XLEN notify:telegram
```

- [ ] Count is >= 1 (at least some of the jobs above should have published notifications)

### D2. Read notification messages from Redis

```bash
docker compose exec redis redis-cli XRANGE notify:telegram - + COUNT 10
```

For each message, verify the JSON data field contains:
- [ ] `"user_id"` is an integer (e.g., 12345)
- [ ] `"message_type"` is one of: `llm_image_tag_result`, `llm_intent_result`, `llm_followup_result`, `llm_task_match_result`, `event_confirmation`
- [ ] `"content"` is a dict matching the expected shape for that message type

### D3. Verify notification shapes match Telegram consumer expectations

For `llm_image_tag_result`:
- [ ] content has `"memory_id"` (string)
- [ ] content has `"tags"` (list of strings)
- [ ] content has `"description"` (string)

For `llm_intent_result`:
- [ ] content has `"query"` (string)
- [ ] content has `"intent"` (string)
- [ ] content has `"results"` (list)

For `llm_followup_result`:
- [ ] content has `"question"` (string)

For `llm_task_match_result` (only if a match was found):
- [ ] content has `"task_id"` (string)
- [ ] content has `"task_description"` (string)
- [ ] content has `"memory_id"` (string)

For `event_confirmation` (only if event was extracted):
- [ ] content has `"description"` (string)
- [ ] content has `"event_date"` (string, ISO8601 format)

### D4. Verify no notification for null results

If a handler returns `None` (e.g., task_match with no match, email_extract with no events):
- [ ] No notification message was published for that job
- [ ] The job was still marked as `completed` in the database

---

## Test Group E: Retry and Error Handling

### E1. Test LLM connection failure and retry

Simulate an LLM API failure by temporarily pointing the worker at a non-existent endpoint:

```bash
# Stop the worker, change the LLM_BASE_URL to something unreachable, restart
docker compose stop llm-worker

# Edit .env temporarily:
# Change LLM_BASE_URL=https://api.openai.com/v1
# To:    LLM_BASE_URL=http://localhost:19999/v1

docker compose up -d llm-worker
```

Create a new job:

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "intent_classify",
    "payload": {"query": "test retry behavior"},
    "user_id": 12345
  }' | python3 -m json.tool
```

Note the job `id`: ____________

```bash
# Watch worker logs for retry behavior
docker compose logs -f llm-worker
```

- [ ] Log shows `Job <job_id> failed: LLM API error: ...`
- [ ] Log shows `Job <job_id> will retry (attempt 1), backing off 1.0s`
- [ ] Subsequent retries show increasing backoff: 2.0s, 4.0s, 8.0s, etc.
- [ ] After `LLM_MAX_RETRIES` (default 5) failures, log shows `Job <job_id> exceeded max retries, marking failed`

Verify the job ends as `failed`:

```bash
curl -s http://localhost:8000/llm_jobs/<job_id> | python3 -m json.tool
```

- [ ] `"status": "failed"`
- [ ] `"error_message"` is non-empty and describes the LLM error

### E2. Verify failure notification is sent

```bash
docker compose exec redis redis-cli XRANGE notify:telegram - + COUNT 50
```

Look for the failure notification:
- [ ] A message with `"message_type": "llm_failure"` exists
- [ ] Content has `"job_type": "intent_classify"`
- [ ] Content has `"memory_id"` (may be empty string if not in payload)

### E3. Restore LLM config and verify recovery

Restore the correct `LLM_BASE_URL` in `.env` and restart the worker:

```bash
# Edit .env:
# Change LLM_BASE_URL=http://localhost:19999/v1
# Back to: LLM_BASE_URL=https://api.openai.com/v1

docker compose up -d llm-worker
```

Then create a new job:

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "intent_classify",
    "payload": {"query": "test after recovery"},
    "user_id": 12345
  }' | python3 -m json.tool
```

- [ ] New job completes successfully (status = `completed`)
- [ ] Worker did not need to be restarted

### E4. Test bad image path

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "image_tag",
    "payload": {"memory_id": "mem-bad", "image_path": "/data/images/nonexistent.jpg"},
    "user_id": 12345
  }' | python3 -m json.tool
```

Note the job `id`: ____________

```bash
docker compose logs --since=60s llm-worker 2>&1 | grep -i "mem-bad\|nonexistent\|failed\|FileNotFound"
```

- [ ] Worker logs show `FileNotFoundError` or similar
- [ ] After max retries, job is marked `"status": "failed"`
- [ ] Worker did NOT crash (still running: `docker compose ps llm-worker`)

---

## Test Group F: Job Lifecycle and State Transitions

### F1. Verify full lifecycle: queued -> processing -> completed

Create a job and immediately check its status:

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "intent_classify",
    "payload": {"query": "what is the weather"},
    "user_id": 12345
  }' | python3 -m json.tool
```

- [ ] Initial response shows `"status": "queued"`

Wait a few seconds, then:

```bash
curl -s http://localhost:8000/llm_jobs/<job_id> | python3 -m json.tool
```

- [ ] Status is now `"completed"` (or `"processing"` if you check fast enough)
- [ ] `"result"` is populated
- [ ] `"updated_at"` > `"created_at"`

### F2. List jobs with filters

```bash
# All completed jobs
curl -s "http://localhost:8000/llm_jobs?status=completed" | python3 -m json.tool

# All failed jobs
curl -s "http://localhost:8000/llm_jobs?status=failed" | python3 -m json.tool

# All image_tag jobs
curl -s "http://localhost:8000/llm_jobs?job_type=image_tag" | python3 -m json.tool

# Jobs for a specific user
curl -s "http://localhost:8000/llm_jobs?user_id=12345" | python3 -m json.tool
```

- [ ] Filters work correctly, returning only matching jobs
- [ ] Results are ordered by `created_at DESC` (newest first)

---

## Test Group G: Worker Resilience

### G1. Worker survives Redis restart

```bash
docker compose restart redis
```

Wait for Redis to be healthy again:

```bash
docker compose ps redis
```

- [ ] LLM Worker reconnects (check `docker compose logs --since=60s llm-worker`)
- [ ] New jobs can be processed after Redis restart

### G2. Worker handles graceful shutdown

```bash
docker compose stop llm-worker
docker compose logs llm-worker 2>&1 | tail -5
```

- [ ] Log shows `Received shutdown signal` or `LLM Worker shutting down`
- [ ] No unhandled exception on shutdown

```bash
docker compose start llm-worker
```

- [ ] Worker starts up again cleanly
- [ ] Consumer groups are re-created (existing ones are ignored)

### G3. Worker handles LLM returning invalid JSON

This depends on the LLM's actual behavior. If you can craft a prompt that causes the LLM to return non-JSON, test it. Otherwise, this is covered by automated tests.

---

## Test Group H: End-to-End Flow (All Services Together)

### H1. Full image tagging flow

1. Create a memory via Core API (or use an existing one):

```bash
curl -s -X POST http://localhost:8000/memories \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "Photo from the park",
    "owner_user_id": 12345,
    "content_type": "image",
    "image_path": "/data/images/test-image.jpg"
  }' | python3 -m json.tool
```

Note the memory `id`: ____________

2. Create an image_tag job referencing that memory:

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "image_tag",
    "payload": {"memory_id": "<memory_id>", "image_path": "/data/images/test-image.jpg"},
    "user_id": 12345
  }' | python3 -m json.tool
```

3. Wait for processing, then verify:

- [ ] Job status is `completed`
- [ ] Tags were suggested (check job result)
- [ ] `add_tags` was called on the memory (check worker logs)
- [ ] A notification was published to `notify:telegram` with `message_type=llm_image_tag_result`

### H2. Full email-to-event flow

1. Create an email_extract job:

```bash
curl -s -X POST http://localhost:8000/llm_jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "email_extract",
    "payload": {
      "subject": "Dentist Appointment Confirmation",
      "body": "Dear patient, your dental appointment is confirmed for March 15, 2026 at 2:30 PM with Dr. Smith at Downtown Dental Clinic.",
      "user_id": 12345
    },
    "user_id": 12345
  }' | python3 -m json.tool
```

2. Wait for processing, then verify:

- [ ] Job status is `completed`
- [ ] An event was created via Core API:

```bash
curl -s "http://localhost:8000/events?owner_user_id=12345" | python3 -m json.tool
```

- [ ] Event exists with `"source_type": "email"` and description about the dental appointment
- [ ] A notification was published to `notify:telegram` with `message_type=event_confirmation`

---

## Test Group I: Automated Tests

Run these from the repo root to confirm all Phase 3 automated tests pass.

### I1. LLM Worker unit tests

```bash
pytest tests/test_llm_worker/test_retry.py -v
pytest tests/test_llm_worker/test_utils.py -v
pytest tests/test_llm_worker/test_llm_client.py -v
pytest tests/test_llm_worker/test_core_api_client.py -v
```

- [ ] All tests pass

### I2. LLM Worker handler tests

```bash
pytest tests/test_llm_worker/test_image_tag.py -v
pytest tests/test_llm_worker/test_intent.py -v
pytest tests/test_llm_worker/test_followup.py -v
pytest tests/test_llm_worker/test_task_match.py -v
pytest tests/test_llm_worker/test_email_extract.py -v
```

- [ ] All tests pass

### I3. Consumer loop tests

```bash
pytest tests/test_llm_worker/test_consumer.py -v
```

- [ ] All tests pass

### I4. Core API tests (regression check)

```bash
pytest tests/test_core/ -v
```

- [ ] All existing tests pass (no regressions)
- [ ] New Redis publish tests pass (test_create_llm_job_publishes_to_redis, etc.)

### I5. Full test suite

```bash
pytest -v
```

- [ ] All tests pass across all test directories

---

## Summary Scorecard

| Group | Description | Pass/Fail |
|-------|-------------|-----------|
| A | Docker and Build | |
| B | Redis Stream Publishing | |
| C | LLM Worker Job Processing | |
| D | Notification Publishing | |
| E | Retry and Error Handling | |
| F | Job Lifecycle | |
| G | Worker Resilience | |
| H | End-to-End Flows | |
| I | Automated Tests | |
