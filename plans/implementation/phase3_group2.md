# Sub-phase 3.2: Handlers -- Prompt Templates and 5 Job Handlers

## Context

This sub-phase builds on the foundation from sub-phase 3.1. It creates the 5 job handlers and their prompt templates. Each handler follows the same pattern:

1. Receive a job payload dict
2. Call the LLM via `LLMClient` (from `llm_worker/worker/llm_client.py`)
3. Parse the response with `extract_json()` (from `llm_worker/worker/utils.py`)
4. Optionally call Core API side-effects via `CoreAPIClient` (from `llm_worker/worker/core_api_client.py`)
5. Return a notification content dict matching the Telegram consumer's expected format, or `None` if no notification needed

**Prerequisites from sub-phase 3.1 (already built):**
- `llm_worker/worker/config.py` -- `LLMWorkerSettings` with `llm_vision_model`, `llm_text_model`
- `llm_worker/worker/llm_client.py` -- `LLMClient` with `complete(model, prompt)` and `complete_with_image(model, prompt, image_b64)`
- `llm_worker/worker/core_api_client.py` -- `CoreAPIClient` with `update_job()`, `add_tags()`, `create_event()`, `get_open_tasks()`
- `llm_worker/worker/utils.py` -- `extract_json(text) -> dict`
- `llm_worker/worker/retry.py` -- `RetryTracker`
- `tests/test_llm_worker/conftest.py` -- `mock_llm_client`, `mock_core_api`, `llm_worker_config` fixtures

**Notification contracts (the Telegram consumer at `telegram/tg_gateway/consumer.py` expects these exact shapes):**

All notifications published to `notify:telegram` use the wrapper: `{"user_id": int, "message_type": str, "content": dict}`

| message_type | content dict shape | Handler |
|---|---|---|
| `llm_image_tag_result` | `{"memory_id": str, "tags": list[str], "description": str}` | ImageTagHandler |
| `llm_intent_result` | `{"query": str, "intent": str, "results": list[dict]}` | IntentHandler |
| `llm_followup_result` | `{"question": str}` | FollowupHandler |
| `llm_task_match_result` | `{"task_id": str, "task_description": str, "memory_id": str}` | TaskMatchHandler |
| `event_confirmation` | `{"description": str, "event_date": str}` | EmailExtractHandler |

**Core API endpoints the handlers call (already exist, do not modify):**
- `POST /memories/{memory_id}/tags` -- body: `{"tags": ["tag1", ...], "status": "suggested"}` (schema: `TagsAddRequest`)
- `POST /events` -- body: `{"owner_user_id": int, "event_time": "ISO8601", "description": str, "source_type": "email"}` (schema: `EventCreate`)
- `GET /tasks?owner_user_id={id}&state=NOT_DONE` -- returns `list[TaskResponse]` with fields: `id`, `description`, `state`, etc.

---

## Files to Create

### 1. `llm_worker/worker/prompts.py`

All prompt templates as string constants. Use double-brace `{{` for literal braces in f-string-compatible templates.

```python
"""Prompt templates for LLM handlers.

Each constant is a string template with {placeholders} for .format() calls.
Double braces {{ }} are literal braces in the expected JSON output examples.
"""

IMAGE_TAG_PROMPT = """\
Analyze this image and provide:
1. A brief one-sentence description
2. A list of 3-7 relevant tags (single words or short phrases)

Respond ONLY with valid JSON in this exact format:
{{"description": "A short description of the image", "tags": ["tag1", "tag2", "tag3"]}}"""

INTENT_CLASSIFY_PROMPT = """\
Classify the search intent of this query: "{query}"

Possible intents:
- memory_search: looking for a saved memory or note
- task_lookup: looking for a task or to-do item
- reminder_check: looking for a reminder
- event_search: looking for an event or appointment
- ambiguous: cannot determine intent

Respond ONLY with valid JSON:
{{"intent": "one_of_the_above", "keywords": ["extracted", "keywords"]}}"""

FOLLOWUP_PROMPT = """\
The user searched for: "{message}"
Context from their recent data: {context}

The search returned few or no results. Generate a single clarifying \
follow-up question to help narrow down what the user is looking for.
Respond with ONLY the question text, nothing else."""

TASK_MATCH_PROMPT = """\
A user just saved this new memory: "{memory_content}"

Their open tasks are:
{tasks_list}

Does this new memory indicate that any of these tasks might be completed?
Respond ONLY with valid JSON:
{{"matched_task_id": "the_task_id_or_null", "confidence": 0.0, "reason": "brief explanation"}}

If no task matches, set matched_task_id to null and confidence to 0.0."""

EMAIL_EXTRACT_PROMPT = """\
Extract any calendar events or appointments from this email.

Subject: {subject}
Body:
{body}

Respond ONLY with valid JSON:
{{"events": [{{"description": "event description", "event_time": "ISO8601 datetime", "confidence": 0.8}}]}}

If no events are found, return {{"events": []}}."""
```

