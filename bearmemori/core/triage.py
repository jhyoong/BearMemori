import json
import logging
from dataclasses import dataclass

import openai
from pydantic import ValidationError

from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft
from bearmemori.utils.time import get_server_time

logger = logging.getLogger(__name__)


@dataclass
class TriageResult:
    should_save: bool
    draft: MemoryDraft | None = None
    reason: str | None = None


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
    llm,
    current_time: str,
) -> TriageResult | None:
    """Call extraction-only prompt. Returns TriageResult on success, None on failure."""
    try:
        data = await llm.extract_triage(conv_text, current_time)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Extraction LLM returned unparseable output: %s", e)
        return None
    except openai.APIError as e:
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
    llm,
    current_time: str,
) -> TriageResult:
    """Run full triage (should_save decision + extraction) and return a TriageResult."""
    try:
        data = await llm.triage(conv_text, hint_text, current_time)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Triage LLM returned unparseable output: %s", e)
        return TriageResult(should_save=False, reason="extraction_failed")
    except openai.APIError as e:
        logger.error("Triage LLM call failed (%s): %s", type(e).__name__, e)
        return TriageResult(should_save=False, reason="extraction_failed")

    if not data.get("should_save", False):
        logger.info("Triage decision: should_save=False")
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
    llm,
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
        result = await _try_extraction(conv_text, llm, current_time)
        if result is not None:
            return result
        logger.warning("High-confidence extraction failed, falling back to full triage")

    return await _run_full_triage(conv_text, hint_text, llm, current_time)
