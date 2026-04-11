import base64
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel

from bearmemori.llm.parsing import extract_json
from bearmemori.utils.time import get_server_time

logger = logging.getLogger(__name__)


def _get_content(message) -> str:
    """Extract text content from a chat completion message.

    Handles reasoning models (e.g. Qwen3.5) where the actual JSON may
    appear in content or, if content is empty, in reasoning_content.
    """
    content = message.content or ""
    if content:
        return content

    reasoning = getattr(message, "reasoning_content", None) or ""
    if reasoning:
        logger.info("LLM content empty, checking reasoning_content for JSON")
        try:
            extract_json(reasoning)
            return reasoning
        except Exception:
            pass

    return content


class ClassificationResult(BaseModel):
    action: str  # "store" or "followup"
    category: str | None = None
    confidence: float | None = None
    question: str | None = None


class ExtractionResult(BaseModel):
    content: str
    category: str
    title: str
    tags: list[str]
    importance: int = 5
    event_fields: dict | None = None


CLASSIFY_SYSTEM_PROMPT = (
    "/no_think\n"
    "You are a memory classification assistant. Given user input, decide whether to:\n"
    '1. "store" - the input contains information worth remembering\n'
    '2. "followup" - the input is unclear and needs more context\n'
    "\n"
    "IMPORTANT: Prefer to store the memory even if the input is vague or incomplete. "
    "Extract what you can and save it. Only request a follow-up if the input is truly "
    "unintelligible or you cannot determine any meaningful content to extract.\n"
    "\n"
    "You MUST respond with a single valid JSON object and nothing else.\n"
    '- For store: {"action": "store", "category": "<category>", "confidence": <0-1>}\n'
    "  Categories: profile, general, event, location, task, reminder\n"
    '- For followup: {"action": "followup", "question": "<your clarifying question>"}'
)

_EXTRACT_SYSTEM_TEMPLATE = (
    "/no_think\n"
    "You are a memory extraction assistant. Extract structured memory data from the user input.\n"
    "If follow-up context is provided, use the full conversation to understand the memory.\n"
    "\n"
    "Current date and time: {current_time}\n"
    'When the user mentions relative times (e.g. "in 10 minutes", "tomorrow", "next week"), '
    "use the current date and time above to compute the absolute "
    "ISO 8601 datetime for event_fields.\n"
    "\n"
    "Assign an importance score from 1-10:\n"
    "  1-3: Trivial/ephemeral (casual observations, low-value notes)\n"
    "  4-6: Useful but not critical (general facts, routine tasks)\n"
    "  7-9: Important (key personal info, significant events, recurring tasks)\n"
    "  10: Critical (health info, credentials, life events)\n"
    "\n"
    "You MUST respond with a single valid JSON object and nothing else.\n"
    '{{"content": "<clear summary of the memory>", "category": "<category>", '
    '"title": "<short descriptive title>", "tags": ["tag1", "tag2"], '
    '"importance": <1-10>, "event_fields": null}}\n'
    "Categories: profile, general, event, location, task, reminder\n"
    "\n"
    "For events, tasks, and reminders, set event_fields to:\n"
    '{{"datetime": "<ISO 8601 datetime>", "status": "pending", "recurrence": null}}\n'
    "For non-event categories, set event_fields to null"
)

# Backward-compatible alias
EXTRACT_SYSTEM_PROMPT = _EXTRACT_SYSTEM_TEMPLATE.format(current_time="(not provided)")

FOLLOWUP_SYSTEM_PROMPT = (
    "You are a helpful assistant gathering information for a personal memory store.\n"
    "Ask a single, clear clarifying question to better understand "
    "what the user wants to remember.\n"
    "Keep your question short and direct."
)

_TRIAGE_SYSTEM_TEMPLATE = """\
You are a memory triage agent. Given a conversation, decide if any information \
is worth saving as a long-term memory.

Current date and time: {current_time}
When the user mentions relative times (e.g. "in 10 minutes", "tomorrow", "next week"), \
use the current date and time above to compute the absolute ISO 8601 datetime for event_fields.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

You MUST respond with a single valid JSON object and nothing else. No explanation, \
no commentary, no markdown formatting.

Importance (1-10 integer):
- 1-3: Low importance (trivial facts, casual mentions)
- 4-6: Medium importance (useful information, general preferences)
- 7-8: High importance (key personal facts, significant events, strong preferences)
- 9-10: Critical importance (core identity, health/safety, major life events)

If the conversation contains memory-worthy information:
{{"should_save": true, "category": "<category>", "title": "<short title>", \
"content": "<key information>", "tags": ["tag1", "tag2"], \
"importance": <1-10>, "event_fields": null}}

For events/tasks/reminders, set event_fields to:
{{"datetime": "ISO 8601", "status": "pending", "recurrence": null}}

If nothing is worth saving:
{{"should_save": false}}

IMPORTANT: Reminders and events are always worth saving. A reminder about a
future action (e.g., "pack my bag in 10 minutes") is valuable user
information - do NOT treat it as trivial. Set importance 5-8 for
reminders, 6-9 for events/tasks.

When in doubt, lean toward saving. It is better to save something \
the user can dismiss than to lose information they wanted kept.

The conversation may contain information spread across multiple messages. \
Synthesize the full conversation to extract the complete memory, not just \
the last message.

If the conversation covers multiple unrelated topics, focus on the most \
recent topic that contains memory-worthy information.

Save specific, actionable information. Skip only:
- Greetings or small talk
- Questions without answers
- Truly trivial information (e.g., casual mentions without context)
"""