---

### 2. `llm_worker/worker/handlers/__init__.py`

Empty file (package marker).

---

### 3. `llm_worker/worker/handlers/base.py`

Abstract base class for all handlers.

```python
"""Abstract base handler for LLM job processing."""

from abc import ABC, abstractmethod
from typing import Any

from worker.llm_client import LLMClient
from worker.core_api_client import CoreAPIClient
from worker.config import LLMWorkerSettings


class BaseHandler(ABC):
    """Base class for LLM job handlers.

    Each handler processes a specific job type. It receives a payload,
    calls the LLM, and returns a notification content dict (or None).
    """

    def __init__(
        self,
        llm_client: LLMClient,
        core_api: CoreAPIClient,
        config: LLMWorkerSettings,
    ):
        self.llm = llm_client
        self.core_api = core_api
        self.config = config

    @abstractmethod
    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        """Process a job and return notification content.

        Args:
            job_id: The LLM job ID.
            payload: Job-specific payload dict.
            user_id: Telegram user ID (may be None for system jobs).

        Returns:
            Notification content dict for the Telegram consumer,
            or None if no notification should be sent.
        """
```

---

### 4. `llm_worker/worker/handlers/image_tag.py`

Processes `image_tag` jobs. Uses the vision model to analyze an image and suggest tags.

**Payload expected:** `{"memory_id": str, "image_path": str}`
**Returns:** `{"memory_id": str, "tags": list[str], "description": str}`

Steps:
1. Read image file from `payload["image_path"]` on the local filesystem
2. Base64-encode the image bytes
3. Call `self.llm.complete_with_image(config.llm_vision_model, IMAGE_TAG_PROMPT, b64_image)`
4. Parse response with `extract_json()` to get `{"description": str, "tags": list[str]}`
5. Call `self.core_api.add_tags(memory_id, tags, status="suggested")` to persist tags in Core
6. Return the notification content dict

```python
"""Image tagging handler -- uses vision model to suggest tags."""

import base64
import logging
from pathlib import Path
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import IMAGE_TAG_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class ImageTagHandler(BaseHandler):
    """Process image_tag jobs using a vision LLM."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        memory_id = payload["memory_id"]
        image_path = payload["image_path"]

        # Read and encode image
        image_bytes = Path(image_path).read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Call vision model
        raw_response = await self.llm.complete_with_image(
            self.config.llm_vision_model, IMAGE_TAG_PROMPT, image_b64
        )

        # Parse structured response
        result = extract_json(raw_response)
        tags = result.get("tags", [])
        description = result.get("description", "")

        # Persist suggested tags in Core API
        if tags:
            await self.core_api.add_tags(memory_id, tags, status="suggested")

        logger.info(
            "Tagged memory %s with %d tags: %s",
            memory_id, len(tags), tags,
        )

        return {
            "memory_id": memory_id,
            "tags": tags,
            "description": description,
        }
```

---

### 5. `llm_worker/worker/handlers/intent.py`

Processes `intent_classify` jobs. Classifies a search query's intent.

**Payload expected:** `{"query": str, "user_id": int}`
**Returns:** `{"query": str, "intent": str, "results": list[dict]}`

```python
"""Intent classification handler -- classifies search queries."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import INTENT_CLASSIFY_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class IntentHandler(BaseHandler):
    """Classify the intent of a user's search query."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        query = payload["query"]

        prompt = INTENT_CLASSIFY_PROMPT.format(query=query)
        raw_response = await self.llm.complete(
            self.config.llm_text_model, prompt
        )

        result = extract_json(raw_response)
        intent = result.get("intent", "ambiguous")

        logger.info("Classified query '%s' as intent: %s", query, intent)

        return {
            "query": query,
            "intent": intent,
            "results": [],
        }
```

---

### 6. `llm_worker/worker/handlers/followup.py`

Processes `followup` jobs. Generates a clarifying question.

**Payload expected:** `{"message": str, "context": str (optional)}`
**Returns:** `{"question": str}`

