import json
import logging
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from bearmemori.llm.parsing import extract_json
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft

logger = logging.getLogger(__name__)

TRIAGE_SYSTEM_PROMPT = """\
/no_think
You are a memory triage agent. Given a conversation, decide if any information \
is worth saving as a long-term memory.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

You MUST respond with a single valid JSON object and nothing else. No explanation, \
no commentary, no markdown formatting.

If the conversation contains memory-worthy information:
{"should_save": true, "category": "<category>", "title": "<short title>", \
"content": "<key information>", "tags": ["tag1", "tag2"], "event_fields": null}

For events/tasks/reminders, set event_fields to:
{"datetime": "ISO 8601", "status": "pending", "recurrence": null}

If nothing is worth saving:
{"should_save": false}

Be selective. Only save genuinely useful, specific information. Do not save:
- Greetings or small talk
- Questions without answers
- Temporary or trivial information
"""


@dataclass
class TriageResult:
    should_save: bool
    draft: MemoryDraft | None = None


async def _llm_call(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
) -> dict:
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    ) as client:
        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 512,
            },
        )
        response.raise_for_status()
        return response.json()


async def run_triage(
    conversation: list[dict],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    memory_hint: dict | None = None,
) -> TriageResult:
    hint_text = ""
    if memory_hint:
        hint_text = f"\n\nMemory hint from chatbot: {json.dumps(memory_hint)}"

    try:
        conv_text = "\n".join(
            f"{msg['role'].upper()}: {msg.get('content', '')}" for msg in conversation[-10:]
        )
    except (KeyError, AttributeError) as e:
        logger.warning("Malformed conversation item: %s", e)
        return TriageResult(should_save=False)

    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Conversation:\n{conv_text}{hint_text}"},
    ]

    try:
        response = await _llm_call(messages, llm_base_url, llm_api_key, llm_model)
        message = response["choices"][0]["message"]
        logger.info("Triage LLM full message keys: %s", list(message.keys()))
        raw = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        if not raw and reasoning:
            logger.info("Triage LLM content empty, falling back to reasoning_content")
            raw = reasoning
        if not raw:
            logger.warning("Triage LLM returned empty content. Full message: %s", message)
        logger.debug("Triage LLM raw output: %s", raw)
        data = extract_json(raw)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Triage LLM returned unparseable output: %s", e)
        return TriageResult(should_save=False)
    except httpx.HTTPError as e:
        logger.error("Triage LLM call failed: %s", e)
        return TriageResult(should_save=False)

    if not data.get("should_save", False):
        return TriageResult(should_save=False)

    try:
        event_fields = None
        if data.get("event_fields"):
            event_fields = EventFields(**data["event_fields"])

        draft = MemoryDraft(
            category=MemoryCategory(data["category"]),
            title=data["title"],
            content=data["content"],
            tags=data.get("tags", []),
            event_fields=event_fields,
        )
        return TriageResult(should_save=True, draft=draft)
    except (ValueError, KeyError, ValidationError) as e:
        logger.warning("Triage produced invalid draft: %s", e)
        return TriageResult(should_save=False)
