import json
import logging
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from bearmemori.llm.parsing import extract_json
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft
from bearmemori.utils.time import get_server_time

logger = logging.getLogger(__name__)


def _extract_from_response(content: str, reasoning: str) -> dict:
    """Try to extract JSON from content first, then from reasoning_content.

    Reasoning models (e.g. Qwen3.5) may put the JSON answer in content,
    or when max_tokens is exhausted by reasoning, the JSON may only appear
    within the reasoning_content field.
    """
    if content:
        try:
            return extract_json(content)
        except json.JSONDecodeError:
            logger.debug("No JSON in content field, trying reasoning_content")

    if reasoning:
        try:
            return extract_json(reasoning)
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(
        "No valid JSON found in content or reasoning_content",
        content or reasoning or "",
        0,
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

# Backward-compatible alias for code that references TRIAGE_SYSTEM_PROMPT directly
TRIAGE_SYSTEM_PROMPT = _TRIAGE_SYSTEM_TEMPLATE.format(current_time="(not provided)")


@dataclass
class TriageResult:
    should_save: bool
    draft: MemoryDraft | None = None
    reason: str | None = None


async def _llm_call(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int = 4096,
    timeout: float = 60.0,
) -> dict:
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    ) as client:
        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        return response.json()


def _build_draft(data: dict) -> MemoryDraft:
    """Build a MemoryDraft from parsed LLM response data. Raises ValueError/KeyError on failure."""
    event_fields = None
    if data.get("event_fields"):
        event_fields = EventFields(**data["event_fields"])

    importance = max(1, min(10, int(data.get("importance", 5))))

    return MemoryDraft(
        category=MemoryCategory(data["category"]),
        title=data["title"],
        content=data["content"],
        tags=data.get("tags", []),
        importance=importance,
        event_fields=event_fields,
    )


async def _try_extraction(
    conv_text: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    llm_max_tokens: int,
    triage_timeout: float,
    current_time: str,
) -> TriageResult | None:
    """Call extraction-only prompt. Returns TriageResult on success, None on failure."""
    system_prompt = _EXTRACTION_SYSTEM_TEMPLATE.format(current_time=current_time)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Conversation:\n{conv_text}"},
    ]
    raw = ""
    try:
        response = await _llm_call(
            messages, llm_base_url, llm_api_key, llm_model, llm_max_tokens, triage_timeout
        )
        message = response["choices"][0]["message"]
        raw = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        logger.debug("Extraction LLM raw output: %s", raw)
        data = _extract_from_response(raw, reasoning)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Extraction LLM returned unparseable output: %s | raw: %s", e, raw[:500])
        return None
    except httpx.HTTPError as e:
        logger.error("Extraction LLM call failed (%s): %s", type(e).__name__, e)
        return None

    try:
        draft = _build_draft(data)
        logger.info(
            "Extraction decision: should_save=True, category=%s, title=%s, importance=%d",
            draft.category,
            draft.title,
            draft.importance,
        )
        return TriageResult(should_save=True, draft=draft, reason="high_confidence")
    except (ValueError, KeyError, ValidationError) as e:
        logger.warning("Extraction produced invalid draft: %s", e)
        return None


async def _run_full_triage(
    conv_text: str,
    hint_text: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    llm_max_tokens: int,
    triage_timeout: float,
    current_time: str,
) -> TriageResult:
    """Run full triage (should_save decision + extraction) and return a TriageResult."""
    system_prompt = _TRIAGE_SYSTEM_TEMPLATE.format(current_time=current_time)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Conversation:\n{conv_text}{hint_text}"},
    ]

    try:
        response = await _llm_call(
            messages, llm_base_url, llm_api_key, llm_model, llm_max_tokens, triage_timeout
        )
        message = response["choices"][0]["message"]
        logger.info("Triage LLM full message keys: %s", list(message.keys()))
        raw = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        if not raw:
            logger.warning("Triage LLM returned empty content. Full message: %s", message)
        logger.debug("Triage LLM raw output: %s", raw)
        logger.debug("Triage LLM reasoning output: %s", reasoning[:200] if reasoning else "")
        data = _extract_from_response(raw, reasoning)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Triage LLM returned unparseable output: %s", e)
        return TriageResult(should_save=False, reason="extraction_failed")
    except httpx.HTTPError as e:
        logger.error("Triage LLM call failed (%s): %s", type(e).__name__, e)
        return TriageResult(should_save=False, reason="extraction_failed")

    if not data.get("should_save", False):
        logger.info("Triage decision: should_save=False (from LLM data: %s)", data)
        return TriageResult(should_save=False, reason="llm_decided_no")

    try:
        draft = _build_draft(data)
        logger.info(
            "Triage decision: should_save=True, category=%s, title=%s, importance=%d",
            draft.category,
            draft.title,
            draft.importance,
        )
        return TriageResult(should_save=True, draft=draft)
    except (ValueError, KeyError, ValidationError) as e:
        logger.warning("Triage produced invalid draft: %s", e)
        return TriageResult(should_save=False, reason="validation_failed")


async def run_triage(
    conversation: list[dict],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    llm_max_tokens: int = 4096,
    triage_timeout: float = 60.0,
    memory_hint: dict | None = None,
    current_time: str | None = None,
    user_timezone: str = "UTC",
) -> TriageResult:
    if current_time is None:
        current_time = get_server_time(user_timezone)

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

    # High-confidence path: skip should_save decision, use extraction-only prompt.
    # Fall back to full triage if extraction fails.
    if memory_hint and memory_hint.get("confidence") == "high":
        result = await _try_extraction(
            conv_text,
            llm_base_url,
            llm_api_key,
            llm_model,
            llm_max_tokens,
            triage_timeout,
            current_time,
        )
        if result is not None:
            return result
        logger.warning("High-confidence extraction failed, falling back to full triage")

    return await _run_full_triage(
        conv_text,
        hint_text,
        llm_base_url,
        llm_api_key,
        llm_model,
        llm_max_tokens,
        triage_timeout,
        current_time,
    )