_EXTRACTION_SYSTEM_TEMPLATE = """\
You are a memory extraction agent. The following conversation contains \
information that should be saved as a long-term memory.

Current date and time: {current_time}
When the user mentions relative times (e.g. "in 10 minutes", "tomorrow", "next week"), \
use the current date and time above to compute the absolute ISO 8601 datetime for event_fields.

Extract the memory details from the conversation. You MUST respond with a \
single valid JSON object and nothing else. No explanation, no commentary, \
no markdown formatting.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

Importance (1-10 integer):
- 1-3: Low importance (trivial facts, casual mentions)
- 4-6: Medium importance (useful information, general preferences)
- 7-8: High importance (key personal facts, significant events, strong preferences)
- 9-10: Critical importance (core identity, health/safety, major life events)

Respond with:
{{"category": "<category>", "title": "<short title>", \
"content": "<key information>", "tags": ["tag1", "tag2"], \
"importance": <1-10>, "event_fields": null}}

For events/tasks/reminders, set event_fields to:
{{"datetime": "ISO 8601", "status": "pending", "recurrence": null}}

IMPORTANT: Reminders and events should have importance 5-8 for reminders, \
6-9 for events/tasks.

The conversation may contain information spread across multiple messages. \
Synthesize the full conversation to extract the complete memory, not just \
the last message.
"""

DESCRIBE_IMAGE_SYSTEM_PROMPT = (
    "/no_think\n"
    "You are a memory extraction assistant. "
    "Describe the image and extract structured memory data.\n"
    "\n"
    "Assign an importance score from 1-10:\n"
    "  1-3: Trivial/ephemeral\n"
    "  4-6: Useful but not critical\n"
    "  7-9: Important\n"
    "  10: Critical\n"
    "\n"
    "You MUST respond with a single valid JSON object and nothing else.\n"
    '{"content": "<description of what the image shows>", "category": "<category>", '
    '"title": "<short descriptive title>", "tags": ["tag1", "tag2"], '
    '"importance": <1-10>, "event_fields": null}\n'
    "Categories: profile, general, event, location, task, reminder"
)


def _clamp_importance(data: dict) -> dict:
    """Clamp importance to 1-10, defaulting to 5 if missing."""
    raw = data.get("importance", 5)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = 5
    data["importance"] = max(1, min(10, val))
    return data


class _AsyncCompletionsWrapper:
    """Thin wrapper so that `create` is a proper coroutine function.

    `patch.object` auto-selects AsyncMock only when the target attribute is
    detected as a coroutine function via `inspect.iscoroutinefunction`. The
    openai SDK's AsyncCompletions.create is implemented differently and is not
    detected that way, so this wrapper ensures tests can patch it correctly.
    """

    def __init__(self, completions) -> None:
        self._completions = completions

    async def create(self, **kwargs):
        return await self._completions.create(**kwargs)


class _ChatWrapper:
    def __init__(self, chat) -> None:
        self.completions = _AsyncCompletionsWrapper(chat.completions)


class _ClientWrapper:
    """Wraps AsyncOpenAI so that chat.completions.create is patchable."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._openai = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.chat = _ChatWrapper(self._openai.chat)


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "not-needed",
        user_timezone: str = "UTC",
    ) -> None:
        self._client = _ClientWrapper(base_url=base_url, api_key=api_key)
        self._model = model
        self._user_timezone = user_timezone

    async def classify_input(self, text: str) -> ClassificationResult:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        raw = _get_content(response.choices[0].message)
        logger.debug("Classify raw output: %s", raw)
        data = extract_json(raw)
        return ClassificationResult(**data)

    async def extract_memory(self, text: str, context: dict | None) -> ExtractionResult:
        current_time = get_server_time(self._user_timezone)
        system_prompt = _EXTRACT_SYSTEM_TEMPLATE.format(current_time=current_time)
        messages = [{"role": "system", "content": system_prompt}]
        if context and "messages" in context:
            messages.extend(context["messages"])
        messages.append({"role": "user", "content": text})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.1,
        )
        raw = _get_content(response.choices[0].message)
        logger.debug("Extract raw output: %s", raw)
        data = extract_json(raw)
        data = _clamp_importance(data)
        logger.debug("Extracted data event_fields: %s", data.get("event_fields"))
        return ExtractionResult(**data)

    async def generate_followup(self, text: str, context: dict | None) -> str:
        messages = [{"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT}]
        if context and "messages" in context:
            messages.extend(context["messages"])
        messages.append({"role": "user", "content": text})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.7,
        )
        return _get_content(response.choices[0].message)

    async def describe_image(
        self, image_bytes: bytes, caption: str | None = None
    ) -> ExtractionResult:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        user_content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]
        if caption:
            user_content.append({"type": "text", "text": caption})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": DESCRIBE_IMAGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
        )
        raw = _get_content(response.choices[0].message)
        logger.debug("Describe image raw output: %s", raw)
        data = extract_json(raw)
        data = _clamp_importance(data)
        return ExtractionResult(**data)

    async def triage(self, conversation_text: str, hint_text: str, current_time: str) -> dict:
        system_prompt = _TRIAGE_SYSTEM_TEMPLATE.format(current_time=current_time)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Conversation:\n{conversation_text}{hint_text}"},
            ],
            temperature=0.1,
        )
        raw = _get_content(response.choices[0].message)
        logger.debug("Triage LLM raw output: %s", raw)
        return extract_json(raw)

    async def extract_triage(self, conversation_text: str, current_time: str) -> dict:
        system_prompt = _EXTRACTION_SYSTEM_TEMPLATE.format(current_time=current_time)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Conversation:\n{conversation_text}"},
            ],
            temperature=0.1,
        )
        raw = _get_content(response.choices[0].message)
        logger.debug("Extraction LLM raw output: %s", raw)
        return extract_json(raw)