```python
"""Follow-up question handler -- generates clarifying questions."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import FOLLOWUP_PROMPT

logger = logging.getLogger(__name__)


class FollowupHandler(BaseHandler):
    """Generate a clarifying follow-up question."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        message = payload["message"]
        context = payload.get("context", "No additional context available.")

        prompt = FOLLOWUP_PROMPT.format(message=message, context=context)
        raw_response = await self.llm.complete(
            self.config.llm_text_model, prompt
        )

        question = raw_response.strip()
        logger.info("Generated followup question: %s", question[:80])

        return {"question": question}
```

Note: This handler does NOT use `extract_json()` because the prompt asks for plain text, not JSON.

---

### 7. `llm_worker/worker/handlers/task_match.py`

Processes `task_match` jobs. Checks if a new memory matches an open task.

**Payload expected:** `{"memory_id": str, "memory_content": str, "user_id": int}`
**Returns:** `{"task_id": str, "task_description": str, "memory_id": str}` or `None`

```python
"""Task match handler -- suggests task completion based on new memories."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import TASK_MATCH_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class TaskMatchHandler(BaseHandler):
    """Check if a new memory indicates an open task is done."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        memory_id = payload["memory_id"]
        memory_content = payload["memory_content"]

        # Fetch open tasks from Core API
        tasks = await self.core_api.get_open_tasks(user_id)
        if not tasks:
            logger.info("No open tasks for user %s, skipping match", user_id)
            return None

        # Format task list for the prompt
        tasks_list = "\n".join(
            f"- ID: {t['id']}, Description: {t['description']}"
            for t in tasks
        )

        prompt = TASK_MATCH_PROMPT.format(
            memory_content=memory_content, tasks_list=tasks_list
        )
        raw_response = await self.llm.complete(
            self.config.llm_text_model, prompt
        )

        result = extract_json(raw_response)
        matched_id = result.get("matched_task_id")
        confidence = result.get("confidence", 0.0)

        if matched_id and confidence > 0.7:
            # Find the task description
            task_desc = ""
            for t in tasks:
                if t["id"] == matched_id:
                    task_desc = t["description"]
                    break

            logger.info(
                "Matched memory %s to task %s (confidence: %.2f)",
                memory_id, matched_id, confidence,
            )
            return {
                "task_id": matched_id,
                "task_description": task_desc,
                "memory_id": memory_id,
            }

        logger.info(
            "No confident task match for memory %s (best: %s at %.2f)",
            memory_id, matched_id, confidence,
        )
        return None
```

---

### 8. `llm_worker/worker/handlers/email_extract.py`

Processes `email_extract` jobs. Extracts calendar events from email content.

**Payload expected:** `{"subject": str, "body": str, "user_id": int}`
**Returns:** `{"description": str, "event_date": str}` or `None`

```python
"""Email event extraction handler -- extracts events from emails."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import EMAIL_EXTRACT_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class EmailExtractHandler(BaseHandler):
    """Extract calendar events from email content."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        subject = payload["subject"]
        body = payload["body"]

        prompt = EMAIL_EXTRACT_PROMPT.format(subject=subject, body=body)
        raw_response = await self.llm.complete(
            self.config.llm_text_model, prompt
        )

        result = extract_json(raw_response)
        events = result.get("events", [])

        # Filter to high-confidence events and create them in Core
        first_event_notification = None
        for event in events:
            confidence = event.get("confidence", 0.0)
            if confidence <= 0.7:
                continue

            event_data = {
                "owner_user_id": user_id,
                "event_time": event["event_time"],
                "description": event["description"],
                "source_type": "email",
                "source_detail": subject,
            }
            await self.core_api.create_event(event_data)

            # Use the first high-confidence event for the notification
            if first_event_notification is None:
                first_event_notification = {
                    "description": event["description"],
                    "event_date": event["event_time"],
                }

        if first_event_notification:
            logger.info(
                "Extracted %d events from email '%s'",
                len([e for e in events if e.get("confidence", 0) > 0.7]),
                subject[:50],
            )
        else:
            logger.info("No high-confidence events in email '%s'", subject[:50])

        return first_event_notification
```

---

## Test Files to Create

### 9. `tests/test_llm_worker/test_image_tag.py`

Uses `mock_llm_client`, `mock_core_api`, `llm_worker_config` from conftest.

