import json
from unittest.mock import AsyncMock, patch

import pytest

from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient
from bearmemori.storage.models import MemoryCategory


@pytest.fixture
def llm():
    return LLMClient(base_url="http://localhost:11434/v1", model="test", api_key="test")


@pytest.mark.asyncio
async def test_triage_should_save(llm):
    response_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "importance": 5,
        "event_fields": None,
    }
    with patch.object(llm, "triage", new_callable=AsyncMock, return_value=response_data):
        result = await run_triage(
            [{"role": "user", "content": "I love black coffee"}],
            llm=llm,
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.PROFILE


@pytest.mark.asyncio
async def test_triage_should_not_save(llm):
    with patch.object(llm, "triage", new_callable=AsyncMock, return_value={"should_save": False}):
        result = await run_triage(
            [{"role": "user", "content": "Hello"}],
            llm=llm,
        )
    assert result.should_save is False
    assert result.draft is None


@pytest.mark.asyncio
async def test_triage_malformed_response(llm):
    with patch.object(llm, "triage", new_callable=AsyncMock, side_effect=json.JSONDecodeError("bad", "", 0)):
        result = await run_triage(
            [{"role": "user", "content": "test"}],
            llm=llm,
        )
    assert result.should_save is False


@pytest.mark.asyncio
async def test_triage_with_memory_hint(llm):
    response_data = {
        "should_save": True,
        "category": "event",
        "title": "Meeting tomorrow",
        "content": "Team standup at 9am",
        "tags": ["meeting"],
        "importance": 7,
        "event_fields": {"datetime": "2026-03-22T09:00:00", "status": "pending", "recurrence": None},
    }
    with patch.object(llm, "triage", new_callable=AsyncMock, return_value=response_data):
        result = await run_triage(
            [{"role": "user", "content": "I have a standup at 9am tomorrow"}],
            llm=llm,
            memory_hint={"likely_category": "event", "confidence": "low"},
        )
    assert result.should_save is True
    assert result.draft.event_fields is not None
    assert result.draft.event_fields.datetime == "2026-03-22T09:00:00"


@pytest.mark.asyncio
async def test_triage_high_confidence_skips_should_save(llm):
    """When memory_hint has confidence='high', uses extraction-only path."""
    response_data = {
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending", "recurrence": None},
    }
    with patch.object(llm, "extract_triage", new_callable=AsyncMock, return_value=response_data):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm=llm,
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER
    assert result.draft.title == "Pack bag"


@pytest.mark.asyncio
async def test_triage_high_confidence_falls_back_on_extraction_failure(llm):
    """When extraction-only fails, should fall back to full triage prompt."""
    full_triage_data = {
        "should_save": True,
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending", "recurrence": None},
    }
    with (
        patch.object(llm, "extract_triage", new_callable=AsyncMock, side_effect=json.JSONDecodeError("bad", "", 0)),
        patch.object(llm, "triage", new_callable=AsyncMock, return_value=full_triage_data),
    ):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm=llm,
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER


def test_triage_prompt_contains_when_in_doubt_save():
    from bearmemori.llm.client import _TRIAGE_SYSTEM_TEMPLATE
    assert "when in doubt" in _TRIAGE_SYSTEM_TEMPLATE.lower()
    assert "Be selective" not in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_multi_turn_guidance():
    from bearmemori.llm.client import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple messages" in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_mixed_topic_guidance():
    from bearmemori.llm.client import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple unrelated topics" in _TRIAGE_SYSTEM_TEMPLATE
