import json
from unittest.mock import patch

import pytest

from bearmemori.core.triage import run_triage
from bearmemori.storage.models import MemoryCategory


@pytest.mark.asyncio
async def test_triage_should_save():
    response_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "event_fields": None,
    }
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps(response_data)}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "I love black coffee"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.PROFILE


@pytest.mark.asyncio
async def test_triage_should_not_save():
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps({"should_save": False})}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "Hello"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is False
    assert result.draft is None


@pytest.mark.asyncio
async def test_triage_malformed_response():
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": "not json"}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "test"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is False


@pytest.mark.asyncio
async def test_triage_with_memory_hint():
    response_data = {
        "should_save": True,
        "category": "event",
        "title": "Meeting tomorrow",
        "content": "Team standup at 9am",
        "tags": ["meeting"],
        "event_fields": {"datetime": "2026-03-22T09:00:00", "status": "pending"},
    }
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps(response_data)}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "I have a standup at 9am tomorrow"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
            memory_hint={"likely_category": "event", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft.event_fields is not None
    assert result.draft.event_fields.datetime == "2026-03-22T09:00:00"


@pytest.mark.asyncio
async def test_triage_high_confidence_skips_should_save():
    """When memory_hint has confidence='high', triage should always save."""
    response_data = {
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending"},
    }
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps(response_data)}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER
    assert result.draft.title == "Pack bag"


@pytest.mark.asyncio
async def test_triage_high_confidence_falls_back_on_extraction_failure():
    """When extraction-only fails, should fall back to full triage prompt."""
    extraction_response = {"choices": [{"message": {"content": "not json at all"}}]}
    full_triage_response_data = {
        "should_save": True,
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending"},
    }
    full_triage_response = {
        "choices": [{"message": {"content": json.dumps(full_triage_response_data)}}]
    }

    call_count = 0

    async def mock_llm_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return extraction_response  # First call: extraction fails
        return full_triage_response  # Second call: full triage succeeds

    with patch("bearmemori.core.triage._llm_call", side_effect=mock_llm_call):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert call_count == 2  # Both extraction and full triage were called
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER


def test_triage_prompt_contains_when_in_doubt_save():
    """The full triage prompt should bias toward saving."""
    from bearmemori.core.triage import _TRIAGE_SYSTEM_TEMPLATE
    assert "when in doubt" in _TRIAGE_SYSTEM_TEMPLATE.lower()
    assert "Be selective" not in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_multi_turn_guidance():
    """The full triage prompt should guide multi-turn synthesis."""
    from bearmemori.core.triage import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple messages" in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_mixed_topic_guidance():
    """The full triage prompt should guide mixed-topic focus."""
    from bearmemori.core.triage import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple unrelated topics" in _TRIAGE_SYSTEM_TEMPLATE