```
Test cases:
- test_image_tag_success:
    - Write a small test image to a temp file
    - Mock llm.complete_with_image to return '{"description": "A cat", "tags": ["cat", "pet"]}'
    - Call handler.handle(job_id, {"memory_id": "mem-1", "image_path": temp_path}, user_id=12345)
    - Assert result == {"memory_id": "mem-1", "tags": ["cat", "pet"], "description": "A cat"}
    - Assert core_api.add_tags was called with ("mem-1", ["cat", "pet"], status="suggested")

- test_image_tag_wrapped_json:
    - Mock response as 'Here are the tags: {"description": "A dog", "tags": ["dog"]} Done.'
    - Verify extract_json still parses correctly

- test_image_tag_empty_tags:
    - Mock response as '{"description": "Unclear image", "tags": []}'
    - Assert result has empty tags list
    - Assert core_api.add_tags was NOT called (no tags to add)

- test_image_tag_file_not_found:
    - Pass a non-existent image_path
    - Assert FileNotFoundError or appropriate exception is raised
```

### 10. `tests/test_llm_worker/test_intent.py`

```
Test cases:
- test_intent_memory_search:
    - Mock LLM returns '{"intent": "memory_search", "keywords": ["butter", "recipe"]}'
    - Assert result == {"query": "butter recipe", "intent": "memory_search", "results": []}

- test_intent_ambiguous:
    - Mock LLM returns '{"intent": "ambiguous", "keywords": []}'
    - Assert result has intent "ambiguous"

- test_intent_task_lookup:
    - Mock LLM returns '{"intent": "task_lookup", "keywords": ["groceries"]}'
    - Verify correct intent returned
```

### 11. `tests/test_llm_worker/test_followup.py`

```
Test cases:
- test_followup_generates_question:
    - Mock LLM returns "Could you specify which recipe you're looking for?"
    - Assert result == {"question": "Could you specify which recipe you're looking for?"}

- test_followup_with_context:
    - Provide context in payload
    - Verify prompt includes both message and context

- test_followup_strips_whitespace:
    - Mock LLM returns "  What do you mean?  \n"
    - Assert question is stripped
```

### 12. `tests/test_llm_worker/test_task_match.py`

```
Test cases:
- test_task_match_found:
    - Mock core_api.get_open_tasks returns [{"id": "t-1", "description": "Buy groceries"}]
    - Mock LLM returns '{"matched_task_id": "t-1", "confidence": 0.9, "reason": "mentions groceries"}'
    - Assert result == {"task_id": "t-1", "task_description": "Buy groceries", "memory_id": "mem-1"}

- test_task_match_low_confidence:
    - Mock confidence 0.3
    - Assert result is None

- test_task_match_no_tasks:
    - Mock get_open_tasks returns []
    - Assert result is None, LLM was NOT called

- test_task_match_null_match:
    - Mock LLM returns '{"matched_task_id": null, "confidence": 0.0, "reason": "no match"}'
    - Assert result is None

- test_task_match_formats_task_list:
    - Mock multiple tasks, verify prompt contains all task descriptions
```

### 13. `tests/test_llm_worker/test_email_extract.py`

```
Test cases:
- test_email_extract_event_found:
    - Mock LLM returns '{"events": [{"description": "Team meeting", "event_time": "2026-03-01T10:00:00Z", "confidence": 0.9}]}'
    - Assert core_api.create_event was called with correct event_data
    - Assert result == {"description": "Team meeting", "event_date": "2026-03-01T10:00:00Z"}

- test_email_extract_low_confidence:
    - Mock confidence 0.3
    - Assert core_api.create_event was NOT called
    - Assert result is None

- test_email_extract_no_events:
    - Mock LLM returns '{"events": []}'
    - Assert result is None

- test_email_extract_multiple_events:
    - Mock two high-confidence events
    - Assert core_api.create_event called twice
    - Assert result contains the FIRST event's data

- test_email_extract_mixed_confidence:
    - One event at 0.9, one at 0.4
    - Assert only the high-confidence event creates an API call
```

---

## Checkpoint

After this sub-phase is complete, verify:

1. `pytest tests/test_llm_worker/test_image_tag.py` -- all pass
2. `pytest tests/test_llm_worker/test_intent.py` -- all pass
3. `pytest tests/test_llm_worker/test_followup.py` -- all pass
4. `pytest tests/test_llm_worker/test_task_match.py` -- all pass
5. `pytest tests/test_llm_worker/test_email_extract.py` -- all pass
6. `pytest tests/test_llm_worker/` -- all sub-phase 3.1 and 3.2 tests pass together

---

## Code Conventions

- Async throughout: `async def`, `await`
- Type hints on all function signatures
- Max 100 char line length, double quotes, f-strings
- Logger per module: `logger = logging.getLogger(__name__)`
- Imports: stdlib, then third-party, then first-party, alphabetical within groups
