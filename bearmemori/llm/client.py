import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


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
    event_fields: dict | None = None


CLASSIFY_SYSTEM_PROMPT = (
    "You are a memory classification assistant. Given user input, decide whether to:\n"
    '1. "store" - the input contains clear information worth remembering\n'
    '2. "followup" - the input is unclear and needs more context\n'
    "\n"
    "Respond with JSON only:\n"
    '- For store: {"action": "store", "category": "<category>", "confidence": <0-1>}\n'
    "  Categories: profile, general, event, location, task, reminder\n"
    '- For followup: {"action": "followup", "question": "<your clarifying question>"}'
)

EXTRACT_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Extract structured memory data from the user input.\n"
    "If follow-up context is provided, use the full conversation to understand the memory.\n"
    "\n"
    "Respond with JSON only:\n"
    '{"content": "<clear summary of the memory>", "category": "<category>", '
    '"title": "<short descriptive title>", "tags": ["tag1", "tag2"], '
    '"event_fields": null}\n'
    "Categories: profile, general, event, location, task, reminder\n"
    "\n"
    "For events, tasks, and reminders, set event_fields to:\n"
    '{"datetime": "<ISO 8601 datetime>", "status": "pending", "recurrence": null}\n'
    "For non-event categories, set event_fields to null"
)

FOLLOWUP_SYSTEM_PROMPT = (
    "You are a helpful assistant gathering information for a personal memory store.\n"
    "Ask a single, clear clarifying question to better understand "
    "what the user wants to remember.\n"
    "Keep your question short and direct."
)


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
    def __init__(self, base_url: str, model: str, api_key: str = "not-needed") -> None:
        self._client = _ClientWrapper(base_url=base_url, api_key=api_key)
        self._model = model

    async def classify_input(self, text: str) -> ClassificationResult:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        data = json.loads(response.choices[0].message.content)
        return ClassificationResult(**data)

    async def extract_memory(self, text: str, context: dict | None) -> ExtractionResult:
        messages = [{"role": "system", "content": EXTRACT_SYSTEM_PROMPT}]
        if context and "messages" in context:
            messages.extend(context["messages"])
        messages.append({"role": "user", "content": text})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.1,
        )
        data = json.loads(response.choices[0].message.content)
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
        return response.choices[0].message.content
